"""Tests for the fixed-rate tick scheduler used by the signal engine.

The audit found the generation loop did `last_tick = now` on every fire,
which throws away the overshoot between the deadline and the moment the loop
actually got scheduled. Over 120 s that made the simulated clock run at
0.9829x real time, i.e. a commanded 75 BPM played back at 73.7 BPM — outside
the +/-1 BPM the reference instrument (AECG100) specifies.

A correct fixed-rate ticker advances its deadline by exactly one period so the
error never accumulates, and bounds catch-up so a long stall cannot produce an
unbounded burst.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.rate_scheduler import FixedRateTicker  # noqa: E402


def test_no_tick_before_the_period_elapses():
    ticker = FixedRateTicker(period_s=0.01, now=100.0)

    assert ticker.due(100.009) == 0


def test_single_tick_when_exactly_one_period_elapses():
    ticker = FixedRateTicker(period_s=0.01, now=100.0)

    assert ticker.due(100.010) == 1


def test_deadline_does_not_drift_with_late_wakeups():
    """Late wakeups must not push the schedule forward.

    Each call arrives 1 ms late; after 1000 periods a `= now` scheduler would
    have lost a full second, a `+= period` scheduler loses nothing.
    """
    period = 0.01
    ticker = FixedRateTicker(period_s=period, now=0.0)

    ticks = 0
    for i in range(1, 1001):
        ticks += ticker.due(i * period + 0.001)

    assert ticks == 1000


def test_long_stall_produces_catch_up_ticks_up_to_the_limit():
    ticker = FixedRateTicker(period_s=0.01, period_catch_up_limit=5, now=0.0)

    assert ticker.due(1.0) == 5


def test_catch_up_limit_resynchronises_instead_of_backlogging():
    """After a bounded catch-up the deadline must be re-based on `now`.

    Otherwise the ticker keeps firing its limit forever, trying to repay a
    debt it already gave up on.
    """
    ticker = FixedRateTicker(period_s=0.01, period_catch_up_limit=5, now=0.0)
    ticker.due(1.0)

    assert ticker.due(1.005) == 0
    assert ticker.due(1.010) == 1


def test_reset_rebases_the_deadline():
    ticker = FixedRateTicker(period_s=0.01, now=0.0)
    ticker.reset(now=50.0)

    assert ticker.due(50.005) == 0
    assert ticker.due(50.010) == 1


def test_period_must_be_positive():
    with pytest.raises(ValueError):
        FixedRateTicker(period_s=0.0, now=0.0)
