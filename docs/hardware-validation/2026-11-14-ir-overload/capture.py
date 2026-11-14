"""Headless app path (SignalEngine + OPT101Receiver, config.json params): Calib steady, Calib sine, Classic.
Saves every RX sample (t, raw) per channel plus TX history and engine stats."""
import json, sys, time
sys.path.insert(0, '.')
from config_store import load_config, apply_config_to_params
from core.signal_engine import SignalEngine
from hw.opt101_rx import OPT101Receiver
eng = SignalEngine.get_instance(); eng.begin()
rx = OPT101Receiver.get_instance(); rx.begin(); rx.start()
p = eng.get_ppg_params(); apply_config_to_params(load_config(), p); eng.load_parameters(p)
time.sleep(2)
out = {}
def run(name, start, seconds):
    eng.reset_stats(); t0 = time.monotonic(); start()
    time.sleep(seconds)
    out[name] = dict(t0=t0, stats=eng.get_stats(),
                     rx={ch: [(s.timestamp - t0, s.raw) for s in rx.get_samples_since(ch, t0)] for ch in (0, 4)})
    eng.stop_simulation(); time.sleep(3)
    n = {ch: len(v) for ch, v in out[name]["rx"].items()}
    print(name, "stats", out[name]["stats"], "samples", n, flush=True)
run("calib_steady", lambda: eng.start_calibration(1.0, 1000.0, 1000.0, 0.0), 20)
run("calib_sine", lambda: eng.start_calibration(1.0, 1000.0, 1000.0, 300.0), 20)
run("classic", lambda: eng.start_simulation(), 45)
print("params dc_ir", p.dc_ir_mv, "dc_red", p.dc_red_mv, "ac_ir", p.ac_ir_mv, "spo2", p.spo2, "hr", p.heart_rate)
json.dump(out, open(sys.argv[1], "w"))
