"""Heuristic artifact mask (signal-quality index) for 30 s, 40 Hz PPG windows without artifact annotations.

draft
"""
import numpy as np
from scipy.ndimage import maximum_filter1d, minimum_filter1d, percentile_filter
from scipy.signal import find_peaks

from ml.kaggle_lsm.train_lsm import FS, LENGTH

MIN_BPM, MAX_BPM = 40., 200.
PEAK_DISTANCE = int(np.floor(FS*60/MAX_BPM))
PEAK_WLEN = int(np.ceil(2*FS*60/MIN_BPM))
LOCAL_S, LOCAL_PERCENTILES = 3., (10, 90)
PEAK_PROMINENCE = .3
NO_BEAT_S, NO_BEAT_PROMINENCE = 2., .1
TEMPLATE_MIN_BEATS = 5
TEMPLATE_SUPPORT = .5
ANCHOR = "half"
CORR_MIN, CORR_LAG, MIN_OVERLAP = .8, 1, 8
TIME_SCALES = (.8, .9, 1., 1.12, 1.25)
AMP_LOW, AMP_HIGH = .2, 4.
FLAT_S, FLAT_REL = 1., .05
CLIP_RUN, CLIP_EPS = 3, 1e-3
GROUPS = ("0%", "0-20%", "20-60%", "60-100%")


def normalise(x):
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 2:
        raise ValueError("windows must be a 2-D array (n, samples)")
    if not np.isfinite(x).all():
        raise ValueError("windows must be finite")
    lo, hi = x.min(1, keepdims=True), x.max(1, keepdims=True)
    return (x-lo)/np.where(hi > lo, hi-lo, 1.)


def local_span(x):
    size = int(round(LOCAL_S*FS)) | 1
    lo, hi = (percentile_filter(x, q, size=(1, size), mode="nearest") for q in LOCAL_PERCENTILES)
    return hi-lo


def detect_peaks(row, span, relative=None):
    relative = PEAK_PROMINENCE if relative is None else relative
    peaks, props = find_peaks(row, distance=PEAK_DISTANCE, prominence=1e-6, wlen=PEAK_WLEN)
    return peaks[props["prominences"] >= relative*span[peaks]]


def beat_table(row, peaks):
    """(k, 3) int [start, peak, end]: troughs between peaks; outer troughs searched one median interval out."""
    if len(peaks) == 0:
        return np.zeros((0, 3), int)
    reach = int(np.median(np.diff(peaks))) if len(peaks) > 1 else int(FS*60/MIN_BPM)
    inner = [p+int(np.argmin(row[p:q+1])) for p, q in zip(peaks[:-1], peaks[1:])]
    lo = max(0, peaks[0]-reach)
    first = lo+int(np.argmin(row[lo:peaks[0]+1]))
    last = peaks[-1]+int(np.argmin(row[peaks[-1]:min(len(row), peaks[-1]+reach+1)]))
    return np.c_[np.r_[first, inner], peaks, np.r_[inner, last]].astype(int)


def anchors(row, beats):
    if ANCHOR == "peak":
        return beats[:, 1].copy()
    if ANCHOR == "foot":
        return beats[:, 0].copy()
    if ANCHOR == "half":
        out = []
        for s, p, _ in beats:
            half = .5*(row[s]+row[p])
            out.append(s+int(np.argmax(row[s:p+1] >= half)))
        return np.array(out)
    d = np.diff(row)
    return np.array([s+int(np.argmax(d[s:p])) if p > s else p for s, p, _ in beats])


def beat_matrix(row, beats, anc, pre, width):
    """(k, width): row[anc-pre+j] inside each beat's own [start, end], NaN elsewhere."""
    idx = anc[:, None]-pre+np.arange(width)[None]
    inside = (idx >= beats[:, :1]) & (idx <= beats[:, 2:])
    return np.where(inside, row[np.clip(idx, 0, len(row)-1)], np.nan)


def masked_corr(a, b):
    """Row-wise Pearson correlation over pairs where both are finite; NaN below MIN_OVERLAP pairs."""
    ok = np.isfinite(a) & np.isfinite(b)
    n = ok.sum(1)
    a0, b0 = np.where(ok, a, 0.), np.where(ok, b, 0.)
    with np.errstate(invalid="ignore", divide="ignore"):
        ma, mb = a0.sum(1)/n, b0.sum(1)/n
        da, db = np.where(ok, a0-ma[:, None], 0.), np.where(ok, b0-mb[:, None], 0.)
        r = (da*db).sum(1)/np.sqrt((da**2).sum(1)*(db**2).sum(1))
    return np.where((n >= MIN_OVERLAP) & np.isfinite(r), r, np.nan)


def beat_scores(row, beats):
    """Per beat: best template correlation over time scales and +-CORR_LAG lags; foot-to-peak amplitude / median."""
    anc = anchors(row, beats)
    pre, post = int(np.median(anc-beats[:, 0])), int(np.median(beats[:, 2]-anc))
    width = pre+post+1
    amp = row[beats[:, 1]]-row[beats[:, 0]]
    own = beat_matrix(row, beats, anc, pre, width)
    stack = (own-row[beats[:, :1]])/np.maximum(amp, 1e-9)[:, None]
    support = np.isfinite(stack).mean(0) >= TEMPLATE_SUPPORT
    with np.errstate(all="ignore"):
        tmpl = np.where(support, np.nanmedian(np.where(support, stack, 0.), 0), np.nan)
    offsets = np.arange(width)-pre
    reach = int(np.ceil(max(TIME_SCALES)*max(pre, post)))+CORR_LAG
    grid = np.arange(-reach, reach+1)
    seen = beat_matrix(row, beats, anc, reach, len(grid))
    best = np.full(len(beats), -np.inf)
    for scale in TIME_SCALES:
        scaled = np.interp(grid/scale, offsets, np.where(support, tmpl, 0.), left=np.nan, right=np.nan)
        scaled[np.interp(grid/scale, offsets, support.astype(float), left=0., right=0.) < 1] = np.nan
        for lag in range(-CORR_LAG, CORR_LAG+1):
            shifted = np.roll(scaled, lag)
            if lag > 0:
                shifted[:lag] = np.nan
            elif lag < 0:
                shifted[lag:] = np.nan
            r = masked_corr(seen, np.broadcast_to(shifted, seen.shape))
            best = np.fmax(best, np.where(np.isfinite(r), r, -np.inf))
    return np.where(np.isfinite(best), best, np.nan), amp/max(np.median(amp), 1e-9)


def runs_mask(flags, min_len):
    """True on every run of at least min_len consecutive True flags."""
    out = np.zeros(len(flags), bool)
    edges = np.flatnonzero(np.diff(np.r_[0, flags.astype(np.int8), 0]))
    for start, stop in zip(edges[::2], edges[1::2]):
        if stop-start >= min_len:
            out[start:stop] = True
    return out


def flat_mask(row, reference):
    n = int(round(FLAT_S*FS))
    view = np.lib.stride_tricks.sliding_window_view(row, n)
    starts = np.ptp(view, 1) < FLAT_REL*reference
    return np.convolve(starts.astype(float), np.ones(n))[:len(row)] > 0


RULES = ("clipped", "no_beat", "morphology", "amplitude_low", "amplitude_high", "flat")


def rule_masks(row, span):
    n = len(row)
    out = {r: np.zeros(n, bool) for r in RULES}
    out["clipped"] = runs_mask((row <= CLIP_EPS) | (row >= 1-CLIP_EPS), CLIP_RUN)
    peaks = detect_peaks(row, span)
    stops = np.r_[0, detect_peaks(row, span, NO_BEAT_PROMINENCE), n-1]
    for a, b in zip(stops[:-1], stops[1:]):
        if b-a > NO_BEAT_S*FS:
            out["no_beat"][a:b+1] = True
    reference = 1.
    if len(peaks) >= TEMPLATE_MIN_BEATS:
        beats = beat_table(row, peaks)
        corr, amp = beat_scores(row, beats)
        reference = float(np.median(row[beats[:, 1]]-row[beats[:, 0]]))
        judged = beats[:, 0] > 0
        for rule, bad in (("morphology", (corr < CORR_MIN) & judged), ("amplitude_low", (amp < AMP_LOW) & judged),
                          ("amplitude_high", (amp > AMP_HIGH) & judged)):
            for s, _, e in beats[bad]:
                out[rule][s:e+1] = True
    out["flat"] = flat_mask(row, reference)
    return out


def window_mask(row, span):
    return np.logical_or.reduce(list(rule_masks(row, span).values()))


def artifact_mask(x):
    x = normalise(x)
    span = local_span(x)
    return np.stack([window_mask(row, s) for row, s in zip(x, span)]) if len(x) else np.zeros(x.shape, bool)


def artifact_fraction(x):
    return artifact_mask(x).mean(1)


def quality_group(fraction):
    f = np.asarray(fraction, dtype=np.float64)
    if np.any((f < 0) | (f > 1)) or not np.isfinite(f).all():
        raise ValueError("fractions must lie in [0, 1]")
    idx = np.where(f <= 0, 0, np.where(f <= .2, 1, np.where(f <= .6, 2, 3)))
    return np.asarray(GROUPS)[idx]
