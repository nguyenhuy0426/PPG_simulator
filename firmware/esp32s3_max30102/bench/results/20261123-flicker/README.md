# Red simulator LED received by the MAX30102 without sync hardware (23 November 2026)

Method: `bench/pi_red_flicker.py` toggles the red DAC between 0 and L(t) = DC + AC·pulse(t) at about
2590 writes/s (≈1.3 kHz on/off; I2C at 100 kHz). The MAX30102 subtracts an ambient sample from each
LED-window sample; a steady light cancels (run of 23 Nov, `../20261123/`), but a flickering light differs
between the two samples. Negative differences clip at 0, so the averaged output follows L(t) and the
firmware's normal HR estimator reads the pulse rate. This is an unsynchronised method: the pulse shape
in the output is a noisy, rectified envelope, not a calibrated optical waveform, and both MAX30102
channels see the same red light (no RED/IR separation, so no SpO₂ from this).

Setup: MAX30102 LEDs 0 mA, SpO₂ mode, 200 sps, LED_PW 411 µs, ADC 16384 nA; Pi app stopped during runs,
restarted after; Pi and laptop clocks agree within ~2 ms.

| File | What |
|---|---|
| `fl1.log.gz`, `pi_fl1.txt` | 200 sps without averaging: dark / flicker 75 bpm / dark / steady 75 bpm (control) |
| `live1.log.gz`, `pi_live1.txt` | firmware defaults (avg 2 → 100 Hz), flicker at 60, 90, 120 bpm |
| `final.log.gz`, `pi_final.txt` | firmware defaults, no serial commands, flicker at 80 bpm |
| `analyze_hr.py` | per-segment summary of the firmware `R,` lines |

Raw level (run fl1, RED channel): dark mean 25.7 counts, SD 4.3; flicker mean 467, max 2163;
steady mean 20.1, SD 5.5. Envelope power in 1.1–1.4 Hz vs neighbouring bands: flicker 27×, dark ≤ 1.9×.

Firmware HR (one report per second, first 10 s of each segment skipped for the 8 s window):

| Pi set | Reports OK | HR reported (min–max) |
|---|---|---|
| dark | 0 (NO SIGNAL) | – |
| 60 bpm | 25/25 | 59.3–60.0 |
| 90 bpm | 23/25 (2 LOW QUALITY) | 89.5–90.8 |
| 120 bpm | 25/25 | 119.2–120.3 |
| 80 bpm (defaults, no commands) | 20/20 | 79.7–80.2 |

Before the refractory change in `ppg_hr.c` (peaks earlier than 60 % of the autocorrelation period are
ignored), the 75 bpm replay of `fl1` gave OK in only ~60 % of seconds; the change was tuned on that
replay and then checked live on 60/90/120/80 bpm. Engineering check of the simulator → sensor chain only;
not a clinical or validated HR measurement. Not tested: other DC/AC levels, a finger, long runs, heating.
