"""rate_scheduler.py — drift-free fixed-rate tick scheduling.

The signal engine has two periodic jobs with hard rate requirements:
the PPG model tick (100 Hz) and the DAC update (1 kHz). Both used to be
driven by `if now - last >= period: last = now`, which silently absorbs the
overshoot: every late wakeup shortens the simulated timeline, so the played
back heart rate ends up lower than the commanded one.

`FixedRateTicker` advances its deadline by exactly one period per tick, so
the scheduling error is bounded by one period instead of accumulating. A
bounded catch-up keeps a long stall (a GC pause, a blocked I2C write) from
producing an unbounded burst of ticks.
"""

DEFAULT_CATCH_UP_LIMIT = 4


class FixedRateTicker:
    """Counts how many fixed-period deadlines have passed, without drifting."""

    __slots__ = ("_period", "_limit", "_next_deadline")

    def __init__(self, period_s: float, now: float,
                 period_catch_up_limit: int = DEFAULT_CATCH_UP_LIMIT) -> None:
        if period_s <= 0.0:
            raise ValueError("period_s must be > 0")
        if period_catch_up_limit < 1:
            raise ValueError("period_catch_up_limit must be >= 1")
        self._period = period_s
        self._limit = period_catch_up_limit
        self._next_deadline = now + period_s

    @property
    def period_s(self) -> float:
        return self._period

    def reset(self, now: float) -> None:
        """Re-base the schedule on `now` (used when the loop (re)starts)."""
        self._next_deadline = now + self._period

    def due(self, now: float) -> int:
        """Return how many periods have elapsed since the last call.

        The deadline advances by whole periods so the long-run rate stays
        exact. If more than `period_catch_up_limit` periods are owed, the
        surplus is dropped and the schedule is re-based on `now` — repaying an
        arbitrarily large debt would only make the next stall worse.
        """
        if now < self._next_deadline:
            return 0

        ticks = 0
        while now >= self._next_deadline and ticks < self._limit:
            self._next_deadline += self._period
            ticks += 1

        if now >= self._next_deadline:
            # Still behind after the allowed catch-up: give up on the backlog.
            self.reset(now)

        return ticks
