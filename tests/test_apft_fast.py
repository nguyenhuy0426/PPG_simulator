"""core.apft_fast: the faster APFT runtime must sample what PhysiGPT.integrate samples, load the same weights, and
give a valid window when quantised. Tiny random network (every weight random, so the zero-initialised flow-head
outputs do not hide a mistake)."""
from dataclasses import replace

import pytest
import torch

from core import apft_fast
from core.apft_network import CONFIGS, PhysiGPT


def tiny(seed=0):
    torch.manual_seed(seed)
    model = PhysiGPT(replace(CONFIGS["tiny"], hr_cond=True))
    with torch.no_grad():
        for p in model.parameters():
            p.normal_(0, .2)
    return model.eval()


def checkpoint(tmp_path, model):
    path = tmp_path / "generator.pt"
    torch.save(dict(config="tiny", hr_cond=True, model=model.state_dict()), path)
    return path


def test_precomputed_flow_head_samples_the_same_windows():
    model = tiny()
    with torch.inference_mode():
        ref = model.generate(3, steps=16, seed=7, hr=torch.tensor([60., 90., 140.]))
        fast = apft_fast.fast(tiny()).generate(3, steps=16, seed=7, hr=torch.tensor([60., 90., 140.]))
    assert fast.shape == (3, 1200)
    torch.testing.assert_close(fast, ref, rtol=0, atol=1e-4)


def test_precompute_handles_other_step_counts_and_keeps_the_training_path():
    model, fast = tiny(1), apft_fast.fast(tiny(1))
    h, x = torch.randn(2, model.cfg.dim), torch.randn(2, model.cfg.patch)
    with torch.inference_mode():
        for steps in (1, 4, 32):
            torch.testing.assert_close(fast.integrate(x, h, steps), model.integrate(x, h, steps), rtol=0, atol=1e-5)
    # an explicit flow (adversarial fine-tuning's checkpointed call) still goes through the original integrator
    calls = []
    fast.integrate(x, h, 2, flow=lambda *a: calls.append(1) or torch.zeros(2, model.cfg.patch))
    assert len(calls) == 3


def test_load_skips_the_random_init_but_not_the_weights(tmp_path):
    model = tiny(2)
    loaded = apft_fast.load(checkpoint(tmp_path, model))
    for (name, a), (_, b) in zip(model.state_dict().items(), loaded.state_dict().items()):
        assert torch.equal(a, b), name
    assert torch.equal(loaded.cos, model.cos) and torch.equal(loaded.sin, model.sin)
    assert not loaded.training and all(p.device.type == "cpu" for p in loaded.parameters())


def test_int8_model_gives_a_valid_window(tmp_path):
    q = apft_fast.fast(apft_fast.quantize(apft_fast.load(checkpoint(tmp_path, tiny(3)))))
    assert isinstance(q.embed, torch.nn.Linear)              # left in float: sample_patches reads its dtype
    assert type(q.flow.outp).__module__.startswith("torch.ao.nn.quantized")
    with torch.inference_mode():
        wave = q.generate(2, steps=16, seed=1, hr=torch.tensor([70., 120.]))
    assert wave.shape == (2, 1200) and torch.isfinite(wave).all()
    assert float(wave.min()) == pytest.approx(0) and float(wave.max()) == pytest.approx(1)
