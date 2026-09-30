"""LSM network, spectrum and split regression tests (offline only)."""
import importlib.util
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
pytest.importorskip("scipy")
spec = importlib.util.spec_from_file_location("train_lsm", Path(__file__).parents[1]/"ml/kaggle_lsm/train_lsm.py")
lsm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lsm)
torch.set_num_threads(1)


def test_shapes_parameter_counts_and_gradients():
    g, d = lsm.make_networks()
    y = g(torch.randn(2, 1200))
    assert y.shape == (2, 1, 1200)
    assert y.amin() >= 0 and y.amax() <= 1
    assert d(y).shape == (2, 2)
    assert torch.all((d(y) > 0) & (d(y) < 1))
    (d(y).mean()+lsm.spectral_loss(y, torch.rand_like(y))[0]).backward()
    assert all(torch.isfinite(p.grad).all() for p in g.parameters() if p.grad is not None)


def test_log_spectra_preserves_batch_independence():
    x = torch.rand(3, 1, 1200)
    whole = lsm.log_spectra(x)
    for i in range(3):
        torch.testing.assert_close(whole[i:i+1], lsm.log_spectra(x[i:i+1]))
    assert whole.shape == (3, 5, 201)


def test_log_spectrum_matches_independent_numpy_formula():
    x = np.random.default_rng(5).random((3, 1200))
    blocks = np.lib.stride_tricks.sliding_window_view(x, 400, axis=-1)[:, ::200, :]
    power = np.abs(np.fft.rfft(blocks*(2*np.hanning(401)[:-1]), axis=-1))**2
    logs = np.log(np.maximum(power, 1e-6))
    expected = (logs-logs.min(-1, keepdims=True))/np.maximum(np.ptp(logs, axis=-1, keepdims=True), 1e-6)
    np.testing.assert_allclose(lsm.log_spectra(torch.tensor(x)).numpy(), expected, atol=1e-10)


@pytest.mark.parametrize("value", [0., .5, 1.])
def test_constant_inputs_have_finite_loss_and_gradient(value):
    x = torch.full((2, 1, 1200), value, requires_grad=True)
    a, b = lsm.spectral_loss(x, x.detach(), pairing="all_pairs")
    (a+b).backward()
    assert torch.isfinite(a+b) and torch.isfinite(x.grad).all()


def test_paper_matching_is_zero_for_identical_signal():
    x = torch.rand(2, 1, 1200)
    match, _ = lsm.spectral_loss(x, x, pairing="aligned")
    assert float(match) == pytest.approx(0., abs=1e-8)
    all_pairs, _ = lsm.spectral_loss(x, x, pairing="all_pairs")
    assert all_pairs > 0


def test_loss_aggregation_and_invalid_arguments():
    x, y = torch.rand(2, 1, 1200), torch.rand(2, 1, 1200)
    mean = lsm.spectral_loss(x, y)
    maximum = lsm.spectral_loss(x, y, aggregation="max")
    assert maximum[0] >= mean[0] and maximum[1] >= mean[1]
    with pytest.raises(ValueError):
        lsm.spectral_loss(x, y, pairing="wrong")


def test_psd_peak_tracks_real_sampling_rate_and_mmd():
    t = np.arange(1200)/40
    x = np.stack([.5+.4*np.sin(2*np.pi*1.2*t)]*3)
    acf, spec = lsm.features(x)
    assert acf.shape == (3, 200)
    assert spec.shape[0] == 3
    metrics = lsm.describe(x)
    assert metrics["dominant_bpm_median"] == pytest.approx(72, abs=1)
    assert lsm.mmd2(acf, acf, 1.) == pytest.approx(0., abs=1e-7)


def test_discriminator_optimizer_updates_d_not_generator():
    g, d = lsm.make_networks()
    fake = g(torch.randn(2, 1200)).detach()
    old_g = [p.detach().clone() for p in g.parameters()]
    old_d = [p.detach().clone() for p in d.parameters()]
    optimizer = torch.optim.Adam(d.parameters(), lr=5e-4)
    loss = d(fake).square().mean()+(d(torch.rand_like(fake))-1).square().mean()
    loss.backward(); optimizer.step()
    assert any(not torch.equal(a,b) for a,b in zip(old_d,d.parameters()))
    assert all(torch.equal(a,b) for a,b in zip(old_g,g.parameters()))


def test_network_parameter_counts_are_frozen_for_comparison():
    g, d = lsm.make_networks()
    assert sum(p.numel() for p in g.parameters()) == 117940
    assert sum(p.numel() for p in d.parameters()) == 692370


def test_auc_handles_ties_and_direction():
    from ml.audit_lsm_run import auc
    assert auc(np.ones(3), np.zeros(3)) == 1
    assert auc(np.zeros(3), np.ones(3)) == 0
    assert auc(np.ones(3), np.ones(3)) == .5


def test_generator_update_uses_training_bn_but_frozen_discriminator_weights():
    g, d = lsm.make_networks()
    d.eval()
    lsm.prepare_discriminator_for_generator(d)
    assert d.training
    assert all(not p.requires_grad for p in d.parameters())
    bn = next(m for m in d.modules() if isinstance(m, torch.nn.BatchNorm1d))
    previous = int(bn.num_batches_tracked)
    loss = (d(g(torch.randn(2,1200)))-1).square().mean()
    loss.backward()
    assert int(bn.num_batches_tracked) == previous+1
    assert all(p.grad is None for p in d.parameters())
    assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in g.parameters())
