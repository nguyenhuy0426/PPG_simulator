"""FramedGroveADC undoes the Pi 4 one-bit slip of Grove Hat frames.

Hardware-free: a scripted SMBus replays frames measured on the Pi 4 Hat.
Intact: [lo, hi, x != 0xFF]. Slipped: [lo, hi >> 1, 0xFF].
"""
import logging

import pytest

from hw.grove_adc import FramedGroveADC, FRAMES_WITHOUT_SLIP_PROOF
from hw.opt101_rx import OPT101Receiver

ADDR = 0x08
CODE_2945 = [0x81, 11, 192]   # intact
SLIPPED_2945 = [0x81, 5, 0xFF]


@pytest.fixture(autouse=True)
def quiet_logs():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


class ScriptedBus:
    def __init__(self, frames=()):
        self.frames = list(frames)
        self.calls = []

    def read_i2c_block_data(self, address, register, length):
        self.calls.append((address, register, length))
        return self.frames.pop(0) if self.frames else list(SLIPPED_2945)


def test_intact_frame_is_the_code_and_reads_register_0x10_plus_channel():
    bus = ScriptedBus([CODE_2945])
    assert FramedGroveADC(ADDR, smbus=bus).read_raw(2) == 2945
    assert bus.calls == [(ADDR, 0x12, 3)]


@pytest.mark.parametrize("near, expected", [(2950, 2945), (2700, 2689)])
def test_slipped_frame_takes_the_candidate_nearest_the_previous_sample(near, expected):
    # 0x581 with bit 8 lost: 0xA81 = 2689 or 0xB81 = 2945.
    adc = FramedGroveADC(ADDR, smbus=ScriptedBus(), max_attempts=3)
    assert adc.read_near(0, near) == expected


def test_intact_frame_wins_over_the_previous_sample():
    bus = ScriptedBus([SLIPPED_2945, CODE_2945])
    assert FramedGroveADC(ADDR, smbus=bus).read_near(0, 100) == 2945


def test_first_read_waits_for_an_intact_frame():
    bus = ScriptedBus([SLIPPED_2945] * 5 + [CODE_2945])
    assert FramedGroveADC(ADDR, smbus=bus).read_raw(0) == 2945
    assert len(bus.calls) == 6


def test_undecidable_read_raises_and_returns_no_guess():
    adc = FramedGroveADC(ADDR, smbus=ScriptedBus(), sync_attempts=4)
    with pytest.raises(OSError):
        adc.read_raw(0)


def test_slipped_frame_far_from_the_previous_sample_is_not_trusted():
    adc = FramedGroveADC(ADDR, smbus=ScriptedBus(), max_attempts=3)
    with pytest.raises(OSError):
        adc.read_near(0, 100)


def test_candidates_above_12_bits_are_ignored():
    adc = FramedGroveADC(ADDR, smbus=ScriptedBus([[0x10, 7, 0xFF]] * 3), max_attempts=3)
    # 0xE10 or 0xF10; both valid. 0x810 hi 8 would give 0x1010, out of range.
    assert adc.read_near(0, 3700) == 0xE10
    adc = FramedGroveADC(ADDR, smbus=ScriptedBus([[0x10, 8, 0xFF]] * 3), max_attempts=3)
    with pytest.raises(OSError):
        adc.read_near(0, 3700)


def test_a_bus_without_the_slip_is_read_as_plain_frames():
    adc = FramedGroveADC(ADDR, smbus=ScriptedBus([[0x25, 2, 0xFF]] * (FRAMES_WITHOUT_SLIP_PROOF + 1)),
                         sync_attempts=FRAMES_WITHOUT_SLIP_PROOF)
    with pytest.raises(OSError):
        adc.read_raw(0)
    assert not adc.slip_decoding
    assert adc.read_raw(0) == 0x225


def test_receiver_uses_the_lane_history_for_slipped_frames():
    bus = ScriptedBus([CODE_2945])
    rx = OPT101Receiver(adc=FramedGroveADC(ADDR, smbus=bus), dry_run=False, enabled_channels=(0,))
    assert rx.begin()
    bus.frames = [CODE_2945, SLIPPED_2945, SLIPPED_2945, SLIPPED_2945]
    state = rx._channels[0]
    assert rx._read_channel(state).raw == 2945
    assert rx._read_channel(state).raw == 2945


def test_receiver_records_an_error_and_no_sample_when_undecidable():
    bus = ScriptedBus([CODE_2945])
    rx = OPT101Receiver(adc=FramedGroveADC(ADDR, smbus=bus, sync_attempts=3),
                        dry_run=False, enabled_channels=(0,))
    assert rx.begin()
    assert rx._read_channel(rx._channels[0]) is None
    assert rx.error_count(0) == 1 and rx.sample_count(0) == 0
