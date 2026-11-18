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
BUFFER = 32                        # noise sigma from ~0.3 s
TAIL = DELAY + SMOOTH_HALF + MAX_SPIKE_LEN + 4   # samples despiked per call: the read point +- the mean and a spike
NOISE_EVERY = 16                   # samples between noise sigma updates (a sort of BUFFER values)
CONFIRM_DROP = 0.25                # fraction of the rise the signal must fall back to confirm a peak
MIN_PROMINENCE_MV = 5.0            # ~6 ADC codes, the rate estimator's MIN_SWING_CODES
RELATIVE_PROMINENCE = 0.5          # of the median rise of the recent beats (dicrotic bump < this)
NOISE_PROMINENCE = 5.0             # x the local white-noise sigma: an artefact burst of noise stays silent
MIN_INTERVAL_S = 60.0 / 360.0      # the HR setpoint goes to 300 bpm, with beat-to-beat variation
MAX_INTERVAL_S = 60.0 / 15.0
LOCK_BEATS = 3                     # beats (2 intervals) before the first tone
IRREGULARITY = 0.35                # each interval within ±35 % of the median of the recent ones
UNLOCK_PERIODS = 2.5               # no beat for this many median intervals -> unlocked
MAX_GAP_S = 0.25                   # a longer hole in the samples restarts the peak search
MAX_PEAK_WAIT_S = 1.2              # a candidate peak not confirmed by then is a level step, not a pulse
MAX_RISE_S = 1.2                   # longest trough-to-peak upstroke (the model's is 0.8 s at 15 bpm)
STEP_MV_PER_S = 10000.0            # 10 V/s on the smoothed signal: a level step; a 500 mV pulse rises at ~5 V/s


class BeatDetector:
    def __init__(self, record=False):
        self.record = record                      # keep every accepted peak in .accepted (offline use)
        self.reset()

    def reset(self):
        self.accepted = []                        # (peak time, rise) of every accepted peak, locked or not
        self._raw = deque(maxlen=BUFFER)          # (t, mV)
        self._last_t = None
        self._lo = self._hi = None
        self._lo_t = self._hi_t = None
        self._recent = deque()                    # (t, smoothed mV) of the last MAX_RISE_S
        self._beats = deque(maxlen=LOCK_BEATS + 2)
        self._rises = deque(maxlen=5)
        self._noise = 0.0
        self._count = 0
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
        # Per-sample cost on the Pi 4 was 0.55 ms (whole-buffer despike + sort every sample) x 2 lanes x 91 Hz:
        # 17 % of the GIL-bound core. Only the tail around the read point is despiked, sigma refreshed every
        # NOISE_EVERY samples.
        self._count += 1
        if self._count % NOISE_EVERY == 1 or not self._noise:
            self._noise = noise_sigma([v for _, v in self._raw])
        tail = [v for _, v in list(self._raw)[-TAIL:]]
        values = despike(tail, sigma=self._noise)
        offset = len(self._raw) - len(tail)
        index = len(values) - 1 - DELAY
        window = values[index - SMOOTH_HALF:index + SMOOTH_HALF + 1]
        return self._step(self._raw[offset + index][0], sum(window) / len(window))

    def feed_clean(self, t, x, noise_sigma_mv):
        """Offline path: one sample already despiked and smoothed by the caller (whole series at once), with
        its noise sigma. Skips the per-sample despike of feed(), ~0.5 ms a sample on the Pi 4."""
        self._noise = noise_sigma_mv
        self._check_unlock(t)
        return self._step(t, x)

    def _check_unlock(self, now):
        interval = self.interval_s
        limit = min(UNLOCK_PERIODS * interval, UNLOCK_PERIODS * MAX_INTERVAL_S) if interval else MAX_INTERVAL_S * 1.5
        if self._beats and now - self._beats[-1] > limit:
            self._beats.clear()
            self.locked = False

    def _step(self, t, x):
        # A trough older than the longest beat interval belongs to another level (the lane was dark, the DC
        # stepped): restart from here, or a 1 V step would need a 250 mV fall to confirm the next 50 mV pulse.
        # A peak still unconfirmed after MAX_PEAK_WAIT_S is the top of such a step (a real one is confirmed
        # within ~0.6 s even at 15 bpm): restart then too, so the tone starts ~1 s after the light comes on.
        recent = self._recent
        prev = recent[-1] if recent else None
        recent.append((t, x))
        while t - recent[0][0] > MAX_RISE_S:
            recent.popleft()
        # The output switching on (dark -> DC) is a step far steeper than any pulse upstroke: start the search on
        # top of it, so the first full pulse after it is already a beat.
        step = prev is not None and t > prev[0] and abs(x - prev[1]) / (t - prev[0]) > STEP_MV_PER_S
        if (step or self._lo is None or x < self._lo or t - self._lo_t > MAX_INTERVAL_S
                or t - self._hi_t > MAX_PEAK_WAIT_S):
            self._lo, self._lo_t, self._hi, self._hi_t = x, t, x, t
            return None
        if x > self._hi:
            # No upstroke lasts longer than MAX_RISE_S (0.8 s at 15 bpm): an older trough is the dark level before
            # the light came on (or a DC step), and each new pulse peak on top of it kept the search open. The
            # trough of this pulse is the lowest point of the last MAX_RISE_S.
            if t - self._lo_t > MAX_RISE_S:
                self._lo_t, self._lo = min(recent, key=lambda s: s[1])
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
        if self.record:
            self.accepted.append((peak_t, rise))
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
