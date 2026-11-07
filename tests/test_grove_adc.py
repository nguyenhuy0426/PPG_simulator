"""GroveVoltageADC reads the Hat's voltage register with a STOP-terminated pointer write.

Hardware-free: the scripted bus models what was measured on the Pi 4 Hat, where
a combined read alone returns the register selected by the last plain write.
"""
import logging

import pytest

from hw.grove_adc import GroveVoltageADC
from hw.opt101_rx import OPT101Receiver

ADDR = 0x08


@pytest.fixture(autouse=True)
def quiet_logs():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


class LatchingBus:
    """Reads ignore their register argument, as the Hat does."""

    def __init__(self, registers):
        self.registers = registers
        self.pointer = None

    def write_byte(self, address, register):
        assert address == ADDR
        self.pointer = register

    def read_word_data(self, address, _register):
        assert address == ADDR
        return self.registers.get(self.pointer, 0)


@pytest.mark.parametrize("millivolts, code", [(0, 0), (1, 1), (2542, 3154), (3300, 4095)])
def test_voltage_register_is_converted_to_a_12_bit_code(millivolts, code):
    assert GroveVoltageADC(ADDR, smbus=LatchingBus({0x20: millivolts})).read_raw(0) == code


def test_each_read_moves_the_pointer_so_channels_do_not_alias():
    adc = GroveVoltageADC(ADDR, smbus=LatchingBus({0x20: 1000, 0x24: 2000}))
    assert [adc.read_raw(0), adc.read_raw(4), adc.read_raw(0)] == [1241, 2482, 1241]


def test_value_above_full_scale_raises_and_returns_no_guess():
    with pytest.raises(OSError):
        GroveVoltageADC(ADDR, smbus=LatchingBus({0x20: 0x8000})).read_raw(0)


def test_receiver_records_an_error_and_no_sample_on_a_bad_value():
    bus = LatchingBus({0x20: 1000})
    rx = OPT101Receiver(adc=GroveVoltageADC(ADDR, smbus=bus), dry_run=False, enabled_channels=(0,))
    assert rx.begin()
    assert rx._read_channel(rx._channels[0]).raw == 1241
    bus.registers[0x20] = 0xFFFF
    assert rx._read_channel(rx._channels[0]) is None
    assert rx.error_count(0) == 1 and rx.sample_count(0) == 1
