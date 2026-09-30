"""Validated finite voltage clip, interpolated on the engine's 100 Hz clock."""
from dataclasses import dataclass
import math
from config import DAC_FULLSCALE_V


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

    def validate(self):
        if not math.isfinite(self.sample_rate) or not 1 <= self.sample_rate <= 100:
            raise ValueError("Clip sample rate must be 1–100 Hz")
        if not 2 <= len(self.samples) <= 100*300:
            raise ValueError("Clip must contain 2–30000 samples")
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
