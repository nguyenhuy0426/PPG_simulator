"""
adc_reader.py — Grove Base Hat ADC reader for potentiometer input.

Uses grove.adc (Seeed Studio Grove Base Hat for Raspberry Pi 4).
In dry-run mode, returns a simulated value controlled by the UI.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import GROVE_ADC_CHANNEL, ADC_MAX_VALUE, DRY_RUN
from comm.logger import log


class ADCReader:
    """Reads the potentiometer via the Grove Base Hat ADC."""

    def __init__(self):
        self._adc = None
        self._channel = GROVE_ADC_CHANNEL
        self._smoothed = 0.0
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
            log.info(f"[ADCReader] Grove ADC initialized, channel A{self._channel}, initial={raw}")
            return True
        except Exception as e:
            log.error(f"[ADCReader] Failed to initialize Grove ADC: {e}")
            log.info("[ADCReader] Falling back to simulated ADC")
            return False

    def read_raw(self) -> int:
        """Read raw 12-bit value (0-4095) with EMA smoothing."""
        if DRY_RUN or self._adc is None:
            return self._simulated_value

        try:
            raw = self._adc.read_raw(self._channel)
            # EMA filter (alpha = 0.2)
            self._smoothed = 0.8 * self._smoothed + 0.2 * float(raw)
            return int(self._smoothed)
        except Exception as e:
            log.error(f"[ADCReader] Read error: {e}")
            return int(self._smoothed)

    def set_simulated_value(self, value: int):
        """Set the simulated ADC value (for dry-run / mouse control)."""
        self._simulated_value = max(0, min(ADC_MAX_VALUE, value))
        self._smoothed = float(self._simulated_value)
