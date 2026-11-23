# On the Pi, app stopped: Model (Gaussian) and Recording clips through the app's SignalEngine in MAX30102 mode,
# OPT101 RX running as in the app. Prints "flicker on: HR x" / "flicker off" markers for an_live.py.
import os, sys, time
sys.path.insert(0, os.getcwd())
import instance_lock; instance_lock.acquire()
from core.signal_engine import SignalEngine
from core.neural_preview import gaussian_preview
from core.waveform_clip import WaveformClip, pulse_span
from hw.opt101_rx import OPT101Receiver
from ui.recordings import load_recording
from config_store import load_config, apply_config_to_params
REC = sys.argv[1] if len(sys.argv) > 1 else "dataset/data_1.csv"
eng = SignalEngine.get_instance(); rx = OPT101Receiver.get_instance()
try:
    eng.begin(); rx_ok = rx.begin() and rx.start()
    p = eng.get_ppg_params(); apply_config_to_params(load_config(), p); eng.load_parameters(p)
    eng.set_max30102_mode(True)
    samples, params, _ = load_recording(REC)
    hrs = [q[0] for q in params if q[0] is not None]
    rec_hr = round(sum(hrs) / len(hrs)) if hrs else 0
    clips = [(80, WaveformClip.from_preview(gaussian_preview(80), 1500, 45)),
             (rec_hr, WaveformClip.from_recording(samples, os.path.basename(REC)))]
    print(f"rx {rx_ok}; recording {REC}: {len(samples)} rows, HR set {min(hrs) if hrs else '-'}-{max(hrs) if hrs else '-'}", flush=True)
    print(f"{time.time():.3f} dark 8 s", flush=True); time.sleep(8)
    for hr, clip in clips:
        print(f"clip {clip.name}: {clip.duration:.1f} s, span {pulse_span(clip)}", flush=True)
        eng.start_waveform(clip); eng.reset_stats(); t0 = time.monotonic()
        print(f"{time.time():.3f} flicker on: HR {hr}", flush=True)
        while eng.is_running and time.monotonic() - t0 < 45:
            time.sleep(0.2)
        dt = time.monotonic() - t0
        eng.stop_simulation(); st = eng.get_stats()   # the writer's count is added when it stops
        print(f"{time.time():.3f} flicker off: {dt:.1f} s writes/s {st['max30102_writes']/dt:.0f} clipped {st['max30102_clipped']} "
              f"red_err {eng.dac_manager.error_count_red} rx running again {rx.is_running}", flush=True)
        time.sleep(3)
finally:
    rx.shutdown(); eng.shutdown()
    print("DACs parked", flush=True)
