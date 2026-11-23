"""Validated finite voltage clip, interpolated on the engine's 100 Hz clock."""
from dataclasses import dataclass
import math
from config import DAC_FULLSCALE_V

MAX_SAMPLES = 100*60*30     # 30 min at 100 Hz (~25 MB of row tuples): a recording played to the LEDs may be this long
SPAN_PERCENTILE = 0.02      # pulse_span: low/high taken at 2 % / 98 %, so a few spikes do not set the scale


def pulse_span(clip):
    """(lane, low V, high V) of the clip's pulse: the lane (1 = IR, 2 = RED) whose 2nd-98th percentile span is
    the larger, and that span. The MAX30102 mode maps it onto its preset DC/AC (SignalEngine)."""
    best = None
    for lane in (1, 2):
        values = sorted(row[lane] for row in clip.samples)
        k = int(SPAN_PERCENTILE*(len(values)-1))
        low, high = values[k], values[len(values)-1-k]
        if best is None or high-low > best[2]-best[1]:
            best = (lane, low, high)
    return best


@dataclass(frozen=True)
class WaveformClip:
    samples: tuple
    sample_rate: float
    name: str

    @classmethod
    def from_preview(cls, preview, dc_mv=1500, ac_mv=45):
        if not all(math.isfinite(v) and 0 <= v <= 1500 for v in (dc_mv, ac_mv)):
            raise ValueError("DC / AC must be 0–1500 mV")
        rows = tuple((float(t), dc_mv/1000 + ac_mv/1000*(ir-1.5)/.045,
                      dc_mv/1000 + ac_mv/1000*(red-1.5)/.045)
                     for t,ir,red in preview.samples)
        clip = cls(rows, float(preview.native_fs), preview.name)
        clip.validate()
        return clip

    @classmethod
    def from_recording(cls, samples, name, start_s=0.0, rate=100.0):
        """A recording's (t, IR V, RED V) rows from start_s on, linearly resampled onto a uniform grid at `rate`
        (the engine's 100 Hz tick; recordings are written on that tick, a dropped row is bridged)."""
        times = [row[0] for row in samples]
        end = times[-1] if times else 0.0
        if not 0.0 <= start_s < end:
            raise ValueError("Start must lie inside the recording")
        count = int((end-start_s)*rate)+1
        if count > MAX_SAMPLES:
            raise ValueError(f"Recording is longer than {MAX_SAMPLES/100/60:.0f} min from this point")
        rows, j = [], 0
        for i in range(count):
            t = start_s+i/rate
            while j+1 < len(samples) and times[j+1] <= t:
                j += 1
            a, b = samples[j], samples[min(j+1, len(samples)-1)]
            w = 0.0 if b[0] == a[0] else min(1.0, max(0.0, (t-a[0])/(b[0]-a[0])))
            rows.append((i/rate, a[1]+w*(b[1]-a[1]), a[2]+w*(b[2]-a[2])))
        clip = cls(tuple(rows), float(rate), name)
        clip.validate()
        return clip

    def validate(self):
        if not math.isfinite(self.sample_rate) or not 1 <= self.sample_rate <= 100:
            raise ValueError("Clip sample rate must be 1–100 Hz")
        if not 2 <= len(self.samples) <= MAX_SAMPLES:
            raise ValueError(f"Clip must contain 2–{MAX_SAMPLES} samples")
        for i, row in enumerate(self.samples):
            if len(row) != 3 or not all(math.isfinite(v) for v in row):
                raise ValueError("Clip contains invalid samples")
            t, ir, red = row
            if abs(t-i/self.sample_rate) > 1e-7:
                raise ValueError("Clip timestamps must be uniform and start at zero")
            if not 0 <= ir <= DAC_FULLSCALE_V or not 0 <= red <= DAC_FULLSCALE_V:
                raise ValueError("Clip exceeds DAC voltage limits")

    @property
    def duration(self):
        return len(self.samples)/self.sample_rate

    def at(self, seconds):
        if not math.isfinite(seconds) or seconds < 0 or seconds >= self.duration:
            raise ValueError("Time outside finite clip")
        phase = seconds*self.sample_rate
        left = min(int(phase),len(self.samples)-1)
        right = min(left+1,len(self.samples)-1)
        weight = phase-left
        a,b = self.samples[left],self.samples[right]
        return a[1]+weight*(b[1]-a[1]), a[2]+weight*(b[2]-a[2])
