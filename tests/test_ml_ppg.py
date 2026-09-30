"""Offline regression tests; numerical ML dependencies are optional at runtime."""
import importlib.util
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

SPEC = importlib.util.spec_from_file_location(
    "train_ppg", Path(__file__).parents[1] / "ml/kaggle/train_ppg.py")
ppg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ppg)


def pulse():
    t = np.linspace(0, 1, 256)
    y = np.exp(-0.5 * ((t - .18) / .06)**2)
    y += .4 * np.exp(-0.5 * ((t - .48) / .10)**2)
    y -= np.linspace(y[0], y[-1], len(y))
    y = np.maximum(y, 0)
    return y / y.max()


def test_landmarks_are_observed_extrema_in_order():
    m = ppg.measure(pulse())
    assert m["has_notch"]
    assert 0 < m["sp_phase"] < m["dn_phase"] < m["dp_phase"] < 1
    assert 0 < m["dn_level"] < m["dp_level"] < 1


def test_monophasic_pulse_has_missing_notch_not_fabricated_landmarks():
    t = np.linspace(0, 1, 256)
    y = t * (1 - t)**4
    m = ppg.measure(y / y.max())
    assert not m["has_notch"]
    assert m["dn_phase"] is None
    assert m["dp_phase"] is None


@pytest.mark.parametrize("x", [np.zeros(256), np.full(256, np.nan)])
def test_invalid_pulse_rejected(x):
    with pytest.raises(ValueError):
        ppg.measure(x)


def test_subject_split_is_disjoint_reproducible_and_groups_duplicates():
    ids = np.repeat([f"s{i:05d}" for i in range(20)], 5)
    a = ppg.split_subjects(ids, 42)
    b = ppg.split_subjects(ids, 42)
    assert a == b
    assert set(a["train"]).isdisjoint(a["validation"])
    assert set(a["train"]).isdisjoint(a["test"])
    assert set(a["validation"]).isdisjoint(a["test"])
    assert set(sum(a.values(), [])) == set(ids)


def test_sampling_rate_and_hr_are_independent_of_template_length():
    for fs in (100, 125, 1000):
        t, ir, red = ppg.render_ir_red(pulse(), fs=fs, hr=75, seconds=4)
        assert len(t) == 4 * fs
        assert np.diff(t) == pytest.approx(np.full(4 * fs - 1, 1 / fs))
        assert ir[0] == pytest.approx(ir[int(.8 * fs)])
        assert np.ptp(red) / np.ptp(ir) == pytest.approx(.48)


def test_unequal_dc_ratio_and_polarity_and_voltage_rail_checks():
    _, ir, red = ppg.render_ir_red(
        pulse(), dc_ir=1.5, dc_red=1.0, ac_ir=.045, polarity=-1)
    assert ir.max() <= 1.5 and red.max() <= 1.0
    ratio = (np.ptp(red) / 1.0) / (np.ptp(ir) / 1.5)
    assert ratio == pytest.approx(.48)
    with pytest.raises(ValueError):
        ppg.render_ir_red(pulse(), dc_ir=3.27, ac_ir=.045)


@pytest.mark.parametrize("kwargs", [{"fs": 0}, {"hr": 0}, {"dc_ir": 0},
                                   {"seconds": -1}, {"polarity": 0},
                                   {"spo2": 101}, {"fs": float("nan")}])
def test_invalid_render_parameters_rejected(kwargs):
    with pytest.raises(ValueError):
        ppg.render_ir_red(pulse(), **kwargs)


def test_negative_or_discontinuous_template_rejected():
    y = pulse()
    y[100] = -.01
    with pytest.raises(ValueError):
        ppg.render_ir_red(y)
    y = pulse()
    y[-1] = .1
    with pytest.raises(ValueError):
        ppg.render_ir_red(y)


def test_gaussian_baseline_matches_current_default_shaper():
    from models.waveform import PulseShaper
    shaper = PulseShaper()
    expected = np.array([shaper.sample("ppg", float(p)) for p in ppg.PHASE])
    expected /= expected.max()
    np.testing.assert_allclose(ppg.gaussian_baseline(), expected, atol=1e-7)


def test_notch_audit_does_not_hide_missing_positive_predictions():
    from ml.evaluate_run import classification
    report = classification([1, 1, 0, 0], [0, 0, 0, 0])
    assert report["sensitivity"] == 0
    assert report["specificity"] == 1
    assert report["precision"] is None


def test_generator_output_and_gradient_penalty_are_finite():
    torch = pytest.importorskip("torch")
    torch.set_num_threads(1)
    g, critic = ppg.make_networks()
    c = torch.tensor(np.tile(ppg.condition(pulse(), 75), (4, 1)))
    y = g(torch.randn(4, ppg.LATENT_DIM), c)
    assert y.shape == (4, 256)
    assert torch.all(y >= 0) and torch.all(y <= 1.00001)
    assert torch.all(y[:, 0] == 0) and torch.all(y[:, -1] == 0)
    gp = ppg.gradient_penalty(critic, torch.rand_like(y), y.detach(), c)
    gp.backward()
    assert torch.isfinite(gp)
    assert all(torch.isfinite(p.grad).all() for p in critic.parameters()
               if p.grad is not None)
