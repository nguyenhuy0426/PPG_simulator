"""Display filter for the RX lanes: drop isolated spikes, then smooth lightly.

Measured on the Pi (docs/hardware-validation/2026-11-14-ir-overload, section 10): the OPT101 lanes
have ~1 mV MAD background noise plus isolated 1-3 sample spikes of +-15..100 mV, about one or two
per second. A run of 1-3 samples that leaves the chord between its neighbours by more than
max(12 mV, 6 noise sigmas) is replaced by that chord; a centred moving average of SMOOTH_HALF*2+1 samples then removes the
remaining 1 mV ripple without delaying the trace. At 100 Hz the 5-sample average keeps 99.6 % of a
1.25 Hz pulse and 65 % at 10 Hz.

Only the plotted trace is filtered. Runs longer than the spike length (an LED that is really off,
the trace falling to 0 mV for seconds) pass unchanged, so hardware faults stay visible. Rate, SpO2,
RR and the Calibration match read the raw samples.
"""
from typing import List, Sequence, Tuple

MAX_SPIKE_LEN = 3        # spikes measured on the Pi last 1-3 samples (10-30 ms)
SPIKE_SIGMAS = 6.0       # threshold in robust noise sigmas
MIN_SPIKE_MV = 12.0      # never below this: a 74 mV RX pulse bends <= 12 mV from a 3-sample chord at 100 Hz
SMOOTH_HALF = 2          # 5-sample centred moving average

Point = Tuple[float, float]


def _segments(points: Sequence[Point], max_gap_s: float) -> List[List[Point]]:
    out: List[List[Point]] = []
    for point in points:
        if out and point[0] - out[-1][-1][0] <= max_gap_s:
            out[-1].append(point)
        else:
            out.append([point])
    return out


def noise_sigma(values: Sequence[float]) -> float:
    """Robust white-noise sigma from second differences (insensitive to the slow pulse itself)."""
    d2 = sorted(abs(values[i] - 2 * values[i + 1] + values[i + 2]) for i in range(len(values) - 2))
    return 1.4826 * d2[len(d2) // 2] / 6 ** .5 if d2 else 0.0


def despike(values: Sequence[float]) -> List[float]:
    """Replace runs of 1..MAX_SPIKE_LEN samples that all sit on one side of the straight line
    between their two neighbours, farther than the threshold, by that line."""
    out = list(values)
    threshold = max(MIN_SPIKE_MV, SPIKE_SIGMAS * noise_sigma(values))
    n = len(out)
    for length in range(1, MAX_SPIKE_LEN + 1):
        i = 1
        while i + length < n:
            a, b = out[i - 1], out[i + length]
            line = [a + (b - a) * (k + 1) / (length + 1) for k in range(length)]
            dev = [out[i + k] - line[k] for k in range(length)]
            # A spike returns to the trend: it must stand out more than the neighbours differ,
            # otherwise this is a step (LED switching on/off) and is kept.
            if (all(d > threshold for d in dev) or all(d < -threshold for d in dev)) \
                    and min(abs(d) for d in dev) > abs(b - a):
                out[i:i + length] = line
                i += length
            else:
                i += 1
    return out


def smooth(values: Sequence[float]) -> List[float]:
    n = len(values)
    out = []
    for i in range(n):
        lo, hi = max(0, i - SMOOTH_HALF), min(n, i + SMOOTH_HALF + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def filter_points(points: Sequence[Point], max_gap_s: float) -> List[Point]:
    """(t, mV) points -> despiked and smoothed points; segments split at gaps are filtered apart."""
    result: List[Point] = []
    for segment in _segments(points, max_gap_s):
        values = smooth(despike([v for _, v in segment]))
        result.extend((t, v) for (t, _), v in zip(segment, values))
    return result


CONTEXT = 64                                   # samples re-filtered behind the newest ones
SETTLE = MAX_SPIKE_LEN + SMOOTH_HALF + 2       # beyond this many samples from the end a value no longer changes


class StreamFilter:
    """filter_points for a scrolling window, re-filtering only the new samples plus CONTEXT.

    Refiltering the whole 8 s window (800 points) costs ~15 ms per lane on the Pi 4 at the
    10 Hz panel refresh; the newest ~10 samples plus context cost ~1 ms."""

    def __init__(self):
        self._settled = {}                     # timestamp -> filtered mV

    def update(self, points: Sequence[Point], max_gap_s: float) -> List[Point]:
        """`points`: (absolute timestamp, mV), oldest first; returns the filtered points."""
        if not points:
            self._settled.clear()
            return []
        first_new = next((i for i, (t, _) in enumerate(points) if t not in self._settled), len(points))
        start = max(0, first_new - CONTEXT)
        fresh = filter_points(points[start:], max_gap_s)[first_new - start:]
        out = [(t, self._settled[t]) for t, _ in points[:first_new]] + fresh
        oldest = points[0][0]
        self._settled = {t: v for t, v in self._settled.items() if t >= oldest}
        self._settled.update(out[first_new:max(first_new, len(out) - SETTLE)])
        return out
