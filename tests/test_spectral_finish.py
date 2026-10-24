"""spectral_finish: removes 12-20 Hz content inside the window, keeps the band below and the boundary slope."""
import numpy as np
import pytest

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain import spectral_finish as sf


def windows(seed=0, n=8, hf=1e-3):
    rng = np.random.default_rng(seed)
    t = np.arange(LENGTH)/FS
    rate = rng.uniform(1, 2, (n, 1))
    x = np.sin(2*np.pi*rate*t+rng.uniform(0, 6, (n, 1)))+.3*np.sin(4*np.pi*rate*t)
    x = x+.4*t/30    # not periodic over the window: the boundary must not wrap
    return x+hf*rng.standard_normal(x.shape)


def interior_power(x, lo, hi):
    """Mean |rFFT|^2 between lo and hi Hz of the Hann-tapered middle 20 s (edges excluded)."""
    mid = x[:, 200:1000]*np.hanning(800)
    freq = np.fft.rfftfreq(800, 1/FS)
    return (np.abs(np.fft.rfft(mid-mid.mean(1, keepdims=True), axis=1))**2)[:, (freq >= lo) & (freq < hi)].mean()


def test_high_band_removed_low_band_kept():
    x = windows()
    y = sf.low_pass(x, 10, 12)
    ref = (x-x.min(1, keepdims=True))/np.ptp(x, 1, keepdims=True)
    assert interior_power(y, 12.5, 20) < 1e-4*interior_power(ref, 12.5, 20)
    assert interior_power(y, .5, 9) == pytest.approx(interior_power(ref, .5, 9), rel=.02)
    assert y.dtype == np.float32 and y.min() == 0 and y.max() == 1


def test_boundary_slope_kept_not_flattened():
    x = windows(hf=0)
    y = sf.low_pass(x, 10, 12)
    ref = (x-x.min(1, keepdims=True))/np.ptp(x, 1, keepdims=True)
    for edge in (slice(0, 3), slice(-3, None)):
        # within 10% of the slope (renormalisation and the removed noise move it slightly); a reflection pad gives ~0
        np.testing.assert_allclose(np.diff(y[:, edge]), np.diff(ref[:, edge]), rtol=.1, atol=1e-3)


def test_mask_and_input_checks():
    m = sf.low_pass_mask(10, 12, LENGTH)
    freq = np.fft.rfftfreq(LENGTH, 1/FS)
    assert (m[freq <= 10] == 1).all() and (m[freq >= 12] == 0).all()
    with pytest.raises(ValueError):
        sf.low_pass_mask(12, 10, LENGTH)
    with pytest.raises(ValueError):
        sf.low_pass(windows()[0], 10, 12)
    with pytest.raises(ValueError):
        sf.low_pass(np.full((1, LENGTH), np.nan), 10, 12)


def test_wrapper_passes_ids_and_seed():
    calls = []

    def generate(ids, conditions, seed):
        calls.append((list(ids), seed))
        return windows(seed, len(ids))
    out = sf.low_passed(generate, 10, 12)([1, 2, 3], None, 7)
    assert calls == [([1, 2, 3], 7)] and out.shape == (3, LENGTH)
