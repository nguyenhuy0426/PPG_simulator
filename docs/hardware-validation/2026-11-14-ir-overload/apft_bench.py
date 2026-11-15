"""Time APFT-GAN v3 (checkpoint 1250) on the Pi as the app runs it, plus CPU and memory.
Run from the repo root: OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python apft_bench.py"""
import os, sys, time, json, threading
sys.path.insert(0, os.getcwd())
CLK = os.sysconf("SC_CLK_TCK")
def proc_cpu():
    f = open("/proc/self/stat").read().rsplit(")", 1)[1].split()
    return (int(f[11]) + int(f[12])) / CLK
def sys_cpu():
    v = [int(x) for x in open("/proc/stat").readline().split()[1:]]
    return sum(v), v[3] + v[4]
def rss_mb():
    for line in open("/proc/self/status"):
        if line.startswith("VmHWM"): return int(line.split()[1]) / 1024
def temp(): return int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
peak_freq = [0]
def watch(stop):
    while not stop.is_set():
        try: peak_freq[0] = max(peak_freq[0], int(open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq").read()))
        except OSError: pass
        time.sleep(0.5)
def measure(label, fn):
    w0, p0, (t0, i0) = time.monotonic(), proc_cpu(), sys_cpu()
    out = fn()
    w1, p1, (t1, i1) = time.monotonic(), proc_cpu(), sys_cpu()
    wall, cpu = w1 - w0, p1 - p0
    total = 100 * (1 - (i1 - i0) / (t1 - t0))
    r = dict(label=label, wall_s=round(wall, 2), proc_cpu_s=round(cpu, 2),
             proc_pct_of_one_core=round(100 * cpu / wall, 1), system_pct_all_4_cores=round(total, 1),
             peak_rss_mb=round(rss_mb()), temp_c=temp())
    print(json.dumps(r), flush=True)
    return out, r
stop = threading.Event(); threading.Thread(target=watch, args=(stop,), daemon=True).start()
import torch
from core.apft_preview import APFTSequenceGenerator
print(json.dumps(dict(torch=torch.__version__, env={k: os.environ.get(k) for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")})), flush=True)
gen, _ = measure("load (sha256 + torch.load + build)", APFTSequenceGenerator)
print(json.dumps(dict(threads=torch.get_num_threads())), flush=True)
def window(seed, hr):
    with torch.inference_mode():
        w = gen.model.generate(1, steps=16, seed=seed, hr=hr)
    assert tuple(w.shape) == (1, 1200) and torch.isfinite(w).all()
    return w
for seed, hr in ((1, 75.0), (2, 120.0), (3, 60.0)):
    measure(f"1 thread (app setting): 30 s window seed {seed} HR {hr}", lambda: window(seed, hr))
torch.set_num_threads(4)
for seed, hr in ((4, 75.0), (5, 120.0)):
    measure(f"4 threads: 30 s window seed {seed} HR {hr}", lambda: window(seed, hr))
stop.set(); print(json.dumps(dict(peak_cpu0_khz=peak_freq[0])), flush=True)
