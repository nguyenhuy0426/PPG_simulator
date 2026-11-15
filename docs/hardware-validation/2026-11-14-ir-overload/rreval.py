import json, sys
sys.path.insert(0, ".")
from hw.opt101_rx import RXSample
from core.rx_resp_rate import estimate_rx_rr
d = json.load(open(sys.argv[1]))
for st in d["steps"]:
    ir = [RXSample(t, r, r >= 4095) for t, r in st["ir"]]; red = [RXSample(t, r, r >= 4095) for t, r in st["red"]]
    t0 = ir[0].timestamp
    for label, kw in (("IR", {}), ("IR+RED", {"red_samples": red})):
        out = []
        for end in range(35, 64, 4):
            r = estimate_rx_rr(ir, now=t0 + end, max_gap_s=.25, **kw)
            out.append(f"{end}s:{round(r.brpm,1) if r.brpm else r.reason}({r.quality:.1f})")
        print(f"RR {st['rr']:4} {label:7}", " ".join(out))
