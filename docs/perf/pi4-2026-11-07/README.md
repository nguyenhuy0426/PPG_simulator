# UI load on a Raspberry Pi 4, before and after (2026-11-07)

Hardware and setup: Raspberry Pi 4 Model B Rev 1.5, 4 cores, Ubuntu 24.04, Python 3.12, GNOME on Wayland
(app under Xwayland, display 1920x1080, app window 1024x600), CPU governor `ondemand`, reached over Wi-Fi.
Run with `scripts/measure_ui_load.py --seconds 8 --pages Pathology,Playback`, three alternating runs per version,
median shown. Raw runs: `ab_ppg_bench_base_*.json` (before) and `ab_ppg_bench_*.json` (after).

What this is not: **dry-run**, with a synthetic 100 Hz RX stream fed to the receiver. `i2cdetect -y 1` showed none of
0x08, 0x60, 0x61 on this Pi, so no DAC write, ADC read or I2C timing was measured. The numbers are Tk/Python load
only. The Pi has run-to-run noise (frequency scaling), so read differences of a few percent as noise.

| Page (output running on Pathology) | UI thread CPU | Process CPU | Canvas render | `update_gui` mean | p99 | max |
|---|---|---|---|---|---|---|
| Pathology, before | 31.9% | 52.0% | 8.9 ms | 14.5 ms | 57 ms | 70 ms |
| Pathology, after | 25.0% | 44.7% | 4.5 ms | 9.2 ms | 32 ms | 58 ms |
| Playback, before | 16.5% | 18.9% | 7.0 ms | 6.6 ms | 54 ms | 56 ms |
| Playback, after | 14.2% | 16.9% | 5.6 ms | 5.4 ms | 30 ms | 44 ms |

(Percentages are of one core.) The p95 of `update_gui` on Playback went up (16.6 to 23.5 ms): the three estimates that
used to refresh in the same tick now refresh one per tick, so more ticks carry one estimate and none carries all of
them. The worst frames got shorter, the typical ones did not.

## What changed

1. **In-place canvas updates** (`ui/trace_view.py`). Before: every frame deleted the canvas and re-created ~40 items
   (grid, labels, headers, polylines). Now the items are kept: polylines get new coordinates, the scrolling time grid is
   moved as one tagged group, and a text is touched only when it changed (a live mV reading, a rate, y-axis labels). A
   size, theme, title, colour or layout change still rebuilds. `tests/test_ui_performance.py` checks that a scrolled
   frame leaves the same items as a fresh draw, including header changes, a gap in the samples and a second header row.
2. **Cheaper geometry**: no window filter when the trace is already inside the window, C-speed unzip/slicing, and one
   pass to find out whether a gap needs splitting.
3. **RX window without copying and filtering the whole buffer** (`OPT101Receiver.get_samples_since`, binary search),
   and one multiply per sample instead of a function call.
4. **Rate and SpO2 estimates every 2 s instead of 1 s, one per tick** (`RXPanel._may_estimate`). A rate estimate is
   about 14 ms on the Pi 4 (measured), so three due at once stalled the Tk thread.

## Not changed / still open

The render rate itself (RX 10 Hz, TX ~20 Hz) and the 8 s window are unchanged. The engine threads (model tick ~0.7 ms
on the Pi) are untouched. I2C/DAC timing, the Grove ADC and the RX acquisition rate need the hardware connected.
