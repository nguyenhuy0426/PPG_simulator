# MAX30102 reading the simulator: app mode, Model/Recording clips, LCD on the same board (23 November 2026)

Result: the Pi app's **MAX30102 mode** (Settings → MAX30102) drives the red simulator LED so that an unmodified
MAX30102 reads the set heart rate. On the bench the ESP32-S3 + MAX30102 reported **OK in 114 of 115 one-second
reports** while the app played Classic, Model and Recording output. The mean rate it read was 0.5–2.0 % below the
set rate. Darkness read NO SIGNAL every time, and there were no I2C errors or lost samples. The ST7789 LCD and the
sensor run together on the soldered PCB (300 s, 0 I2C errors).

This is an engineering check of the simulator → sensor chain on one bench, not a validated or clinical heart-rate
measurement. SpO₂ is not available in this mode (see *Limits*).

## Setup

| Part | Configuration |
|---|---|
| Simulator | Raspberry Pi 4, app on this branch: `core/signal_engine.py`, `hw/max30102_flicker.py`. MCP4725 RED = 0x60, IR = 0x61, I2C bus 1 at 100 kHz, shared with the Grove ADC (OPT101 RX at 0x08) |
| Sensor | ESP32-S3-DevKitC-1 + MAX30102 module, I2C SDA = GPIO8, SCL = GPIO9; ST7789 240×240 on SPI2 (MOSI 11, SCLK 12, DC 13, RST 14, BLK 15, CS tied low) |
| Sensor firmware | `firmware/esp32s3_max30102` as committed: the MAX30102's own LEDs at 0 mA, SpO₂ mode, 200 sps averaged by 2 → 100 Hz, 411 µs, 16384 nA range. HR estimator `ppg_hr.c`, one `R,` report per second over an 8 s window |
| Logging | `serial_log.py` / `watch_i2c.py` on the laptop add host timestamps to each serial line. The Pi scripts print a timestamped marker at each segment change. Pi and laptop clocks agree within a few ms |
| Analysis | `analyze_segments.py <serial log> <pi txt>`. It skips the first 10 s of each lit segment (the 8 s window filling) and the first 2 s of each dark one |

## Method

The MAX30102 subtracts an ambient sample (its own LED off) from every LED sample, so steady or slowly varying light
from the simulator cancels (`firmware/esp32s3_max30102/bench/results/20261123/`). In MAX30102 mode the app does the
following:
- It switches the red LED between 0 and the PPG level L(t) at 1500 writes/s (750 Hz on/off). The two samples then
  differ, and the sensor's output follows L(t) (`bench/results/20261123-flicker/`).
- It holds the IR LED at 0 V.
- It sets the amplitude preset to DC 600 mV / AC 300 mV and caps the LED on-level at 1000 mV. Heart rate, SpO₂
  target, respiration and noise stay the user's settings.
- It writes the red LED from a separate process paced to fixed times (`hw/max30102_flicker.py`), not from a thread
  inside the app.
- It pauses the OPT101 acquisition for as long as the mode runs.
- It sends Model (PPG morphology page) and Recording clips through the same path. Each clip's pulse is rescaled so
  that its 2nd–98th percentile span runs from DC 600 to 900 mV. The clip's pulse shape, beat timing and
  respiration are kept.

## Results

### App MAX30102 mode: the final design

| Run (serial log / Pi output) | Source on the Pi | Set rate | Reports OK | Rate read (min–max) | Error of the mean |
|---|---|---|---|---|---|
| `modetest3` / `pi_mode3.txt` | darkness | – | NO SIGNAL 6/6 | – | – |
| `modetest3` | Classic | 75 bpm | 29/30 (1 LOW QUALITY) | 72.6–73.9, mean 73.5 | −2.0 % |
| `modetest3` | Classic | 110 bpm | 30/30 | 106.6–109.1, mean 108.0 | −1.8 % |
| `clip` / `pi_clip.txt` | darkness | – | NO SIGNAL 6/6 | – | – |
| `clip` | Model page: Gaussian clip, 30 s | 80 bpm | 20/20 | 79.2–80.1, mean 79.6 | −0.5 % |
| `clip` | Recordings page: `dataset/data_1.csv`, first 45 s | 79 bpm (recorded setpoint) | 35/35 | 76.4–78.9, mean 77.9 | −1.4 % |
| user, on the Pi screen | Classic, Settings → MAX30102 → Apply → Run | 72 bpm | LCD showed OK | 72 | – |
| user, on the Pi screen | Model and Recordings pages, *Play LED* | – | reported "measured correctly" | – | – |

The writer process held 1494–1496 writes/s with 0 red-DAC errors. No on-level reached the 1000 mV cap. The OPT101
acquisition was running again after every stop, and both DACs read back 0 after each run.

The Classic runs used the configuration saved on the Pi, with beat variability on. In a 30 s model run at 75 bpm
the model itself produced 37 beats (74 bpm), so part of the low reading in the Classic rows comes from the set
waveform. The rest is not explained: the model clock was checked to be exact, and the sensor-side error was not
separated further. The `data_1.csv` setpoint was 64 bpm in its first second and 79 bpm afterwards.

### Why 1500 writes/s, a separate process and the OPT101 pause

| Run | Writer | Writes/s | OPT101 reads | Set 75 bpm → read |
|---|---|---|---|---|
| `ratetest` / `pi_rate.txt` | standalone script (`pi_rate_test.py`) | free-running, ~2600 | stopped | 74.2–75.0 (20/20 OK) |
| `ratetest` | standalone, paced | 2000 | stopped | **143.3–144.6** (20/20 "OK", wrong) |
| `ratetest` | standalone, paced | 1500 | stopped | 73.7–74.4 (20/20 OK) |
| `rate_rx` / `pi_rate_rx.txt` | standalone, paced | 1500 | running (app) | NO SIGNAL 20/20 |
| `modetest` / `pi_mode.txt` | app DAC thread | ~2040 | running | NO SIGNAL 30/30 (110 bpm: 30/30) |
| `modetest2` / `pi_mode2.txt` | app DAC thread, paced | 1495 | running | NO SIGNAL 30/30 (110 bpm: 30/30) |
| `mt_rx` / `pi_mt_rx.txt` | app DAC thread, paced | 1487 | running | NO SIGNAL 25/25. Write interval SD 132 µs, max 10.8 ms |
| `mt_norx` / `pi_mt_norx.txt` | app DAC thread, paced | 1488 | stopped | OK 5/25. Interval SD 101 µs, max 12.3 ms |
| `modetest3` | **separate process, paced** | **1500** | **paused by the mode** | 72.6–73.9 (29/30 OK) |

What these runs show:
- A 2000 writes/s toggle is 1000 Hz, which is 5 × the sensor's 200 sps. The beat between the two lands in the
  heart-rate band, and the firmware reports a confident wrong rate.
- 1500 writes/s (750 Hz = 3.75 × 200, 7.5 × 100, 1.875 × 400) keeps clear of these multiples.
- The sensor needs regular write times. A thread inside the app (GIL, GUI) and OPT101 reads on the same I2C bus
  both break that regularity. Pacing in a separate process and pausing the OPT101 reads fixed it.

`pi_write_timing_test.py` produced the interval statistics in the `mt_*` rows.

### Standalone flicker with the LCD running

The run is `lcdpi` / `pi_lcd.txt`. `firmware/esp32s3_max30102/bench/pi_red_flicker.py` ran with the app stopped,
DC 600 / AC 300 mV, about 2596 writes/s, 0 I2C errors on the Pi.

| Set | Reports OK | Rate read |
|---|---|---|
| darkness | NO SIGNAL 6/6 | – |
| 72 bpm | 30/30 | 71.5–72.4 |
| darkness | NO SIGNAL 6/6 | – |
| 100 bpm | 31/31 | 99.5–100.4 |

The user also saw OK and 72 on the LCD.

### LCD and MAX30102 on the same ESP32-S3 board

**Fault.** While SPI2 owns GPIO11/12, the I2C SCL line (GPIO9) is held low, and the sensor stops answering ("MAX30102
not found"). The user's continuity measurements found no short between GPIO9 and GPIO11, or between GPIO9 and
GPIO10, and the PCB is soldered, so the wiring cannot be changed. Measurements from diagnostic builds (not
committed):
- `spidiag*.log`: once the SPI bus is set up, GPIO9 reads low 34–100 % of the time. After a transfer the ADC on
  GPIO10 reads 0.6–0.8 V.
- `rel2.log`: once GPIO11/12 are released, GPIO9 returns high within 17–75 µs.

The physical mechanism is not known. The earlier note in `bench/results/20261123/` ("its MOSI line was shorted to
SDA") was wrong.

**Workaround in the firmware.** The sensor's I2C transfers and the LCD's transfers take turns on one FreeRTOS mutex
(`s_pin_mtx` in `main.c`). `lcd.c` drives GPIO11/12 only during a transfer and releases them afterwards. It keeps
SCLK high between transfers (SPI mode 3, no CS).

**Result.** `share_lcd.log.gz` covers 300 s with the LCD on: 30035 samples streamed, `i2c_err` 0 and `lost` 0
throughout. This holds for the conditions measured. Because the mechanism is unknown, a change in timing or a
different board may behave differently.

## Limits

- **No SpO₂.** Only the red LED is driven, and both MAX30102 channels see the same light, so there is no red/IR
  separation. Getting SpO₂ would need the LED gating design in `docs/hardware/MAX30102_LED_SYNC_DESIGN.md`, which
  has not been built.
- **The waveform is not calibrated.** The sensor output is a rectified, noisy envelope of L(t), not a calibrated
  optical PPG. AC/DC values on the sensor side are not meaningful.
- **No OPT101 data while the mode runs.** The OPT101 RX plot and its estimates stop until the mode is switched off.
- **Limited coverage.** One sensor module, one optical alignment, one bench. Not tested: other DC/AC presets,
  arrhythmia and noise presets, runs longer than 45 s per segment in the app mode, LED heating, and a finger in the
  path.
- **The OPT101 calibration does not carry over.** AC balance and the receive-path SpO₂ calibration are off in this
  mode, since they belong to the OPT101 path.

## Files

| File | What |
|---|---|
| `*.log.gz` | ESP32 serial output with host timestamps (`S,` samples, `R,` reports once per second) |
| `pi_*.txt` | Pi script output with segment markers. In `pi_mode3.txt`, "writes/s 0" is an artefact of the script reading the count before the writer stopped; it was fixed in `pi_mode_test.py` afterwards |
| `pi_mode_test.py`, `pi_clip_test.py` | Drive the app's `SignalEngine` in MAX30102 mode with the OPT101 running (app stopped, run from the app folder) |
| `pi_rate_test.py`, `pi_write_timing_test.py` | Toggle-rate test and the in-thread write timing test |
| `serial_log.py`, `watch_i2c.py`, `analyze_segments.py` | Laptop-side logging and the per-segment summary |
