# ESP32-S3 + MAX30102 test receiver

This is a bench receiver for the PPG simulator. A MAX30102 module faces the simulator's LEDs. The ESP32-S3 estimates
the pulse rate, streams the raw samples over serial and shows the waveform and HR on an ST7789 LCD. It is a test
instrument for the simulator → sensor chain, not a medical device.

## Hardware

| Signal | ESP32-S3-DevKitC-1 pin |
|---|---|
| MAX30102 SDA / SCL | GPIO8 / GPIO9. Tried in this order at boot and swapped if nothing answers |
| ST7789 240×240 MOSI / SCLK | GPIO11 / GPIO12 (SPI2, mode 3, 20 MHz) |
| ST7789 DC / RST / BLK | GPIO13 / GPIO14 / GPIO15. CS is tied low on the module |

On the bench PCB, SPI2 driving GPIO11/12 holds SCL (GPIO9) low. There is no short between the pins, and the cause
is unknown. The firmware therefore time-shares the pins: every I2C transfer and every LCD transfer holds one FreeRTOS
mutex (`s_pin_mtx`). `lcd.c` drives GPIO11/12 only during a transfer and keeps SCLK high between transfers. Measured
over 300 s with the LCD on: 0 I2C errors and 0 lost samples
([docs/hardware-validation/2026-11-23-max30102](../../docs/hardware-validation/2026-11-23-max30102/README.md)).
For serial output only, add `build_flags = -DAPP_USE_LCD=0` to `platformio.ini`.

## Build and flash

The build uses PlatformIO and ESP-IDF 5.3 (`platformio.ini`), with the board on `/dev/ttyACM0`:

```bash
pio run -t upload && pio device monitor
```

To test the HR estimator on the host with synthetic PPG (no sensor data):

```bash
cd test && gcc -O2 -Wall -Wextra -fsanitize=address,undefined -I../src host_test_ppg_hr.c ../src/ppg_hr.c -lm -o /tmp/hrtest && /tmp/hrtest
```

## Defaults and serial protocol

- **Sensor defaults:** the MAX30102's own LEDs are at **0 mA**, so the module only receives the simulator's light.
  SpO₂ mode, 200 sps averaged by 2 → 100 Hz, 411 µs (18-bit), 16384 nA range.
- **Serial port:** 115200 8N1. `S,<seq>,<red>,<ir>,<ppg>,<beat>` is one line per sample when streaming is on.
  `R,<json>` is printed once per second and gives the state (`OK`, `NO SIGNAL`, `LOW QUALITY`, `SATURATED`,
  warm-up), HR, the channel in use, per-channel DC/AC and the `lost` / `i2c_err` counters.
- **Commands:** `led <red_mA> <ir_mA>`, `range <0-3>`, `stream <0|1>`, `ch <auto|red|ir>`, `info`, `rd` (captures
  the module's RD/IRD pins), and for bench use only `sr <0-3>` and `avg <0-5>`. Use `led 7.2 7.2` to measure a
  finger.

## Using it with the simulator

A MAX30102 cancels steady light as ambient, so a continuous simulator LED gives NO SIGNAL. Two ways to drive it:

- **In the app (normal use):** open Settings → **MAX30102**, tick the mode, press Apply, then Run Classic, or press
  *Play LED* on the PPG morphology page or *Play* on Recordings. The red LED then flickers at 1500 writes/s with
  DC 600 / AC 300 mV, and the IR LED is off. HR, SpO₂ target, respiration and noise stay under your control. The
  OPT101 RX pauses while the mode runs.
- **Standalone, with the app stopped:** `bench/pi_red_flicker.py` (flicker) or `bench/pi_led_ppg.py` (steady
  Classic output, which the sensor cancels).

## Bench results

| Folder | Result |
|---|---|
| [docs/hardware-validation/2026-11-23-max30102](../../docs/hardware-validation/2026-11-23-max30102/README.md) | App MAX30102 mode: Classic 75 → 72.6–73.9 and 110 → 106.6–109.1 bpm, Model clip 80 → 79.2–80.1, Recording 79 → 76.4–78.9. Darkness reads NO SIGNAL. Toggle-rate and timing tests. LCD sharing |
| [bench/results/20261123-flicker](bench/results/20261123-flicker/README.md) | Standalone flicker: 60/80/90/120 bpm read within about 1 bpm |
| [bench/results/20261123](bench/results/20261123/README.md) | Steady simulator light is cancelled by the sensor (no HR) |

**Limits:** only the red LED carries the pulse and both sensor channels see it, so there is no SpO₂. The sensor
waveform is a rectified envelope, not a calibrated PPG. For SpO₂, see the gating design in
`docs/hardware/MAX30102_LED_SYNC_DESIGN.md` (not built).
