"""Classic path without GUI (app stopped): user's saved parameters, RR stepped, raw IR/RED RX saved per step.
python rrcapture.py out.json"""
import json, sys, time
sys.path.insert(0, '.')
from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED
from config_store import load_config, apply_config_to_params
from core.signal_engine import SignalEngine
from hw.opt101_rx import OPT101Receiver
from models.respiration import RespirationConfig
VAR = float(sys.argv[2])
eng = SignalEngine.get_instance(); eng.begin()
rx = OPT101Receiver.get_instance(); rx.begin(); rx.start()
p = eng.get_ppg_params(); apply_config_to_params(load_config(), p); eng.load_parameters(p)
p = eng.get_ppg_params()
info = {k: getattr(p, k) for k in ("heart_rate", "spo2", "perfusion_index", "dc_ir_mv", "dc_red_mv", "ac_ir_mv", "ac_red_mv",
        "resp_rate", "resp_variation_ir_pct", "resp_variation_red_pct", "resp_mod_baseline", "resp_mod_amplitude",
        "resp_mod_frequency", "resp_ie_ratio", "apnea_enabled", "noise_level", "condition")}
print("params", info, flush=True)
out = {"params": info, "steps": []}
eng.start_simulation(p.condition)
try:
    for rr in (10.0, 18.0, 27.0, 36.0):
        eng.update_respiration(RespirationConfig(rate_brpm=rr, variation_ir_pct=VAR, variation_red_pct=VAR, inhale_exhale_ratio=1)); t0 = time.monotonic(); time.sleep(70)
        ir = rx.get_samples_since(ADC_CHANNEL_IR, t0); red = rx.get_samples_since(ADC_CHANNEL_RED, t0)
        out["steps"].append(dict(rr=rr, t0=t0, ir=[(s.timestamp, s.raw) for s in ir], red=[(s.timestamp, s.raw) for s in red]))
        print("rr", rr, "samples", len(ir), len(red), flush=True)
finally:
    eng.stop_simulation(); json.dump(out, open(sys.argv[1], "w"))
