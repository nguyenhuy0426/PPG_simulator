"""Engineering respiratory-rate estimate from the received IR PPG waveform.

No TX RR is an input. Breathing modulates the PPG three ways (Charlton et al. 2018): the pulse baseline (RIIV),
the pulse amplitude (RIAV) and the beat interval (RIFV, sinus arrhythmia). Each is taken per beat over the latest
30-60 s of real IR samples, resampled at 4 Hz, linearly detrended, Hann-windowed and turned into a power spectrum
on a 0.25 breath/min grid from 4 /min to min(40, 0.45 x pulse rate). The three spectra are normalised to unit power
and averaged (spectral fusion), so a modulation too weak to stand alone still adds to the common peak, and a peak
seen in one feature only (the generator's non-respiratory 0.3 Hz baseline drift is in RIIV only) is diluted.

A value is given only when the fused peak holds CONCENTRATION of the in-band power within +-1 /min and stands
PEAK_RATIO above the strongest point 2 /min or more away. Thresholds from model PPG with 1 mV RX noise
(tests/test_rx_resp_rate.py): with every modulation off the scores reach 0.40 / 2.4, never both; the generator's
default 4 % modulation at 6-27 /min scores 0.39-0.69 / 3.7-13. This checks the optical loop; it is not a clinical
respiratory rate.
"""
from dataclasses import dataclass
import math

from config import ADC_MAX_VALUE, RX_STALE_THRESHOLD_S
from core.beat_detector import BeatDetector
from core.rx_filter import despike, noise_sigma
from core.rx_heart_rate import latest_stretch, _moving_average, _percentile, _resample

WINDOW_S = 60.0
MIN_SECONDS = 30.0
MIN_BRPM = 4.0
MAX_BRPM = 40.0
GRID_BRPM = 0.25
FEATURE_HZ = 4.0
PEAK_HALF_WIDTH = 1.0      # /min summed into the peak (Hann main lobe at 30-60 s)
FAR_BRPM = 2.0             # competitors are at least this far from the peak
CONCENTRATION = 0.30
PEAK_RATIO = 3.0
MIN_CYCLES = 3.0           # breaths inside the analysed stretch
# A feature joins the fusion only when its p95-p5 spread is above what quantisation alone gives: an exactly
# regular synthetic pulse has a constant interval whose 20 ms grid rounding makes a strong false peak.
MIN_SPREAD = (3.0, 3.0, 0.02)    # baseline codes, amplitude codes, interval s
BEAT_HZ = 100.0            # grid for the beat search: at 50 Hz the trough/peak tracking missed 1 beat in 7-3 on
                           # the Pi captures; 100 Hz (the RX rate is ~91 Hz) finds the same beats as sample-by-sample
HAMPEL_HALF = 4            # beats each side for the running median of a feature series
HAMPEL_SIGMAS = 3.0        # a beat value farther than this many robust sigmas is replaced by the median


@dataclass(frozen=True)
class RxRespRate:
    brpm: float | None = None
    reason: str = "short"
    quality: float = 0.0     # fused peak / strongest competitor (0 when no spectrum was made)


def _spectrum(times, values, rates):
    """Normalised power of the detrended, Hann-windowed 4 Hz feature series at each rate (Goertzel)."""
    x = _resample(times, values, FEATURE_HZ)
    n = len(x)
    if n < 8:
        return None
    mid = (n - 1) / 2
    mean = sum(x) / n
    slope = sum((i - mid) * (v - mean) for i, v in enumerate(x)) / sum((i - mid) ** 2 for i in range(n))
    x = [(v - mean - slope * (i - mid)) * (.5 - .5 * math.cos(2 * math.pi * i / (n - 1))) for i, v in enumerate(x)]
    power = []
    for rate in rates:
        coefficient = 2 * math.cos(2 * math.pi * rate / 60 / FEATURE_HZ)
        previous = older = 0.0
        for v in x:
            previous, older = v + coefficient * previous - older, previous
        power.append(max(0.0, previous ** 2 + older ** 2 - coefficient * previous * older))
    total = sum(power)
    return [p / total for p in power] if total > 0 else None


def _hampel(values):
    """Running-median outlier replacement: a beat hit by an RX spike, a missed or an extra pulse would otherwise
    put a broadband step into the feature spectrum (measured on the Pi IR lane: spikes to +300 mV, ±300 ms
    interval outliers)."""
    out = list(values)
    for i in range(len(values)):
        window = sorted(values[max(0, i - HAMPEL_HALF):i + HAMPEL_HALF + 1])
        median = window[len(window) // 2]
        mad = sorted(abs(v - median) for v in window)[len(window) // 2]
        if abs(values[i] - median) > HAMPEL_SIGMAS * 1.4826 * mad:
            out[i] = median
    return out


def _beat_features(stretch, hz=BEAT_HZ):
    """Per-beat times and baseline / amplitude / interval series from the IR stretch.

    Beats come from core.beat_detector (trough-to-peak with relative prominence, spikes removed): the rate
    estimator's band-pass + 30 % prominence peak finder dropped 1 in 7 beats at 27 /min and 1 in 2 at 36 /min
    under the generator's 16 % breathing modulation (Pi capture), which turned the interval series into noise."""
    t0 = stretch[0].timestamp
    raw = despike(_resample([s.timestamp for s in stretch], [float(s.raw) for s in stretch], hz))
    smooth = _moving_average(raw, 5)
    sigma = noise_sigma(raw)
    detector = BeatDetector(record=True)
    for i, v in enumerate(smooth):
        detector.feed_clean(t0 + i / hz, v, sigma)
    beats = [t for t, _ in detector.accepted]
    if len(beats) < 3:
        return [], ((), (), ())
    index = lambda t: min(len(smooth) - 1, max(0, round((t - t0) * hz)))

    def refined(t):        # parabolic sub-sample peak position: intervals free of the 1/hz grid rounding
        i = index(t)
        if 0 < i < len(smooth) - 1:
            a, b, c = smooth[i - 1], smooth[i], smooth[i + 1]
            if a - 2 * b + c < 0:
                return t + .5 * (a - c) / (a - 2 * b + c) / hz
        return t
    beats = [refined(t) for t in beats]
    times, baseline, amplitude, interval = [], [], [], []
    for previous, peak, following in zip(beats, beats[1:], beats[2:]):
        a, b, c = index(previous), index(peak), index(following)
        low = min(smooth[a:b + 1])
        high = max(smooth[max(a, b - 2):min(c, b + 3)])
        times.append(peak)
        baseline.append((high + low) / 2)
        amplitude.append(high - low)
        interval.append((following - previous) / 2)
    return times, tuple(_hampel(series) for series in (baseline, amplitude, interval))


def _lit_stretch(samples, now, max_gap_s):
    """Newest gap-free stretch of the window after the last 0 mV sample (LED off before Start, or a dropout)."""
    window = [s for s in samples if s.timestamp >= now - WINDOW_S]
    last_dark = max((i for i, s in enumerate(window) if s.raw == 0), default=None)
    if last_dark is not None:
        window = window[last_dark + 1:]
    return latest_stretch(window, max_gap_s), last_dark is not None


def _red_features(red_samples, now, max_gap_s):
    """Beat features of the RED lane when it is lit, unclipped and >= MIN_SECONDS gap-free; else None."""
    red = [s for s in red_samples if s.timestamp <= now and math.isfinite(s.raw) and 0 <= s.raw <= ADC_MAX_VALUE]
    if any(y.timestamp <= x.timestamp for x, y in zip(red, red[1:])):
        return None
    stretch, _ = _lit_stretch(red, now, max_gap_s)
    if (len(stretch) < 2 or stretch[-1].timestamp - stretch[0].timestamp < MIN_SECONDS
            or any(s.saturated or s.raw >= ADC_MAX_VALUE for s in stretch)):
        return None
    times, features = _beat_features(stretch)
    return (times, features) if len(times) >= 12 else None


def estimate_rx_rr(samples, *, now, max_gap_s=.05, red_samples=None):
    """RR from the latest 30-60 s of IR RX samples (objects with .timestamp, .raw, .saturated), oldest first.

    With red_samples the RED lane's three features join the fusion while that lane is usable: on the Pi rig the
    IR baseline wanders 45-55 mV against a ~4 mV breathing component, so more features help. Samples newer than
    `now` are ignored (the receiver keeps appending while the caller works)."""
    samples = [s for s in samples if s.timestamp <= now] if samples else []
    if not samples:
        return RxRespRate()
    if any(not math.isfinite(s.timestamp) or not math.isfinite(s.raw)
           or not 0 <= s.raw <= ADC_MAX_VALUE for s in samples):
        return RxRespRate(reason="invalid")
    if any(y.timestamp <= x.timestamp for x, y in zip(samples, samples[1:])):
        return RxRespRate(reason="invalid")
    if now - samples[-1].timestamp > RX_STALE_THRESHOLD_S:
        return RxRespRate(reason="stale")
    stretch, had_dark = _lit_stretch(samples, now, max_gap_s)
    if any(s.saturated or s.raw >= ADC_MAX_VALUE for s in stretch):
        return RxRespRate(reason="saturated")
    if len(stretch) < 2 or stretch[-1].timestamp - stretch[0].timestamp < MIN_SECONDS:
        return RxRespRate(reason="dark" if had_dark else "short")
    times, features = _beat_features(stretch)
    if not times:
        return RxRespRate(reason="weak")       # no pulses resolved (dark-ish lane, or only noise)
    seconds = times[-1] - times[0] if len(times) > 1 else 0.0
    if len(times) < 12 or seconds < MIN_SECONDS:
        return RxRespRate()
    # Pulse rate from the beats themselves: the autocorrelation rate estimator reads "unclear" under the
    # generator's 16 % amplitude/interval modulation at 27-36 breaths/min (Pi capture), which is exactly when
    # the breathing is clearest. Breathing must stay below 0.45 x the pulse rate to be sampled by the beats.
    upper = min(MAX_BRPM, .45 * 60 * (len(times) - 1) / seconds)
    rates = [k * GRID_BRPM for k in range(int(MIN_BRPM / GRID_BRPM), int(upper / GRID_BRPM) + 1)]
    spread = lambda v: _percentile(sorted(v), .95) - _percentile(sorted(v), .05)
    lanes = [(times, features)]
    red = _red_features(red_samples, now, max_gap_s) if red_samples else None
    if red is not None:
        lanes.append(red)
    spectra = [s for lane_times, lane_features in lanes
               for s in (_spectrum(lane_times, values, rates) for values, floor in zip(lane_features, MIN_SPREAD)
                         if spread(values) >= floor) if s is not None]
    if not spectra or not rates:
        return RxRespRate(reason="unclear")
    fused = [sum(column) / len(spectra) for column in zip(*spectra)]
    best = max(range(len(rates)), key=fused.__getitem__)
    rate = rates[best]
    near = sum(p for r, p in zip(rates, fused) if abs(r - rate) <= PEAK_HALF_WIDTH)
    far = max((p for r, p in zip(rates, fused) if abs(r - rate) >= FAR_BRPM), default=0.0)
    quality = fused[best] / far if far > 0 else float("inf")
    if near < CONCENTRATION or quality < PEAK_RATIO or seconds * rate / 60 < MIN_CYCLES:
        return RxRespRate(reason="unclear", quality=quality)
    # Parabolic interpolation between grid points.
    if 0 < best < len(rates) - 1:
        a, b, c = fused[best - 1], fused[best], fused[best + 1]
        if a - 2 * b + c < 0:
            rate += GRID_BRPM * .5 * (a - c) / (a - 2 * b + c)
    return RxRespRate(rate, "ok", quality)
