"""Step C judges (report only) and the training snapshots used by the presentation page."""
import numpy as np
import pytest
import torch

from ml.kaggle_multidomain import judges

FS, LENGTH = 40, 1200


def synthetic_ppg(rate_bpm=72., notch=True, seed=0, n=1):
    """Two-Gaussian pulses (systolic + diastolic wave) per beat: a clean PPG-like window in [0, 1]."""
    rng = np.random.default_rng(seed)
    t = np.arange(LENGTH)/FS
    out = []
    for _ in range(n):
        beats = np.cumsum(np.full(60, 60/rate_bpm)*(1+.02*rng.standard_normal(60)))-1
        y = np.zeros(LENGTH)
        for b in beats:
            y += np.exp(-.5*((t-b-.18)/.07)**2)
            if notch:
                y += .45*np.exp(-.5*((t-b-.45)/.08)**2)
        out.append((y-y.min())/np.ptp(y))
    return np.asarray(out, np.float32)


def test_physiology_features_find_the_dicrotic_wave_and_the_rate():
    with_notch, without = judges.physiology(synthetic_ppg(n=4)), judges.physiology(synthetic_ppg(notch=False, n=4, seed=1))
    names = list(judges.FEATURES)
    assert np.isfinite(with_notch).all()
    # Without a notch its phase is undefined (NaN); every other feature is measured.
    assert np.isnan(without[:, names.index("notch_phase")]).all()
    assert np.isfinite(np.delete(without, names.index("notch_phase"), axis=1)).all()
    assert (with_notch[:, names.index("notch_share")] > .8).all()
    assert (without[:, names.index("notch_share")] < .2).all()
    assert (with_notch[:, names.index("beat_consistency")] > .95).all()
    assert (with_notch[:, names.index("ibi_cv")] < .1).all()
    flat = judges.physiology(np.zeros((1, LENGTH), np.float32)+.5)
    assert np.isnan(flat).all()


def test_band_limit_keeps_only_the_band():
    t = np.arange(LENGTH)/FS
    x = (np.sin(2*np.pi*1.*t)+np.sin(2*np.pi*6.*t))[None]
    low, high = judges.band_limit(x, .5, 1.5), judges.band_limit(x, 5., 8.)
    spectrum = lambda y: np.abs(np.fft.rfft(y[0]-y[0].mean()))
    f = np.fft.rfftfreq(LENGTH, 1/FS)
    assert f[spectrum(low).argmax()] == pytest.approx(1.) and f[spectrum(high).argmax()] == pytest.approx(6.)
    assert low.min() >= 0 and low.max() <= 1


def test_papagei_input_is_three_ten_second_segments_at_125_hz():
    segments, per_window = judges.papagei_segments(synthetic_ppg(n=2))
    assert per_window == 3 and segments.shape == (6, 1, 1250)
    assert torch.allclose(segments.mean(-1), torch.zeros(6, 1), atol=1e-5)


def test_linear_c2st_separates_shifted_embeddings_and_not_identical_ones():
    rng = np.random.default_rng(0)
    real, groups = rng.standard_normal((80, 16)), np.repeat(np.arange(8), 10)
    assert judges.linear_c2st(real, groups, rng.standard_normal((80, 16))+1.5, None) > .95
    assert abs(judges.linear_c2st(real, groups, rng.standard_normal((80, 16)), None)-.5) < .15
    assert judges.frechet(real, real) == pytest.approx(0., abs=1e-6)


def test_feature_distance_is_one_for_a_set_as_far_as_the_reference():
    rng = np.random.default_rng(1)
    target = rng.normal(0, 1, (200, len(judges.FEATURES)))
    other = target+.5
    gap = {name: .5 for name in judges.FEATURES}
    out = judges.feature_distance(target, other, gap)
    assert all(out[name]["ratio"] == pytest.approx(1., abs=1e-6) for name in judges.FEATURES)
    assert out["measurable_share"] == 1.


def test_training_snapshots_do_not_change_the_training_random_stream(tmp_path):
    from ml.kaggle_multidomain.experiment_v3 import Snapshots

    class Conditions:
        domains = ["gxu_finger", "wrist"]

        def prompt(self, domain, bpm, sigma, n):
            return np.ones((n, 7), np.float32)

    class Model(torch.nn.Module):
        def forward(self, z, condition):
            return (z+torch.randn_like(z))[:, None]  # uses the global RNG like a stochastic sampler would

    import ml.kaggle_multidomain.experiment_v3 as v3
    cfg = dict(diffusion=False, guidance=1., sample_steps=1)
    original = v3.draw
    v3.draw = lambda model, z, c, *args: model(z, c)
    try:
        torch.manual_seed(5)
        expected = torch.rand(3)
        torch.manual_seed(5)
        snaps = Snapshots(Conditions(), cfg, "cpu", tmp_path/"snapshots.npz")
        model = Model().train()
        snaps.maybe(500, 1000, model)
        snaps.maybe(501, 1000, model)  # not a snapshot step
        snaps.maybe(1000, 1000, model)
        assert torch.equal(torch.rand(3), expected)
        assert model.training
    finally:
        v3.draw = original
    with np.load(tmp_path/"snapshots.npz") as s:
        assert s["steps"].tolist() == [500, 1000] and s["signals"].shape == (2, 2, LENGTH)
        assert s["domains"].tolist() == ["gxu_finger", "wrist"]
