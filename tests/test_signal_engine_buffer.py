"""Tests for the signal engine ring buffer accounting.

The audit measured 984.5 samples/s produced against 881.2 samples/s consumed:
the 1024-sample ring wrapped roughly every 10 s and the writer walked straight
over unread samples with no counter, no log and no visible symptom.

The buffer must (a) never let the writer silently pass the reader and (b)
expose over/underrun counters so the condition is observable.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import SIGNAL_BUFFER_SIZE  # noqa: E402
from core.signal_engine import SignalEngine  # noqa: E402


@pytest.fixture
def engine():
    eng = SignalEngine()
    yield eng
    eng._stop_thread()


def test_stats_start_at_zero(engine):
    stats = engine.get_stats()

    assert stats["overruns"] == 0
    assert stats["underruns"] == 0
    assert stats["dropped_samples"] == 0


def test_reserve_space_does_not_count_an_overrun_when_the_buffer_is_empty(engine):
    engine._reserve_write_space(10)

    assert engine.get_stats()["overruns"] == 0
    assert engine.get_stats()["dropped_samples"] == 0


def test_writer_overtaking_reader_is_counted_and_bounded(engine):
    """Filling the ring without ever reading must be reported, not hidden."""
    for _ in range(SIGNAL_BUFFER_SIZE // 10 + 5):
        engine._reserve_write_space(10)
        engine._write_idx = (engine._write_idx + 10) % SIGNAL_BUFFER_SIZE

    stats = engine.get_stats()
    assert stats["overruns"] > 0
    assert stats["dropped_samples"] > 0
    # Dropping the oldest samples keeps the reader behind the writer, never
    # ahead of it: the readable count must stay within the ring.
    readable = (engine._write_idx - engine._read_idx) % SIGNAL_BUFFER_SIZE
    assert 0 <= readable < SIGNAL_BUFFER_SIZE


def test_pop_returns_none_and_counts_an_underrun_when_empty(engine):
    assert engine._pop_dac_sample() is None

    assert engine.get_stats()["underruns"] == 1


def test_pop_returns_written_samples_in_order(engine):
    engine._reserve_write_space(2)
    engine._buf_ir[engine._write_idx] = 111
    engine._buf_red[engine._write_idx] = 222
    engine._write_idx = (engine._write_idx + 1) % SIGNAL_BUFFER_SIZE
    engine._buf_ir[engine._write_idx] = 333
    engine._buf_red[engine._write_idx] = 444
    engine._write_idx = (engine._write_idx + 1) % SIGNAL_BUFFER_SIZE

    assert engine._pop_dac_sample() == (111, 222)
    assert engine._pop_dac_sample() == (333, 444)
    assert engine._pop_dac_sample() is None
    assert engine.get_stats()["underruns"] == 1


def test_reset_stats_clears_the_counters(engine):
    engine._pop_dac_sample()

    engine.reset_stats()

    assert engine.get_stats()["underruns"] == 0
