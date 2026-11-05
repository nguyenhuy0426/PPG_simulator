"""Do generated windows sit on training windows? A screening test, run on the shards the generators trained on.

For every window: the highest Pearson correlation with any compared training window over every circular shift, the
statistic of ml.kaggle_multidomain.realism.nearest_train_correlation. Three sources go through one procedure: the
evaluation part of each generator's samples and held-out people (real windows of records never trained on, the baseline).
A generator that copies training windows sits above that baseline near 1. A high value alone does not prove copying
(pulse waves look alike), a low value holds only for the part of the training set compared, and copying of a part of a
window would not show. Engineering check of normalised waveform shape; not clinical validation.

The search is exact, not approximate. |sum x[n+s] y[n]| <= sum_k |X_k| |Y_k| / N for every shift s, so the magnitude
spectra give an upper bound at the price of one matrix product, and only pairs whose bound beats the best correlation
so far need the inverse FFT.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy import fft, stats

from ml.kaggle_lsm.train_lsm import LENGTH
from ml.kaggle_physigpt.train import Windows

THRESHOLD = .99
BLOCK = 1 << 15
BATCH = 256
MARGIN = 1e-4   # above the float32 error of bound and correlation, so rounding cannot prune the true nearest window
CONTROLS = 32
SEED = 20261102
# Half-spectrum weights: every bin but DC and Nyquist stands for two bins of the full spectrum.
WEIGHT = np.full(LENGTH//2+1, 2/LENGTH, np.float32)
WEIGHT[[0, -1]] = 1/LENGTH


def unit(x):
    """float32 windows with zero mean and unit norm; a flat window stays zero and so correlates 0 with everything."""
    x = np.asarray(x, np.float32)
    x = x-x.mean(1, keepdims=True)
    norm = np.linalg.norm(x, axis=1, keepdims=True)
    return np.divide(x, norm, out=np.zeros_like(x), where=norm > 1e-6)


def upper_bound(query_magnitude, train_magnitude):
    """[queries, train] upper bound of the shift-invariant correlation of unit windows."""
    return (query_magnitude*WEIGHT)@train_magnitude.T


class Nearest:
    """The running nearest training window of each query. Feed it every block once; the order does not matter."""

    def __init__(self, queries, threads=4):
        self.spectrum = fft.rfft(unit(queries), axis=1)
        self.magnitude = np.abs(self.spectrum)
        self.best = np.full(len(queries), -np.inf)
        self.row = np.full(len(queries), -1, np.int64)
        self.shift = np.zeros(len(queries), np.int32)
        self.threads = threads
        self.bound_pairs = self.exact_pairs = 0

    def refine(self, q, bound, spectra, rows):
        """Exact correlation of query q with the block's candidates, highest bound first, until the bound rules out
        the rest."""
        order = np.flatnonzero(bound > self.best[q]+MARGIN)
        order = order[np.argsort(-bound[order], kind="stable")]
        done = 0
        for start in range(0, len(order), BATCH):
            part = order[start:start+BATCH]
            part = part[bound[part] > self.best[q]+MARGIN]
            if not len(part):
                break
            correlation = fft.irfft(self.spectrum[q]*np.conj(spectra[part]), n=LENGTH, axis=1)
            done += len(part)
            which, shift = np.unravel_index(correlation.argmax(), correlation.shape)
            if correlation[which, shift] > self.best[q]:
                self.best[q], self.row[q], self.shift[q] = correlation[which, shift], rows[part[which]], shift
        return done

    def update(self, windows, rows):
        spectra = fft.rfft(unit(windows), axis=1)
        bound = upper_bound(self.magnitude, np.abs(spectra))
        self.bound_pairs += bound.size
        with ThreadPoolExecutor(self.threads) as pool:
            done = pool.map(lambda q: self.refine(q, bound[q], spectra, rows), range(len(bound)))
            self.exact_pairs += sum(done)


def statistics(r):
    return dict(windows=len(r), median=float(np.median(r)), p95=float(np.quantile(r, .95)),
                above_0_99=float((r > THRESHOLD).mean()), above_0_99_count=int((r > THRESHOLD).sum()),
                max=float(r.max()))


def eval_part(path, sizes=(6000, 1000, 2000)):
    """The final set of a generated.npy, as judge_physigpt splits it."""
    generated = np.load(path, mmap_mode="r")
    if generated.shape != (sum(sizes), LENGTH):
        raise ValueError(f"{path}: shape {generated.shape}, expected ({sum(sizes)}, {LENGTH})")
    return np.asarray(generated[-sizes[-1]:], np.float32), hashlib.sha256(np.asarray(generated).tobytes()).hexdigest()


def run(data, generated, output, held_rows, limit=None, expect_train=None, hours=11., block=BLOCK, threads=4, top=6,
        log=print):
    """data: Windows. generated: {name: eval windows}. held_rows: rows of the held-out baseline. limit: compare only the
    first `limit` training windows (a measured trial, never a whole-set result)."""
    begin = time.time()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    train = data.train
    if expect_train is not None and len(train) != expect_train:
        raise ValueError(f"{len(train)} training windows mounted, the generators trained on {expect_train}")
    if len(np.intersect1d(held_rows, train)):
        raise ValueError("held-out rows are among the training rows")
    compared = train if limit is None else train[:limit]
    rng = np.random.default_rng(SEED)
    planted = np.sort(rng.choice(compared, min(CONTROLS, len(compared)), replace=False))
    copies = np.stack([np.roll(w, s) for w, s in zip(data.rows(planted).astype(np.float32)/65535,
                                                     rng.integers(LENGTH, size=len(planted)))])
    copies = np.clip(copies+rng.normal(0, .01, copies.shape), 0, 1)   # a shifted noisy copy must still be found
    sources = {**generated, "held_out_people": data.rows(held_rows).astype(np.float32)/65535, "control_copy": copies}
    names = list(sources)
    edges = np.cumsum([0]+[len(sources[n]) for n in names])
    queries = np.concatenate([sources[n] for n in names]).astype(np.float32)
    search = Nearest(queries, threads)
    log(f"{len(queries)} queries, {len(compared)} of {len(train)} training windows, block {block}")
    seen, stopped = 0, False
    for first in range(0, len(compared), block):
        rows = compared[first:first+block]
        search.update(data.rows(rows).astype(np.float32)/65535, rows)
        seen += len(rows)
        elapsed = time.time()-begin
        log(f"train {seen}/{len(compared)} minutes {elapsed/60:.1f} exact_share "
            f"{search.exact_pairs/max(1, search.bound_pairs):.5f}")
        if elapsed > hours*3600 and seen < len(compared):
            log(f"stopped by the {hours} h budget")
            stopped = True
            break
    report = dict(train_total=len(train), train_compared=seen, train_fraction=seen/len(train),
                  whole_train_set=seen == len(train), stopped_by_budget=stopped, limit=limit,
                  bound_pairs=int(search.bound_pairs), exact_pairs=int(search.exact_pairs),
                  minutes=(time.time()-begin)/60, threshold=THRESHOLD, sources={},
                  held_rows_sha256=hashlib.sha256(np.asarray(held_rows, np.int64).tobytes()).hexdigest(),
                  held_people=len(np.unique(data.record[held_rows])), shards=data.shards)
    arrays, shown = dict(held_rows=held_rows, planted=planted), {}
    for i, name in enumerate(names):
        r, row, shift = (a[edges[i]:edges[i+1]] for a in (search.best, search.row, search.shift))
        arrays.update({f"{name}/r": r, f"{name}/row": row, f"{name}/shift": shift, f"{name}/record": data.record[row]})
        report["sources"][name] = statistics(r)
        report["sources"][name]["nearest_records"] = len(np.unique(data.record[row]))
        chosen = np.argsort(-r)[:top]
        shown[name] = [dict(index=int(k), r=float(r[k]), row=int(row[k]), shift=int(shift[k]),
                            record=int(data.record[row[k]])) for k in chosen]
        arrays[f"{name}/top_window"] = sources[name][chosen]
        # Rolled by `shift`, the training window lies on the query.
        arrays[f"{name}/top_train"] = np.stack([np.roll(w, s) for w, s in
                                                zip(data.rows(row[chosen]).astype(np.float32)/65535, shift[chosen])])
    report["control_found"] = int((search.row[edges[names.index("control_copy")]:] == planted).sum())
    report["control_planted"] = len(planted)
    report["top"] = shown
    np.savez_compressed(output/"copy_check.npz", **arrays)
    (output/"copy_check.json").write_text(json.dumps(report, indent=1))
    log(json.dumps({k: report[k] for k in ("train_compared", "train_total", "control_found", "minutes", "sources")}))
    return report


def figure(output):
    """Top windows of every source over their nearest training windows."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    output = Path(output)
    report = json.loads((output/"copy_check.json").read_text())
    arrays = np.load(output/"copy_check.npz")
    names = [n for n in report["sources"] if n != "control_copy"]
    rows = max(len(report["top"][n]) for n in names)
    fig, axes = plt.subplots(rows, len(names), figsize=(6*len(names), 1.6*rows), sharex=True, squeeze=False)
    for c, name in enumerate(names):
        for k, item in enumerate(report["top"][name]):
            axes[k, c].plot(arrays[f"{name}/top_window"][k], lw=.8, label=name)
            axes[k, c].plot(arrays[f"{name}/top_train"][k], lw=.8, label="nearest train")
            axes[k, c].set_title(f"{name} r={item['r']:.3f} record {item['record']}", fontsize=8)
            axes[k, c].tick_params(labelsize=6)
    axes[0, 0].legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(output/"top_windows.png", dpi=110)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--data", nargs="+", required=True, help="shard roots (manifest.json under each)")
    parser.add_argument("--generated", nargs="+", required=True, metavar="NAME=PATH", help="generated.npy of a model")
    parser.add_argument("--queries", type=int, default=2000, help="windows per source (trial runs use fewer)")
    parser.add_argument("--limit", type=int, help="compare only the first LIMIT training windows (trial only)")
    parser.add_argument("--expect-train", type=int, help="fail unless this many training windows are mounted")
    parser.add_argument("--hours", type=float, default=11.)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args(argv)
    from ml.kaggle_physigpt.judge_physigpt import Real
    real = Real(args.data)
    held_rows = real.pick("held_out", args.queries)
    generated, digests = {}, {}
    for item in args.generated:
        name, path = item.split("=", 1)
        windows, digests[name] = eval_part(path)
        generated[name] = windows[:args.queries]
    report = run(real.data, generated, args.output, held_rows, args.limit, args.expect_train, args.hours,
                 threads=args.threads, log=lambda text: print(text, flush=True))
    report["generated_sha256"] = digests
    # Identifies the held-out draw: the scoring runs of the same rows report the same median.
    report["held_skew_median"] = float(np.median(stats.skew(real.windows(held_rows), axis=1)))
    (Path(args.output)/"copy_check.json").write_text(json.dumps(report, indent=1))
    figure(args.output)


def package(output, owner, kernels, datasets, models, extra=()):
    """Write a private CPU kernel in the payload format of stage.py. kernels, datasets: slugs of the shards. models:
    {name: (slug, "kernel" or "dataset")}, each slug holding exactly one generated.npy."""
    import base64
    import subprocess
    import zlib
    from ml.kaggle_physigpt import stage as st
    root = Path(__file__).resolve().parents[2]
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip()
    if not branch.startswith("claude/model-benchmark"):
        raise RuntimeError("Stage this experiment from its dedicated branch")
    names = st.SOURCES["judge"]+["ml/kaggle_physigpt/copy_check.py"]
    files = {name: (root/name).read_text() for name in names}
    hashes = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}
    payload = base64.b64encode(zlib.compress(json.dumps(files).encode())).decode()
    entry = (st.mount_lookup(owner)
             + "import os, subprocess\n"
             f"models = { {name: slug for name, (slug, _) in models.items()}!r}\n"
             "generated = []\n"
             "for name, slug in models.items():\n"
             "    found = sorted(pathlib.Path(mounted(slug)).rglob('generated.npy'))\n"
             "    if len(found) != 1:\n"
             "        raise FileNotFoundError(f'{slug}: expected one generated.npy, found {found}')\n"
             "    generated.append(f'{name}={found[0]}')\n"
             f"data = [mounted(slug) for slug in {[*kernels, *datasets]!r}]\n"
             "subprocess.run([sys.executable, '-m', 'ml.kaggle_physigpt.copy_check', '/kaggle/working/copy_check',\n"
             f"                '--data', *data, '--generated', *generated, *{list(extra)!r}],\n"
             "               env={**os.environ, 'PYTHONPATH': str(root)}, check=True)\n")
    body = ("import base64, json, pathlib, sys, zlib\n"
            "root = pathlib.Path('/tmp/ppg_research_source')\nroot.mkdir(exist_ok=True)\n"
            f"FILES = json.loads(zlib.decompress(base64.b64decode({payload!r})))\n"
            "for name, text in FILES.items():\n    path = root/name\n    path.parent.mkdir(parents=True, exist_ok=True)\n"
            "    path.write_text(text)\nsys.path.insert(0, str(root))\n"
            f"pathlib.Path('/kaggle/working/source_manifest.json').write_text({json.dumps(dict(branch=branch, files=hashes))!r})\n"
            + entry)
    script = "if __name__ == '__main__':\n"+"\n".join("    "+line for line in body.splitlines())+"\n"
    compile(script, "run.py", "exec")
    meta = dict(id=f"{owner}/ppg-physigpt-copy-check-v1", title="ppg-physigpt-copy-check-v1", code_file="run.py",
                language="python", kernel_type="script", is_private=True, enable_gpu=False, enable_tpu=False,
                enable_internet=False, competition_sources=[], model_sources=[],
                dataset_sources=[f"{owner}/{s}" for s in [*datasets, *(s for s, k in models.values() if k == "dataset")]],
                kernel_sources=[f"{owner}/{s}" for s in [*kernels, *(s for s, k in models.values() if k == "kernel")]])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output/"run.py").write_text(script)
    (output/"kernel-metadata.json").write_text(json.dumps(meta, indent=2)+"\n")
    (output/"source_manifest.json").write_text(json.dumps(dict(branch=branch, files=hashes), indent=2)+"\n")
    return output


if __name__ == "__main__":
    main()
