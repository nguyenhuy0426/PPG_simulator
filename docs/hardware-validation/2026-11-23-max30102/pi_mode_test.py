# On the Pi, app stopped: drive the app's SignalEngine in MAX30102 mode (with the OPT101 RX running, as in the app).
import os, sys, time
sys.path.insert(0, os.getcwd())
import instance_lock; instance_lock.acquire()
from core.signal_engine import SignalEngine
from hw.opt101_rx import OPT101Receiver
from config_store import load_config, apply_config_to_params
eng = SignalEngine.get_instance(); rx = OPT101Receiver.get_instance()
try:
    eng.begin(); rx_ok = rx.begin() and rx.start()
    p = eng.get_ppg_params(); apply_config_to_params(load_config(), p); eng.load_parameters(p)
    eng.set_max30102_mode(True)
    q = eng.ppg_params
    print(f"rx {rx_ok}; preset: RED DC {q.dc_red_mv} AC {q.ac_red_mv}; user: SpO2 {q.spo2} RR {q.resp_rate} noise {q.noise_kind}/{q.noise_amplitude_mv}", flush=True)
    print(f"{time.time():.3f} dark 8 s", flush=True); time.sleep(8)
    for hr in (75, 110):
        eng.update_heart_rate(hr)
        if not eng.is_running: eng.start_simulation(eng.ppg_params.condition)
        eng.reset_stats(); t0 = time.monotonic()
        print(f"{time.time():.3f} flicker on: HR {hr}", flush=True)
        time.sleep(40)
        dt = time.monotonic() - t0
        eng.stop_simulation(); st = eng.get_stats()   # the writer adds its count when it stops (pi_mode3.txt read it before: 0)
        print(f"{time.time():.3f} flicker off: writes/s {st['max30102_writes']/dt:.0f} clipped {st['max30102_clipped']} "
              f"underruns {st['underruns']} overruns {st['overruns']} red_err {eng.dac_manager.error_count_red}", flush=True)
    eng.stop_simulation()
finally:
    rx.shutdown(); eng.shutdown()
    print("DACs parked", flush=True)
