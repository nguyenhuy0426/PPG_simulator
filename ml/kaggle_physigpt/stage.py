"""Package PPG-physiGPT kernels (same payload format as ml/kaggle_multidomain/stage_kernel.py).

data shard k (CPU, internet): mimic_wdb over the record range [start, stop) -> /kaggle/working/shard
train stage k (T4 x2): train.py on the mounted shards (and solo outputs, --solos) after smoke runs that measure
eager against torch.compile; stage 0 trains on all of them as new data, stage k > 0 mounts stage k-1's output and
starts from its stable.pt, with the earlier shards as replay. Kaggle mounts a kernel's output at
/kaggle/input/notebooks/<owner>/<slug> (seen in solotrain 0); the script also accepts /kaggle/input/<slug>.
tpu stage k (TPU v3-8): train_tpu.py, the same stage as train k on the Kaggle TPU, after a smoke run on synthetic
windows that also logs the torch/torch_xla versions of the TPU image.
solo k (T4 x2, internet): one kernel that needs no finished data kernel: a GPU smoke run on synthetic windows, then
mimic_wdb for --hours into /kaggle/working/shard, then stage 0 of train.py on that shard for the rest of the kernel
budget. Its shard mounts later like any data shard (Windows finds it by manifest.json).
judge (T4 x2): ml.kaggle_physigpt.judge_physigpt on the mounted shards and a finished stage's release.pt: the model
judge and its features on GPU 0, the null and damaged-real control judges on GPU 1, as separate processes.
solotrain k (T4 x2): stage 0 again on solo k's shard (its output mounted), after smoke runs that measure eager
against torch.compile on the same GPUs; planned for many epochs and ended by --plateau, since solo's own 4-epoch
plan over a small shard is a few hundred steps.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zlib

OWNER = "charlesday2612"
COMMON = ["ml/kaggle_lsm/train_lsm.py", "ml/kaggle_physigpt/mimic_wdb.py"]
SOURCES = {"data": COMMON+["ml/kaggle_multidomain/data.py", "ml/kaggle_multidomain/view.py"],
           "train": COMMON+["ml/kaggle_physigpt/model.py", "ml/kaggle_physigpt/train.py"]}
SOURCES["solo"] = SOURCES["data"]+SOURCES["train"][len(COMMON):]
SOURCES["tpu"] = SOURCES["train"]+["ml/kaggle_physigpt/train_tpu.py"]
SOURCES["solotrain"] = SOURCES["train"]
SOURCES["judge"] = SOURCES["train"]+["ml/kaggle_physigpt/judge_physigpt.py", "ml/kaggle_multidomain/strict_judge.py",
                                      "ml/kaggle_multidomain/physio.py", "ml/kaggle_multidomain/view.py",
                                      "ml/kaggle_multidomain/models.py", "ml/kaggle_multidomain/labels.py",
                                      "ml/kaggle_multidomain/data.py", "ml/kaggle_multidomain/benchmark.py",
                                      "ml/kaggle_multidomain/control.py"]
TPU_HOURS = 8.3       # Kaggle's TPU session limit is taken as 9 h (not confirmed from a document)
KERNEL_HOURS = 11.5   # Kaggle stops a GPU kernel at 12 h; the rest is train.py's own reserve plus packing


def shard_slug(k):
    return f"ppg-physigpt-mimic3-shard{k}-v1"


def stage_slug(k):
    return f"ppg-physigpt-stage{k}-v1"


def solo_slug(k):
    return f"ppg-physigpt-solo{k}-v1"


def tpu_slug(k):
    return f"ppg-physigpt-tpu-stage{k}-v1"


def solotrain_slug(k):
    return f"ppg-physigpt-solo{k}-train-v1"


def mount_lookup(owner):
    """Run-time lookup of a mounted kernel output or dataset, failing before any GPU time is spent. Kaggle mounts a
    kernel output under notebooks/<owner>/<slug>; the dataset path is not documented, so the owner level of
    /kaggle/input is searched two levels deep as well."""
    return ("def mounted(slug):\n"
            "    root = pathlib.Path('/kaggle/input')\n"
            "    for path in (root/slug, pathlib.Path('/kaggle/input/notebooks/{owner}')/slug,\n"
            "                 pathlib.Path('/kaggle/input/datasets/{owner}')/slug,\n"
            "                 *root.glob('*/'+slug), *root.glob('*/*/'+slug)):\n"
            "        if path.is_dir():\n            return str(path)\n"
            "    raise FileNotFoundError(f'{slug} is not mounted under /kaggle/input')\n").replace("{owner}", owner)


def entry_for(kind, shard=0, start=0, stop=10**9, cap=300, target=5_000_000, hours=10.5, stage=0, shards=(0,),
              config="base", epochs=4., extra=(), smoke_only=False, solos=(), datasets=(), owner=OWNER,
              kernel_hours=KERNEL_HOURS, checkpoint="release.pt", judge_seeds=3):
    if kind == "data":
        args = ["--output", "/kaggle/working/shard", "--start", str(start), "--stop", str(stop), "--cap", str(cap),
                "--target", str(target), "--hours", str(hours)]
        return f"from ml.kaggle_physigpt.mimic_wdb import main\nmain({args!r})"
    if kind == "solo":
        if hours > KERNEL_HOURS-2:
            raise ValueError(f"solo: --hours {hours} of data leaves under 2 h of the {KERNEL_HOURS} h kernel to train")
        data = ["--output", "/kaggle/working/shard", "--start", str(start), "--stop", str(stop), "--cap", str(cap),
                "--target", str(target), "--hours", str(hours)]
        train = ["--data", "/kaggle/working/shard", "--output", "/kaggle/working/stage0", "--config", config,
                 "--epochs", str(epochs), *extra]
        return ("import time\nfrom ml.kaggle_physigpt.mimic_wdb import main as build\n"
                "from ml.kaggle_physigpt.train import main as train, smoke\nbegin = time.time()\n"
                f"print('smoke', json.dumps(smoke('/tmp/physigpt_smoke', {config!r})), flush=True)\n"
                f"build({data!r})\n"
                f"left = {KERNEL_HOURS} - (time.time()-begin)/3600\n"
                f"train({train!r} + ['--hours', f'{{left:.3f}}'])")
    if kind == "solotrain":
        # The mounted solo output holds shard/ (with manifest.json) and its short stage0/ (none), so the input
        # root finds exactly its shard wherever Kaggle mounts it.
        train = ["--data", "/kaggle/input", "--output", "/kaggle/working/stage0", "--config", config,
                 "--epochs", str(epochs), *extra]
        return ("import time\nfrom ml.kaggle_physigpt.train import main as train, pick_compile\nbegin = time.time()\n"
                f"use, report = pick_compile('/tmp/physigpt_smoke', {config!r})\n"
                "print('smoke', json.dumps(report), flush=True)\n"
                f"left = {KERNEL_HOURS} - (time.time()-begin)/3600\n"
                f"train({train!r} + (['--compile'] if use else []) + ['--hours', f'{{left:.3f}}'])")
    if kind == "judge":
        slugs = [shard_slug(k) for k in shards]+[solo_slug(k) for k in solos]+list(datasets)
        return (mount_lookup(owner)
                + "import os, subprocess\n"
                f"slugs, out = {slugs!r}, '/kaggle/working/eval'\n"
                f"found = sorted(pathlib.Path(mounted({stage_slug(stage)!r})).rglob({checkpoint!r}))\n"
                f"if len(found) != 1:\n    raise FileNotFoundError(f'expected one {checkpoint}, found {{found}}')\n"
                "data = [mounted(slug) for slug in slugs]\n"
                "def run(mode, gpu, *more):\n"
                "    env = {**os.environ, 'CUDA_VISIBLE_DEVICES': gpu, 'PYTHONPATH': str(root)}\n"
                "    argv = [sys.executable, '-m', 'ml.kaggle_physigpt.judge_physigpt', out+'/'+mode, '--data', *data,\n"
                "            '--mode', mode, '--device', 'cuda', '--threads', '4', *more]\n"
                "    return subprocess.Popen(argv, env=env)\n"
                f"seeds = {[str(i) for i in range(judge_seeds)]!r}\n"
                "model = run('model', '0', '--checkpoint', str(found[0]), '--seeds', *seeds)\n"
                "controls = run('controls', '1', '--seeds', '0')\n"
                "codes = [model.wait()]\n"
                "if codes[0] == 0:\n"
                "    codes.append(run('features', '0', '--checkpoint', str(found[0]),\n"
                "                     '--generated', out+'/model/generated.npy').wait())\n"
                "codes.append(controls.wait())\n"
                "print('judge exit codes (model, features, controls):', codes, flush=True)\n"
                "if any(codes):\n    raise SystemExit(f'judge failed: {codes}')")
    new, replay = (shards, ()) if stage == 0 else (shards[-1:], shards[:-1])
    new = [shard_slug(k) for k in new]+[solo_slug(k) for k in solos]+list(datasets)
    replay = [shard_slug(k) for k in replay]
    args = (f"args = ['--data', *map(mounted, {new!r}), '--replay', *map(mounted, {replay!r}), '--output', "
            f"'/kaggle/working/stage{stage}', '--config', {config!r}, '--epochs', {str(epochs)!r}, *{list(extra)!r}]\n")
    if kind == "tpu":
        text = ("import time\nfrom ml.kaggle_physigpt.train_tpu import main, smoke, versions\nbegin = time.time()\n"
                "print('versions', json.dumps(versions()), flush=True)\n"
                f"print('smoke', json.dumps(smoke('/tmp/physigpt_smoke', {config!r})), flush=True)\n")
        if smoke_only:
            return text+"print('smoke only: no stage trained')"
        if stage > 0:
            raise NotImplementedError("tpu: a later stage mounts the previous stage as in train; not wired yet")
        return (text+mount_lookup(owner)+args
                + f"main(args + ['--hours', f'{{{TPU_HOURS} - (time.time()-begin)/3600:.3f}}'])")
    text = ("import time\nfrom ml.kaggle_physigpt.train import main as train, pick_compile\nbegin = time.time()\n"
            + mount_lookup(owner)+args)
    if stage > 0:
        text += (f"stable = sorted(pathlib.Path(mounted({stage_slug(stage-1)!r})).rglob('stable.pt'))\n"
                 "if len(stable) != 1:\n    raise FileNotFoundError(f'expected one stable.pt, found {stable}')\n"
                 "args += ['--resume', str(stable[0])]\n")
    return (text+f"use, report = pick_compile('/tmp/physigpt_smoke', {config!r})\n"
            "print('smoke', json.dumps(report), flush=True)\n"
            f"left = {kernel_hours} - (time.time()-begin)/3600\n"
            "train(args + (['--compile'] if use else []) + ['--hours', f'{left:.3f}'])")


def stage(output, kind, owner=OWNER, **kw):
    root = Path(__file__).resolve().parents[2]
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip()
    if not branch.startswith("claude/model-benchmark"):
        raise RuntimeError("Stage this experiment from its dedicated branch")
    files = {name: (root/name).read_text() for name in SOURCES[kind]}
    hashes = {p: hashlib.sha256(text.encode()).hexdigest() for p, text in files.items()}
    payload = base64.b64encode(zlib.compress(json.dumps(files).encode())).decode()
    entry = entry_for(kind, owner=owner, **kw)
    for module in re.findall(r"from (ml\.[\w.]+) import", entry):
        if module.replace(".", "/")+".py" not in files:
            raise RuntimeError(f"{kind}: entry imports {module}, which is not staged")
    body = ("import base64, json, pathlib, sys, zlib\n"
            "root = pathlib.Path('/tmp/ppg_research_source')\nroot.mkdir(exist_ok=True)\n"
            f"FILES = json.loads(zlib.decompress(base64.b64decode({payload!r})))\n"
            "for name, text in FILES.items():\n    path = root/name\n    path.parent.mkdir(parents=True, exist_ok=True)\n"
            "    path.write_text(text)\nsys.path.insert(0, str(root))\n"
            f"pathlib.Path('/kaggle/working/source_manifest.json').write_text({json.dumps(dict(branch=branch, files=hashes))!r})\n"
            + entry+"\n")
    # DDP workers are spawned: the generated script must not re-run its body when they import it.
    script = "# Generated by ml/kaggle_physigpt/stage.py\nif __name__ == '__main__':\n" + \
        "\n".join("    "+line for line in body.splitlines())+"\n"
    compile(script, "run.py", "exec")
    dataset_sources = [f"{owner}/{d}" for d in kw.get("datasets", ())] if kind in ("tpu", "train", "judge") else []
    if kind == "data":
        k = kw.get("shard", 0)
        meta = dict(id=f"{owner}/{shard_slug(k)}", title=f"PPG physiGPT MIMIC3 Shard{k} v1", enable_gpu=False,
                    kernel_sources=[])
    elif kind == "solo":
        k = kw.get("shard", 0)
        meta = dict(id=f"{owner}/{solo_slug(k)}", title=f"PPG physiGPT Solo{k} v1", enable_gpu=True,
                    machine_shape="NvidiaTeslaT4", kernel_sources=[])
    elif kind == "solotrain":
        k = kw.get("shard", 0)
        meta = dict(id=f"{owner}/{solotrain_slug(k)}", title=f"PPG physiGPT Solo{k} Train v1", enable_gpu=True,
                    machine_shape="NvidiaTeslaT4", kernel_sources=[f"{owner}/{solo_slug(k)}"])
    elif kind == "judge":
        k = kw.get("stage", 0)
        meta = dict(id=f"{owner}/ppg-physigpt-judge{k}-v1", title=f"PPG physiGPT Judge{k} v1", enable_gpu=True,
                    machine_shape="NvidiaTeslaT4", kernel_sources=[f"{owner}/{shard_slug(s)}" for s in kw.get("shards", (0,))]
                    + [f"{owner}/{solo_slug(s)}" for s in kw.get("solos", ())] + [f"{owner}/{stage_slug(k)}"])
    elif kind == "tpu":
        k = kw.get("stage", 0)
        smoke_only = kw.get("smoke_only", False)
        meta = dict(id=f"{owner}/{'ppg-physigpt-tpu-smoke-v1' if smoke_only else tpu_slug(k)}",
                    title="PPG physiGPT TPU Smoke v1" if smoke_only else f"PPG physiGPT TPU Stage{k} v1",
                    enable_gpu=False, machine_shape="Tpu1VmV38",
                    kernel_sources=[] if smoke_only else [f"{owner}/{shard_slug(s)}" for s in kw.get("shards", (0,))]
                    + [f"{owner}/{solo_slug(s)}" for s in kw.get("solos", ())])
    else:
        k = kw.get("stage", 0)
        meta = dict(id=f"{owner}/{stage_slug(k)}", title=f"PPG physiGPT Stage{k} v1", enable_gpu=True,
                    machine_shape="NvidiaTeslaT4", kernel_sources=[f"{owner}/{shard_slug(s)}" for s in kw.get("shards", (0,))]
                    + [f"{owner}/{solo_slug(s)}" for s in kw.get("solos", ())]
                    + ([f"{owner}/{stage_slug(k-1)}"] if k > 0 else []))
    meta.update(code_file="run.py", language="python", kernel_type="script", is_private=True, enable_tpu=kind == "tpu",
                enable_internet=True, dataset_sources=dataset_sources, competition_sources=[], model_sources=[])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output/"run.py").write_text(script)
    (output/"kernel-metadata.json").write_text(json.dumps(meta, indent=2)+"\n")
    (output/"source_manifest.json").write_text(json.dumps(dict(branch=branch, files=hashes), indent=2)+"\n")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("kind", choices=sorted(SOURCES))
    parser.add_argument("--owner", default=OWNER)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--stop", type=int, default=10**9)
    parser.add_argument("--cap", type=int, default=300)
    parser.add_argument("--target", type=int, default=5_000_000)
    parser.add_argument("--hours", type=float, default=10.5)
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--shards", type=int, nargs="+", default=[0])
    parser.add_argument("--solos", type=int, nargs="*", default=[], help="solo k outputs mounted as new data too")
    parser.add_argument("--datasets", nargs="*", default=[], help="Kaggle dataset slugs (same owner) as new data too")
    parser.add_argument("--kernel-hours", type=float, default=KERNEL_HOURS,
                        help="train: time budget of the kernel; keep it under the remaining GPU quota")
    parser.add_argument("--config", default="base")
    parser.add_argument("--epochs", type=float, default=4.)
    parser.add_argument("--smoke-only", action="store_true", help="tpu: versions and the synthetic smoke run only")
    parser.add_argument("--plateau", type=int, default=0, help="train.py --plateau (evaluations of patience)")
    parser.add_argument("--checkpoint", default="release.pt", help="judge: checkpoint file of the stage output")
    parser.add_argument("--judge-seeds", type=int, default=3, help="judge: judge seeds for the generated source")
    parser.add_argument("--plateau-delta", type=float, default=0., help="train.py --plateau-delta (0: its default)")
    parser.add_argument("--eval-every", type=int, default=0, help="train.py --eval-every (0: its default)")
    args = parser.parse_args(argv)
    data = dict(shard=args.shard, start=args.start, stop=args.stop, cap=args.cap, target=args.target, hours=args.hours)
    train = dict(stage=args.stage, shards=tuple(args.shards), solos=tuple(args.solos), config=args.config,
                 epochs=args.epochs, datasets=tuple(args.datasets), kernel_hours=args.kernel_hours,
                 checkpoint=args.checkpoint, judge_seeds=args.judge_seeds)
    extra = ((["--plateau", str(args.plateau)] if args.plateau else [])
             + (["--plateau-delta", str(args.plateau_delta)] if args.plateau_delta else [])
             + (["--eval-every", str(args.eval_every)] if args.eval_every else []))
    train["extra"] = tuple(extra)
    kw = dict(data=data, train=train, judge=train, tpu=dict(train, smoke_only=args.smoke_only),
              solo=dict(data, config=args.config, epochs=args.epochs, extra=tuple(extra)),
              solotrain=dict(shard=args.shard, config=args.config, epochs=args.epochs, extra=tuple(extra)))[args.kind]
    print(stage(args.output, args.kind, args.owner, **kw))


if __name__ == "__main__":
    main()
