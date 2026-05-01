"""
config.py — Global system configuration for PPG Signal Simulator (Raspberry Pi 4)

Hardware: Raspberry Pi 4 + Grove Base Hat (ADC) + Dual MCP4725 DAC (I2C)
         + 7-inch HDMI display (1024×600) + 1 push button + 1 potentiometer (5 kΩ)

Port of the ESP32-S3 config.h to Python.
"""

import os

# ============================================================================
# SYSTEM IDENTIFICATION
# ============================================================================
DEVICE_NAME = "PPG Signal Simulator"
FIRMWARE_VERSION = "3.0.0"
FIRMWARE_DATE = "30 April 2026"
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
DAC_ADDR_IR  = 0x60     # MCP4725 address for IR channel
DAC_ADDR_RED = 0x61     # MCP4725 address for Red channel

# ============================================================================
# PIN CONFIGURATION — GROVE BASE HAT ADC (I2C)
# ============================================================================
# Grove Base Hat uses STM32 MCU at I2C address 0x04
# Potentiometer connected to analog port A0
GROVE_ADC_CHANNEL = 0   # A0 port on Grove Base Hat

# ============================================================================
# PIN CONFIGURATION — PUSH BUTTON (BCM numbering, active LOW, internal pull-up)
# ============================================================================
BTN_MODE_PIN = 17       # GPIO17 (BCM) — Mode button
BTN_DEBOUNCE_MS = 200   # Debounce interval in ms

# ============================================================================
# SIGNAL SAMPLING CONFIGURATION
# ============================================================================

# Timer master frequency (internal buffer rate)
# MCP4725 I2C can sustain ~1 kHz writes in fast mode
FS_TIMER_HZ = 1000             # Hz — DAC output rate
SAMPLE_RATE_HZ = FS_TIMER_HZ   # Alias

# PPG model generation rate
# PPG bandwidth: 0.5–10 Hz → Nyquist = 20 Hz
# Using 100 Hz for smooth waveform display
MODEL_SAMPLE_RATE_PPG = 100     # Hz

# deltaTime for model (seconds)
MODEL_DT_PPG = 1.0 / MODEL_SAMPLE_RATE_PPG  # 10 ms

# Model tick interval in microseconds
MODEL_TICK_US_PPG = 1_000_000 // MODEL_SAMPLE_RATE_PPG  # 10000 us

# Upsample ratio: interpolation from model rate to timer rate
UPSAMPLE_RATIO_PPG = FS_TIMER_HZ // MODEL_SAMPLE_RATE_PPG  # 10

# ============================================================================
# MCP4725 DAC CONFIGURATION (12-bit)
# ============================================================================
DAC_RESOLUTION_BITS = 12
DAC_MAX_VALUE = 4095
DAC_CENTER_VALUE = 2048
DAC_VOLTAGE_MAX = 3.3           # Volts
DAC_MV_PER_STEP = DAC_VOLTAGE_MAX * 1000.0 / 4096.0  # ~0.806 mV

# ============================================================================
# DISPLAY CONFIGURATION (7-inch HDMI, 1024×600)
# ============================================================================
DISPLAY_WIDTH = 1024            # Pixels
DISPLAY_HEIGHT = 600            # Pixels
DISPLAY_FULLSCREEN = True
DISPLAY_FPS = 60                # Target frame rate

# Layout zones (proportional to screen)
HEADER_HEIGHT = 60              # Top metrics bar
FOOTER_HEIGHT = 40              # Bottom status bar
WAVEFORM_Y_START = HEADER_HEIGHT
WAVEFORM_HEIGHT = DISPLAY_HEIGHT - HEADER_HEIGHT - FOOTER_HEIGHT  # 500 px
WAVEFORM_WIDTH = DISPLAY_WIDTH

# Dual waveform layout (IR on top, Red on bottom)
WAVEFORM_IR_HEIGHT = WAVEFORM_HEIGHT // 2       # 250 px
WAVEFORM_RED_HEIGHT = WAVEFORM_HEIGHT // 2      # 250 px
WAVEFORM_RED_Y_START = WAVEFORM_Y_START + WAVEFORM_IR_HEIGHT

# ============================================================================
# BUFFER CONFIGURATION
# ============================================================================
SIGNAL_BUFFER_SIZE = 1024       # Samples (~1 second at 1 kHz)

# ============================================================================
# UI TIMING
# ============================================================================
METRICS_UPDATE_MS = 250         # 4 Hz text metrics update
WAVEFORM_UPDATE_MS = 20         # 50 Hz waveform drawing

# ============================================================================
# ADC CONFIGURATION (Grove Base Hat — 12-bit STM32 ADC)
# ============================================================================
ADC_MAX_VALUE = 4095            # 12-bit
ADC_VOLTAGE_REF = 3.3           # Volts

# ============================================================================
# COLOR PALETTE (RGB tuples for Pygame)
# ============================================================================
COLOR_BG            = (10, 10, 15)          # Near-black background
COLOR_WAVEFORM_IR   = (0, 255, 100)         # Bright green (PPG IR)
COLOR_WAVEFORM_RED  = (255, 60, 60)         # Red (PPG Red channel)
COLOR_WAVEFORM_DIM  = (0, 100, 40)          # Dim green for trailing
COLOR_GRID          = (30, 35, 45)          # Dark gray grid lines
COLOR_HEADER_BG     = (15, 15, 25)          # Dark header
COLOR_FOOTER_BG     = (15, 15, 25)          # Dark footer
COLOR_TEXT          = (220, 225, 235)        # Off-white text
COLOR_TEXT_VALUE    = (0, 220, 255)          # Cyan for values
COLOR_TEXT_LABEL    = (140, 145, 160)        # Light gray for labels
COLOR_HIGHLIGHT     = (255, 220, 50)        # Yellow highlight
COLOR_ACCENT        = (100, 120, 255)       # Blue accent
COLOR_SEPARATOR     = (40, 45, 60)          # Separator lines
COLOR_BUTTON_BG     = (30, 35, 55)          # Button background
COLOR_BUTTON_HOVER  = (50, 60, 90)          # Button hover
COLOR_BUTTON_ACTIVE = (70, 90, 140)         # Button active/pressed

# ============================================================================
# FONT CONFIGURATION
# ============================================================================
FONT_FAMILY = None  # Will use pygame default; set to a .ttf path for custom
FONT_SIZE_HEADER = 22
FONT_SIZE_VALUE = 28
FONT_SIZE_FOOTER = 18
FONT_SIZE_LABEL = 16
FONT_SIZE_SMALL = 14
