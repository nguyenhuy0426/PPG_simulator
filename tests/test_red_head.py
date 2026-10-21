"""ml.kaggle_multidomain.red_head: residual parameterisation of the red channel, baseline and residual score."""
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain import red_head as rh


def pairs(n=6, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(LENGTH)/FS
    ir = .5+.5*np.sin(2*np.pi*1.2*t)[None]+.02*rng.standard_normal((n, LENGTH))
    ir = (ir-ir.min(-1, keepdims=True))/np.ptp(ir, -1, keepdims=True)
    shape = ir+.03*np.sin(2*np.pi*2.4*t+.3)[None]+.01*rng.standard_normal((n, LENGTH))
    ratio = rng.uniform(.4, 1., n)
    red = ratio[:, None]*(shape-shape.mean(-1, keepdims=True))/np.ptp(shape, -1, keepdims=True)
    return ir, red, ratio


def test_compose_inverts_the_residual_target_and_keeps_the_commanded_ratio():
    ir, red, ratio = pairs()
    y, a, valid = rh.residual_target(ir, red)
    assert valid.all() and np.allclose(a, ratio, rtol=.1)
    back = rh.compose(ir, y, ratio)
    assert np.allclose(back, red, atol=1e-6)
    assert np.allclose(np.ptp(rh.compose(ir, 3*y, ratio), -1), ratio)
    as_tensor = rh.compose(torch.tensor(ir), torch.tensor(y.astype(np.float64)), torch.tensor(ratio)).numpy()
    assert np.allclose(as_tensor, back, atol=1e-6)


def test_residual_target_rejects_flat_or_inverted_red():
    ir, red, _ = pairs(3)
    ir[0] = .5
    red[1] = -red[1]
    _, _, valid = rh.residual_target(ir, red)
    assert valid.tolist() == [False, False, True]


def test_head_conditions_reserve_slots_and_reject_unknown_datasets():
    c = rh.HeadConditions(["ptt_sit", "gxu_finger", "ptt_sit"], [.4, .7, .5])
    rows = c.rows(["gxu_finger"], [.5])
    assert rows.shape == (1, rh.HEAD_SLOTS+1) and rows[0, 0] == 1 and rows[0, :rh.HEAD_SLOTS].sum() == 1
    with pytest.raises(ValueError):
        c.rows(["bidmc"], [.5])
    with pytest.raises(ValueError):
        rh.HeadConditions([f"d{i}" for i in range(rh.HEAD_SLOTS+1)], [.5]*(rh.HEAD_SLOTS+1))


def test_residual_score_is_zero_for_the_real_residual_and_large_for_the_copy():
    ir, red, ratio = pairs(12)
    y, _, _ = rh.residual_target(ir, red)
    domains = ["a"]*6+["b"]*6
    assert rh.residual_score(y, y, domains, domains)[0] == pytest.approx(0)
    copy, _, _ = rh.residual_target(ir, rh.compose(ir, np.zeros_like(ir), ratio))
    assert rh.residual_score(copy, y, domains, domains)[0] > 2


def test_coloured_baseline_matches_the_training_amplitude_spectrum():
    ir, red, _ = pairs(40, seed=3)
    y, _, _ = rh.residual_target(ir, red)
    baseline = rh.ColouredResidual(y, ["a"]*40)
    sample = baseline.sample(["a"]*200, np.random.default_rng(1))
    assert sample.shape == (200, LENGTH)
    assert np.median(sample.std(-1)) == pytest.approx(np.median(y.std(-1)), rel=.25)


def test_head_samples_red_with_the_commanded_ratio():
    ir, _, ratio = pairs(2)
    c = rh.HeadConditions(["a"], [.5])
    head = rh.RedHead(c.size, sample_steps=2).eval()
    with torch.no_grad():
        red = head(torch.randn(2, LENGTH), torch.tensor(ir, dtype=torch.float32), torch.tensor(c.rows(["a"]*2, ratio)),
                   torch.tensor(ratio, dtype=torch.float32)).numpy()
    assert np.isfinite(red).all() and np.allclose(np.ptp(red, -1), ratio, rtol=1e-4)
