"""
config.py — Global system configuration for PPG Signal Simulator (Raspberry Pi 4)

Hardware: Raspberry Pi 4 + Grove Base Hat (ADC) + Dual MCP4725 DAC (I2C)
         + HDMI display (auto-detect resolution) + 1 push button + 1 potentiometer (5 kΩ)

Port of the ESP32-S3 config.h to Python.
"""

import os

# ============================================================================
# SYSTEM IDENTIFICATION
# ============================================================================
DEVICE_NAME = "PPG Signal Simulator"
FIRMWARE_VERSION = "3.1.0"
FIRMWARE_DATE = "01 May 2026"
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
DAC_VOLTAGE_MAX = 3.3            # Volts (MCP4725 VDD = 3.3V)
DAC_V_PER_STEP = DAC_VOLTAGE_MAX / 4096.0     # ~0.000806 V per step

# ============================================================================
# DISPLAY CONFIGURATION — Auto-detect resolution
# ============================================================================
# Set to 0 for auto-detection at runtime via pygame.display.Info()
# Override with fixed values for specific screens (e.g., headless testing)
DISPLAY_WIDTH = 0               # 0 = auto-detect
DISPLAY_HEIGHT = 0              # 0 = auto-detect
DISPLAY_FULLSCREEN = True
DISPLAY_FPS = 60                # Target frame rate

# ============================================================================
# WAVEFORM DISPLAY CONFIGURATION
# ============================================================================
# Duration of waveform visible on screen (seconds)
# At 50 Hz GUI update rate, 5s = 250 points across the screen width
WAVEFORM_DISPLAY_DURATION = 15.0    # seconds — extended for better observation

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
# COLOR PALETTE (RGB tuples for Pygame) matching Android UI
# ============================================================================
COLOR_BG            = (0, 0, 0)             # Pure black background
COLOR_WAVEFORM_IR   = (0, 255, 128)         # Neon green
COLOR_WAVEFORM_RED  = (0, 255, 128)         # Make red channel same as IR to match "PPG" trace
COLOR_WAVEFORM_DIM  = (0, 80, 40)           # Dim green
COLOR_GRID          = (0, 40, 20)           # Dark green grid lines
COLOR_HEADER_BG     = (0, 0, 0)             # Black header
COLOR_FOOTER_BG     = (0, 0, 0)             # Black footer
COLOR_TEXT          = (0, 255, 128)         # Neon green text
COLOR_TEXT_VALUE    = (0, 255, 128)         # Neon green for values
COLOR_TEXT_LABEL    = (0, 150, 75)          # Darker green for labels
COLOR_HIGHLIGHT     = (0, 255, 128)         # Neon green highlight
COLOR_ACCENT        = (0, 255, 128)         # Neon green accent
COLOR_SEPARATOR     = (0, 60, 30)           # Dark green separators
COLOR_BUTTON_BG     = (0, 40, 20)           # Inactive button dark green
COLOR_BUTTON_HOVER  = (0, 120, 60)          # Button hover
COLOR_BUTTON_ACTIVE = (0, 255, 128)         # Active button neon green
COLOR_TIME_AXIS     = (0, 100, 50)          # Time axis text/ticks

# ============================================================================
# FONT CONFIGURATION (base sizes — will be scaled proportionally at runtime)
# ============================================================================
FONT_FAMILY = None  # Will use pygame default; set to a .ttf path for custom

# Base sizes at 600px screen height (scale proportionally)
FONT_SIZE_BASE_HEIGHT = 600     # Reference height for font sizes
FONT_SIZE_HEADER = 22
FONT_SIZE_VALUE = 28
FONT_SIZE_FOOTER = 18
FONT_SIZE_LABEL = 16
FONT_SIZE_SMALL = 14

# Maximum font scale factor (cap for very large screens)
FONT_SCALE_MAX = 2.5


# ============================================================================
# LAYOUT PROPORTIONS (percentage of screen dimensions)
# ============================================================================
LAYOUT_HEADER_RATIO = 0.10       # 10% for header
LAYOUT_LEFT_MENU_RATIO = 0.0     # 0% for left menu (disabled to center UI)
LAYOUT_WAVEFORM_H_RATIO = 0.45   # 45% for waveform (below header)
LAYOUT_CONTROLS_H_RATIO = 0.45   # 45% for bottom controls

def compute_layout(screen_w: int, screen_h: int) -> dict:
    """Compute all layout dimensions from actual screen size."""
    header_h = int(screen_h * LAYOUT_HEADER_RATIO)
    left_menu_w = int(screen_w * LAYOUT_LEFT_MENU_RATIO)
    waveform_h = int(screen_h * LAYOUT_WAVEFORM_H_RATIO)
    controls_h = screen_h - header_h - waveform_h
    
    waveform_w = screen_w - left_menu_w

    # Font scaling: proportional to screen height
    font_scale = min(screen_h / FONT_SIZE_BASE_HEIGHT, FONT_SCALE_MAX)

    return {
        "screen_w": screen_w,
        "screen_h": screen_h,
        "header_h": header_h,
        "left_menu_w": left_menu_w,
        "controls_h": controls_h,
        "waveform_x": left_menu_w,
        "waveform_y": header_h,
        "waveform_w": waveform_w,
        "waveform_h": waveform_h,
        "controls_y": header_h + waveform_h,
        "font_scale": font_scale,
        "font_header": max(14, int(FONT_SIZE_HEADER * font_scale)),
        "font_value": max(16, int(FONT_SIZE_VALUE * font_scale)),
        "font_footer": max(12, int(FONT_SIZE_FOOTER * font_scale)),
        "font_label": max(10, int(FONT_SIZE_LABEL * font_scale)),
        "font_small": max(10, int(FONT_SIZE_SMALL * font_scale)),
    }
