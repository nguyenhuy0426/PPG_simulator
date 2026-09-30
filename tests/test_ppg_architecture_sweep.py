import importlib

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
pytest.importorskip("scipy")

sweep = importlib.import_module("ml.kaggle_arch.train_architectures")


@pytest.mark.parametrize("name", sweep.ARCHITECTURES)
def test_architecture_shapes_bounds_and_gradients(name):
    generator, critic = sweep.make_networks(name)
    z = torch.randn(3, sweep.LATENT_DIM, requires_grad=True)
    condition = torch.rand(3, sweep.N_CONDITIONS)
    condition[:, -1] = torch.tensor([0., 1., 1.])
    pulse = generator(z, condition)
    score, prediction = critic(pulse, condition)
    assert pulse.shape == (3, sweep.POINTS)
    assert score.shape == (3,)
    assert prediction.shape == (3, sweep.N_CONDITIONS)
    assert torch.isfinite(pulse).all() and torch.isfinite(score).all()
    assert pulse.min() >= 0 and pulse.max() <= 1.000001
    torch.testing.assert_close(pulse[:, 0], torch.zeros(3), atol=0, rtol=0)
    torch.testing.assert_close(pulse[:, -1], torch.zeros(3), atol=0, rtol=0)
    (score.mean()+pulse.mean()).backward()
    assert z.grad is not None and torch.isfinite(z.grad).all()


def test_auxiliary_head_does_not_copy_supplied_condition():
    _, critic = sweep.make_networks("resnet_film_projection")
    pulse = torch.rand(4, sweep.POINTS)
    first = torch.zeros(4, sweep.N_CONDITIONS)
    second = torch.ones(4, sweep.N_CONDITIONS)
    score_a, aux_a = critic(pulse, first)
    score_b, aux_b = critic(pulse, second)
    assert not torch.equal(score_a, score_b)
    torch.testing.assert_close(aux_a, aux_b)


def test_losses_are_finite_and_backpropagate():
    condition = torch.tensor([[.4, .2, .45, .60, .2, .35, 1.],
                              [.5, .25, 0., 0., 0., 0., 0.]])
    fake = torch.rand(2, sweep.POINTS, requires_grad=True)
    real = torch.rand(2, sweep.POINTS)
    loss = (sweep.morphology_loss(fake, condition)+sweep.spectral_loss(fake, real)+
            sweep.derivative_loss(fake, real))
    assert torch.isfinite(loss)
    loss.backward()
    assert fake.grad is not None and torch.isfinite(fake.grad).all()


def test_gradient_penalty_and_balanced_batch():
    _, critic = sweep.make_networks("resnet_film_projection")
    condition = torch.rand(8, sweep.N_CONDITIONS)
    real, fake = torch.rand(8, sweep.POINTS), torch.rand(8, sweep.POINTS)
    rng = torch.Generator().manual_seed(1)
    penalty = sweep.gradient_penalty(critic, real, fake, condition, rng)
    assert torch.isfinite(penalty) and penalty >= 0
    indices = sweep.balanced_batch(torch.tensor([1, 3]), torch.tensor([2, 4]), 8, rng)
    assert sum(int(value) in {1, 3} for value in indices[:4]) == 4
    assert sum(int(value) in {2, 4} for value in indices[4:]) == 4


def test_frozen_prepared_data_and_stratification():
    x, condition, masks = sweep.load_prepared("ml/runs/kaggle-v1/ppg_run/prepared.npz")
    assert x.shape[1] == sweep.POINTS
    assert sum(mask.sum() for mask in masks.values()) == len(x)
    selected = sweep.stratified_indices(masks["validation"], condition, maximum_per_class=32)
    assert (condition[selected, -1] > .5).sum() == 32
    assert (condition[selected, -1] <= .5).sum() == 32


def test_metrics_reward_reference_more_than_flattened_shape():
    x, condition, masks = sweep.load_prepared("ml/runs/kaggle-v1/ppg_run/prepared.npz")
    indices = sweep.stratified_indices(masks["validation"], condition, maximum_per_class=16)
    real, requested = x[indices], condition[indices]
    bank = x[masks["train"]][:64]
    reference = sweep.morphology_metrics(real, requested, real, bank)
    flattened = np.repeat(np.linspace(0, 1, sweep.POINTS, dtype=np.float32)[None], len(real), 0)
    flattened[:, -1] = 0
    distorted = sweep.morphology_metrics(flattened, requested, real, bank)
    assert reference["primary_morphology_score"] < distorted["primary_morphology_score"]
    assert reference["mean_log_spectrum_rmse"] < distorted["mean_log_spectrum_rmse"]


def test_one_optimizer_step_changes_generator_only():
    generator, critic = sweep.make_networks("resnet_film_projection")
    optimizer = torch.optim.Adam(generator.parameters(), 1e-4)
    condition = torch.rand(4, sweep.N_CONDITIONS)
    before_g = [parameter.detach().clone() for parameter in generator.parameters()]
    before_d = [parameter.detach().clone() for parameter in critic.parameters()]
    fake = generator(torch.randn(4, sweep.LATENT_DIM), condition)
    score, auxiliary = critic(fake, condition)
    loss = -score.mean()+sweep.auxiliary_loss(auxiliary, condition)
    optimizer.zero_grad(); loss.backward(); optimizer.step()
    assert any(not torch.equal(left, right) for left, right in zip(before_g, generator.parameters()))
    assert all(torch.equal(left, right) for left, right in zip(before_d, critic.parameters()))
