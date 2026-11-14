#!/usr/bin/env python3
"""calibrate_optical.py — Measure each LED -> OPT101 -> Grove ADC transfer and
recommend per-channel DC/AC DAC levels that keep the receiver in its linear range.

Run on the Pi with the app stopped (it takes the app's instance lock):
    .venv/bin/python scripts/calibrate_optical.py [--apply] [--report out.json]

For each channel, with the other LED off:
  1. dark level (LED off);
  2. short-pulse sweep (PULSE_S on, REST_S off) so self-heating and overload
     memory do not bias the curve;
  3. ceiling = the highest received level; knee = first DAC level that reaches it;
     window bottom = first level above the LED toe (TOE of the span);
  4. safe top = highest DAC level whose RX stays under HEADROOM of the
     dark-to-ceiling span, then held for HOLD_S: if RX collapses (falls more
     than COLLAPSE_DRIFT) the top is lowered and the hold repeated; a smaller
     drift either way is only reported, since lowering the drive does not cure it.
Recommended DC/AC centre the PPG swing (pulse-up, DC .. DC+AC) between the
window bottom and the verified safe top; PI = AC/DC stays inside the app limit.

Why: on 2026-11-14 the IR path reached a ~2.0 V ceiling at only ~550 mV DAC,
and any drive above that knee made the IR reading fall by ~45 % within 20 s
and stay depressed for seconds after. That is what clipped the Calib sine and
made Classic IR drift and lose amplitude. These are engineering levels for this
optical assembly, not an optical or SpO2 calibration.

--apply writes dc_*/ac_* (and the matching PI) into config.json after copying
the old file to config.json.bak-<time>. Both DACs are parked at 0 V on exit.
"""

import argparse
import json
import os
import shutil
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import (ADC_CHANNEL_IR, ADC_CHANNEL_RED, CONFIG_JSON_PATH,  # noqa: E402
                    DAC_IDLE_VALUE, GROVE_ADC_ADDR)
from calibration import dac_voltage_to_code  # noqa: E402

PULSE_S = 0.04          # LED on before the RX read; RC + OPT101 settle in a few ms
REST_S = 0.8            # LED off between pulses
SWEEP_STEP_MV = 50
SWEEP_MAX_MV = 2000
MIN_SIGNAL_MV = 30      # RX above dark that counts as "LED on"
CEILING_BAND_MV = 30    # RX within this of the ceiling counts as saturated
CEILING_STEPS = 3       # sweep stops after this many steps on the ceiling
HEADROOM = 0.70         # safe top: RX <= dark + HEADROOM * (ceiling - dark)
TOE = 0.15              # window bottom: RX >= dark + TOE * (ceiling - dark), above the LED toe
HOLD_S = 20.0
COLLAPSE_DRIFT = -0.15  # hold falling this much = overload collapse: lower the top and retry
STABLE_DRIFT = 0.05     # |drift| above this is reported as an unstable path (not fixed by lowering)
HOLD_RETRIES = 4
COOL_S = 8.0            # LED off before each hold, overload memory lasts seconds
SWING_MARGIN = 1.15     # respiration modulation rides on top of AC
DEFAULT_AC_MV = 60.0


def median_mv(adc, channel, n):
    from hw.opt101_rx import raw_to_millivolts
    return statistics.median(raw_to_millivolts(adc.read_raw(channel)) for _ in range(n))


class Bench:
    def __init__(self, dacs, adc):
        self.dacs, self.adc = dacs, adc

    def drive(self, name, mv):
        code = dac_voltage_to_code(mv / 1000.0)
        ir, red = (code, DAC_IDLE_VALUE) if name == "ir" else (DAC_IDLE_VALUE, code)
        self.dacs.set_values(ir, red)
        if not self.dacs.output_ok:
            raise OSError("DAC write failed")

    def off(self):
        self.dacs.set_values(DAC_IDLE_VALUE, DAC_IDLE_VALUE)


def sweep(bench, name, channel, max_mv):
    bench.off()
    time.sleep(COOL_S)
    dark = median_mv(bench.adc, channel, 15)
    curve = []
    for mv in range(0, int(max_mv) + 1, SWEEP_STEP_MV):
        bench.drive(name, mv)
        time.sleep(PULSE_S)
        rx = median_mv(bench.adc, channel, 3)
        bench.off()
        curve.append((mv, rx))
        print(f"  {name} pulse {mv:5d} mV DAC -> {rx:6.0f} mV RX", flush=True)
        time.sleep(REST_S)
        top = max(r for _, r in curve)
        lit = top - dark > 4 * MIN_SIGNAL_MV          # a dark dead zone is flat too, but not a ceiling
        if lit and len(curve) > CEILING_STEPS and all(r >= top - CEILING_BAND_MV for _, r in curve[-CEILING_STEPS:]):
            break   # on the ceiling: more overload pulses only depress the IR path (see module doc)
    return dark, curve


def hold(bench, name, channel, mv):
    bench.off()
    time.sleep(COOL_S)
    bench.drive(name, mv)
    start, series = time.monotonic(), []
    while (t := time.monotonic() - start) < HOLD_S:
        series.append((t, median_mv(bench.adc, channel, 1)))
        time.sleep(0.05)
    bench.off()
    first = statistics.median(v for t, v in series if t < 1.0)
    last = statistics.median(v for t, v in series if t > HOLD_S - 1.0)
    return first, last, series


def interpolate(curve, mv):
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x0 <= mv <= x1:
            return y0 + (y1 - y0) * (mv - x0) / (x1 - x0)
    return curve[-1][1]


def analyse(name, dark, curve, ac_wanted):
    ceiling = max(rx for _, rx in curve)
    knee = next(mv for mv, rx in curve if rx >= ceiling - CEILING_BAND_MV)
    turn_on = next((mv for mv, rx in curve if rx - dark >= MIN_SIGNAL_MV), None)
    if turn_on is None or ceiling - dark < 4 * MIN_SIGNAL_MV:
        raise RuntimeError(f"{name}: no usable optical signal (dark {dark:.0f} mV, ceiling {ceiling:.0f} mV)")
    limit = dark + HEADROOM * (ceiling - dark)
    top = max((mv for mv, rx in curve if mv < knee and rx <= limit), default=turn_on)
    floor = dark + TOE * (ceiling - dark)
    low = next(mv for mv, rx in curve if rx >= floor)
    return dict(dark_mv=dark, ceiling_mv=ceiling, knee_dac_mv=knee, turn_on_dac_mv=turn_on,
                window_low_dac_mv=max(low, turn_on + SWEEP_STEP_MV),
                safe_rx_limit_mv=limit, safe_top_dac_mv=top, ac_wanted_mv=ac_wanted)


def recommend(result, curve):
    from models.limits import PERFUSION_INDEX
    low, top = result["window_low_dac_mv"], result["safe_top_dac_mv"]
    if top - low < 20:
        raise RuntimeError(f"linear window {low}-{top} mV DAC is too narrow")
    ac = min(result["ac_wanted_mv"], (top - low) / (2 * SWING_MARGIN))
    dc = low + (top - low - ac * SWING_MARGIN) / 2
    ac = min(ac, PERFUSION_INDEX.maximum / 100.0 * dc)   # the config loader rejects a larger PI
    dc, ac = round(dc), int(ac)
    rx_dc, rx_peak = interpolate(curve, dc), interpolate(curve, dc + ac)
    result.update(dc_mv=dc, ac_mv=ac, rx_dc_mv=round(rx_dc), rx_ac_mv=round(rx_peak - rx_dc))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the recommendation to config.json")
    parser.add_argument("--report", default=os.path.join(ROOT, "optical-calibration.json"))
    parser.add_argument("--max-mv", type=float, default=SWEEP_MAX_MV)
    args = parser.parse_args()

    import instance_lock
    from config_store import load_config, save_config
    from hw.dac_manager import DACManager
    from hw.grove_adc import GroveVoltageADC

    instance_lock.acquire()  # raises AlreadyRunning while the app owns the bus
    saved = load_config()
    dacs = DACManager()
    if not dacs.begin():
        sys.exit("MCP4725 DACs did not answer")
    bench = Bench(dacs, GroveVoltageADC(address=GROVE_ADC_ADDR))
    report = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "channels": {}}
    try:
        for name, channel in (("ir", ADC_CHANNEL_IR), ("red", ADC_CHANNEL_RED)):
            print(f"[{name.upper()}] A{channel}", flush=True)
            dark, curve = sweep(bench, name, channel, args.max_mv)
            ac_wanted = saved.get(f"ac_{name}_mv") or DEFAULT_AC_MV
            result = analyse(name, dark, curve, ac_wanted)
            holds = []
            for _ in range(HOLD_RETRIES):
                first, last, series = hold(bench, name, channel, result["safe_top_dac_mv"])
                drift = last / first - 1 if first > 0 else float("inf")
                holds.append(dict(dac_mv=result["safe_top_dac_mv"], first_mv=first, last_mv=last, drift=drift))
                print(f"  hold {result['safe_top_dac_mv']} mV DAC: {first:.0f} -> {last:.0f} mV ({drift:+.1%})",
                      flush=True)
                if drift > COLLAPSE_DRIFT:
                    break
                step = max(SWEEP_STEP_MV, round(0.1 * (result["safe_top_dac_mv"] - result["turn_on_dac_mv"])))
                result["safe_top_dac_mv"] -= step
            else:
                raise RuntimeError(f"{name}: RX still collapses at the lowest tried level; check the optics")
            recommend(result, curve)
            result.update(curve=curve, holds=holds, unstable=abs(holds[-1]["drift"]) > STABLE_DRIFT)
            if result["unstable"]:
                print(f"  WARNING: {name} RX drifted {holds[-1]['drift']:+.1%} in {HOLD_S:.0f} s at a fixed DAC "
                      "level. That is the LED/driver/optics, not the ADC; measure V_sense before trusting "
                      "this channel's DC.", flush=True)
            report["channels"][name] = result
            print(f"  -> DC {result['dc_mv']} mV, AC {result['ac_mv']} mV DAC "
                  f"(RX ~{result['rx_dc_mv']} mV, pulse ~{result['rx_ac_mv']} mV); ceiling "
                  f"{result['ceiling_mv']:.0f} mV reached at {result['knee_dac_mv']} mV DAC", flush=True)
    finally:
        bench.off()
        dacs.shutdown()
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=1)
        print(f"Report: {args.report}. DACs parked at 0 V.")

    if args.apply:
        ir, red = report["channels"]["ir"], report["channels"]["red"]
        backup = f"{CONFIG_JSON_PATH}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        if os.path.exists(CONFIG_JSON_PATH):
            shutil.copy2(CONFIG_JSON_PATH, backup)
        saved.update(dc_ir_mv=float(ir["dc_mv"]), ac_ir_mv=float(ir["ac_mv"]),
                     dc_red_mv=float(red["dc_mv"]), ac_red_mv=float(red["ac_mv"]),
                     perfusion_index=round(ir["ac_mv"] / ir["dc_mv"] * 100.0, 3),
                     output_dc_offset_mv=0.0)
        if not save_config(saved):
            sys.exit("config.json was not written")
        print(f"Applied to {CONFIG_JSON_PATH} (previous copy: {backup})")


if __name__ == "__main__":
    main()
