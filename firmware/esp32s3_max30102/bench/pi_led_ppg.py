"""Drive the simulator LEDs with the Classic PPG for an external sensor (MAX30102 bench), app stopped.

Usage (on the Pi, from the app directory, with the GUI app stopped; takes the app's instance lock):
    .venv/bin/python pi_led_ppg.py --hr 75 --dc 500 --ac 45 --seconds 120 [--off-first 10] [--channels both|ir|red]

The saved config (SpO2, RR, noise ...) is the base; HR, DC and AC come from the arguments. With --off-first N
the LEDs stay dark for N seconds before the PPG starts (a dark reference for the sensor). Every 5 s it prints the
OPT101 receive level (A4 = IR, A0 = RED) as evidence that the LEDs emit. TX values are commanded, not measured.
Both DACs are parked at 0 V on exit, including Ctrl-C and SIGTERM.
"""
import argparse
import os
import signal
import statistics as st
import sys
import time

sys.path.insert(0, os.getcwd())
import instance_lock  # noqa: E402
instance_lock.acquire()
from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED  # noqa: E402
from config_store import apply_config_to_params, load_config  # noqa: E402
from core.signal_engine import SignalEngine  # noqa: E402
from hw.opt101_rx import OPT101Receiver, raw_to_millivolts  # noqa: E402

REPORT_S = 5.0
DC_MAX_MV = 700.0   # IR receive level fades when held above ~600-750 mV (docs/hardware-validation/2026-11-14)


def _stop(_sig, _frm):
    raise KeyboardInterrupt


def rx_summary(rx, since):
    out = []
    for name, ch in (("IR", ADC_CHANNEL_IR), ("RED", ADC_CHANNEL_RED)):
        v = [raw_to_millivolts(s.raw) for s in rx.get_samples_since(ch, since)]
        out.append(f"{name} n={len(v)} med {st.median(v):6.0f} mV pp {max(v) - min(v):5.0f}" if v else f"{name} n=0")
    return "  ".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hr", type=float, default=75.0)
    ap.add_argument("--dc", type=float, default=500.0, help="DC baseline, mV (both LEDs unless --channels)")
    ap.add_argument("--ac", type=float, default=45.0, help="AC amplitude, mV")
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--off-first", type=float, default=0.0)
    ap.add_argument("--channels", choices=("both", "ir", "red"), default="both")
    args = ap.parse_args()
    if not 0.0 <= args.dc <= DC_MAX_MV:
        raise SystemExit(f"--dc must be 0..{DC_MAX_MV:.0f} mV")
    signal.signal(signal.SIGTERM, _stop)

    eng = SignalEngine.get_instance()
    rx = OPT101Receiver.get_instance()
    try:
        eng.begin()
        if not eng.dac_manager.is_ready:
            raise SystemExit("DACs not ready")
        rx_ok = rx.begin() and rx.start()
        if args.off_first > 0:
            print(f"LEDs dark for {args.off_first:.0f} s", flush=True)
            t0 = time.monotonic()
            time.sleep(args.off_first)
            print("dark: " + (rx_summary(rx, t0) if rx_ok else "RX unavailable"), flush=True)

        apply_config_to_params(load_config(), eng.ppg_params)
        p = eng.ppg_params
        p.lock_ac, p.lock_dc = False, False
        p.output_dc_offset_mv = 0.0
        dc_ir = args.dc if args.channels in ("both", "ir") else 0.0
        dc_red = args.dc if args.channels in ("both", "red") else 0.0
        ac_ir = args.ac if dc_ir else 0.0
        ac_red = args.ac if dc_red else 0.0
        p.dc_ir_mv, p.dc_red_mv, p.ac_ir_mv, p.ac_red_mv = dc_ir, dc_red, ac_ir, ac_red
        p.heart_rate = args.hr
        eng.start_simulation(p.condition)
        eng.update_heart_rate(args.hr)
        eng.update_ac_dc(ac_ir, dc_ir, dc_red)
        eng.update_ac_levels(ac_ir, ac_red)
        q = eng.ppg_params
        print(f"PPG on: HR {q.heart_rate:.0f} bpm  IR DC {q.dc_ir_mv:.0f}/AC {q.ac_ir_mv:.1f} mV  "
              f"RED DC {q.dc_red_mv:.0f}/AC {q.ac_red_mv:.1f} mV  for {args.seconds:.0f} s", flush=True)
        t_start = time.time()
        while time.time() - t_start < args.seconds:
            t0 = time.monotonic()
            time.sleep(REPORT_S)
            print(f"t={time.time() - t_start:5.0f} s  " + (rx_summary(rx, t0) if rx_ok else "RX unavailable"),
                  flush=True)
    except KeyboardInterrupt:
        print("stopped", flush=True)
    finally:
        try:
            eng.stop_simulation()
        finally:
            rx.shutdown()
            eng.shutdown()
            print("DACs parked", flush=True)


if __name__ == "__main__":
    main()
