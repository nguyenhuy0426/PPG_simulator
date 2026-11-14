"""Does the received level match the commanded level within ± tolerance?

Used by the Calibration page: a DAC command of level ± swing mV is compared with
the millivolts read on the OPT101 lane (Δ = received − sent).
"""
from dataclasses import dataclass

SETTLE_S = 1.5        # ignore the first seconds after Start (LED/OPT101/RC settling)
WINDOW_S = 2.0        # judge the latest two seconds: two cycles at the 1 Hz minimum
MIN_SAMPLES = 20
EDGE = 0.03           # sine peak/trough as the 97th / 3rd percentile (−0.4 % of the swing, robust to spikes)


@dataclass(frozen=True)
class Match:
    ok: bool
    measured: tuple      # (median,) for a steady level, (peak, trough) for a sine
    error_mv: float      # largest |received - commanded| of the compared points


def _percentile(ordered, q):
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]


def level_match(values_mv, level_mv, swing_mv, tolerance_mv):
    """Match for received mV `values_mv` (oldest first) against level ± swing; None if too few samples."""
    if len(values_mv) < MIN_SAMPLES:
        return None
    ordered = sorted(values_mv)
    if swing_mv <= 0:
        measured = (_percentile(ordered, 0.5),)
        targets = (level_mv,)
    else:
        measured = (_percentile(ordered, 1 - EDGE), _percentile(ordered, EDGE))
        targets = (level_mv + swing_mv, level_mv - swing_mv)
    error = max((m - t for m, t in zip(measured, targets)), key=abs)
    return Match(abs(error) <= tolerance_mv, measured, error)
