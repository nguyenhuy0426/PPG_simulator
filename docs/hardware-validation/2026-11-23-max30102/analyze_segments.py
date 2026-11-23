import gzip, json, re, sys
# usage: analyze_segments.py serial.log[.gz] pi.txt  -- firmware R lines per Pi segment (dark / flicker HR).
# The first 10 s of a flicker segment (the 8 s HR window filling) and 2 s of a dark one are skipped.
log, pi = sys.argv[1], sys.argv[2]
ev = []
for l in open(pi):
    m = re.match(r"(\d+\.\d+) (dark|flicker on: HR (\d+)|flicker off)", l)
    if m: ev.append((float(m.group(1)), m.group(2), m.group(3)))
segs = []
for k, (t, kind, hr) in enumerate(ev):
    if kind.startswith("dark"): segs.append(("dark", t, ev[k + 1][0] if k + 1 < len(ev) else t + 8))
    elif kind.startswith("flicker on"): segs.append((f"HR {hr}", t, ev[k + 1][0]))
rep = []
for l in (gzip.open(log, 'rt') if log.endswith('.gz') else open(log)):
    p = l.split(" ", 1)
    if len(p) == 2 and p[1].startswith('R,{"t_ms"'):
        rep.append((float(p[0]), json.loads(p[1][2:])))
for name, a, b in segs:
    rs = [d for t, d in rep if a + 10 <= t <= b] if name != "dark" else [d for t, d in rep if a + 2 <= t <= b]
    if not rs: continue
    states = {}
    for d in rs: states[d["state"]] = states.get(d["state"], 0) + 1
    hrs = [d["hr"] for d in rs if d["state"] == "OK"]
    acf = [d["red"]["hr_acf"] for d in rs]
    s = f"{name:7s} reports {len(rs):2d} states {states}"
    if hrs: s += f"  HR(OK) mean {sum(hrs)/len(hrs):6.1f} min {min(hrs):6.1f} max {max(hrs):6.1f}"
    s += f"  red ACF median {sorted(acf)[len(acf)//2]:6.1f}  ch {set(d['ch'] for d in rs)}"
    print(s)
