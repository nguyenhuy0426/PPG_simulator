"""Classic path without GUI: user's saved parameters, SpO2 swept, RX SpO2/R vs the TX target.
Run from the app dir with the app stopped: python spo2sweep.py out.json"""
import json, sys, time
sys.path.insert(0, '.')
from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED
from config_store import load_config, apply_config_to_params
from core.signal_engine import SignalEngine
from core.rx_spo2 import estimate_rx_spo2
from core.rx_heart_rate import latest_stretch
from hw.opt101_rx import OPT101Receiver, raw_to_millivolts
eng = SignalEngine.get_instance(); eng.begin()
rx = OPT101Receiver.get_instance(); rx.begin(); rx.start()
p = eng.get_ppg_params(); apply_config_to_params(load_config(), p); eng.load_parameters(p)
p.ac_red_mv = None; eng.load_parameters(p)   # SpO2 drives RED AC
p = eng.get_ppg_params()
info = {k: getattr(p, k) for k in ("heart_rate", "spo2", "perfusion_index", "dc_ir_mv", "dc_red_mv", "ac_ir_mv",
        "ac_red_mv", "ac_polarity", "spo2_coeff_a", "spo2_coeff_b", "noise_level", "spo2_coupling_enabled") if hasattr(p, k)}
print("params", info, flush=True)
eng.start_simulation()
out = {"params": info, "steps": []}
try:
    for spo2 in (99, 95, 90, 85, 80, 75, 70):
        eng.update_spo2(spo2); time.sleep(32)
        now = time.monotonic()
        ir = rx.get_samples_since(ADC_CHANNEL_IR, now - 25); red = rx.get_samples_since(ADC_CHANNEL_RED, now - 25)
        res = estimate_rx_spo2(ir, red, p.spo2_coeff_a, p.spo2_coeff_b)
        m = eng.model if hasattr(eng, "model") else None
        tx = {k: getattr(m, k, None) for k in ("last_ac_ir", "last_ac_red", "dc_ir", "dc_red")} if m else {}
        mv = lambda s: sorted(raw_to_millivolts(x.raw) for x in s)
        ir_mv, red_mv = mv(ir), mv(red)
        pct = lambda v, q: v[int(q * (len(v) - 1))]
        r_target = (p.spo2_coeff_a - spo2) / p.spo2_coeff_b
        step = dict(spo2=spo2, r_target=r_target, rx=res.__dict__, tx=tx,
                    ir_p5_p95=(pct(ir_mv, .05), pct(ir_mv, .95)), red_p5_p95=(pct(red_mv, .05), pct(red_mv, .95)),
                    n=(len(ir), len(red)), ir_raw=[(x.timestamp, x.raw, x.saturated) for x in ir], red_raw=[(x.timestamp, x.raw, x.saturated) for x in red])
        out["steps"].append(step)
        print({k: v for k, v in step.items() if not k.endswith('_raw')}, flush=True)
finally:
    eng.stop_simulation(); json.dump(out, open(sys.argv[1], "w"), default=str)
