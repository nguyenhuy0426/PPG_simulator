#!/usr/bin/env python3
"""Measure the DAC → LED → OPT101 → Grove ADC step response for TDM mode.

Pulses one LED at a time (the other stays at 0) and reads the shared OPT101
on A0 as fast as the I2C bus allows, timestamping every read relative to the
end of the DAC write. Reports, per LED and edge, how long the reading takes
to enter and stay inside a tolerance band around its final level; the
largest value is the minimum PPG_TDM_READ_DELAY_MS for this assembly.

Run only on the Pi, with the app stopped (this script owns both DACs and the
ADC), both LEDs and the single OPT101 fitted in one chamber, and an LED level
already known to be safe for the driver. Both DACs are parked at 0 in finally.

Read spacing is one Grove transaction (~0.45 ms at 100 kHz I2C), so settling
times are resolved to about that step, not better.
"""
import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calibration import dac_voltage_to_code  # noqa: E402
from config import (ADC_MAX_VALUE, DAC_FULLSCALE_MV, DAC_IDLE_VALUE, DRY_RUN,  # noqa: E402
                    GROVE_ADC_ADDR, RX_TDM_ADC_CHANNEL)
from hw.dac_manager import DACManager  # noqa: E402

# Final level = median of the last part of each window.
PLATEAU_FRACTION = 0.25


def read_window(adc, seconds, switched_at):
    """[(t_since_switch_s, raw)] for every successful read in the window."""
    rows = []
    end = switched_at + seconds
    while time.perf_counter() < end:
        try:
            raw = adc.read_raw(RX_TDM_ADC_CHANNEL)
        except (SystemExit, Exception):  # grove.adc calls sys.exit(2) on IOError
            continue
        rows.append((time.perf_counter() - switched_at, raw))
    return rows


def settle_time(rows, tolerance):
    """Time of the first read after which every read stays within
    `tolerance` counts of the plateau, plus the plateau itself."""
    if len(rows) < 8:
        return None, None
    tail = rows[int(len(rows) * (1 - PLATEAU_FRACTION)):]
    plateau = statistics.median(raw for _, raw in tail)
    settled_at = None
    for t, raw in rows:
        if abs(raw - plateau) <= tolerance:
            if settled_at is None:
                settled_at = t
        else:
            settled_at = None
    return settled_at, plateau


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--level-mv", type=float, default=1500.0,
                        help="DAC command while an LED is on (default 1500 mV, the app's DC default)")
    parser.add_argument("--window-ms", type=float, default=30.0,
                        help="Length of each on and off window")
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--tolerance-counts", type=float, default=2.0,
                        help="Settled band around the final level, in ADC counts")
    parser.add_argument("--output", type=Path, required=True,
                        help="New directory for steps.csv and summary.json")
    args = parser.parse_args()
    if DRY_RUN:
        raise SystemExit("Settling measurement needs real hardware; refusing DRY RUN")
    if not 0 < args.level_mv <= DAC_FULLSCALE_MV:
        raise SystemExit(f"--level-mv must be within (0, {DAC_FULLSCALE_MV:g}]")
    args.output.mkdir(parents=True, exist_ok=False)

    from grove.adc import ADC
    adc = ADC(address=GROVE_ADC_ADDR)
    dac = DACManager()
    if not dac.begin():
        raise SystemExit("MCP4725 DACs unavailable")
    code = dac_voltage_to_code(args.level_mv / 1000.0)
    window_s = args.window_ms / 1000.0
    steps = []  # (led, edge, repeat, t_s, raw)
    summary = {"level_mv": args.level_mv, "dac_code": code, "window_ms": args.window_ms,
               "tolerance_counts": args.tolerance_counts, "adc_channel": RX_TDM_ADC_CHANNEL,
               "caveat": "Commanded DAC level, not measured LED current. Settling is resolved "
                         "only to the spacing between Grove reads."}
    try:
        for led in ("red", "ir"):
            on = (0, code) if led == "red" else (code, 0)
            settle = {"rise": [], "fall": []}
            plateaus = {"rise": [], "fall": []}
            saturated = 0
            for repeat in range(args.repeats):
                for edge, values in (("rise", on), ("fall", (DAC_IDLE_VALUE, DAC_IDLE_VALUE))):
                    dac.set_values(*values)
                    rows = read_window(adc, window_s, time.perf_counter())
                    saturated += sum(raw >= ADC_MAX_VALUE for _, raw in rows)
                    steps.extend((led, edge, repeat, t, raw) for t, raw in rows)
                    t_settle, plateau = settle_time(rows, args.tolerance_counts)
                    if t_settle is not None:
                        settle[edge].append(t_settle)
                        plateaus[edge].append(plateau)
            summary[led] = {
                edge: {
                    "settle_ms_median": statistics.median(v) * 1000 if v else None,
                    "settle_ms_max": max(v) * 1000 if v else None,
                    "plateau_raw_median": statistics.median(plateaus[edge]) if plateaus[edge] else None,
                    "edges_settled": len(v), "edges_total": args.repeats,
                } for edge, v in settle.items()}
            summary[led]["saturated_reads"] = saturated
        worst = [summary[led][edge]["settle_ms_max"] for led in ("red", "ir")
                 for edge in ("rise", "fall") if summary[led][edge]["settle_ms_max"] is not None]
        summary["worst_settle_ms"] = max(worst) if worst else None
        if worst:
            # 25 % margin over the slowest observed edge.
            summary["suggested_read_delay_ms"] = round(max(worst) * 1.25, 1)
    finally:
        dac.shutdown()

    with (args.output / "steps.csv").open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["led", "edge", "repeat", "t_since_switch_s", "raw"])
        writer.writerows(steps)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
