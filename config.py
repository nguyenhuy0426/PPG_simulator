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
# Pi desktop + shared I2C may not sustain 1 kHz. Keep a validated integer
# multiple of the 100 Hz model rate; deployment can select 500 Hz explicitly.
FS_TIMER_HZ = int(os.environ.get("PPG_DAC_RATE_HZ", "500" if platform.machine() == "aarch64" else "1000"))
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
UPSAMPLE_RATIO_PPG = FS_TIMER_HZ // MODEL_SAMPLE_RATE_PPG  # 5 on Pi; 10 at 1 kHz

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
RX_BUFFER_SIZE = 1024           # Bounded per-channel sample buffer (~10 s @ 100 Hz)
RX_STALE_THRESHOLD_S = 0.5      # Newest sample older than this ⇒ channel stale
RX_DISCONNECT_ERROR_THRESHOLD = 10   # Consecutive read errors ⇒ channel disconnected

# ============================================================================
# RX MODE — "dual" (one OPT101 per LED, separate lanes) or "tdm" (RED and IR
# share ONE chamber and ONE OPT101, time-multiplexed like the MAX30102)
# ============================================================================
# In "tdm" the SignalEngine output thread is the single slot master: it turns
# one LED on (the other off), waits RX_TDM_READ_DELAY_S for the optical/analog
# path to settle, reads the shared OPT101 on RX_TDM_ADC_CHANNEL, then moves to
# the next slot. Slot order: RED, IR and, when enabled, DARK (both LEDs off,
# measures OPT101 offset + leaked ambient light). Per-channel rate is
# 1 / (slot × number of slots): 22.2 Hz with the 15 ms / 3-slot default.
#
# READ DELAY [INFERENCE — must be measured]: the receiver PCB v1.5 output RC
# Measured on the Pi 4 with R = 1 kΩ, C = 100 nF [VERIFIED 2026-11-03]: the OPT101
# falls more slowly than the RC alone explains. After IR switches off, the part of
# its level still present is ~25 % at 6 ms, ~5 % at 12 ms and ~0 at 15 ms, and this
# lands in the dark lane. PPG_TDM_READ_DELAY_MS=15 with PPG_TDM_SLOT_MS=18 removes
# it at 18.5 Hz per channel; the 12/15 default keeps 22.2 Hz.
# scripts/measure_tdm_settling.py measures this step response on the assembly.
RX_MODE = os.environ.get("PPG_RX_MODE", "dual")
if RX_MODE not in ("dual", "tdm"):
    raise ValueError("PPG_RX_MODE must be 'dual' or 'tdm'")
RX_TDM_ADC_CHANNEL = 0   # the single shared TDM OPT101 sits on physical A0
RX_TDM_SLOT_S = float(os.environ.get("PPG_TDM_SLOT_MS", "15")) / 1000.0
RX_TDM_READ_DELAY_S = float(os.environ.get("PPG_TDM_READ_DELAY_MS", "12")) / 1000.0
RX_TDM_DARK_SLOT = os.environ.get("PPG_TDM_DARK", "1") == "1"
# The read delay counts from the END of the LED-switching DAC writes, so it is
# the real settling time. Two DAC writes (~0.3 ms each) and one Grove read
# (~0.45 ms) at 100 kHz I2C [INFERENCE, Phase 4 budget] must also fit in the
# slot. One Grove read measured ~0.7 ms on the Pi 4 [VERIFIED 2026-11-03]; a slot
# that overruns is counted (tdm_late_slots) and re-based.
RX_TDM_MIN_READ_DELAY_S = 0.001
RX_TDM_IO_BUDGET_S = 0.003
if not RX_TDM_MIN_READ_DELAY_S <= RX_TDM_READ_DELAY_S <= RX_TDM_SLOT_S - RX_TDM_IO_BUDGET_S:
    raise ValueError("PPG_TDM_READ_DELAY_MS must be ≥ 1 ms and leave ≥ 3 ms of the "
                     "slot for the DAC writes and the ADC read")
RX_TDM_SLOTS = ("red", "ir", "dark") if RX_TDM_DARK_SLOT else ("red", "ir")
RX_TDM_FRAME_S = RX_TDM_SLOT_S * len(RX_TDM_SLOTS)   # one sample per channel per frame
