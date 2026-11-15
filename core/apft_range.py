"""APFT-GAN heart-rate range: generate, measure the window's beat rate, keep it only inside [lo, hi].

The requested HR is a condition the generator follows only partly (docs/hardware-validation/2026-11-14-ir-overload/
README.md section 19: 16 windows per level, share within +-10 % of the request: 38-56 % at 60-100 bpm, 0-19 % at
50 and 110-150 bpm, where it gives ~80 bpm). So the range is limited to HR_LIMITS and enforced by measurement:
each window's beats are found with core.beat_detector (the pulse-tone detector, on the min-max window scaled to
SCALE_MV) and its rate is 60 x (beats - 1) / (last - first beat time). A window is kept when that rate is inside
[lo, hi] and its beat intervals are regular (at most MAX_ODD of them off the median by more than IRREGULARITY, so
missed beats cannot average a faster window down into the range); of several such windows the one nearest the middle
of the range is kept. The page never plays a window outside the range.

Windows are made BATCH at a time, with requests spread over the range: on the Pi 4 one call for 8 windows takes 57 s
against 44 s for 1 (the single-row matrix products are bound by reading the weights, not by arithmetic). Each new
batch shifts all requests by the median miss of the last one, until a window fits or the time budget runs out.
Measured success with 4 single windows per search was 35-65 % for 5-10 bpm ranges (scripts/apft_range_eval.py).
Pure Python apart from the generator.
"""
from dataclasses import dataclass, field, replace
import time

from core.beat_detector import IRREGULARITY, BeatDetector
from core.rx_filter import noise_sigma

HR_LIMITS = (60.0, 100.0)      # bpm: where the generator follows the request at all (section 19)
MIN_WIDTH = 2.0                # bpm: narrowest range the page offers
DEFAULT_RANGE = (70.0, 80.0)
FS = 40
SCALE_MV = 100.0               # min-max window -> mV for the detector's 5 mV prominence floor
MIN_BEATS = 8
MAX_ODD = 0.05                 # one missed beat in a 30 s window at 60 bpm is 3.4 % of the intervals
BATCH = 8                      # windows per generator call
DEFAULT_BUDGET_S = 240.0       # search time; with loading and a slow last try it stays inside the 300 s worker limit


@dataclass(frozen=True)
class RateCheck:
    bpm: float | None          # mean beat rate of the window, None when too few beats were found
    beats: int
    odd: float                 # share of intervals off the median by more than IRREGULARITY


def window_rate(window, fs=FS):
    """Beat rate of one min-max window (floats in [0, 1])."""
    values = [SCALE_MV * x for x in window]
    detector = BeatDetector(record=True)
    sigma = noise_sigma(values)
    for i, v in enumerate(values):
        detector.feed_clean(i / fs, v, sigma)
    beats = [t for t, _ in detector.accepted]
    if len(beats) < MIN_BEATS:
        return RateCheck(None, len(beats), 1.0)
    # Until it has three rises to compare, the detector can take the first beat's dicrotic bump for a beat (one
    # extra beat: +2 bpm at 60 bpm). A beat closer to the last kept one than (1 - IRREGULARITY) of the median
    # interval is such a stray and is dropped; a missed beat (a long interval) stays and counts as irregular.
    median = sorted(b - a for a, b in zip(beats, beats[1:]))[(len(beats) - 1) // 2]
    kept = [beats[0]]
    for t in beats[1:]:
        if t - kept[-1] >= (1 - IRREGULARITY) * median:
            kept.append(t)
    if len(kept) > 1 and kept[1] - kept[0] < (1 - IRREGULARITY) * median:
        kept.pop(0)
    beats = kept
    if len(beats) < MIN_BEATS:
        return RateCheck(None, len(beats), 1.0)
    gaps = [b - a for a, b in zip(beats, beats[1:])]
    median = sorted(gaps)[len(gaps) // 2]
    odd = sum(abs(g - median) > IRREGULARITY * median for g in gaps) / len(gaps)
    return RateCheck(60.0 * (len(beats) - 1) / (beats[-1] - beats[0]), len(beats), odd)


def validate_range(lo, hi):
    lo, hi = float(lo), float(hi)
    if not (HR_LIMITS[0] <= lo <= hi <= HR_LIMITS[1]) or hi - lo < MIN_WIDTH:
        raise ValueError(f"APFT HR range must lie within {HR_LIMITS[0]:g}-{HR_LIMITS[1]:g} bpm and be at least "
                         f"{MIN_WIDTH:g} bpm wide (got {lo:g}-{hi:g})")
    return lo, hi


def accepts(check, lo, hi):
    return check.bpm is not None and lo <= check.bpm <= hi and check.odd <= MAX_ODD


@dataclass
class RangeResult:
    window: list | None
    request: float | None
    check: RateCheck | None
    seed: int | None            # seed of the generator call that made the window
    index: int | None = None    # the window's place in that call's batch
    tries: list = field(default_factory=list)       # (seed, index, requested bpm, measured bpm or None, odd share)


def spread(lo, hi, n, shift=0.0):
    """n requests spread evenly over [lo, hi], moved by shift and kept inside HR_LIMITS."""
    step = (hi - lo) / n
    return [min(HR_LIMITS[1], max(HR_LIMITS[0], lo + step * (i + .5) + shift)) for i in range(n)]


def search(make_windows, lo, hi, seed, budget_s=DEFAULT_BUDGET_S, batch=BATCH, clock=time.monotonic):
    """make_windows(seed, [bpm, ...]) -> one min-max window per requested bpm. Calls it with seed, seed+1, ... until a
    window's measured rate is in range; stops before a call that would likely overrun budget_s (the slowest call so
    far is the estimate)."""
    lo, hi = validate_range(lo, hi)
    mid, shift = (lo + hi) / 2, 0.0
    start, slowest, result = clock(), 0.0, RangeResult(None, None, None, None)
    k = 0
    while k == 0 or clock() - start + slowest <= budget_s:
        t0 = clock()
        call_seed = (seed + k) % 2**32
        requests = spread(lo, hi, batch, shift)
        windows = make_windows(call_seed, requests)
        checks = [window_rate(w) for w in windows]
        slowest = max(slowest, clock() - t0)
        for i, (request, check) in enumerate(zip(requests, checks)):
            result.tries.append((call_seed, i, round(request, 2), None if check.bpm is None else round(check.bpm, 2),
                                 round(check.odd, 3)))
        hits = [i for i, c in enumerate(checks) if accepts(c, lo, hi)]
        if hits:
            i = min(hits, key=lambda j: abs(checks[j].bpm - mid))
            return replace(result, window=windows[i], request=requests[i], check=checks[i], seed=call_seed, index=i)
        misses = sorted(c.bpm - r for c, r in zip(checks, requests) if c.bpm is not None)
        if misses:      # the generator ran fast or slow on the whole batch: move every request against it
            shift = max(-20.0, min(20.0, shift - misses[len(misses) // 2]))
        k += 1
    return result
