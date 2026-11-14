import json, sys, time, statistics as st
sys.path.insert(0, '.')
from core.rx_filter import filter_points
d = json.load(open(sys.argv[1]))
def spikes(v):
    m = [st.median(v[max(0,i-4):i+5]) for i in range(len(v))]
    return sum(1 for i in range(1, len(v)) if abs(v[i]-m[i]) > 15 and abs(v[i-1]-m[i-1]) <= 15)
for name, start in (("calib_steady", 11), ("calib_sine", 3), ("classic", 8)):
    for ch in ("4", "0"):
        pts = [(t, r*3280/4095) for t, r in d[name]["rx"][ch] if t > start]
        f = filter_points(pts, .25)
        raw, flt = [v for _, v in pts], [v for _, v in f]
        sw = lambda v: sorted(v)[-len(v)*3//100] - sorted(v)[len(v)*3//100]
        print(f"{name} A{ch}: spikes raw {spikes(raw)} -> filtered {spikes(flt)}; p3-p97 swing raw {sw(raw):.0f} -> {sw(flt):.0f} mV")
pts = [(i/100, 700 + (i % 7)) for i in range(800)]
t0 = time.perf_counter(); [filter_points(pts, .25) for _ in range(20)]
print(f"800-point lane: {(time.perf_counter()-t0)/20*1000:.1f} ms")
