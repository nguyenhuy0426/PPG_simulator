"""
grove_adc.py — Grove Base Hat ADC reader for the Pi 4 (MM32 Hat at 0x08).

Why not grove.adc.ADC.read_raw(): over the bcm2835 I2C master most reads of the
raw registers 0x10+ch come back as [lo, hi >> 1, ...], so bit 8 is lost and the
upper bits halve. A steady 2.54 V reads as code 1620 most of the time and 3156
in the rest (the 3156 = 0xC54, 1620 = 0x654 pair is the same value slipped).

The Hat's voltage registers 0x20+ch do not show this [VERIFIED on this Hat,
2026-11-03: 2700 reads over nine LED levels from 0.1 to 2.5 V, largest spread
28 mV at any level, none further than 30 mV from the median, and the value
agrees with the unslipped raw frames as mV = code * 3300 / 4095].
Why the two registers differ is not known. This reader therefore takes the
voltage register and converts it back to a 12-bit code. One count is 0.8 mV and
the register resolves 1 mV.

The register pointer must be written in its own transaction ending in a STOP.
A combined read alone does not move it on this Hat: it returns whatever the
last STOP-terminated write selected, which is all zeros after power-up
[VERIFIED 2026-11-03]. Hence write_byte before each read, as grove.adc does.

Nothing is fabricated: an out-of-range value raises OSError and the receiver
records a read error. Unlike grove.adc this never calls sys.exit().
"""
import threading

ADC_VOLTAGE_REGISTER = 0x20  # + channel; millivolts
ADC_MAX_CODE = 4095
ADC_FULL_SCALE_MV = 3300     # the Hat's own conversion, code * 3300 / 4095


class GroveVoltageADC:
    """read_raw(channel) has the same contract as grove.adc.ADC."""

    def __init__(self, address, bus=1, smbus=None):
        if smbus is None:
            import smbus2
            smbus = smbus2.SMBus(bus)
        self._bus = smbus
        self._address = address
        self._lock = threading.Lock()

    def read_raw(self, channel: int) -> int:
        """12-bit code for `channel`, from the voltage register."""
        register = ADC_VOLTAGE_REGISTER + channel
        with self._lock:
            self._bus.write_byte(self._address, register)
            millivolts = self._bus.read_word_data(self._address, register)
        if millivolts > ADC_FULL_SCALE_MV:
            raise OSError(f"Grove ADC 0x{self._address:02X} A{channel}: "
                          f"{millivolts} mV is above full scale")
        return round(millivolts * ADC_MAX_CODE / ADC_FULL_SCALE_MV)
