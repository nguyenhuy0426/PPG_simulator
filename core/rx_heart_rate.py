"""Pulse rate of the received OPT101 waveform for display (pure Python; the Pi runtime has no numpy).

Input is the raw RX sample stream (timestamps from time.monotonic(), 12-bit codes). Only the newest
gap-free stretch is used: it is linearly resampled to a uniform grid, band-limited with moving
averages (drift and LED DC out, sample noise down), then the rate comes from an autocorrelation peak that
repeats at twice its lag and agrees with the count of prominent pulses. A strip without both (noise, or a
strongly irregular rhythm) gets no rate rather than a guess. This is a received-signal pulse rate for
checking the optical loop, not a clinical heart rate.
"""
from dataclasses import dataclass
import math

GRID_HZ = 50.0             # resampling rate: ample for 0.5-4 Hz pulses, halves the work of 100 Hz RX
MIN_SECONDS = 5.0          # shortest stretch that holds >= 3 beats at 40 bpm
MAX_GAP_S = 0.1            # a longer hole between RX samples (>= ~9 missed at 100 Hz) splits the stretch
MAX_SATURATED = 0.02       # clipped fraction above which the pulse shape is unreliable
MIN_SWING_CODES = 6        # p95-p5 of the band-passed signal; below this the pulse is not resolved (~5 mV)
DETREND_S, SMOOTH_S = 1.5, 0.2   # high-pass ~0.5 Hz, low-pass first null at 5 Hz
BPM_RANGE = (30.0, 220.0)
# Autocorrelation at the period and again at twice the period, and agreement with the count of prominent
# pulses (a strongly irregular rhythm can give a confident wrong period: 95 bpm read as 56). Measured on
# synthetic RX streams (tests/test_rx_heart_rate.py generator): 2 of 200 band-passed white/random-walk noise
# strips get a rate; regular 40-180 bpm pulses all read within 1 bpm; log-normal IBI sigma 0.1 / 0.2 / 0.3
# get a rate 97% / 53% / 7% of the time, within 15% of the mean rate.
MIN_PERIODICITY, MIN_REPEAT, MAX_DISAGREEMENT = 0.5, 0.3, 0.15


@dataclass(frozen=True)
class RxRate:
    bpm: float | None
    reason: str             # "ok", "short", "saturated", "weak", "unclear"
    seconds: float          # length of the stretch that was analysed
    periodicity: float      # autocorrelation at the chosen lag (0 when not periodic)


def latest_stretch(samples, max_gap_s=MAX_GAP_S):
    """The newest run of samples with no gap longer than max_gap_s, oldest first."""
    if not samples:
        return []
    start = len(samples)-1
    while start > 0 and samples[start].timestamp-samples[start-1].timestamp <= max_gap_s:
        start -= 1
    return list(samples[start:])


def _resample(times, values, hz):
    out, j, t = [], 0, times[0]
    step = 1/hz
    while t <= times[-1]:
        while times[j+1] < t:
            j += 1
        t0, t1 = times[j], times[j+1]
        w = 0. if t1 == t0 else (t-t0)/(t1-t0)
        out.append(values[j]+w*(values[j+1]-values[j]))
        t += step
    return out


def _moving_average(x, width):
    """Centred moving average with a shrinking window at the edges (O(n) by cumulative sums)."""
    half, n = max(1, width//2), len(x)
    cumulative = [0.]
    for v in x:
        cumulative.append(cumulative[-1]+v)
    return [(cumulative[min(n, i+half+1)]-cumulative[max(0, i-half)])/(min(n, i+half+1)-max(0, i-half))
            for i in range(n)]


def band_pass(x, hz=GRID_HZ):
    trend = _moving_average(x, round(DETREND_S*hz))
    return _moving_average([a-b for a, b in zip(x, trend)], round(SMOOTH_S*hz))


def _percentile(sorted_values, q):
    return sorted_values[min(len(sorted_values)-1, max(0, round(q*(len(sorted_values)-1))))]


def _acf_rate(x, hz):
    """(bpm, periodicity) from the earliest strong autocorrelation peak that repeats at twice its lag."""
    n = len(x)
    mean = sum(x)/n
    y = [v-mean for v in x]
    energy = sum(v*v for v in y)
    lo, hi = max(1, int(hz*60/BPM_RANGE[1])), min(int(hz*60/BPM_RANGE[0]), n-2)
    if energy <= 0 or hi <= lo:
        return None, 0.
    longest = min(2*hi+2, n-1)
    # Overlap-corrected so a lag is not penalised for its shorter overlap.
    acf = [sum(y[i]*y[i+lag] for i in range(n-lag))/energy*n/(n-lag) if lag else 1. for lag in range(longest+1)]
    peaks = [k for k in range(lo, hi+1) if acf[k-1] <= acf[k] > acf[k+1]]
    top = max((acf[k] for k in peaks), default=0.)
    if top < MIN_PERIODICITY:
        return None, max(0., top)
    # Every period multiple of a regular pulse is also a peak; the shortest comparable one is the period.
    lag = min(k for k in peaks if acf[k] >= .8*top)
    again = range(max(lo, 2*lag-2), min(longest, 2*lag+2)+1)
    if 2*lag+2 <= longest and max(acf[k] for k in again) < MIN_REPEAT:
        return None, acf[lag]
    a, b, c = acf[lag-1], acf[lag], acf[lag+1]
    shift = .5*(a-c)/(a-2*b+c) if a-2*b+c else 0.
    return 60*hz/(lag+shift), b


def _pulse_count_rate(x, hz, swing):
    """Mean rate over prominent maxima at least one 220-bpm period apart; None below 3 pulses."""
    gap, base = max(1, round(hz*60/BPM_RANGE[1])), max(1, round(.6*hz))
    peaks = []
    for i in range(1, len(x)-1):
        if x[i] == max(x[max(0, i-gap):i+gap+1]) and x[i] > x[i-1]:
            floor = max(min(x[max(0, i-base):i]), min(x[i+1:i+base+1]))
            if x[i]-floor >= .3*swing:
                peaks.append(i)
    if len(peaks) < 3:
        return None
    return 60*(len(peaks)-1)/((peaks[-1]-peaks[0])/hz)


def estimate_rx_rate(samples, hz=GRID_HZ):
    """RxRate for RX samples (objects with .timestamp, .raw, .saturated), oldest first."""
    stretch = latest_stretch(samples)
    seconds = stretch[-1].timestamp-stretch[0].timestamp if len(stretch) > 1 else 0.
    if seconds < MIN_SECONDS:
        return RxRate(None, "short", seconds, 0.)
    if sum(s.saturated for s in stretch) > MAX_SATURATED*len(stretch):
        return RxRate(None, "saturated", seconds, 0.)
    x = band_pass(_resample([s.timestamp for s in stretch], [float(s.raw) for s in stretch], hz), hz)
    # Edges of a moving-average filter are biased; drop one detrend half-window at each end.
    edge = round(DETREND_S*hz/2)
    x = x[edge:len(x)-edge]
    ordered = sorted(x)
    swing = _percentile(ordered, .95)-_percentile(ordered, .05)
    if swing < MIN_SWING_CODES:
        return RxRate(None, "weak", seconds, 0.)
    bpm, periodicity = _acf_rate(x, hz)
    if bpm is None or not math.isfinite(bpm):
        return RxRate(None, "unclear", seconds, periodicity)
    counted = _pulse_count_rate(x, hz, swing)
    if counted is None or abs(counted-bpm) > MAX_DISAGREEMENT*bpm:
        return RxRate(None, "unclear", seconds, periodicity)
    return RxRate(bpm, "ok", seconds, periodicity)
