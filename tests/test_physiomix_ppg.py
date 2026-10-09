"""Train-only conditioning, genuine descriptor diversity, GPU guard and full frozen workflow."""
import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
pytest.importorskip("scipy")
pytest.importorskip("h5py")
pytest.importorskip("wfdb")

from ml.kaggle_multidomain import data, data_more, experiment, physio, stage_kernel
from ml.kaggle_multidomain.benchmark import Evaluator
from ml.kaggle_multidomain.train import ARMS

torch.set_num_threads(1)


def extended_pack():
    rows=[]
    rng=np.random.default_rng(10)
    domains=("bidmc", "perform_af", "perform_non_af", "perform_large", "wrist", "capnobase")
    for domain in domains:
        for split in (("external",) if domain == "capnobase" else ("train", "validation", "test")):
            for person in range(3):
                t=np.arange(1200)/40
                phase=rng.uniform(0, 6)
                wave=np.sin(2*np.pi*(1+.2*person)*t+phase)+.2*np.sin(4*np.pi*(1+.2*person)*t+phase)+.01*rng.normal(size=1200)
                rows.append((data.normalize(wave), f"{domain}:{split}:{person}", domain, split, f"{domain}:{split}:{person}", 0))
    pack={k:np.asarray(v) for k,v in zip(("signal", "subject", "domain", "split", "record", "start"), zip(*rows))}
    pack.update(rhythm_label=np.full(len(rows), -1), activity_label=np.full(len(rows), -1),
                reference_hr_bpm=np.full(len(rows), np.nan, dtype=np.float32))
    return pack


def save_pack(path, pack):
    path.mkdir()
    np.savez_compressed(path/"windows.npz", **pack)
    (path/"manifest.json").write_text(json.dumps(dict(protocol=data_more.PROTOCOL,
        windows_sha256=data.digest(path/"windows.npz"), limitations=[])))


def test_conditions_fit_and_sample_training_only():
    pack=extended_pack()
    before=physio.Conditions(pack)
    altered={k:v.copy() for k,v in pack.items()}
    altered["signal"][altered["split"] != "train"] *= .01
    after=physio.Conditions(altered)
    np.testing.assert_array_equal(before.bank, after.bank)
    np.testing.assert_array_equal(before.draw(9, 24), after.draw(9, 24))
    assert before.bank.shape[1] == 8
    with pytest.raises(ValueError, match="training-only"):
        before.for_ids(np.flatnonzero(pack["split"] == "test")[:1])
    assert "capnobase" not in before.domains


def test_filtered_prior_and_diversity_have_finite_gradients():
    torch.manual_seed(2)
    conditions=physio.Conditions(extended_pack())
    model=physio.PhysioMix(8, conditions.center, conditions.scale)
    c=torch.tensor(conditions.draw(7, 4))
    a=model(torch.randn(4, 1200), c)
    b=model(torch.randn(4, 1200), c)
    assert a.shape == (4, 1, 1200) and a.min() >= 0 and a.max() <= 1
    assert not torch.allclose(physio.descriptors(a), physio.descriptors(b))
    power=torch.fft.rfft(a-a.mean(-1, keepdim=True)).abs().square()
    f=torch.fft.rfftfreq(1200, 1/40)
    assert float((power[:, :, f > 5].sum()/power.sum()).detach()) < 1e-10
    real=torch.tensor(extended_pack()["signal"][:4, None])
    value=physio.joint_loss(a, real)+experiment.distribution_loss(a, real)
    value.backward()
    assert all(p.grad is None or p.grad.isfinite().all() for p in model.parameters())


def test_joint_loss_detects_collapse_and_is_unpaired():
    real=torch.tensor(extended_pack()["signal"][:6, None])
    matched=physio.joint_loss(real, real.flip(0))
    collapsed=physio.joint_loss(real[:1].expand_as(real), real)
    assert matched.item() == pytest.approx(0, abs=1e-6)
    assert collapsed.item() > matched.item()+.01
    x=real.clone().requires_grad_()
    physio.joint_loss(x, real.flip(0)).backward()
    assert x.grad.isfinite().all()


def test_capno_holdout_and_hash_guards(tmp_path):
    pack=extended_pack();save_pack(tmp_path/"good", pack)
    loaded,_=data_more.load_input(tmp_path/"good")
    assert set(loaded["split"][loaded["domain"] == "capnobase"]) == {"external"}
    bad={k:v.copy() for k,v in pack.items()};bad["split"][bad["domain"] == "capnobase"] = "train"
    save_pack(tmp_path/"bad", bad)
    with pytest.raises(ValueError, match="external-only"):
        data_more.load_input(tmp_path/"bad")
    (tmp_path/"good"/"windows.npz").write_bytes(b"damaged")
    with pytest.raises(ValueError, match="checksum"):
        data_more.load_input(tmp_path/"good")


def test_missing_padding_and_gaps_are_not_interpolated():
    t=np.arange(256*90)/256
    raw=np.sin(2*np.pi*1.3*t)
    raw[256*31:256*32] = np.nan
    padded=np.r_[raw, np.full(234, np.nan)]
    clips,bad=data_more.finite_windows(padded, 256)
    assert [start for start,_ in clips] == [0, 32*40]
    assert bad["nonfinite_samples_excluded"] == 490
    assert all(np.isfinite(wave).all() for _,wave in clips)
    for fs in (0, np.nan, 10001):
        with pytest.raises(ValueError, match="sampling"):
            data_more.finite_windows(raw, fs)


def test_two_t4_guard_and_staged_spawn_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda _: "Tesla T4")
    with pytest.raises(RuntimeError, match="Two T4"):
        experiment.main(["--input-root", str(tmp_path), "--output", str(tmp_path/"run")])
    staged=stage_kernel.stage(tmp_path/"stage", "physio_train", steps=6000)
    script=(staged/"run.py").read_text()
    assert script.startswith("if __name__ == '__main__':")
    compile(script, "run.py", "exec")
    metadata=json.loads((staged/"kernel-metadata.json").read_text())
    assert metadata["is_private"] and metadata["kernel_sources"] == ["charlesday2612/ppg-physiomix-data-v1"]
    manifest=json.loads((staged/"source_manifest.json").read_text())
    root=Path(stage_kernel.__file__).resolve().parents[2]
    assert all(data.digest(root/name) == sha for name,sha in manifest["files"].items())


def test_clean_diffusion_and_ema_update():
    cond=physio.Conditions(extended_pack()); model=physio.CleanDenoiser(8)
    real=torch.tensor(extended_pack()["signal"][:4, None]); c=torch.tensor(cond.draw(7, 4))
    loss=physio.clean_diffusion_loss(model, real, c)
    loss.backward()
    assert loss.isfinite() and all(p.grad is None or p.grad.isfinite().all() for p in model.parameters())
    ema=physio.ema_model(model)
    with torch.no_grad(): next(model.parameters()).add_(1)
    original=next(ema.parameters()).clone()
    physio.update_ema(ema, model, decay=.5)
    torch.testing.assert_close(next(ema.parameters()), original+.5)
    samples=physio.draw(ema, torch.randn(4, 1200), c, diffusion=True, sample_steps=4)
    assert samples.isfinite().all() and samples.shape == real.shape


def test_full_validation_pilot_freeze_and_benchmark(tmp_path):
    save_pack(tmp_path/"input", extended_pack())
    output=tmp_path/"experiment"
    experiment.main(["--input-root", str(tmp_path/"input"), "--output", str(output), "--allow-cpu",
                     "--steps", "16", "--pilot-steps", "16", "--batch", "4", "--interval", "16",
                     "--seeds", "42", "--eval-samples", "8", "--bootstrap", "0"])
    complete=json.loads((output/"COMPLETE.json").read_text())
    assert complete["trained_runs"] == 7 and complete["pilot_runs"] == 4
    frozen=json.loads((output/"FROZEN_PROTOCOL.json").read_text())
    results=json.loads((output/"benchmark"/"results.json").read_text())["models"]
    assert set(frozen["arms"]) == set(ARMS) | {r["arm"] for r in results if r["arm"].startswith("physio")}
    for result in results:
        assert "capnobase" in result["external"] and "wrist" in result["test"]
        assert result["latency"]["median_ms"] > 0
        if "stability" in result and "diffusion" not in result["arm"]:
            assert result["stability"]["r1_updates"] == 1
        assert result["diagnostics"]["finite"]
    assert (output/"FROZEN_PROTOCOL.json").stat().st_mtime <= (output/"benchmark"/"results.json").stat().st_mtime
    for name in ("REPORT_VI.md", "domain_benchmark.png", "learning_and_stability.png", "waveforms_and_spectra.png"):
        assert (output/name).stat().st_size > 100
