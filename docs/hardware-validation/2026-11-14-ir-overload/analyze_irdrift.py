"""Summarise irdrift.py output: per-phase IR/RED medians every 3 s, jumps, DAC readback, pulsed on-levels."""
import gzip, json, statistics as st, sys
path = sys.argv[1]
d = json.load(gzip.open(path) if path.endswith(".gz") else open(path))
marks = d["marks"] + [("end", d["rows"][-1][0], 0)]
codes = {(ir, red) for _, ir, red, *_ in d["info"]}
print("DAC readback codes (IR, RED):", sorted(codes))
temps = [i[3] for i in d["info"]]
print(f"CPU {min(temps):.1f}-{max(temps):.1f} C, under-voltage flags {sorted({i[4] for i in d['info']})}")
for (name, start, ir_mv), (_, stop, _) in zip(marks, marks[1:]):
    if name == "pulsed_1000":
        continue
    rows = [r for r in d["rows"] if start <= r[0] < stop]
    for idx, lane in ((2, "IR "), (1, "RED")):
        meds, t = [], start
        while t < stop:
            w = [r[idx] for r in rows if t <= r[0] < t + 3]
            if w: meds.append(round(st.median(w)))
            t += 3
        # jumps: 0.2 s medians stepping > 40 mV
        bins, t = [], start
        while t < stop:
            w = [r[idx] for r in rows if t <= r[0] < t + 0.2]
            if w: bins.append((round(t - start, 1), st.median(w)))
            t += 0.2
        jumps = [(b[0], round(b[1] - a[1])) for a, b in zip(bins[2:], bins[3:]) if abs(b[1] - a[1]) > 40]
        print(f"{name:12s} {lane} IR={ir_mv:4d}  3s-medians {meds}  jumps>40mV {jumps[:8]}")
p = d["pulses"]
if p:
    on = [(t, st.median(r), dk, red) for t, r, dk, red in p]
    t0 = on[0][0]
    for k in range(0, len(on), max(1, len(on) // 12)):
        t, v, dk, red = on[k]
        print(f"pulse t+{t - t0:5.1f}s on {v:6.0f}  off {dk:4d}  RED {red}")
