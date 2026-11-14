"""Engineering respiratory-rate estimate from measured IR pulse features.

No TX RR is an input. Baseline, amplitude and pulse-interval modulation are
analysed on 30–60 s of RX; absent/ambiguous modulation produces no number.
"""
from dataclasses import dataclass
import math

from config import ADC_MAX_VALUE, RX_STALE_THRESHOLD_S
from core.rx_heart_rate import (band_pass, estimate_rx_rate, latest_stretch,
                                pulse_peaks, _moving_average, _percentile, _resample)

WINDOW_S = 60.0
MIN_SECONDS = 30.0


@dataclass(frozen=True)
class RxRespRate:
    brpm: float | None = None
    reason: str = "short"


def _feature_rate(times, values, upper):
    """Detrended 4 Hz feature spectrum, 0.25 breath/min grid; ≥3 cycles."""
    values = _resample(times, values, 4.0)
    n = len(values)
    mid = (n - 1) / 2
    mean = sum(values) / n
    slope = sum((i - mid) * (v - mean) for i, v in enumerate(values)) / sum((i - mid)**2 for i in range(n))
    x = [v - mean - slope * (i - mid) for i, v in enumerate(values)]
    energy = sum(v * v for v in x)
    if energy <= 0:
        return None
    scores = []
    for k in range(16, int(upper * 4) + 1):
        rate = k / 4
        if (times[-1] - times[0]) * rate / 60 < 3:
            continue
        omega = 2 * math.pi * rate / 60 / 4
        coefficient = 2 * math.cos(omega)
        previous = older = 0.0
        for v in x:
            current = v + coefficient * previous - older
            older, previous = previous, current
        power = previous**2 + older**2 - coefficient * previous * older
        scores.append((2 * power / (n * energy), rate))
    if not scores:
        return None
    score, rate = max(scores)
    competitor = max((s for s, r in scores if abs(r - rate) >= 3), default=0)
    if score < .65 or competitor > .7 * score:
        return None
    return rate, score


def estimate_rx_rr(samples, *, now, max_gap_s=.05):
    """Latest 30–60 s of real IR ADC data; RR search 4–40 and below half pulse rate."""
    if not samples:
        return RxRespRate()
    if any(not math.isfinite(s.timestamp) or not math.isfinite(s.raw)
           or not 0 <= s.raw <= ADC_MAX_VALUE for s in samples):
        return RxRespRate(reason="invalid")
    if any(y.timestamp <= x.timestamp for x, y in zip(samples, samples[1:])) or samples[-1].timestamp > now:
        return RxRespRate(reason="invalid")
    if now - samples[-1].timestamp > RX_STALE_THRESHOLD_S:
        return RxRespRate(reason="stale")
    stretch = latest_stretch([s for s in samples if s.timestamp >= now - WINDOW_S], max_gap_s)
    if any(s.saturated or s.raw >= ADC_MAX_VALUE for s in stretch):
        return RxRespRate(reason="saturated")
    if any(s.raw == 0 for s in stretch):   # LED off before Start, or a dropout: not ADC clipping
        return RxRespRate(reason="dark")
    if len(stretch) < 2 or stretch[-1].timestamp - stretch[0].timestamp < MIN_SECONDS:
        return RxRespRate()
    pulse = estimate_rx_rate([s for s in stretch if s.timestamp >= now - 8])
    if pulse.bpm is None:
        return RxRespRate(reason=pulse.reason)
    hz = 50.0
    raw = _resample([s.timestamp for s in stretch], [float(s.raw) for s in stretch], hz)
    filtered = band_pass(raw)
    swing = _percentile(sorted(filtered), .95) - _percentile(sorted(filtered), .05)
    peaks = [p for p in pulse_peaks(filtered, hz, swing) if hz <= p < len(raw) - hz]
    if len(peaks) < 12:
        return RxRespRate()
    times, baseline, amplitude, intervals = [], [], [], []
    smooth = _moving_average(raw, 3)
    for previous, peak, following in zip(peaks, peaks[1:], peaks[2:]):
        low = min(smooth[previous:peak])
        high = max(smooth[max(previous, peak - 6):min(following, peak + 7)])
        times.append(stretch[0].timestamp + peak / hz)
        baseline.append((high + low) / 2)
        amplitude.append(high - low)
        intervals.append((following - previous) / (2 * hz))
    if times[-1] - times[0] < MIN_SECONDS:
        return RxRespRate()
    candidates = []
    for values, minimum_swing in ((baseline, 3.0), (amplitude, 3.0), (intervals, 2 / hz)):
        ordered = sorted(values)
        if _percentile(ordered, .95) - _percentile(ordered, .05) < minimum_swing:
            continue
        candidate = _feature_rate(times, values, min(40.0, .45 * pulse.bpm))
        if candidate:
            candidates.append(candidate)
    if not candidates:
        return RxRespRate(reason="unclear")
    best = max(candidates, key=lambda item: sum(abs(item[0] - other[0]) <= 1.5 for other in candidates))
    agreeing = [r for r, score in candidates if abs(r - best[0]) <= 1.5]
    # A single modulation needs a very clear spectrum and four cycles.
    if len(agreeing) == 1 and (best[1] < .85 or (times[-1] - times[0]) * best[0] / 60 < 4):
        return RxRespRate(reason="unclear")
    if len(agreeing) < len(candidates):
        return RxRespRate(reason="mismatch")
    return RxRespRate(sum(agreeing) / len(agreeing), "ok")
