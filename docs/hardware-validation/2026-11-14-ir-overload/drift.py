"""Classic (config.json params) 150 s then Calib 1000/1000 for 40 s: RX every sample, DAC readback every 0.5 s."""
import json, sys, time, threading
sys.path.insert(0, '.')
from smbus2 import SMBus, i2c_msg
from config_store import load_config, apply_config_to_params
from core.signal_engine import SignalEngine
from hw.opt101_rx import OPT101Receiver
eng = SignalEngine.get_instance(); eng.begin()
rx = OPT101Receiver.get_instance(); rx.begin(); rx.start()
p = eng.get_ppg_params(); apply_config_to_params(load_config(), p); eng.load_parameters(p)
bus = SMBus(1)
def rb(a):
    m = i2c_msg.read(a, 5); bus.i2c_rdwr(m); b = list(m); return (b[1] << 4) | (b[2] >> 4)
dac_log, stop = [], threading.Event()
rx_log = {0: [], 4: []}
def sysinfo():
    t = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
    uv = int(open("/sys/class/hwmon/hwmon1/in0_lcrit_alarm").read())
    return t, uv
T0 = time.monotonic()
def poll():
    while not stop.is_set():
        try: dac_log.append((time.monotonic() - T0, rb(0x61), rb(0x60)) + sysinfo())
        except OSError: pass
        for ch in (0, 4):
            last = rx_log[ch][-1][0] + T0 if rx_log[ch] else T0
            rx_log[ch].extend((s.timestamp - T0, s.raw) for s in rx.get_samples_since(ch, last) if s.timestamp > last)
        time.sleep(0.5)
threading.Thread(target=poll, daemon=True).start()
time.sleep(3)
marks = {"calib1_start": time.monotonic() - T0}
eng.start_calibration(1.0, 1000.0, 1000.0, 0.0); time.sleep(30); eng.stop_simulation(); time.sleep(3)
marks["classic_start"] = time.monotonic() - T0
eng.start_simulation(); time.sleep(150); eng.stop_simulation()
marks["classic_stop"] = time.monotonic() - T0; time.sleep(3)
marks["calib_start"] = time.monotonic() - T0
eng.start_calibration(1.0, 1000.0, 1000.0, 0.0); time.sleep(40); eng.stop_simulation()
marks["calib_stop"] = time.monotonic() - T0; stop.set(); time.sleep(1)
out = dict(marks=marks, dac=dac_log, stats=eng.get_stats(),
           rx=rx_log)
json.dump(out, open(sys.argv[1], "w")); print("marks", marks, "n", {k: len(v) for k, v in out["rx"].items()}, "stats", out["stats"])
