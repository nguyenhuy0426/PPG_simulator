"""Red simulator LED for a MAX30102 without sync hardware: fast on/off flicker whose on-level follows a PPG.

The MAX30102 subtracts an ambient sample (its own LED off) from each LED-on sample, so a steady or slowly
varying external light cancels (bench run of 23 Nov 2026). A light that changes between the two samples does
not cancel. This script toggles the red DAC between 0 and L(t) as fast as the I2C bus allows, where
L(t) = DC + AC * pulse(t) at the requested heart rate; the ESP32 recovers L(t) from the size of the residual.
It is an unsynchronised experiment, not a validated optical simulator. IR DAC stays at 0 V.

Usage (on the Pi, app stopped; takes the app's instance lock):
    .venv/bin/python pi_red_flicker.py --mode flicker --hr 75 --dc 600 --ac 200 --seconds 40 --off-first 10
    --mode steady writes L(t) without the flicker (control: should cancel as on 23 Nov).
Both DACs are parked at 0 V on exit, including Ctrl-C and SIGTERM.
"""
import argparse
import math
import os
import signal
import sys
import time

sys.path.insert(0, os.getcwd())
import instance_lock  # noqa: E402
instance_lock.acquire()
from smbus2 import SMBus  # noqa: E402
from config import DAC_ADDR_IR, DAC_ADDR_RED, DAC_FULLSCALE_MV, DAC_MAX_VALUE, I2C_BUS  # noqa: E402

PEAK_MAX_MV = 1000.0     # cap on the on-level (red channel; IR is not driven)
STEADY_RATE_HZ = 500.0
REPORT_S = 5.0


def code(mv):
    return max(0, min(DAC_MAX_VALUE, int(round(mv / DAC_FULLSCALE_MV * DAC_MAX_VALUE))))


def write(bus, addr, c):
    # MCP4725 fast-mode write: [0 0 PD1 PD0 D11..D8] [D7..D0], PD = 00 (normal)
    bus.write_byte_data(addr, (c >> 8) & 0x0F, c & 0xFF)


def pulse(phase):
    """Two-Gaussian PPG beat shape, peak normalised to 1."""
    a = math.exp(-((phase - 0.20) / 0.07) ** 2)
    b = 0.45 * math.exp(-((phase - 0.48) / 0.10) ** 2)
    return (a + b) / 1.0005


def _stop(_sig, _frm):
    raise KeyboardInterrupt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("flicker", "steady"), default="flicker")
    ap.add_argument("--hr", type=float, default=75.0)
    ap.add_argument("--dc", type=float, default=600.0, help="on-level baseline, mV")
    ap.add_argument("--ac", type=float, default=200.0, help="pulse amplitude added on top, mV")
    ap.add_argument("--seconds", type=float, default=40.0)
    ap.add_argument("--off-first", type=float, default=0.0)
    args = ap.parse_args()
    if args.dc < 0 or args.ac < 0 or args.dc + args.ac > PEAK_MAX_MV:
        raise SystemExit(f"need 0 <= dc, ac and dc + ac <= {PEAK_MAX_MV:.0f} mV")
    signal.signal(signal.SIGTERM, _stop)

    with SMBus(I2C_BUS) as bus:
        try:
            write(bus, DAC_ADDR_IR, 0)
            write(bus, DAC_ADDR_RED, 0)
            if args.off_first > 0:
                print(f"{time.time():.3f} dark {args.off_first:.0f} s", flush=True)
                time.sleep(args.off_first)
            print(f"{time.time():.3f} {args.mode} on: HR {args.hr:.0f} bpm, red L = {args.dc:.0f} + "
                  f"{args.ac:.0f}*pulse mV, {args.seconds:.0f} s", flush=True)
            t0 = time.monotonic()
            next_report = t0 + REPORT_S
            writes = errors = 0
            on = False
            while True:
                now = time.monotonic()
                t = now - t0
                if t >= args.seconds:
                    break
                level = args.dc + args.ac * pulse((t * args.hr / 60.0) % 1.0)
                if args.mode == "flicker":
                    on = not on
                    c = code(level) if on else 0
                else:
                    c = code(level)
                try:
                    write(bus, DAC_ADDR_RED, c)
                    writes += 1
                except OSError:
                    errors += 1
                if args.mode == "steady":
                    time.sleep(max(0.0, 1.0 / STEADY_RATE_HZ - (time.monotonic() - now)))
                if now >= next_report:
                    print(f"{time.time():.3f} t={t:5.1f} s  writes/s {writes / t:7.0f}  i2c errors {errors}",
                          flush=True)
                    next_report += REPORT_S
            print(f"{time.time():.3f} {args.mode} off: {writes} writes in {args.seconds:.0f} s "
                  f"({writes / args.seconds:.0f}/s), {errors} errors", flush=True)
        except KeyboardInterrupt:
            print("stopped", flush=True)
        finally:
            write(bus, DAC_ADDR_RED, 0)
            write(bus, DAC_ADDR_IR, 0)
            print(f"{time.time():.3f} DACs parked", flush=True)


if __name__ == "__main__":
    main()
