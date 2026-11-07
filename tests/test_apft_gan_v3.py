"""APFT-GAN v3 pieces on CPU: the differentiable feature copy against the feature tier, the rate label, the
heart-rate condition's zero start, head-only adversarial gradients and the conditional sampler of the judge."""
import numpy as np
import pytest
import torch

from ml.kaggle_physigpt import gan
from ml.kaggle_physigpt.judge_physigpt import generate, signal_features
from ml.kaggle_physigpt.mimic_wdb import rate_features
from ml.kaggle_physigpt.model import CONFIGS, PhysiGPT, build, load_init, window_rate
from dataclasses import replace


def pulses(n=16, seed=0):
    """Pulse-like windows of 40-150 bpm with a little noise, min-max normalised, [n, 1200]."""
    rng = np.random.default_rng(seed)
    t = np.arange(1200)/40
    rows = []
    for _ in range(n):
        f = rng.uniform(40, 150)/60
        phase = (t*f+rng.uniform()) % 1
        x = np.exp(-((phase-.2)/.08)**2)+.4*np.exp(-((phase-.45)/.1)**2)+.01*rng.standard_normal(len(t))
        rows.append((x-x.min())/(x.max()-x.min()))
    return np.array(rows, dtype=np.float32)


def test_soft_features_match_the_feature_tier():
    x = pulses()
    soft = gan.soft_features(torch.from_numpy(x)).numpy()
    ref = signal_features(x.astype(np.float64))
    names = [f"power_{k}" for k in ("0.5-1.5 Hz", "1.5-3 Hz", "3-5 Hz", "5-8 Hz", "8-20 Hz")]+["centroid_hz"]
    for i, k in enumerate(names):
        np.testing.assert_allclose(soft[:, i], ref[k], rtol=1e-3, atol=1e-3, err_msg=k)
    np.testing.assert_allclose(soft[:, 6], np.log(ref["diff_std"]+1e-6), rtol=1e-3, atol=1e-3)
    np.testing.assert_allclose(soft[:, 7], np.log(ref["diff2_std"]+1e-6), rtol=1e-3, atol=1e-3)
    np.testing.assert_allclose(soft[:, 8], ref["skew"], rtol=1e-3, atol=2e-3)
    np.testing.assert_allclose(soft[:, 9], ref["kurtosis"], rtol=1e-3, atol=2e-3)
    np.testing.assert_allclose(soft[:, 10], ref["diff_skew"], rtol=1e-3, atol=2e-3)
    np.testing.assert_allclose(soft[:, 11], ref["mean_level"], rtol=1e-4, atol=1e-5)
    np.testing.assert_allclose(soft[:, 12], ref["acf_peak"], rtol=1e-3, atol=1e-3)


def test_window_rate_is_the_feature_tier_rate():
    x = pulses(32, 1)
    np.testing.assert_allclose(window_rate(torch.from_numpy(x)).numpy(), rate_features(x)[1], rtol=1e-5)


def test_feature_distance_is_zero_on_the_same_batch_and_differentiable():
    x = torch.from_numpy(pulses())
    assert float(gan.feature_distance(x, x)) == pytest.approx(0., abs=1e-6)
    y = torch.from_numpy(pulses(seed=3)).requires_grad_(True)
    d = gan.feature_distance(y, x)
    d.backward()
    assert float(d) > 0 and torch.isfinite(y.grad).all() and float(y.grad.abs().sum()) > 0


def test_hr_condition_starts_as_the_loaded_model():
    torch.manual_seed(0)
    plain = PhysiGPT(CONFIGS["tiny"])
    cond = PhysiGPT(replace(CONFIGS["tiny"], hr_cond=True))
    added = load_init(cond, dict(model=plain.state_dict()))
    assert added and all(k.startswith("hr.") for k in added)
    x = torch.from_numpy(pulses(4)).view(4, 30, 40)
    domain = torch.zeros(4, dtype=torch.long)
    torch.testing.assert_close(cond.hidden(x, domain, torch.tensor([50., 80., 120., 160.])), plain.hidden(x, domain))
    with pytest.raises(ValueError):
        cond.hidden(x, domain)
    with pytest.raises(ValueError):   # a state with keys the model does not have
        load_init(plain, dict(model=cond.state_dict()))


def test_head_scope_keeps_adversarial_gradients_out_of_the_backbone():
    torch.manual_seed(0)
    model = PhysiGPT(CONFIGS["tiny"])
    g = torch.Generator().manual_seed(0)
    patches, noise = gan.rollout(model, 4, 2, g, "cpu")
    out = gan.regenerate(model, patches, noise, 2, use_checkpoint=False, head_only=True)
    out.square().mean().backward()
    head = {id(p) for p in model.flow.parameters()}
    assert all(p.grad is None for p in model.parameters() if id(p) not in head)
    assert any(p.grad is not None and float(p.grad.abs().sum()) > 0 for p in model.flow.parameters())


def test_judge_samples_a_conditional_checkpoint_from_its_rate_bank(tmp_path):
    torch.manual_seed(0)
    model = PhysiGPT(replace(CONFIGS["tiny"], hr_cond=True))
    path = tmp_path/"gan_release.pt"
    torch.save(dict(model=model.state_dict(), config="tiny", hr_cond=True,
                    hr_bank=np.array([60., 90.], dtype=np.float32)), path)
    x = generate(str(path), 3, 0, "cpu", batch=2, steps=2)
    assert x.shape == (3, 1200) and np.isfinite(x).all()
    assert isinstance(build(torch.load(path, weights_only=False)), PhysiGPT)


def test_adaptive_weight_ignores_overflow():
    assert gan.adaptive(1., 4., 10.) == pytest.approx(.25)
    assert gan.adaptive(1., 1e-12, 10.) == 10.
    assert gan.adaptive(float("inf"), 1., 10.) == 0.
