"""Offline patient isolation, weighting, numerical behavior, and complete training smoke."""
import json

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
pytest.importorskip("scipy")

from ml.kaggle_multidomain import data, models, train
from ml.kaggle_multidomain.benchmark import Evaluator, morphology

torch.set_num_threads(1)


def toy_pack():
    rows = []
    rng = np.random.default_rng(37)
    for domain in ("bidmc", "perform_large", "perform_af", "perform_non_af", "ptt_sit", "ptt_walk", "ptt_run"):
        splits = ("external",) if domain.startswith("ptt") else ("train", "validation", "test")
        for split in splits:
            for person in range(3):
                x = np.sin(np.arange(1200)/40*2*np.pi*(.9+.1*person)+rng.uniform(0, 6))+.01*rng.normal(size=1200)
                rows.append((data.normalize(x), f"{domain}:{split}:{person}", domain, split, f"{domain}:{split}:{person}", 0))
    return {k: np.asarray(v) for k, v in zip(("signal", "subject", "domain", "split", "record", "start"), zip(*rows))}


def test_patient_identity_and_repeatable_split():
    assert data.patient_id({"id": "s00946"}, True) == data.patient_id({"subj_id": "p000946"})
    patients = [f"p{i}" for i in range(20)]
    a, b = data.split_patients(patients), data.split_patients(patients[::-1])
    assert a == b and set(a.values()) == {"train", "validation", "test"}
    with pytest.raises(ValueError):
        data.patient_id({"subj_id": "unknown"})


def test_large_nested_record_identity_joins_matched_af_patient():
    fix = {"mimic_details": {"subj_id": "3462211", "file": "3462211_0001"}}
    aliases = data.record_aliases([{"fix": {"subj_id": "p000946", "files": "3462211_0001"}}])
    assert data.patient_id(fix) == "mimic-record:3462211"
    assert data.patient_id(fix, aliases=aliases) == "mimic:946"
    with pytest.raises(ValueError, match="Conflicting"):
        data.record_aliases([{"fix": {"subj_id": p, "files": "3462211_0001"}} for p in ("p000946", "p000947")])


def test_pack_rejects_leakage_and_duplicate_waveforms():
    pack = toy_pack(); data.validate_pack(pack)
    pack["subject"][3] = pack["subject"][0]
    with pytest.raises(ValueError, match="leakage"):
        data.validate_pack(pack)
    pack = toy_pack(); pack["signal"][1] = pack["signal"][0]
    with pytest.raises(ValueError, match="Duplicate"):
        data.validate_pack(pack)


def test_domain_and_subject_weighting_despite_unequal_windows():
    pack = toy_pack()
    ids = np.r_[np.arange(len(pack["signal"])), np.repeat(0, 100)]
    pack = {k: v[ids] for k, v in pack.items()}
    ix, weights = data.balanced_pool(pack, "train")
    for domain in ("bidmc", "perform_large", "perform_af", "perform_non_af"):
        mask = pack["domain"][ix] == domain
        assert weights[mask].sum() == pytest.approx(.25)
        for subject in np.unique(pack["subject"][ix][mask]):
            assert weights[pack["subject"][ix] == subject].sum() == pytest.approx(1/12)


def test_resampling_rejects_bad_data_and_preserves_frequency():
    t = np.arange(125*60)/125
    accepted, rejected = data.windows(np.sin(2*np.pi*1.2*t), 125)
    assert len(accepted) == 2 and not rejected
    assert all(w.shape == (1200,) for _, w in accepted)
    assert morphology(np.stack([w for _, w in accepted]))[:, 0].mean() == pytest.approx(72, abs=2)
    for x in (np.zeros(7500), np.full(7500, np.nan)):
        assert not data.windows(x, 125)[0]
    with pytest.raises(ValueError):
        data.windows(t, 0)


def test_distribution_loss_is_unpaired_and_has_finite_gradient():
    real = torch.rand(3, 1, 1200)
    fake = real.clone().requires_grad_()
    value = models.distribution_loss(fake, real[[2, 0, 1]])
    assert value.item() == pytest.approx(0, abs=1e-6)
    value.backward()
    assert torch.isfinite(fake.grad).all()
    assert models.distribution_loss(torch.zeros_like(real), real).isfinite()


@pytest.mark.parametrize("arm", ["tcn_multi", "hybrid_multi", "diffusion_multi"])
def test_new_models_train_with_finite_gradients(arm):
    g, d = models.networks(arm)
    real = torch.rand(2, 1, 1200)
    if d is None:
        loss = models.diffusion_loss(g, real)
    else:
        fake = g(torch.randn(2, 1200))
        assert fake.shape == real.shape and fake.min() >= 0 and fake.max() <= 1
        loss = d(fake).mean()+models.distribution_loss(fake, real)
    loss.backward()
    assert all(torch.isfinite(p.grad).all() for p in g.parameters() if p.grad is not None)
    assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in g.parameters())


def test_evaluation_fit_does_not_depend_on_test_signals():
    pack = toy_pack(); a = Evaluator(pack, 8)
    changed = {k: v.copy() for k, v in pack.items()}
    mask = np.isin(changed["split"], ["test", "external"])
    changed["signal"][mask] = 1-changed["signal"][mask]
    b = Evaluator(changed, 8)
    assert a.bandwidths == b.bandwidths
    assert a.validation(pack["signal"][:8])[0] == b.validation(pack["signal"][:8])[0]


def test_end_to_end_all_arms_and_exports(tmp_path):
    source = tmp_path/"input"; source.mkdir()
    np.savez_compressed(source/"windows.npz", **toy_pack())
    (source/"manifest.json").write_text(json.dumps(dict(protocol="ppg_multidomain_v1", windows_sha256=data.digest(source/"windows.npz"))))
    output = tmp_path/"run"
    train.main(["--input-root", str(source), "--output", str(output), "--steps", "2", "--batch", "2",
                "--seeds", "42", "--interval", "2", "--eval-samples", "8", "--bootstrap", "2", "--allow-cpu"])
    complete = json.loads((output/"COMPLETE.json").read_text())
    assert complete["trained_runs"] == 5
    results = json.loads((output/"results.json").read_text())["models"]
    assert len(results) == 5
    assert all(len(r["test"]) == 4 and len(r["external"]) == 3 for r in results)
    g = torch.jit.load(str(output/"hybrid_multi_seed42/generator_cpu.ts"))
    assert g(torch.randn(3, 1200)).shape == (3, 1, 1200)
    assert len(list(output.rglob("last_training_state.pt"))) == 5
