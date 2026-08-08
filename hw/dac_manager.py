"""
dac_manager.py — Dual MCP4725 DAC manager for Raspberry Pi 4.

Port of dac_manager.cpp. Uses adafruit-circuitpython-mcp4725 via I2C.
In dry-run mode, simulates DAC output without hardware.

Channel mapping [VERIFIED-USER, fixed — never swap]:
    0x60 (DAC_ADDR_IR)  = IR  TX channel
    0x61 (DAC_ADDR_RED) = Red TX channel

Thread ownership: the SignalEngine generation thread is the sole writer while
a simulation runs; UI code (calibration frame) writes only after stopping the
engine. All writes are additionally serialized by _write_lock because the
adafruit MCP4725 driver shares one class-level payload buffer across BOTH DAC
instances and is documented as "not thread-safe or re-entrant by design".
This lock is also the single serialization point for the TX side of the
shared I2C bus (Phase 5 ADC reads use a separate driver/file descriptor;
the kernel serializes individual I2C transactions per adapter).
"""

import sys
import os
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DAC_ADDR_IR, DAC_ADDR_RED, DAC_MAX_VALUE, DAC_IDLE_VALUE, DRY_RUN
from comm.logger import log

# At the 1 kHz write rate a disconnected DAC would emit ~1000 log lines/s;
# log the 1st failure per channel, then every Nth.
ERROR_LOG_INTERVAL = 1000


class DACManager:
    """Manager for dual MCP4725 12-bit DACs (IR: 0x60, Red: 0x61)."""

    def __init__(self):
        self._ready = False
        self._dac_ir = None
        self._dac_red = None
        self._last_ir = DAC_IDLE_VALUE
        self._last_red = DAC_IDLE_VALUE
        self._write_lock = threading.Lock()
        self._error_count_ir = 0
        self._error_count_red = 0

    def begin(self) -> bool:
        """Initialize both MCP4725 DACs on the I2C bus (IR 0x60 first, then Red 0x61)."""
        if DRY_RUN:
            log.info("[DACManager] DRY-RUN mode — simulated DACs")
            self._ready = True
            return True

        try:
            import board
            import busio
            import adafruit_mcp4725

            i2c = busio.I2C(board.SCL, board.SDA)
            # Fixed channel mapping: 0x60 = IR, 0x61 = Red [VERIFIED-USER].
            self._dac_ir = adafruit_mcp4725.MCP4725(i2c, address=DAC_ADDR_IR)
            self._dac_red = adafruit_mcp4725.MCP4725(i2c, address=DAC_ADDR_RED)
            self._ready = True
            # Park outputs at the safe idle level (0 V → LEDs off).
            self.set_values(DAC_IDLE_VALUE, DAC_IDLE_VALUE)
            log.info(f"[DACManager] Both DACs initialized (IR: 0x{DAC_ADDR_IR:02X}, Red: 0x{DAC_ADDR_RED:02X})")
            return True
        except Exception as e:
            log.error(f"[DACManager] Failed to initialize DACs: {e}")
            self._ready = False
            return False

    def set_values(self, value_ir: int, value_red: int):
        """Write 12-bit values to both DACs — IR first, then Red.

        Each write is one 2-byte fast-mode I2C transaction, so Red always
        updates one transaction time after IR within the same 1 kHz tick.
        A write failure on one channel must not block the other channel.
        """
        value_ir = max(0, min(DAC_MAX_VALUE, int(value_ir)))
        value_red = max(0, min(DAC_MAX_VALUE, int(value_red)))
        self._last_ir = value_ir
        self._last_red = value_red

        if not self._ready:
            return

        if DRY_RUN:
            return

        with self._write_lock:
            try:
                self._dac_ir.raw_value = value_ir
            except Exception as e:
                self._error_count_ir += 1
                if self._error_count_ir % ERROR_LOG_INTERVAL == 1:
                    log.error(f"[DACManager] IR DAC (0x{DAC_ADDR_IR:02X}) write error #{self._error_count_ir}: {e}")
            try:
                self._dac_red.raw_value = value_red
            except Exception as e:
                self._error_count_red += 1
                if self._error_count_red % ERROR_LOG_INTERVAL == 1:
                    log.error(f"[DACManager] Red DAC (0x{DAC_ADDR_RED:02X}) write error #{self._error_count_red}: {e}")

    def shutdown(self):
        """Drive both channels to the safe idle level (0 V → LEDs off) and
        stop accepting hardware writes. Called once at process exit."""
        self.set_values(DAC_IDLE_VALUE, DAC_IDLE_VALUE)
        self._ready = False
        log.info("[DACManager] Shutdown — outputs parked at safe idle (0 V)")

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def last_ir(self) -> int:
        return self._last_ir

    @property
    def last_red(self) -> int:
        return self._last_red

    @property
    def error_count_ir(self) -> int:
        return self._error_count_ir

    @property
    def error_count_red(self) -> int:
        return self._error_count_red
