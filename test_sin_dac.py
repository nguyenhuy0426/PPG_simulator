"""
test_sin_dac.py — Output a continuous sine waveform via MCP4725 DAC.

Uses the adafruit-circuitpython-mcp4725 library (same as hw/dac_manager.py).
The 12-bit DAC outputs 0-4095 counts, mapped to 0-VDD analog voltage.
The sine wave is centered at mid-scale (2048) with full-scale amplitude.

Wiring:
    MCP4725 SDA -> Raspberry Pi GPIO 2 (SDA)
    MCP4725 SCL -> Raspberry Pi GPIO 3 (SCL)
    MCP4725 VCC -> 3.3V or 5V
    MCP4725 GND -> GND
    Analog output -> Oscilloscope or multimeter
"""

import time
import math
import board
import busio
import adafruit_mcp4725

# ----- Configuration -----
DAC_ADDRESS   = 0x60     # MCP4725 I2C address (A0 = GND)
DAC_MAX       = 4095     # 12-bit max value
DAC_CENTER    = 2048     # Mid-scale (zero-crossing of sine)
AMPLITUDE     = 2047     # Peak amplitude in DAC counts (full swing)
FREQUENCY_HZ  = 1.0      # Sine wave frequency in Hz
SAMPLES       = 200      # Number of points per cycle (higher = smoother)
VDD           = 3.3      # DAC supply voltage (change to 5.0 if using 5V)

# ----- Initialize I2C & DAC -----
print("=" * 50)
print("  MCP4725 Sine Waveform Generator")
print("=" * 50)
print(f"  DAC address : 0x{DAC_ADDRESS:02X}")
print(f"  Frequency   : {FREQUENCY_HZ} Hz")
print(f"  Samples     : {SAMPLES} per cycle")
print(f"  VDD         : {VDD} V")
print("=" * 50)

i2c = busio.I2C(board.SCL, board.SDA)
dac = adafruit_mcp4725.MCP4725(i2c, address=DAC_ADDRESS)
print("[OK] DAC initialized successfully.\n")

# ----- Pre-compute sine lookup table -----
# Building the table once avoids repeated math.sin() calls in the loop,
# which is important for maintaining a stable output frequency.
sine_table = []
for i in range(SAMPLES):
    angle = 2.0 * math.pi * i / SAMPLES
    value = int(DAC_CENTER + AMPLITUDE * math.sin(angle))
    value = max(0, min(DAC_MAX, value))  # Clamp to 12-bit range
    sine_table.append(value)

# Calculate the delay between samples to achieve the target frequency
sample_period = 1.0 / (FREQUENCY_HZ * SAMPLES)

print(f"[INFO] Sample period: {sample_period * 1000:.2f} ms")
print(f"[INFO] DAC range   : {min(sine_table)} — {max(sine_table)}")
print(f"[INFO] Voltage range: {min(sine_table)/4096*VDD:.3f} V — {max(sine_table)/4096*VDD:.3f} V")
print("\nOutputting sine wave... Press Ctrl+C to stop.\n")

# ----- Main output loop -----
cycle_count = 0
try:
    while True:
        t_cycle_start = time.monotonic()

        for idx, dac_value in enumerate(sine_table):
            t_start = time.monotonic()

            dac.raw_value = dac_value

            # Print a status line every 50 samples to avoid flooding the console
            if idx % 50 == 0:
                voltage = dac_value / 4096.0 * VDD
                print(f"  Cycle {cycle_count:>4d} | Sample {idx:>3d}/{SAMPLES} | "
                      f"DAC: {dac_value:>4d} | Voltage: {voltage:.3f} V")

            # Compensate for the time spent writing + printing
            elapsed = time.monotonic() - t_start
            sleep_time = sample_period - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        cycle_count += 1
        actual_period = time.monotonic() - t_cycle_start
        actual_freq = 1.0 / actual_period if actual_period > 0 else 0
        print(f"  >> Cycle {cycle_count} complete | "
              f"Actual freq: {actual_freq:.2f} Hz | "
              f"Period: {actual_period:.4f} s")

except KeyboardInterrupt:
    # Gracefully set DAC to mid-scale on exit
    dac.raw_value = DAC_CENTER
    voltage_center = DAC_CENTER / 4096.0 * VDD
    print(f"\n[STOP] Output stopped. DAC set to center ({DAC_CENTER} = {voltage_center:.3f} V).")
    print(f"       Total cycles completed: {cycle_count}")