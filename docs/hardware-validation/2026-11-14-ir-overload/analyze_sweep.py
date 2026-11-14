import json, sys
sys.path.insert(0, ".")
from collections import namedtuple
from core import rx_spo2 as m
from core.rx_heart_rate import latest_stretch, band_pass, pulse_peaks
S = namedtuple("S", "timestamp raw saturated")
d = json.load(open(sys.argv[1])); p = d["params"]
for st in d["steps"]:
    ir = [S(*x) for x in st["ir_raw"]]; red = [S(*x) for x in st["red_raw"]]
    res = m.estimate_rx_spo2(ir, red, p["spo2_coeff_a"], p["spo2_coeff_b"])
    a, b = latest_stretch(ir), latest_stretch(red)
    start = max(a[0].timestamp, b[0].timestamp); sec = min(a[-1].timestamp, b[-1].timestamp) - start
    n = int(sec * 100); ir_g, red_g = m._on_grid(a, start, n, 100.), m._on_grid(b, start, n, 100.)
    e = round(m.DETREND_S * 100 / 2)
    ai, ar = band_pass(ir_g, 100.)[e:n-e], band_pass(red_g, 100.)[e:n-e]
    corr = m._correlation(ai, ar)
    peaks = [q + e for q in pulse_peaks(ai, 100., m._swing(ai))]
    sw = sorted(m._beat_swing_ratios(ir_g, red_g, peaks))
    ir_sw = sorted(m._beat_swing(m._moving_average(ir_g, 3)[s:t+1]) for s, t in zip(peaks, peaks[1:]))
    red_sw = sorted(m._beat_swing(m._moving_average(red_g, 3)[s:t+1]) for s, t in zip(peaks, peaks[1:]))
    med = lambda v: v[len(v)//2] if v else None
    k = 3280/4095
    print(f"SpO2 {st['spo2']} Rt {st['r_target']:.2f} -> {res.reason} spo2={res.spo2} R={res.ratio} corr={corr:.2f} "
          f"stretch={sec:.1f}s beats={len(peaks)} ACir={med(ir_sw) and med(ir_sw)*k:.1f}mV ACred={med(red_sw) and med(red_sw)*k:.1f}mV "
          f"DCir={sum(ir_g)/n*k:.0f} DCred={sum(red_g)/n*k:.0f} swingR={med(sw)}")
