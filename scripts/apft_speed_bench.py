"""APFT-GAN speed on this machine: loading and one 30 s window for each runtime variant, with CPU time and RSS.
Variants: fp32 (as shipped), fp32 + flow-head precompute, dynamic int8 Linear (+ precompute).
Run from the repo root: OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python scripts/apft_speed_bench.py [--threads 1 2]"""
import argparse, hashlib, json, os, sys, time
sys.path.insert(0, os.getcwd())
import torch
from core import apft_fast
from core.apft_network import build
from core.apft_preview import DEFAULT_APFT_BUNDLE

CLK = os.sysconf("SC_CLK_TCK")
def cpu():
    f = open("/proc/self/stat").read().rsplit(")", 1)[1].split()
    return (int(f[11]) + int(f[12])) / CLK
def rss_mb():
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS"): return int(line.split()[1]) / 1024
def timed(label, fn, **extra):
    w, c = time.monotonic(), cpu()
    out = fn()
    w, c = time.monotonic() - w, cpu() - c
    print(json.dumps(dict(label=label, wall_s=round(w, 2), cpu_pct_one_core=round(100 * c / w, 1),
                          rss_mb=round(rss_mb()), **extra)), flush=True)
    return out
def window(model, seed=42, hr=75.):
    with torch.inference_mode():
        return model.generate(1, steps=16, seed=seed, hr=hr)

parser = argparse.ArgumentParser()
parser.add_argument("--threads", type=int, nargs="+", default=[1])
parser.add_argument("--skip-baseline", action="store_true")
args = parser.parse_args()
path = DEFAULT_APFT_BUNDLE / "generator.pt"
torch.set_num_threads(1)
timed("sha256", lambda: hashlib.sha256(path.read_bytes()).hexdigest())
ref = timed("load fp32: torch.load + build (as shipped)", lambda: build(torch.load(path, map_location="cpu", weights_only=True)).eval())
fast = timed("load fp32: mmap + meta build", lambda: apft_fast.load(path))
q = timed("dynamic int8 quantisation", lambda: apft_fast.quantize(apft_fast.load(path)))
print(json.dumps(dict(engine=torch.backends.quantized.engine)), flush=True)
del ref
outs = {}
for threads in args.threads:
    torch.set_num_threads(threads)
    if not args.skip_baseline:
        outs["fp32"] = timed("window fp32 (as shipped)", lambda: window(fast), threads=threads)
    apft_fast.fast(fast)
    outs["fp32_fast"] = timed("window fp32 + precompute", lambda: window(fast), threads=threads)
    fast.integrate = type(fast).integrate.__get__(fast)
    apft_fast.fast(q)
    outs["int8_fast"] = timed("window int8 + precompute", lambda: window(q), threads=threads)
base = outs.get("fp32", outs["fp32_fast"])
for k, v in outs.items():
    print(json.dumps(dict(variant=k, max_abs_diff_vs_fp32=float((v - base).abs().max()),
                          corr=float(torch.corrcoef(torch.stack((v[0], base[0])))[0, 1]))), flush=True)
