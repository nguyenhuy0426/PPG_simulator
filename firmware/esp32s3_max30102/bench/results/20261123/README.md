# MAX30102 facing the simulator LEDs, 23 November 2026

Files: `run1.log.gz`, `run2.log.gz` (serial, host time + line), `pi_run*.txt` (Pi script output).

Setup: ESP32-S3-DevKitC-1, MAX30102 on I2C (GPIO8/9), LCD disabled (its MOSI line was shorted to SDA).
Firmware `firmware/esp32s3_max30102` streams raw 18-bit FIFO counts at 100 Hz (`S,seq,red,ir`).
Pi 4 app stopped; `bench/pi_led_ppg.py` drove both simulator LEDs (Classic PPG, HR 75 bpm).
Host timestamps on every line. The Pi lines of run 1 arrived buffered at the end, so run-1 segments are
placed back from "DACs parked" (about 1 s uncertainty); run 2 is line-buffered.

| Run | MAX30102 setting | Pi LEDs | RED mean | IR mean | HR band / reference power (RED, IR) |
|---|---|---|---|---|---|
| 1 | 7.2 mA LEDs, 16384 nA | off | 241.4 | 157.1 | 0.63, 0.26 |
| 1 | 7.2 mA LEDs, 16384 nA | DC 500 / AC 45 mV | 237.3 | 153.8 | 0.75, 0.70 |
| 1 | LEDs 0 mA, 16384 nA | DC 500 / AC 45 mV | 21.0 | 20.5 | 1.29, 2.24 |
| 1 | LEDs 0 mA, 16384 nA | off (2.5 s only) | 25.5 | 24.8 | 0.26, 0.32 |
| 2 | LEDs 0 mA, 2048 nA | off | 63.8 | 61.4 | 0.79, 1.37 |
| 2 | LEDs 0 mA, 2048 nA | DC 700 / AC 100 mV | 46.6 | 45.1 | 1.11, 1.11 |
| 2 | LEDs 0 mA, 2048 nA | off | 63.5 | 61.2 | 0.68, 0.99 |

HR band = mean FFT power 1.1–1.4 Hz; reference = 0.6–1.0 and 1.5–2.0 Hz (detrended, Hann window).
Full scale is 262143 counts. ALC overflow flag: never set. I2C errors and lost samples: 0.

Reading: the simulator light reaches the photodiode (the mean drops reversibly by about 17 counts at
2048 nA when the Pi LEDs turn on), but the MAX30102's ambient light cancellation removes it: the
remaining offset is ~0.007 % of full scale and the 75 bpm component is not distinguishable from the
noise floor (sample SD about 3 counts at 16384 nA, 21 counts at 2048 nA). A continuous LED that is not
synchronised with the sensor's own LED pulses is treated as ambient light, so no HR can be measured
this way. What was verified: DAC codes during the run (read back), raw sensor counts. Not verified:
optical power at the sensor, alignment.
