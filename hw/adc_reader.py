"""
DEPRECATED: This module is no longer used. UI sliders now control parameters.

adc_reader.py — Grove Base Hat ADC reader for potentiometer input.

Uses grove.adc (Seeed Studio Grove Base Hat for Raspberry Pi 4).
In dry-run mode, returns a simulated value controlled by the UI.

Smoothing strategy:
  - Heavy EMA (alpha=0.05) to remove high-frequency ADC noise
  - Deadzone (±15 counts) to reject small jitter around a stable position
  - This prevents erratic parameter/condition jumping when the pot is held still
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import GROVE_ADC_CHANNEL, ADC_MAX_VALUE, DRY_RUN
from comm.logger import log

# ADC smoothing parameters
_EMA_ALPHA = 0.05          # Heavy smoothing to suppress noise
_DEADZONE = 15             # Ignore changes smaller than this (out of 4095)


class ADCReader:
    """Reads the potentiometer via the Grove Base Hat ADC."""

    def __init__(self):
        self._adc = None
        self._channel = GROVE_ADC_CHANNEL
        self._smoothed = 0.0
        self._output = 0            # Last committed output value (after deadzone)
        self._simulated_value = 2048  # Mid-scale for dry-run

    def begin(self) -> bool:
        """Initialize the Grove Base Hat ADC."""
        if DRY_RUN:
            log.info("[ADCReader] DRY-RUN mode — simulated ADC")
            return True

        try:
            from grove.adc import ADC
            self._adc = ADC()
            raw = self._adc.read_raw(self._channel)
            self._smoothed = float(raw)
            self._output = raw
            log.info(f"[ADCReader] Grove ADC initialized, channel A{self._channel}, initial={raw}")
            return True
        except Exception as e:
            log.error(f"[ADCReader] Failed to initialize Grove ADC: {e}")
            log.info("[ADCReader] Falling back to simulated ADC")
            return False

    def read_raw(self) -> int:
        """Read raw 12-bit value (0-4095) with heavy EMA smoothing + deadzone.

        The deadzone prevents the output from changing unless the smoothed
        value moves more than _DEADZONE counts away from the last committed
        output. This eliminates jitter when the pot is held in a fixed position.
        """
        if DRY_RUN or self._adc is None:
            return self._simulated_value

        try:
            raw = self._adc.read_raw(self._channel)
            # Heavy EMA filter (alpha = 0.05) for strong noise suppression
            self._smoothed = (1.0 - _EMA_ALPHA) * self._smoothed + _EMA_ALPHA * float(raw)

            # Deadzone: only update output if smoothed moved far enough
            smoothed_int = int(self._smoothed)
            if abs(smoothed_int - self._output) >= _DEADZONE:
                self._output = smoothed_int

            # Clamp to valid range
            return max(0, min(ADC_MAX_VALUE, self._output))
        except Exception as e:
            log.error(f"[ADCReader] Read error: {e}")
            return max(0, min(ADC_MAX_VALUE, self._output))

    def set_simulated_value(self, value: int):
        """Set the simulated ADC value (for dry-run / mouse control)."""
        self._simulated_value = max(0, min(ADC_MAX_VALUE, value))
        self._smoothed = float(self._simulated_value)
        self._output = self._simulated_value
