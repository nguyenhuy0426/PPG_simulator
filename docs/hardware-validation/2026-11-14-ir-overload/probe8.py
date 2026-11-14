"""App path: SignalEngine.start_calibration + OPT101Receiver (no GUI). Time from start to first DAC write
and to A0 > 300 mV in the receiver buffer, 6 trials."""
import sys, time
sys.path.insert(0, '.')
from core.signal_engine import SignalEngine
from hw.opt101_rx import OPT101Receiver, raw_to_millivolts
eng = SignalEngine.get_instance(); eng.begin()
rx = OPT101Receiver.get_instance(); rx.begin(); rx.start()
time.sleep(2)
for trial in range(6):
    t0 = time.monotonic(); eng.start_calibration(1.0, 0.0, 1000.0, 0.0); on = None
    while time.monotonic() - t0 < 10:
        s = rx.get_samples_since(0, t0)
        hit = next((x.timestamp for x in s if raw_to_millivolts(x.raw) > 300), None)
        if hit: on = round(hit - t0, 3); break
        time.sleep(0.02)
    lvl = [raw_to_millivolts(x.raw) for x in rx.get_samples_since(0, time.monotonic() - 1)]
    print(f"trial {trial}: A0 > 300 mV after {on}s; last 1 s median {sorted(lvl)[len(lvl)//2] if lvl else None:.0f} mV", flush=True)
    eng.stop_simulation(); time.sleep(4)
rx.stop() if hasattr(rx, 'stop') else None
eng.stop_simulation()
