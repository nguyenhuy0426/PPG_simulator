"""Does a faster APFT runtime change what it generates? Distribution check, not sample-by-sample (sampling is
autoregressive, so any rounding change sends a window down another path).

For each variant, N windows at requested HRs spread over 50-150 bpm with seed S1 are compared with fp32 windows of
the same HRs: per feature 1 - KS (the judge's 22 features, ml/kaggle_physigpt/judge_physigpt.all_features), the
mean over features, and the requested-vs-measured rate error. The reference row is fp32 against fp32 with another
seed: the spread sampling alone gives. Quantised variants use the qnnpack engine, as on the Pi 4.
Run from the repo root: python scripts/apft_quant_quality.py --n 192"""
import argparse, json, os, sys, time
sys.path.insert(0, os.getcwd())
import numpy as np
import torch
from core import apft_fast
from core.apft_preview import DEFAULT_APFT_BUNDLE
from ml.kaggle_physigpt.judge_physigpt import all_features, finite_similarity

parser = argparse.ArgumentParser()
parser.add_argument("--n", type=int, default=192)
parser.add_argument("--batch", type=int, default=64)
parser.add_argument("--out")
args = parser.parse_args()
path = DEFAULT_APFT_BUNDLE / "generator.pt"
hr = np.linspace(50, 150, args.n).astype(np.float32)


def windows(model, seed):
    out = []
    with torch.inference_mode():
        for start in range(0, args.n, args.batch):
            h = torch.from_numpy(hr[start:start + args.batch])
            out.append(model.generate(len(h), steps=16, seed=seed + start, hr=h).numpy())
    return np.concatenate(out).astype(np.float64)


fp32 = apft_fast.fast(apft_fast.load(path))
torch.backends.quantized.engine = "qnnpack"
names = {n for n, m in fp32.named_modules() if isinstance(m, torch.nn.Linear) and n != "embed"}
int8 = apft_fast.fast(torch.ao.quantization.quantize_dynamic(apft_fast.load(path), names, dtype=torch.qint8))
sets = {}
for label, model, seed in (("fp32 seed A", fp32, 1000), ("fp32 seed B", fp32, 5000), ("int8 seed A", int8, 1000),
                           ("int8 seed B", int8, 5000)):
    t = time.monotonic()
    sets[label] = windows(model, seed)
    print(f"{label}: {len(sets[label])} windows in {time.monotonic() - t:.0f} s", flush=True)
features = {k: all_features(v) for k, v in sets.items()}
report = {}
ref = features["fp32 seed A"]
for label in ("fp32 seed B", "int8 seed A", "int8 seed B"):
    sim = {k: finite_similarity(ref[k], features[label][k]) for k in ref}
    rate = features[label]["rate_bpm"]
    report[label] = dict(mean_similarity=float(np.mean(list(sim.values()))), lowest=min(sim, key=sim.get),
                         lowest_value=min(sim.values()),
                         rate_mae_bpm=float(np.nanmean(np.abs(rate - hr))), per_feature=sim)
report["fp32 seed A"] = dict(rate_mae_bpm=float(np.nanmean(np.abs(ref["rate_bpm"] - hr))))
for label, r in report.items():
    print(label, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k != "per_feature"})
if args.out:
    json.dump(dict(n=args.n, hr=[50, 150], report=report), open(args.out, "w"), indent=1)
