"""
digital_filters.py — Biquad IIR digital filters for biomedical signals.

Port of digital_filters.cpp. Implements:
  - BiquadSection (Direct Form II Transposed)
  - LowpassFilter (Butterworth 2nd order)
  - HighpassFilter (Butterworth 2nd order)
  - NotchFilter (2nd order)
  - BandpassFilter (4th order = HP + LP cascade)
  - SignalFilterChain (HP → LP → Notch pipeline)
"""

import math

_PI = math.pi


class BiquadSection:
    """Single biquad IIR section — Direct Form II Transposed."""
    __slots__ = ("b0", "b1", "b2", "a1", "a2", "w1", "w2")

    def __init__(self, b0=1.0, b1=0.0, b2=0.0, a1=0.0, a2=0.0):
        self.b0 = b0; self.b1 = b1; self.b2 = b2
        self.a1 = a1; self.a2 = a2
        self.w1 = 0.0; self.w2 = 0.0

    def reset(self):
        self.w1 = 0.0; self.w2 = 0.0

    def process(self, x: float) -> float:
        y = self.b0 * x + self.w1
        self.w1 = self.b1 * x - self.a1 * y + self.w2
        self.w2 = self.b2 * x - self.a2 * y
        return y


class LowpassFilter:
    """2nd-order Butterworth lowpass."""
    def __init__(self, fc=40.0, fs=500.0):
        self.biquad = BiquadSection()
        self.cutoff = fc; self.fs = fs; self.enabled = True
        self._calc()

    def configure(self, fc, fs):
        self.cutoff = fc; self.fs = fs; self._calc()

    def _calc(self):
        wd = 2 * _PI * self.cutoff / self.fs
        T = 1.0 / self.fs
        wa = (2 / T) * math.tan(wd * T / 2)
        wa2 = wa * wa; s2wa = 1.41421356 * wa
        K = 2 * self.fs; K2 = K * K
        d = K2 + s2wa * K + wa2
        self.biquad.b0 = wa2 / d
        self.biquad.b1 = 2 * wa2 / d
        self.biquad.b2 = wa2 / d
        self.biquad.a1 = (2 * wa2 - 2 * K2) / d
        self.biquad.a2 = (K2 - s2wa * K + wa2) / d

    def process(self, x): return self.biquad.process(x) if self.enabled else x
    def reset(self): self.biquad.reset()


class HighpassFilter:
    """2nd-order Butterworth highpass."""
    def __init__(self, fc=0.5, fs=500.0):
        self.biquad = BiquadSection()
        self.cutoff = fc; self.fs = fs; self.enabled = True
        self._calc()

    def configure(self, fc, fs):
        self.cutoff = fc; self.fs = fs; self._calc()

    def _calc(self):
        wd = 2 * _PI * self.cutoff / self.fs
        T = 1.0 / self.fs
        wa = (2 / T) * math.tan(wd * T / 2)
        wa2 = wa * wa; s2wa = 1.41421356 * wa
        K = 2 * self.fs; K2 = K * K
        d = K2 + s2wa * K + wa2
        self.biquad.b0 = K2 / d
        self.biquad.b1 = -2 * K2 / d
        self.biquad.b2 = K2 / d
        self.biquad.a1 = (2 * wa2 - 2 * K2) / d
        self.biquad.a2 = (K2 - s2wa * K + wa2) / d

    def process(self, x): return self.biquad.process(x) if self.enabled else x
    def reset(self): self.biquad.reset()


class NotchFilter:
    """2nd-order IIR notch filter for 50/60 Hz rejection."""
    def __init__(self, fc=60.0, fs=500.0, Q=30.0):
        self.biquad = BiquadSection()
        self.fc = fc; self.fs = fs; self.Q = Q; self.enabled = True
        self._calc()

    def configure(self, fc, fs, Q=30.0):
        self.fc = fc; self.fs = fs; self.Q = Q; self._calc()

    def _calc(self):
        w0 = 2 * _PI * self.fc / self.fs
        alpha = math.sin(w0) / (2 * self.Q)
        a0 = 1.0 + alpha
        self.biquad.b0 = 1.0 / a0
        self.biquad.b1 = -2 * math.cos(w0) / a0
        self.biquad.b2 = 1.0 / a0
        self.biquad.a1 = -2 * math.cos(w0) / a0
        self.biquad.a2 = (1.0 - alpha) / a0

    def process(self, x): return self.biquad.process(x) if self.enabled else x
    def reset(self): self.biquad.reset()


class SignalFilterChain:
    """Complete HP → LP → Notch filter pipeline for PPG signals."""
    def __init__(self):
        self.highpass = HighpassFilter(0.5, 250.0)
        self.lowpass = LowpassFilter(8.0, 250.0)
        self.notch = NotchFilter(60.0, 250.0)
        self.enabled = False  # Disabled by default

    def configure_for_ppg(self, fs=250.0, notch_freq=60.0):
        self.highpass.configure(0.5, fs)
        self.lowpass.configure(8.0, fs)
        self.notch.configure(notch_freq, fs, 30.0)

    def process(self, x):
        if not self.enabled:
            return x
        x = self.highpass.process(x)
        x = self.lowpass.process(x)
        x = self.notch.process(x)
        return x

    def reset(self):
        self.highpass.reset()
        self.lowpass.reset()
        self.notch.reset()
