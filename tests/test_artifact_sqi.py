"""artifact_sqi: the rule-based artifact share behind the report's Fig. 2, 3 (synthetic PPG-like windows)."""
import numpy as np
import pytest

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain import artifact_sqi as sqi
from ml.kaggle_multidomain.physio import view_mask


def ppg(beat_times):
    """Systolic and dicrotic Gaussian pulses at the given beat onsets (s), through the pack's 0.5-8 Hz view filter
    (as every v3 window), min-max normalised."""
    t = np.arange(LENGTH)/FS
    x = np.zeros(LENGTH)
    for b in beat_times:
        x += np.exp(-.5*((t-b-.15)/.07)**2)+.4*np.exp(-.5*((t-b-.42)/.09)**2)
    x = np.fft.irfft(np.fft.rfft(x-x.mean())*view_mask("v3"), n=LENGTH)
    return (x-x.min())/np.ptp(x)


def regular(bpm, start=.2):
    return ppg(np.arange(start, LENGTH/FS, 60/bpm))


@pytest.mark.parametrize("bpm", [45, 75, 120, 180])
def test_clean_beats_at_several_rates_are_not_marked(bpm):
    assert sqi.artifact_fraction(regular(bpm)[None])[0] <= .03


def test_noise_burst_and_flat_run_are_marked():
    x = regular(75)
    noisy = x.copy()
    noisy[400:600] = np.random.default_rng(0).random(200)
    mask = sqi.artifact_mask(noisy[None])[0]
    assert mask[400:600].mean() >= .8 and mask[:300].mean() <= .05
    flat = x.copy()
    flat[700:820] = flat[700]
    assert sqi.artifact_mask(flat[None])[0][700:820].mean() >= .8


def test_irregular_rhythm_with_clean_beats_is_not_artifact():
    gaps = np.random.default_rng(1).uniform(.5, 1.1, size=60)    # 55-120 bpm, AF-like irregularity
    beats = np.cumsum(np.r_[.2, gaps])
    assert sqi.artifact_fraction(ppg(beats[beats < LENGTH/FS])[None])[0] <= .1


def test_groups_follow_the_paper_boundaries():
    labels = sqi.quality_group([0, 1e-9, .2, .2000001, .6, .61, 1.])
    assert list(labels) == ["0%", "0-20%", "0-20%", "20-60%", "20-60%", "60-100%", "60-100%"]
    with pytest.raises(ValueError):
        sqi.quality_group([1.2])


def test_shapes_and_input_checks():
    x = np.stack([regular(60), regular(90)])
    mask = sqi.artifact_mask(x)
    assert mask.shape == (2, LENGTH) and mask.dtype == bool
    assert sqi.artifact_fraction(x).shape == (2,)
    with pytest.raises(ValueError):
        sqi.artifact_mask(regular(60))
    with pytest.raises(ValueError):
        sqi.artifact_mask(np.full((1, LENGTH), np.nan))
