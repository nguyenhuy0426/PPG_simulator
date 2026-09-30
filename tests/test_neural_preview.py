"""Real artifact integration checks, skipped when optional models are not installed."""
import json
import subprocess
import sys

import pytest

from core.neural_preview import DEFAULT_BUNDLE, NeuralPreview, export_preview, gaussian_preview, PREVIEW_MODES


def test_preview_module_does_not_import_torch_or_hardware():
    subprocess.run([sys.executable, "-c", "import sys; import core.neural_preview; "
                    "core.neural_preview.gaussian_preview(); "
                    "core.neural_preview.gaussian_preview(profile='Balanced'); "
                    "core.neural_preview.reference_preview(); "
                    "assert 'torch' not in sys.modules; assert 'core.signal_engine' not in sys.modules"], check=True)


@pytest.fixture(scope="module")
def backend():
    pytest.importorskip("torch")
    if not (DEFAULT_BUNDLE / "tcn_generator.ts").exists():
        pytest.skip("Run scripts/prepare_neural_preview.py to install audited model artifacts")
    return NeuralPreview()


def test_real_inference_is_repeatable_and_does_not_mutate_batchnorm(backend):
    torch = backend.torch
    before = {name: {key: value.clone() for key, value in model.named_buffers()}
              for name, model in backend.models.items()}
    first, second = backend.generate(42, 75), backend.generate(42, 75)
    assert first == second
    assert tuple(first) == PREVIEW_MODES
    assert first["TCN-FiLM"].samples != backend.generate(43, 75)["TCN-FiLM"].samples
    assert first["Gaussian (original)"] == gaussian_preview(75)
    with_notch = backend.generate(42, 75, "With notch")
    assert with_notch["TCN-FiLM"].condition[-1] == 1
    assert with_notch["TCN-FiLM"].samples != first["TCN-FiLM"].samples
    assert with_notch["LSM-GAN"].samples == first["LSM-GAN"].samples
    assert first["cWGAN-GP"].samples != backend.generate(43, 75)["cWGAN-GP"].samples
    assert first["LSM-GAN"].samples == backend.generate(42, 100)["LSM-GAN"].samples
    for name, model in backend.models.items():
        assert not model.training
        for key, value in model.named_buffers():
            assert torch.equal(value, before[name][key])


def test_native_timing_voltage_and_export(backend, tmp_path):
    np = backend.np
    for name, preview in backend.generate().items():
        a = np.asarray(preview.samples)
        assert len(a) == preview.native_fs * 30
        assert a[0, 0] == 0
        assert a[-1, 0] == pytest.approx(30 - 1 / preview.native_fs)
        np.testing.assert_allclose(np.diff(a[:, 0]), 1 / preview.native_fs, atol=1e-12)
        assert np.isfinite(a).all() and a[:, 1:].min() >= 1.5
        assert a[:, 1].max() <= 1.54500001 and a[:, 2].max() <= 1.52160001
        np.testing.assert_allclose(a[:, 2] - 1.5, .48 * (a[:, 1] - 1.5), atol=1e-12)
        file = tmp_path / (name + ".csv")
        export_preview(preview, file)
        np.testing.assert_allclose(np.loadtxt(file, delimiter=",", skiprows=1), a)
        metadata = json.loads(file.with_suffix(".json").read_text())
        assert metadata["model_sha256"] == preview.model_sha256
        assert metadata["same_shape_both_channels"]
        if name in ("cWGAN-GP", "Gaussian (original)", "Gaussian (fitted)"):
            assert preview.discriminator_score is None
        elif name == "LSM-GAN":
            assert 0 <= preview.discriminator_score <= 1
        else:
            assert np.isfinite(preview.discriminator_score)  # Wasserstein score, not probability


@pytest.mark.parametrize("seed,hr", [(-1, 75), (2**32, 75), (True, 75), (2, float("nan")), (2, 181)])
def test_invalid_requests(backend, seed, hr):
    with pytest.raises(ValueError):
        backend.generate(seed, hr)


def test_missing_bundle_is_actionable(backend, tmp_path):
    with pytest.raises(RuntimeError, match="prepare_neural_preview"):
        NeuralPreview(tmp_path)


def test_wrong_model_checksum_is_rejected(backend, tmp_path):
    manifest = json.loads((DEFAULT_BUNDLE / "manifest.json").read_text())
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / manifest["models"]["cwgan_generator"]["file"]).write_bytes(b"broken model")
    with pytest.raises(ValueError, match="checksum"):
        NeuralPreview(tmp_path)
