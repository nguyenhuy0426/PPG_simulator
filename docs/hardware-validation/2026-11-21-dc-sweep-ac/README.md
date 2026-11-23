# DC sweep at a fixed AC, before and after AC balance (2026-11-21)

Raspberry Pi 4 rig, both LED -> OPT101 paths, Grove ADC at 100 Hz per lane. The app was stopped during each
run (the script takes the app's instance lock); both DACs were parked at 0 V at the end.

## What was run

`dc_sweep_ac.py` (run from the app directory on the Pi) drives the Classic generator with the saved
`config.json` (HR 75, SpO₂ 99 %, RR 16, no noise, AC above DC), sets IR and RED to the same DC from 300 to
1500 mV in 50 mV steps, AC 45 mV on both, without stopping the output between steps:

| Run | Command | Step | Window analysed |
|---|---|---|---|
| before | `dc_sweep_ac.py OUT.json --seconds 15` | 15 s | last 12 s (`--settle 3`) |
| after | `dc_sweep_ac.py OUT.json --seconds 20 --balance` | 20 s | last 8 s (`--settle 12`) |

`--balance` runs `core.ac_balance.AcBalance` exactly as the app does (feedforward from the gain table measured
in the "before" run, then the closed-loop trim, ticked every 0.5 s).

`analyze_sweep.py SWEEP.json OUT.csv --settle N` (run from the repository root) gives per step the AC of TX and
RX: the median over beats of the peak-to-trough swing, each beat from one pulse peak to the next with the
straight line through its ends removed (the AC definition of `core/rx_spo2.py`). TX is the commanded AC part
(the generator's display signal, DAC voltage minus DC), not a measured DAC voltage. RX is the OPT101 output
read by the ADC. Every step had 11-12 beats on each lane, no ADC errors, no saturated sample (ADC flag), RX at
100 Hz with holes of at most 35 ms.

The set AC is 45 mV; the generator lowers it by its heart-rate coupling (-3.2 % per 10 bpm above 60), so the
commanded AC is 41-44 mV.

## Results

Δ = RX AC − TX AC, mV, over the 25 steps (full tables in the CSV files):

| | IR mean \|Δ\| | IR max \|Δ\| | RED mean \|Δ\| | RED max \|Δ\| |
|---|---|---|---|---|
| before (`dc-sweep-ac-20261121.csv`) | 34.1 | 46.0 (DC 1500) | 8.9 | 10.8 |
| after (`dc-sweep-ac-balanced-20261121.csv`) | 1.0 | 2.5 | 0.8 | 2.2 |

Before, RX/TX AC rose from 1.28 (DC 300) to 2.08 (DC 1500) on IR and stayed 1.12-1.25 on RED. Each ratio
follows the slope of its lane's received DC against the sent DC (IR ~1.8-1.9 mV/mV, RED ~1.19), so the AC
difference is the small-signal gain of each optical path, which on IR grows with drive.

After, the DAC AC factor went from 0.73 (DC 300) to 0.49 (DC 1500) on IR and 0.87 to 0.82 on RED. The loop
trims stayed within 0.96-1.00: the table carried nearly all of the correction. Per-beat AC spread within a step
is 1-7 mV (interquartile range), so the remaining ±2.5 mV is at the level of the beat-to-beat noise.

## Limits

- One sweep each way, upward only; no repeat run and no downward sweep (hysteresis not checked).
- At DC 1450-1500 mV without balance the IR peaks reached 2372-2469 mV, at or above the ~2.4 V OPT101
  saturation; those two IR gains are less certain. With balance the loop flagged IR "saturated" at 1500 mV and
  did not trim there.
- The gain table belongs to this rig as it was on 2026-11-21 (LED, OPT101, chamber, carrier position). A
  change of the optics needs a new "before" sweep; the result can be saved as `ac_gain_table` in `config.json`.
- This equalises the AC at this simulator's own OPT101 receiver. It is not a calibration of another receiver,
  and nothing here is a clinical measurement.

## Files

| File | Contents |
|---|---|
| `dc_sweep_ac.py`, `analyze_sweep.py` | The sweep (Pi) and its analysis (laptop or Pi) |
| `dc-sweep-ac-20261121.json.gz`, `.csv` | Before: raw TX/RX samples per step (SHA-256 of the JSON starts `0020cfc19e78740d`), per-step table |
| `dc-sweep-ac-balanced-20261121.json.gz`, `.csv` | After, with AC balance (JSON `6b9b86c5cabb7111…`); the JSON also holds the DAC factors and loop state per step |
