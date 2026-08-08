"""
opt101_rx.py — Dual-channel OPT101 acquisition via Grove Base Hat ADC (Phase 5).

Channel mapping [VERIFIED-USER 2026-07-12, fixed — never swap]:
    A0 (Grove ADC channel 0) = OPT101 IR  photodiode
    A2 (Grove ADC channel 2) = OPT101 Red photodiode
    A1 is NOT used for OPT101.

Verified grove.adc API (grove.py 0.6 source audit — see Phase 5 report):
    class ADC(address=...); read_raw(channel) reads register 0x10+channel
    (write_byte + read_word_data via a singleton smbus2 bus) and returns the
    raw 12-bit conversion as int. CRITICAL: on IOError the library prints a
    message and calls sys.exit(2) — every read below therefore catches
    SystemExit as well as Exception so a bus error can never kill this
    process or thread.

Thread ownership: one dedicated daemon thread ("OPT101Rx") is the sole reader
of the Grove ADC. It runs at RX_SAMPLE_RATE_HZ (decoupled from the 1 kHz TX
tick — Phase 4 timing budget shows per-tick RX does not fit at 100 kHz I2C).
The grove.adc smbus2 file descriptor is separate from the Blinka busio fd
used by DACManager; the kernel serializes individual I2C transactions per
adapter, and read_word_data re-addresses the register itself, so interleaved
DAC writes cannot corrupt an ADC read.

RX NEVER writes to the DACs and never imports the DAC/Blinka stack.

Failure semantics: a failed, invalid, or unavailable read appends NOTHING to
the buffers — values are never fabricated. Dry-run mode is a clearly labeled
simulation state that produces no samples at all (statuses report "dry-run",
is_simulated is True, buffers stay empty).
"""

import sys
import os
import time
import threading
from collections import deque
from typing import NamedTuple, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    GROVE_ADC_ADDR,
    ADC_CHANNEL_IR,
    ADC_CHANNEL_RED,
    ADC_MAX_VALUE,
    ADC_VOLTAGE_REF,
    RX_SAMPLE_RATE_HZ,
    RX_BUFFER_SIZE,
    RX_STALE_THRESHOLD_S,
    RX_DISCONNECT_ERROR_THRESHOLD,
    DRY_RUN,
)
from comm.logger import log

# Per-channel status values (strings so logs/UI can show them directly).
RX_STATUS_INIT = "init"                  # begin() not called / no read attempted yet
RX_STATUS_OK = "ok"                      # last read produced a valid sample
RX_STATUS_SATURATED = "saturated"        # last sample at full-scale (ADC clipping)
RX_STATUS_INVALID = "invalid"            # last read returned an out-of-range/non-int value
RX_STATUS_ERROR = "error"                # last read raised (I2C/library error)
RX_STATUS_DISCONNECTED = "disconnected"  # >= RX_DISCONNECT_ERROR_THRESHOLD consecutive errors
RX_STATUS_DRY_RUN = "dry-run"            # simulation mode — no real samples exist

# At 100 Hz a dead hat would emit ~100 log lines/s per channel;
# log the 1st failure per channel, then every Nth (same pattern as DACManager).
ERROR_LOG_INTERVAL = 100

# Responsiveness cap for the pacing sleep: stop() latency stays under ~2 ms
# without busy-waiting the 10 ms tick.
_SLEEP_QUANTUM_S = 0.002


class RXSample(NamedTuple):
    """One acquired OPT101 sample. `raw` is the authoritative value (12-bit
    ADC code, 0..4095). `timestamp` is time.monotonic() at read completion."""
    timestamp: float
    raw: int
    saturated: bool


def raw_to_millivolts(raw: int) -> float:
    """Estimate input millivolts from a raw code using the project's verified
    3.28 V Grove ADC reference (ADC_VOLTAGE_REF). This is a DERIVED estimate,
    not a measured value — the HAT MCU's own voltage register (0x20+ch) is the
    authoritative mV source and is deliberately not read per-sample to halve
    shared-bus traffic.

    ADC_VOLTAGE_REF is the RX-path scale factor and must never be replaced by
    DAC_FULLSCALE_V (the MCP4725 TX full-scale). Both hold 3.28 V on this
    build, but they are independent quantities: a future measurement may move
    one without the other."""
    return (float(raw) / ADC_MAX_VALUE) * (ADC_VOLTAGE_REF * 1000.0)


class _ChannelState:
    """Per-channel acquisition state. Mutated only by the RX thread (and
    begin()); read by any thread under the receiver's lock."""

    def __init__(self, name: str, channel: int, buffer_size: int):
        self.name = name
        self.channel = channel
        self.buffer = deque(maxlen=buffer_size)
        self.status = RX_STATUS_INIT
        self.error_count = 0
        self.consecutive_errors = 0
        self.invalid_count = 0
        self.saturation_count = 0


class OPT101Receiver:
    """Owner of the OPT101/Grove-ADC RX path (IR on A0, Red on A2).

    Read-only I2C client of the Grove ADC at config.GROVE_ADC_ADDR (0x08 on
    this MM32 Base HAT) — contains no DAC writes.
    """

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, adc=None, sample_rate_hz: Optional[float] = None,
                 buffer_size: Optional[int] = None, dry_run: Optional[bool] = None):
        """`adc`, `sample_rate_hz`, `buffer_size`, `dry_run` are injectable
        for hardware-free tests; production code uses the config defaults."""
        self._adc = adc
        self._rate = float(sample_rate_hz if sample_rate_hz is not None else RX_SAMPLE_RATE_HZ)
        self._dry_run = DRY_RUN if dry_run is None else bool(dry_run)
        size = int(buffer_size if buffer_size is not None else RX_BUFFER_SIZE)

        self._channels = {
            ADC_CHANNEL_IR: _ChannelState("IR", ADC_CHANNEL_IR, size),
            ADC_CHANNEL_RED: _ChannelState("Red", ADC_CHANNEL_RED, size),
        }
        self._lock = threading.Lock()
        self._ready = False
        self._running = False
        self._thread = None

    # ─────────────────────────── lifecycle ───────────────────────────

    def begin(self) -> bool:
        """Initialize the Grove ADC client and probe the hat with one real
        read. In dry-run mode no hardware is touched and no samples will
        ever be produced (clearly labeled simulation, nothing fabricated)."""
        if self._dry_run:
            log.info("[OPT101Rx] DRY-RUN mode — simulated RX: no ADC access, "
                     "buffers stay empty, statuses report 'dry-run'")
            with self._lock:
                for state in self._channels.values():
                    state.status = RX_STATUS_DRY_RUN
            self._ready = True
            return True

        if self._adc is None:
            try:
                from grove.adc import ADC
                self._adc = ADC(address=GROVE_ADC_ADDR)
            except Exception as e:
                log.error(f"[OPT101Rx] Failed to init grove.adc.ADC(0x{GROVE_ADC_ADDR:02X}): {e}")
                return False

        # Probe: one real read on the IR channel proves the hat is reachable.
        # grove.adc calls sys.exit(2) on IOError, hence SystemExit here.
        try:
            probe = self._adc.read_raw(ADC_CHANNEL_IR)
        except (SystemExit, Exception) as e:
            log.error(f"[OPT101Rx] Grove ADC (0x{GROVE_ADC_ADDR:02X}) probe read failed: {e!r}")
            return False

        self._ready = True
        log.info(f"[OPT101Rx] Grove ADC ready (addr 0x{GROVE_ADC_ADDR:02X}, "
                 f"IR=A{ADC_CHANNEL_IR}, Red=A{ADC_CHANNEL_RED}, "
                 f"{self._rate:.0f} Hz/ch, probe raw={probe})")
        return True

    def start(self) -> bool:
        """Start the dedicated acquisition thread (no-op in dry-run: a
        labeled simulation must not manufacture RX data)."""
        if not self._ready:
            log.error("[OPT101Rx] start() before successful begin() — ignored")
            return False
        if self._dry_run:
            log.info("[OPT101Rx] DRY-RUN — acquisition thread not started (no simulated samples)")
            return False
        if self._running:
            return True

        self._running = True
        self._thread = threading.Thread(target=self._acquisition_loop,
                                        name="OPT101Rx", daemon=True)
        self._thread.start()
        log.info("[OPT101Rx] Acquisition thread started")
        return True

    def stop(self):
        """Stop the acquisition thread and wait for it to exit."""
        self._running = False
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
            if thread.is_alive():
                log.error("[OPT101Rx] Acquisition thread did not stop within 2 s")
        self._thread = None

    def shutdown(self):
        """Stop acquisition and release readiness. RX has no outputs to park
        (read-only I2C client) — the DAC path is untouched by design."""
        self.stop()
        self._ready = False
        log.info("[OPT101Rx] Shutdown — acquisition stopped")

    # ─────────────────────────── acquisition ───────────────────────────

    def _acquisition_loop(self):
        period = 1.0 / self._rate
        next_tick = time.perf_counter()
        while self._running:
            self._acquire_once()
            next_tick += period
            now = time.perf_counter()
            if now - next_tick > period:
                # Fell behind (bus congestion / scheduling): resync instead
                # of bursting to catch up.
                next_tick = now
            while self._running:
                remaining = next_tick - time.perf_counter()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, _SLEEP_QUANTUM_S))

    def _acquire_once(self):
        """Read both channels, IR first then Red. A failure on one channel
        must not block or contaminate the other."""
        self._read_channel(self._channels[ADC_CHANNEL_IR])
        self._read_channel(self._channels[ADC_CHANNEL_RED])

    def _read_channel(self, state: _ChannelState):
        try:
            raw = self._adc.read_raw(state.channel)
        except SystemExit as e:
            # grove.adc read_register() calls sys.exit(2) on IOError; convert
            # to a channel error so a bus fault never terminates the thread.
            self._record_error(state, f"I2C error (grove.adc exit code {e.code})")
            return
        except Exception as e:
            self._record_error(state, repr(e))
            return

        timestamp = time.monotonic()

        # Validate before accepting: 12-bit code, genuine int (bool excluded).
        if not isinstance(raw, int) or isinstance(raw, bool) \
                or raw < 0 or raw > ADC_MAX_VALUE:
            with self._lock:
                state.invalid_count += 1
                state.consecutive_errors = 0
                state.status = RX_STATUS_INVALID
                count = state.invalid_count
            if count % ERROR_LOG_INTERVAL == 1:
                log.error(f"[OPT101Rx] {state.name} (A{state.channel}) invalid ADC value "
                          f"#{count}: {raw!r} — sample discarded")
            return

        saturated = raw >= ADC_MAX_VALUE
        sample = RXSample(timestamp=timestamp, raw=raw, saturated=saturated)
        with self._lock:
            state.buffer.append(sample)
            state.consecutive_errors = 0
            if saturated:
                state.saturation_count += 1
                state.status = RX_STATUS_SATURATED
            else:
                state.status = RX_STATUS_OK

    def _record_error(self, state: _ChannelState, message: str):
        with self._lock:
            state.error_count += 1
            state.consecutive_errors += 1
            newly_disconnected = (
                state.consecutive_errors == RX_DISCONNECT_ERROR_THRESHOLD)
            if state.consecutive_errors >= RX_DISCONNECT_ERROR_THRESHOLD:
                state.status = RX_STATUS_DISCONNECTED
            else:
                state.status = RX_STATUS_ERROR
            count = state.error_count
        if count % ERROR_LOG_INTERVAL == 1:
            log.error(f"[OPT101Rx] {state.name} (A{state.channel}) read error "
                      f"#{count}: {message}")
        if newly_disconnected:
            log.error(f"[OPT101Rx] {state.name} (A{state.channel}) marked DISCONNECTED "
                      f"after {RX_DISCONNECT_ERROR_THRESHOLD} consecutive errors")

    # ─────────────────────────── consumers ───────────────────────────

    def _state(self, channel: int) -> _ChannelState:
        try:
            return self._channels[channel]
        except KeyError:
            raise ValueError(
                f"Invalid RX channel {channel!r}: only A{ADC_CHANNEL_IR} (IR) "
                f"and A{ADC_CHANNEL_RED} (Red) carry OPT101 signals")

    def get_latest(self, channel: int) -> Optional[RXSample]:
        """Newest real sample for the channel, or None if none exists.
        Never returns a fabricated value."""
        state = self._state(channel)
        with self._lock:
            return state.buffer[-1] if state.buffer else None

    def get_samples(self, channel: int, n: Optional[int] = None) -> Tuple[RXSample, ...]:
        """Immutable snapshot of the most recent `n` samples (all if None),
        oldest first."""
        state = self._state(channel)
        with self._lock:
            samples = tuple(state.buffer)
        if n is not None and n < len(samples):
            samples = samples[len(samples) - n:]
        return samples

    def sample_count(self, channel: int) -> int:
        state = self._state(channel)
        with self._lock:
            return len(state.buffer)

    def channel_status(self, channel: int) -> str:
        state = self._state(channel)
        with self._lock:
            return state.status

    def is_stale(self, channel: int, now: Optional[float] = None,
                 threshold_s: float = RX_STALE_THRESHOLD_S) -> bool:
        """True if the channel has no sample yet, or its newest sample is
        older than `threshold_s`. `now` (time.monotonic domain) is injectable
        for deterministic tests."""
        latest = self.get_latest(channel)
        if latest is None:
            return True
        if now is None:
            now = time.monotonic()
        return (now - latest.timestamp) > threshold_s

    def error_count(self, channel: int) -> int:
        state = self._state(channel)
        with self._lock:
            return state.error_count

    def invalid_count(self, channel: int) -> int:
        state = self._state(channel)
        with self._lock:
            return state.invalid_count

    def saturation_count(self, channel: int) -> int:
        state = self._state(channel)
        with self._lock:
            return state.saturation_count

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_simulated(self) -> bool:
        """True when RX is in labeled dry-run simulation (no real samples)."""
        return self._dry_run
