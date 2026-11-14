"""Causal pulse-peak detector for the received OPT101 stream, for a beat tone like a bedside monitor.

The rate/SpO2 estimators use centred filters and see a beat ~0.8 s late; a tone must follow the peak within
~0.2 s, so this runs sample by sample:

  1. despike (core.rx_filter.despike) on a short rolling buffer and a 5-sample mean, read DELAY samples behind
     the newest so the 1-3 sample ADC spikes measured on the Pi (§10) have their right-hand neighbours: +60 ms;
  2. a peak is the maximum after the lowest point since the last beat; it is confirmed once the signal has
     fallen CONFIRM_DROP of the way back (about 0.1 s after a systolic peak at 60-120 bpm);
  3. its rise must reach MIN_PROMINENCE_MV, NOISE_PROMINENCE local noise sigmas and half of the recent
     beats' rise, which leaves out the dicrotic bump and bursts of artefact; peaks closer than one 360-bpm
     period to the last beat are dropped.

The detector is "locked" after LOCK_BEATS beats whose intervals agree within IRREGULARITY of their median,
and only then reports beats: noise and a dark lane stay silent. While locked, a peak that comes earlier than
(1 - IRREGULARITY) of the median interval is taken as a stray (spike, bump) and skipped, and a missed beat does
not unlock; it unlocks after UNLOCK_PERIODS median intervals without a beat (e.g. a large rate step).
This is a received-pulse tone for the optical loop, not an ECG/QRS or clinical alarm.
"""
from collections import deque

from core.rx_filter import MAX_SPIKE_LEN, SMOOTH_HALF, despike, noise_sigma

DELAY = MAX_SPIKE_LEN + 1 + SMOOTH_HALF   # samples read behind the newest: right-hand context for despike + mean
BUFFER = 32                        # despike window: noise sigma from ~0.3 s
CONFIRM_DROP = 0.25                # fraction of the rise the signal must fall back to confirm a peak
MIN_PROMINENCE_MV = 5.0            # ~6 ADC codes, the rate estimator's MIN_SWING_CODES
RELATIVE_PROMINENCE = 0.5          # of the median rise of the recent beats (dicrotic bump < this)
NOISE_PROMINENCE = 5.0             # x the local white-noise sigma: an artefact burst of noise stays silent
MIN_INTERVAL_S = 60.0 / 360.0      # the HR setpoint goes to 300 bpm, with beat-to-beat variation
MAX_INTERVAL_S = 60.0 / 15.0
LOCK_BEATS = 4                     # beats (3 intervals) before the first tone
IRREGULARITY = 0.35                # each interval within ±35 % of the median of the recent ones
UNLOCK_PERIODS = 2.5               # no beat for this many median intervals -> unlocked
MAX_GAP_S = 0.25                   # a longer hole in the samples restarts the peak search


class BeatDetector:
    def __init__(self):
        self.reset()

    def reset(self):
        self._raw = deque(maxlen=BUFFER)          # (t, mV)
        self._last_t = None
        self._lo = self._hi = None
        self._lo_t = self._hi_t = None
        self._beats = deque(maxlen=LOCK_BEATS + 2)
        self._rises = deque(maxlen=5)
        self._noise = 0.0
        self.locked = False

    @property
    def interval_s(self):
        """Median beat interval of the recent beats, or None."""
        gaps = sorted(b - a for a, b in zip(self._beats, list(self._beats)[1:]))
        return gaps[len(gaps) // 2] if gaps else None

    def feed(self, t, mv):
        """Add one sample; returns the time of a newly confirmed beat while locked, else None."""
        if self._last_t is not None and t - self._last_t > MAX_GAP_S:
            self._raw.clear()
            self._lo = self._hi = None
        self._last_t = t
        self._raw.append((t, mv))
        self._check_unlock(t)
        if len(self._raw) <= DELAY + SMOOTH_HALF:
            return None
        raw = [v for _, v in self._raw]
        self._noise = noise_sigma(raw)
        values = despike(raw)
        index = len(values) - 1 - DELAY
        window = values[index - SMOOTH_HALF:index + SMOOTH_HALF + 1]
        return self._step(self._raw[index][0], sum(window) / len(window))

    def _check_unlock(self, now):
        interval = self.interval_s
        limit = min(UNLOCK_PERIODS * interval, UNLOCK_PERIODS * MAX_INTERVAL_S) if interval else MAX_INTERVAL_S * 1.5
        if self._beats and now - self._beats[-1] > limit:
            self._beats.clear()
            self.locked = False

    def _step(self, t, x):
        # A trough older than the longest beat interval belongs to another level (the lane was dark, the DC
        # stepped): restart from here, or a 1 V step would need a 250 mV fall to confirm the next 50 mV pulse.
        if self._lo is None or x < self._lo or t - self._lo_t > MAX_INTERVAL_S:
            self._lo, self._lo_t, self._hi, self._hi_t = x, t, x, t
            return None
        if x > self._hi:
            self._hi, self._hi_t = x, t
            return None
        rise = self._hi - self._lo
        if rise <= 0 or self._hi - x < CONFIRM_DROP * rise:
            return None
        peak_t = self._hi_t
        self._lo, self._lo_t, self._hi, self._hi_t = x, t, x, t     # look for the next trough/peak from here
        return self._accept(peak_t, rise)

    def _accept(self, peak_t, rise):
        floor = max(MIN_PROMINENCE_MV, NOISE_PROMINENCE * self._noise)
        if len(self._rises) >= 3:
            floor = max(floor, RELATIVE_PROMINENCE * sorted(self._rises)[len(self._rises) // 2])
        if rise < floor:
            return None
        if self._beats:
            gap = peak_t - self._beats[-1]
            if gap < MIN_INTERVAL_S or (self.locked and gap < (1 - IRREGULARITY) * self.interval_s):
                return None
        self._rises.append(rise)
        self._beats.append(peak_t)
        if not self.locked:
            self.locked = self._regular()
        return peak_t if self.locked else None

    def _regular(self):
        beats = list(self._beats)[-LOCK_BEATS:]
        if len(beats) < LOCK_BEATS:
            return False
        gaps = [b - a for a, b in zip(beats, beats[1:])]
        median = sorted(gaps)[len(gaps) // 2]
        return (MIN_INTERVAL_S <= median <= MAX_INTERVAL_S
                and all(abs(g - median) <= IRREGULARITY * median for g in gaps))
