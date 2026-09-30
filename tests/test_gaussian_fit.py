"""Fitted Gaussian shape contracts, without loading any neural networks."""
import json
import math

import pytest

from core.neural_preview import gaussian_preview, GAUSSIAN_PROFILE_FILE
from models.waveform import PulseMorphology, PulseShaper, WAVE_PPG


def test_train_fitted_profiles_retain_the_measured_shape_improvement():
    profiles = json.loads(GAUSSIAN_PROFILE_FILE.read_text())["profiles"]
    original = PulseShaper()
    for name, row in profiles.items():
        fitted = PulseShaper(PulseMorphology(**row["morphology"]))
        target = row["reference_waveform"]
        actual = [fitted.sample(WAVE_PPG,i/255) for i in range(256)]
        before = [original.sample(WAVE_PPG,i/255) for i in range(256)]
        rmse = lambda y: math.sqrt(sum((a-b)**2 for a,b in zip(y,target))/256)
        assert rmse(actual) < .05 and rmse(actual) < rmse(before)/2, name
        assert all(math.isfinite(v) and 0 <= v <= 1 for v in actual)
        assert fitted.sample(WAVE_PPG,0) == fitted.sample(WAVE_PPG,1) == 0
        assert fitted.sample(WAVE_PPG,1e-6) < 1e-7
        assert fitted.sample(WAVE_PPG,1-1e-6) < 1e-7


def test_notch_profile_has_a_real_local_valley_and_rebound():
    profiles = json.loads(GAUSSIAN_PROFILE_FILE.read_text())["profiles"]
    for name, expected in (("With notch",True),("No notch",False)):
        shaper=PulseShaper(PulseMorphology(**profiles[name]["morphology"]))
        y=[shaper.sample(WAVE_PPG,i/1000) for i in range(1001)]
        sp=y.index(max(y))
        valleys=[i for i in range(sp+1,990) if y[i]<y[i-1] and y[i]<y[i+1]]
        assert any(max(y[i:])-y[i] > .035 for i in valleys) == expected


def test_gaussian_profile_failure_does_not_break_original(monkeypatch,tmp_path):
    import core.neural_preview as module
    before=gaussian_preview()
    monkeypatch.setattr(module,"GAUSSIAN_PROFILE_FILE",tmp_path/"missing.json")
    assert gaussian_preview() == before
    with pytest.raises(OSError):
        gaussian_preview(profile="Balanced")
    with pytest.raises(ValueError,match="Unknown Gaussian"):
        gaussian_preview(profile="unknown")


def test_fitted_preview_has_reproducible_profile_identity():
    previews=[gaussian_preview(75,profile) for profile in ("Balanced","No notch","With notch")]
    assert len({p.variant for p in previews}) == 3
    assert all(p.name == "Gaussian (fitted)" and p.seed is None for p in previews)
    assert previews[0].samples != previews[1].samples != previews[2].samples
    assert previews[0].model_sha256 != gaussian_preview().model_sha256
    assert previews[0] == gaussian_preview(75,"Balanced")
