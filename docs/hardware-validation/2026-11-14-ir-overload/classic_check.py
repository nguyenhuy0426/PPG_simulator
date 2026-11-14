"""Headless Classic run on the real DACs/ADC with the saved config; reports RX baseline and pulse swing per window."""
import json, os, statistics as st, sys, time
sys.path.insert(0, os.getcwd())
import instance_lock
instance_lock.acquire()
from config_store import load_config, apply_config_to_params
from core.signal_engine import SignalEngine
from hw.opt101_rx import OPT101Receiver, raw_to_millivolts
from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0
eng = SignalEngine.get_instance(); eng.begin()
apply_config_to_params(load_config(), eng.ppg_params)
p = eng.ppg_params
print(f"config IR DC {p.dc_ir_mv} AC {p.ac_ir_mv} | RED DC {p.dc_red_mv} AC {p.ac_red_mv}", flush=True)
rx = OPT101Receiver.get_instance(); assert rx.begin(); rx.start()
eng.start_simulation(p.condition)
t0 = time.monotonic(); acc = {ADC_CHANNEL_IR: [], ADC_CHANNEL_RED: []}; last = {k: t0 for k in acc}
while time.monotonic() - t0 < DUR:
    time.sleep(2.0)
    for ch in acc:
        new = [x for x in rx.get_samples_since(ch, last[ch]) if x.timestamp > last[ch]]
        if new:
            acc[ch] += new; last[ch] = new[-1].timestamp
stats = eng.get_stats(); eng.stop_simulation(); rx.shutdown(); eng.shutdown()
out = {"stats": stats, "lanes": {}}
for name, ch in (("IR", ADC_CHANNEL_IR), ("RED", ADC_CHANNEL_RED)):
    s = [(x.timestamp - t0, raw_to_millivolts(x.raw)) for x in acc[ch]]
    out["lanes"][name] = s
    print(f"{name} A{ch}: {len(s)} samples, errors {rx.error_count(ch)}, saturated {rx.saturation_count(ch)}")
    for w in range(0, int(DUR), 10):
        v = sorted(m for t, m in s if w <= t < w + 10)
        if len(v) < 50:
            continue
        p5, p95 = v[len(v) // 20], v[-len(v) // 20]
        print(f"  {w:3d}-{w+10:3d}s median {st.median(v):6.0f} mV  pulse p5-p95 {p95 - p5:5.0f} mV  min {v[0]:5.0f} max {v[-1]:5.0f}")
print("engine", stats)
json.dump(out, open(os.path.expanduser("~/ppg-evidence/classic-check.json"), "w"))
