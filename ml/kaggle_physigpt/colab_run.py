"""PPG-physiGPT stage on a Colab VM whose session may end at any time.

Copies the shards from Drive to the VM disk (every file checked against SHA256SUMS.txt, since a Drive copy of a shard
was once found corrupt), resumes from the last checkpoint on Drive, runs train.py as a child process and mirrors its
checkpoints and logs to Drive every --sync-seconds. A new session started with the same --drive-run continues the
stage; once release.pt is on Drive the stage is done and nothing is trained.

    python -m ml.kaggle_physigpt.colab_run --drive-data DIR --drive-run DIR -- <train.py arguments without --data/--output>

The train.py arguments are passed on unchanged (--config, --micro, --lr, --plateau, --hours, ...).
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

CHECKPOINTS = ("last.pt", "best.pt", "stable.pt", "release.pt")
LOGS = ("metrics.jsonl", "run_config.json", "stage_summary.json", "release_samples.npy")
SUMS = "SHA256SUMS.txt"


def sha256(path, block=1 << 24):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            digest.update(chunk)
    return digest.hexdigest()


def copy_atomic(source, target):
    tmp = Path(str(target)+".partial")
    shutil.copyfile(source, tmp)
    if tmp.stat().st_size != Path(source).stat().st_size:
        raise OSError(f"{target}: copied {tmp.stat().st_size} bytes of {Path(source).stat().st_size}")
    tmp.replace(target)


def fetch_data(drive_data, local_data):
    """Copies every shard folder under drive_data to local_data and verifies it; returns the local shard roots."""
    drive_data, local_data = Path(drive_data), Path(local_data)
    sums = drive_data/SUMS
    if not sums.exists():
        raise FileNotFoundError(f"{sums} is missing: cannot tell a corrupt copy from a good one")
    expected = {}
    for line in sums.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        expected[name.strip()] = digest
    roots = sorted(p.name for p in drive_data.iterdir() if p.is_dir())
    for root in roots:
        if (local_data/root).exists():
            continue
        tmp = local_data/(root+".partial")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(drive_data/root, tmp)
        tmp.replace(local_data/root)
    missing = [name for name in expected if not (local_data/name).is_file()]
    if missing:
        raise FileNotFoundError(f"not on the VM after the copy: {missing[:5]}")
    bad = [name for name, digest in expected.items() if sha256(local_data/name) != digest]
    if bad:
        for root in {name.split("/")[0] for name in bad}:
            shutil.rmtree(local_data/root, ignore_errors=True)   # a later run copies it again
        raise ValueError(f"checksum mismatch after copying from Drive: {bad[:5]}")
    return [str(local_data/root) for root in roots]


def sync(local_out, drive_run):
    """Mirrors checkpoints (when changed) and logs to Drive."""
    drive_run = Path(drive_run)
    drive_run.mkdir(parents=True, exist_ok=True)
    for name in CHECKPOINTS+LOGS:
        source, target = Path(local_out)/name, drive_run/name
        if not source.is_file():
            continue
        stat = source.stat()
        if name in CHECKPOINTS and target.exists() and (target.stat().st_size, int(target.stat().st_mtime)) \
                >= (stat.st_size, int(stat.st_mtime)):
            continue
        copy_atomic(source, target)


def restore(drive_run, local_out):
    """Brings the Drive checkpoints and logs to the VM; returns the file to resume from, or None."""
    drive_run, local_out = Path(drive_run), Path(local_out)
    local_out.mkdir(parents=True, exist_ok=True)
    for name in CHECKPOINTS+LOGS:
        if (drive_run/name).is_file() and not (local_out/name).exists():
            shutil.copyfile(drive_run/name, local_out/name)
    return str(local_out/"last.pt") if (local_out/"last.pt").exists() else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--drive-data", required=True, help="Drive folder with shard folders and SHA256SUMS.txt")
    parser.add_argument("--drive-run", required=True, help="Drive folder that keeps this stage's checkpoints")
    parser.add_argument("--local", default="/content/physigpt_local")
    parser.add_argument("--sync-seconds", type=float, default=300.)
    parser.add_argument("train", nargs=argparse.REMAINDER, help="after --: arguments of ml.kaggle_physigpt.train")
    args = parser.parse_args(argv)
    train = args.train[1:] if args.train[:1] == ["--"] else args.train
    local, out = Path(args.local), Path(args.local)/"out"
    if (Path(args.drive_run)/"release.pt").is_file():
        print("release.pt is already on Drive: the stage is done", flush=True)
        return 0
    roots = fetch_data(args.drive_data, local/"data")
    resume = restore(args.drive_run, out)
    command = [sys.executable, "-m", "ml.kaggle_physigpt.train", "--data", *roots, "--output", str(out), *train]
    if resume:
        command += ["--resume", resume]
    print("train:", " ".join(command), flush=True)
    child = subprocess.Popen(command, env={**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "")+os.pathsep
                                           +str(Path(__file__).resolve().parents[2])})
    last = time.time()
    while child.poll() is None:
        time.sleep(min(10., args.sync_seconds))
        if time.time()-last >= args.sync_seconds:
            sync(out, args.drive_run)
            last = time.time()
    sync(out, args.drive_run)
    print("train exit code", child.returncode, flush=True)
    return child.returncode


if __name__ == "__main__":
    sys.exit(main())
