"""AC per DC step from dc_sweep_ac.py output, the project's AC definition (core/rx_spo2.py) on TX and RX alike.

AC = median over beats of the peak-to-trough swing, each beat from one pulse peak to the next with the straight
line through its ends removed. TX is the commanded AC part (generator display signal, DAC voltage minus DC);
RX is the OPT101 voltage the Grove ADC read. Run from the repository root.
Usage: python analyze_sweep.py SWEEP.json OUT.csv [--settle 3]
"""
import csv
import json
import sys

sys.path.insert(0, ".")
from core.rx_heart_rate import DETREND_S, _moving_average, _percentile, band_pass, pulse_peaks  # noqa: E402
from core.rx_spo2 import SWING_SMOOTH, _beat_swing, _swing  # noqa: E402
from hw.opt101_rx import raw_to_millivolts  # noqa: E402

HZ = 100.0


def grid(points, hz=HZ):
    """(t, v) points, oldest first, linearly interpolated onto a uniform grid; also the longest hole in s."""
    t0, t1 = points[0][0], points[-1][0]
    n = int((t1 - t0) * hz)
    out, j = [], 0
    for i in range(n):
        t = t0 + i / hz
        while points[j + 1][0] < t:
            j += 1
        (ta, va), (tb, vb) = points[j], points[j + 1]
        w = 0.0 if tb == ta else (t - ta) / (tb - ta)
        out.append(va + w * (vb - va))
    hole = max(b[0] - a[0] for a, b in zip(points, points[1:]))
    return out, hole


def beat_ac(x, hz=HZ):
    """(median, p25, p75, beats) of the per-beat swings."""
    edge = round(DETREND_S * hz / 2)
    bp = band_pass(x, hz)
    core = bp[edge:len(bp) - edge]
    peaks = [p + edge for p in pulse_peaks(core, hz, _swing(core))]
    smooth = _moving_average(x, SWING_SMOOTH)
    swings = sorted(_beat_swing(smooth[a:b + 1]) for a, b in zip(peaks, peaks[1:]) if b - a >= 2)
    if not swings:
        return None, None, None, 0
    return _percentile(swings, .5), _percentile(swings, .25), _percentile(swings, .75), len(swings)


def main():
    path, out = sys.argv[1], sys.argv[2]
    settle = float(sys.argv[sys.argv.index("--settle") + 1]) if "--settle" in sys.argv else 3.0
    data = json.load(open(path))
    rows = []
    for step in data["steps"]:
        row = {"dc_mv": step["dc_mv"], "set_ac_ir": step["set"]["ac_ir"], "set_ac_red": step["set"]["ac_red"]}
        tx = [r for r in step["tx"] if r[0] >= step["tx_change_stamp"] + settle]
        for k, name in ((1, "IR"), (2, "RED")):
            values = [r[k] for r in tx]
            ac, lo, hi, beats = beat_ac(values)
            row[f"tx_ac_{name}"], row[f"tx_beats_{name}"] = ac, beats
            rx = [(t, raw_to_millivolts(raw), sat) for t, raw, sat in step["rx"][name] if t >= step["t0"] + settle]
            if len(rx) < 200:
                row[f"rx_ac_{name}"] = None
                continue
            values, hole = grid([(t, v) for t, v, _s in rx])
            ac_rx, lo_rx, hi_rx, beats_rx = beat_ac(values)
            row.update({f"rx_ac_{name}": ac_rx, f"rx_ac_iqr_{name}": None if ac_rx is None else hi_rx - lo_rx,
                        f"rx_beats_{name}": beats_rx, f"rx_dc_{name}": sum(v for _t, v, _s in rx) / len(rx),
                        f"rx_max_{name}": max(v for _t, v, _s in rx),
                        f"rx_sat_{name}": sum(s for _t, _v, s in rx) / len(rx),
                        f"rx_hole_s_{name}": hole, f"rx_hz_{name}": (len(rx) - 1) / (rx[-1][0] - rx[0][0])})
            if ac_rx is not None and ac is not None:
                row[f"delta_{name}"] = ac_rx - ac
                row[f"gain_{name}"] = ac_rx / ac
        rows.append(row)
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k != "dc_mv", k))
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        w.writerows(rows)
    print(f"{'DC':>5} | {'TX IR':>6} {'RX IR':>6} {'Δ IR':>7} {'RX/TX':>5} {'DC rx':>6} | "
          f"{'TX RED':>6} {'RX RED':>6} {'Δ RED':>7} {'RX/TX':>5} {'DC rx':>6} | sat IR/RED")
    f = lambda v, p=1: "  —" if v is None else f"{v:.{p}f}"  # noqa: E731
    for r in rows:
        print(f"{r['dc_mv']:5.0f} | {f(r.get('tx_ac_IR')):>6} {f(r.get('rx_ac_IR')):>6} {f(r.get('delta_IR')):>7} "
              f"{f(r.get('gain_IR'), 2):>5} {f(r.get('rx_dc_IR'), 0):>6} | {f(r.get('tx_ac_RED')):>6} "
              f"{f(r.get('rx_ac_RED')):>6} {f(r.get('delta_RED')):>7} {f(r.get('gain_RED'), 2):>5} "
              f"{f(r.get('rx_dc_RED'), 0):>6} | {f(r.get('rx_sat_IR'), 3)}/{f(r.get('rx_sat_RED'), 3)}")


if __name__ == "__main__":
    main()
