"""
dac_manager.py — Dual MCP4725 DAC manager for Raspberry Pi 4.

Port of dac_manager.cpp. Uses adafruit-circuitpython-mcp4725 via I2C.
In dry-run mode, simulates DAC output without hardware.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DAC_ADDR_IR, DAC_ADDR_RED, DAC_MAX_VALUE, DAC_CENTER_VALUE, DRY_RUN
from comm.logger import log


class DACManager:
    """Manager for dual MCP4725 12-bit DACs (IR and Red channels)."""

    def __init__(self):
        self._ready = False
        self._dac_ir = None
        self._dac_red = None
        self._last_ir = DAC_CENTER_VALUE
        self._last_red = DAC_CENTER_VALUE

    def begin(self) -> bool:
        """Initialize both MCP4725 DACs on the I2C bus."""
        if DRY_RUN:
            log.info("[DACManager] DRY-RUN mode — simulated DACs")
            self._ready = True
            return True

        try:
            import board
            import busio
            import adafruit_mcp4725

            i2c = busio.I2C(board.SCL, board.SDA)
            self._dac_ir = adafruit_mcp4725.MCP4725(i2c, address=DAC_ADDR_IR)
            self._dac_red = adafruit_mcp4725.MCP4725(i2c, address=DAC_ADDR_RED)
            self._ready = True
            self.set_values(DAC_CENTER_VALUE, DAC_CENTER_VALUE)
            log.info(f"[DACManager] Both DACs initialized (IR: 0x{DAC_ADDR_IR:02X}, Red: 0x{DAC_ADDR_RED:02X})")
            return True
        except Exception as e:
            log.error(f"[DACManager] Failed to initialize DACs: {e}")
            self._ready = False
            return False

    def set_values(self, value_ir: int, value_red: int):
        """Write 12-bit values to both DACs."""
        value_ir = max(0, min(DAC_MAX_VALUE, value_ir))
        value_red = max(0, min(DAC_MAX_VALUE, value_red))
        self._last_ir = value_ir
        self._last_red = value_red

        if not self._ready:
            return

        if DRY_RUN:
            return

        try:
            # MCP4725 raw_value expects 0-4095 (12-bit)
            self._dac_ir.raw_value = value_ir
            self._dac_red.raw_value = value_red
        except Exception as e:
            log.error(f"[DACManager] DAC write error: {e}")

    @staticmethod
    def ppg_sample_to_dac_value(sample_mv: float, dc_baseline: float, max_ac: float) -> int:
        """Map a PPG sample (mV) to a 12-bit DAC value."""
        min_v = dc_baseline - max_ac
        max_v = dc_baseline + max_ac
        if max_v <= min_v:
            return DAC_CENTER_VALUE
        normalized = (sample_mv - min_v) / (max_v - min_v)
        normalized = max(0.0, min(1.0, normalized))
        return int(normalized * 4095.0)

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def last_ir(self) -> int:
        return self._last_ir

    @property
    def last_red(self) -> int:
        return self._last_red
