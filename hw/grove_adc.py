"""
grove_adc.py — Grove Base Hat ADC reader that undoes the Pi 4 I2C bit slip.

Why not grove.adc.ADC.read_raw(): with the bcm2835 I2C master and the MM32 Hat
(0x08) most 16-bit register reads slip one bit, so the frame is
[lo, hi >> 1, 0xFF]. Bit 8 is lost and the upper bits read half their value.
The library returns that as is, which draws a 1 V level as 0.45 V and a smooth
ramp as a sawtooth dropping at every other 256-count boundary.

Evidence [VERIFIED on this Hat, 2026-11-02, reading three bytes from 0x10+ch]:
about 15 % of frames arrive intact as [lo, hi, x] with x != 0xFF. On an LED step
the intact frames form a smooth exponential (largest backward step 29 counts in
508 frames) while the slipped ones saw-tooth by up to 1022 counts. At steady
levels intact and slipped frames agree on lo, and intact hi >> 1 == slipped hi
(hi 11/5, 10/5, 5/2). The same pattern appears at any bus timing a userspace
program can choose: stop vs repeated start, 0-5 ms gaps.

Decoding: an intact frame gives the code directly. A slipped frame leaves two
candidates 256 counts apart, and the one nearer the lane's previous sample is
taken. A lane that moved more than 128 counts between samples can pick wrongly
until its next intact frame, so an error heals within a few samples. With no
previous sample, only an intact frame is accepted.

If FRAMES_WITHOUT_SLIP_PROOF frames in a row are all "slipped" the premise does
not hold here (other Hat, or a bus speed that avoids the slip), so the reader
logs once and treats frames as plain [lo, hi].

Nothing is fabricated: when no code can be decided an OSError is raised and the
receiver records a read error. Unlike grove.adc this never calls sys.exit().
"""
import threading

from config import RX_ADC_MAX_ATTEMPTS, RX_ADC_SYNC_ATTEMPTS
from comm.logger import log

ADC_RAW_REGISTER = 0x10     # + channel
ADC_MAX_CODE = 4095
FRAME_IDLE_BYTE = 0xFF      # third byte of a slipped frame: the bus idles high
BIT_8 = 1 << 8
MAX_PLAUSIBLE_JUMP = 512    # counts from the previous sample for a slipped frame
FRAMES_WITHOUT_SLIP_PROOF = 256


class FramedGroveADC:
    """read_raw(channel) has the same contract as grove.adc.ADC."""

    def __init__(self, address, bus=1, smbus=None, max_attempts=None, sync_attempts=None):
        if smbus is None:
            import smbus2
            smbus = smbus2.SMBus(bus)
        self._bus = smbus
        self._address = address
        self._max_attempts = RX_ADC_MAX_ATTEMPTS if max_attempts is None else int(max_attempts)
        self._sync_attempts = RX_ADC_SYNC_ATTEMPTS if sync_attempts is None else int(sync_attempts)
        self._lock = threading.Lock()
        self._slip_decoding = True
        self._slipped_in_a_row = 0
        self.frames_read = 0
        self.frames_intact = 0

    @property
    def slip_decoding(self) -> bool:
        return self._slip_decoding

    def read_raw(self, channel: int) -> int:
        return self.read_near(channel, None)

    def read_near(self, channel: int, near) -> int:
        """Code for `channel`; `near` is the lane's previous code, or None."""
        register = ADC_RAW_REGISTER + channel
        attempts = self._sync_attempts if near is None else self._max_attempts
        best = None
        with self._lock:
            for _ in range(attempts):
                lo, hi, third = self._bus.read_i2c_block_data(self._address, register, 3)
                self.frames_read += 1
                if not self._slip_decoding or third != FRAME_IDLE_BYTE:
                    self.frames_intact += 1
                    self._slipped_in_a_row = 0
                    return lo | (hi << 8)
                self._note_slipped_frame()
                if near is not None:
                    best = self._nearest_candidate(lo, hi, near)
        if best is None:
            raise OSError(f"Grove ADC 0x{self._address:02X} A{channel}: "
                          f"no decodable frame in {attempts} reads")
        return best

    @staticmethod
    def _nearest_candidate(lo, hi, near):
        low = lo | (hi << 9)
        candidates = [c for c in (low, low + BIT_8) if c <= ADC_MAX_CODE]
        if not candidates:
            return None
        best = min(candidates, key=lambda c: abs(c - near))
        return best if abs(best - near) <= MAX_PLAUSIBLE_JUMP else None

    def _note_slipped_frame(self):
        self._slipped_in_a_row += 1
        if self._slipped_in_a_row >= FRAMES_WITHOUT_SLIP_PROOF:
            self._slip_decoding = False
            log.error(f"[GroveADC] 0x{self._address:02X}: no intact frame in "
                      f"{FRAMES_WITHOUT_SLIP_PROOF} reads — bit-slip decoding off, "
                      "reading frames as plain [lo, hi]")
