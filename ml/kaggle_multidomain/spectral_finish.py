"""Spectral finish: a zero-phase low-pass that removes the generators' 12-20 Hz residue (scripts/leak_features.py).

Real v3 windows carry almost no power above ~12 Hz inside the window (median STFT power 2.6e-9 at 12-20 Hz on
perform_large validation people) while PhysioFlow's windows carry ~3e-6 there; a log-spectrum judge separates them on
that band alone (logistic AUC 0.99). The finish is a raised-cosine FFT low-pass from `start` to `stop` Hz over an
odd (point-reflected) extension of the window: the odd extension keeps the boundary slope, so the edge frames, which
already match the real windows, are not flattened (a reflection pad flattens them and is itself detectable).
It changes nothing below `start` Hz and is a post-processing step of the generated signal, not a model change.
"""
import numpy as np

from ml.kaggle_lsm.train_lsm import FS, LENGTH

PAD = 200


def low_pass_mask(start, stop, n):
    """Raised-cosine gain on the rFFT grid of an n-sample signal: 1 below start Hz, 0 above stop Hz."""
    if not 0 < start < stop <= FS/2:
        raise ValueError(f"Low-pass band {start}-{stop} Hz outside (0, {FS/2}]")
    freq = np.fft.rfftfreq(n, 1/FS)
    ramp = np.clip((stop-freq)/(stop-start), 0, 1)
    return .5-.5*np.cos(np.pi*ramp)


def low_pass(x, start, stop, pad=PAD):
    """(n, L) windows -> low-passed over an odd extension, min-max normalised (float32)."""
    x = np.asarray(x, np.float64)
    if x.ndim != 2 or x.shape[1] <= pad+1:
        raise ValueError(f"Expected (n, L>{pad+1}) windows, got {x.shape}")
    if not np.isfinite(x).all():
        raise ValueError("Non-finite window values")
    length = x.shape[1]
    head = 2*x[:, :1]-x[:, 1:pad+1][:, ::-1]
    tail = 2*x[:, -1:]-x[:, length-pad-1:length-1][:, ::-1]
    y = np.concatenate((head, x, tail), 1)
    y = np.fft.irfft(np.fft.rfft(y, axis=1)*low_pass_mask(start, stop, y.shape[1]), n=y.shape[1], axis=1)
    y = y[:, pad:pad+length]
    return ((y-y.min(1, keepdims=True))/np.maximum(np.ptp(y, 1, keepdims=True), 1e-9)).astype(np.float32)


def low_passed(generate, start, stop):
    """Wrap a generate(ids, conditions, seed) -> (n, LENGTH) source with the finish."""
    def wrapped(ids, conditions, seed):
        out = generate(ids, conditions, seed)
        if out.shape[1] != LENGTH:
            raise ValueError(f"Generator returned {out.shape[1]} samples, expected {LENGTH}")
        return low_pass(out, start, stop)
    return wrapped
