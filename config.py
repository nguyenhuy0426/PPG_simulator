"""
config.py — Global system configuration for PPG Signal Simulator (Raspberry Pi 4)

Hardware: Raspberry Pi 4 + Grove Base Hat (ADC) + Dual MCP4725 DAC (I2C)
"""

import os
import platform

# ============================================================================
# SYSTEM IDENTIFICATION
# ============================================================================
DEVICE_NAME = "PPG Signal Simulator"
# Single source of truth for the version. README.md must match it
# (tests/test_version_consistency.py enforces this).
FIRMWARE_VERSION = "5.0.0"
FIRMWARE_DATE = "05 September 2026"
HARDWARE_MODEL = "Raspberry Pi 4"

# ============================================================================
# DRY-RUN MODE
# When True, all hardware access is simulated (no GPIO, no I2C, no DAC).
# Useful for development on a non-RPi machine.
# ============================================================================
DRY_RUN = os.environ.get("PPG_DRY_RUN", "0") == "1"

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================
LOG_ENABLED = os.environ.get("PPG_LOG_ENABLED", "1") == "1"
LOG_FILE = "/tmp/ppg_simulator.log"
LOG_LEVEL = "DEBUG"  # DEBUG, INFO, WARNING, ERROR

# ============================================================================
# CONFIGURATION PERSISTENCE
# ============================================================================
CONFIG_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# ============================================================================
# PIN CONFIGURATION — MCP4725 DACs (I2C Bus 1)
# ============================================================================
I2C_BUS = 1             # /dev/i2c-1
# Measured 2026-11-14: DAC 0x60 lights the LED seen on A0 and 0x61 the LED seen
# on A4 (no crosstalk). The user identified the A4 lane as IR on 2026-11-11/12.
DAC_ADDR_IR  = 0x61     # MCP4725 address for IR channel
DAC_ADDR_RED = 0x60     # MCP4725 address for Red channel

# ============================================================================
# PIN CONFIGURATION — GROVE BASE HAT ADC (I2C)
# ============================================================================
# The Grove Base Hat on this system uses the MM32 MCU, which answers at I2C
# address 0x08 [VERIFIED-USER; corroborated by grove_base_hat.pdf p.3: "the IIC
# address of MM32 is 0x08, while the STM32 is 0x04"]. It shares /dev/i2c-1 with
# both MCP4725 DACs at 0x60/0x61. Do NOT revert to 0x04 — that is the STM32
# revision of the same HAT, which is not the board installed here.
# RX mapping [VERIFIED-USER 2026-11-11, pairing measured 2026-11-14]:
#     OPT101 (IR)  -> A4  (Grove ADC channel 4), lit by DAC 0x61
#     OPT101 (Red) -> A0  (Grove ADC channel 0), lit by DAC 0x60
#     A1 is NOT used for OPT101.
GROVE_ADC_ADDR = 0x08   # Grove Base Hat MM32 ADC I2C address [VERIFIED-USER]
ADC_CHANNEL_IR = 4      # A4 — OPT101 IR photodiode channel
ADC_CHANNEL_RED = 0     # A0 — OPT101 Red photodiode channel

# ============================================================================
# SIGNAL SAMPLING CONFIGURATION
# ============================================================================

# Timer master frequency (internal buffer rate)
# MCP4725 I2C can sustain ~1 kHz writes in fast mode
# Integer multiple of the 100 Hz model rate. On the Pi 4 with the GUI and the
# 100 Hz/ch RX sharing I2C at 100 kHz, 500 Hz could not be sustained (measured
# 2026-11-14: ring full at 1019/1024, ~44 samples/s dropped, ~2 s output lag), so
# the Pi default is 200 Hz; PPG content is < 10 Hz and the model runs at 100 Hz.
FS_TIMER_HZ = int(os.environ.get("PPG_DAC_RATE_HZ", "200" if platform.machine() == "aarch64" else "1000"))
if FS_TIMER_HZ not in (100, 200, 500, 1000):
    raise ValueError("PPG_DAC_RATE_HZ must be 100, 200, 500 or 1000")

# PPG model generation rate
# PPG bandwidth: 0.5–10 Hz → Nyquist = 20 Hz
# Using 100 Hz for smooth waveform display
MODEL_SAMPLE_RATE_PPG = 100     # Hz

# deltaTime for model (seconds)
MODEL_DT_PPG = 1.0 / MODEL_SAMPLE_RATE_PPG  # 10 ms

# Model tick interval in microseconds
MODEL_TICK_US_PPG = 1_000_000 // MODEL_SAMPLE_RATE_PPG  # 10000 us

# Upsample ratio: interpolation from model rate to timer rate
UPSAMPLE_RATIO_PPG = FS_TIMER_HZ // MODEL_SAMPLE_RATE_PPG  # 2 on Pi; 10 at 1 kHz

# ============================================================================
# MCP4725 DAC CONFIGURATION (12-bit)
# ============================================================================
DAC_MAX_VALUE = 4095

# Safe idle/shutdown code — 0 → 0 V at the DAC output.
# In the LED-driver concept (I_LED proportional to V_DAC across the sense
# resistor), 0 V commands the LEDs OFF. Init, stop, and process exit must park
# the outputs here; never park at mid-scale (2048 ≈ 1.6 V would hold the LEDs
# at ~half drive indefinitely).
DAC_IDLE_VALUE = 0

# MCP4725 full-scale output voltage — SINGLE SOURCE OF TRUTH for the TX path.
# The MCP4725 supply on this hardware is 3.28 V and, since the MCP4725 is
# ratiometric to VDD, its full-scale output is 3.28 V [VERIFIED-USER]. Every DAC
# voltage->code conversion and every waveform clamp MUST reference this constant
# (or DAC_FULLSCALE_MV) — do not re-hardcode 3.2 / 3.3 / 3200 / 3300 anywhere.
# See calibration.dac_voltage_to_code().
# NOTE: ADC_VOLTAGE_REF (below) currently holds the same 3.28 V number, but it
# describes a physically different quantity on the RX path. Keep the two symbols
# independent; never define one in terms of the other.
DAC_FULLSCALE_V = 3.28                         # Volts (MCP4725 full-scale = VDD)
DAC_FULLSCALE_MV = DAC_FULLSCALE_V * 1000.0    # 3280.0 mV (user-facing convenience)

# ============================================================================
# BUFFER CONFIGURATION
# ============================================================================
SIGNAL_BUFFER_SIZE = 1024       # TX ring samples (~2 s at the 500 Hz Pi DAC rate)

# ============================================================================
# ADC CONFIGURATION (Grove Base Hat — 12-bit MM32 ADC)
# ============================================================================
ADC_MAX_VALUE = 4095            # 12-bit [VERIFIED-USER / grove_base_hat.pdf]
# Grove ADC full-scale/reference used by this project [VERIFIED-USER].
# This is the RX-path scale factor (Grove Base HAT MM32 ADC). It is a separate
# quantity from DAC_FULLSCALE_V (TX path, MCP4725) even though both are 3.28 V
# on this build — do not merge them or alias one to the other.
ADC_VOLTAGE_REF = 3.28          # Volts — Grove ADC reference (RX path)

# ============================================================================
# RX ACQUISITION (Phase 5 — OPT101 via Grove ADC, hw/opt101_rx.py)
# ============================================================================
# RX runs on its own thread, decoupled from the 1 kHz TX rate. Phase 4 timing
# budget [INFERENCE]: at 100 kHz I2C each Grove register read costs ~0.45 ms,
# so per-tick RX at 1 kHz does not fit; PPG bandwidth is 0.5–10 Hz, so 100 Hz
# per channel gives 10x Nyquist margin while adding only ~2 ADC transactions
# per 10 ms to the shared bus.
RX_ENABLED_CHANNELS = (ADC_CHANNEL_IR, ADC_CHANNEL_RED)
RX_SAMPLE_RATE_HZ = 100         # Hz per channel (both channels read each tick)
RX_BUFFER_SIZE = 6400           # Bounded per-channel buffer: 64 s @ 100 Hz, enough for the 60 s RR window
RX_STALE_THRESHOLD_S = 0.5      # Newest sample older than this ⇒ channel stale
RX_DISCONNECT_ERROR_THRESHOLD = 10   # Consecutive read errors ⇒ channel disconnected
# OPT101 output ceiling on its 3.3 V Grove supply: datasheet (TI OPT101 §6.5) V_out high = V_S − 1.3 V min /
# V_S − 1.15 V typ ≈ 2.0–2.15 V; measured 2.51–2.54 V on both lanes (2026-11-14). It is below the ADC full
# scale (3.3 V), so a saturated OPT101 never reads 4095: the RX lane flags readings at or above this level.
OPT101_SATURATION_MV = 2400
