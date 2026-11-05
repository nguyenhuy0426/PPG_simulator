"""PSF-GAN (pure_gan.py), the in-kernel evaluation (kernel_eval.py), the puregan kernel and the key/value cache of the
physiGPT sampler, on CPU. They prove the code paths, nothing about realism."""
import json
from dataclasses import replace

import numpy as np
import pytest
import torch

from ml.kaggle_physigpt import kernel_eval, mimic_wdb as mw, pure_gan as pg, stage as st, train as tr
from ml.kaggle_physigpt.model import CONFIGS, PhysiGPT
from test_physigpt import _pulse_set


def people_shard(root, per=30):
    """40 training and 6 held-out records of pulse windows (the judge needs people on both sides)."""
    writer = mw.ShardWriter(root)
    for valid, records, seed in ((False, range(3000000, 3000040), 0), (True, range(3900000, 3900006), 100)):
        for record in records:
            x = _pulse_set(seed+record % 1000, per)
            writer.add(x, record, [("s", i) for i in range(per)], valid, *mw.rate_features(x))
    writer.flush()
    tr.save_json(root/"manifest.json", dict(protocol=mw.PROTOCOL, record_range=[0, 0], windows=46*per,
                                            chunks=writer.chunks))


def test_view_keeps_the_pulse_band_and_removes_the_rest():
    t = torch.arange(pg.RECORD)/pg.FS
    mask = pg.band_mask()
    inside, outside = torch.sin(2*np.pi*2.*t), torch.sin(2*np.pi*15.*t)+3*t/t[-1]
    x = pg.view(torch.stack((inside, inside+outside)), mask)
    assert x.shape == (2, pg.WINDOW) and float(x.min()) == 0 and float(x.max()) == 1
    assert torch.corrcoef(x)[0, 1] > .99      # the 15 Hz tone and the ramp are gone


def test_excitation_runs_at_the_asked_heart_rate():
    torch.manual_seed(0)
    g = pg.SourceFilterGenerator(hr_cond=True, **pg.CONFIGS["tiny"])
    hr = torch.tensor([48., 75., 132.])
    source, bpm = g.excitation(g.style(torch.randn(3, g.latent), hr), hr)
    spectrum = torch.fft.rfft(source[:, 0], dim=1).abs()
    freq = torch.fft.rfftfreq(pg.RECORD, 1/pg.FS)
    np.testing.assert_allclose(60*freq[spectrum.argmax(1)].numpy(), hr.numpy(), atol=60*pg.FS/pg.RECORD)
    torch.testing.assert_close(bpm, hr)


def test_device_windows_return_the_stored_uint16_values(tmp_path):
    people_shard(tmp_path/"s", per=4)
    data = tr.Windows([str(tmp_path/"s")])
    store = pg.DeviceWindows(data, 0, 1, torch.device("cpu"), 0.)
    store.store[0, :3] = torch.tensor(np.array([0, 40000, 65535], np.uint16).view(np.int16))
    store.n = 1
    x = store.draw(2, None)
    np.testing.assert_allclose(x[0, :3].numpy(), [0., 40000/65535, 1.], rtol=1e-6)


def test_two_process_run_selects_releases_resumes_and_samples(tmp_path):
    tr.synthetic_shard(tmp_path/"shard")
    common = ["--data", str(tmp_path/"shard"), "--config", "tiny", "--batch", "4", "--eval-every", "2",
              "--log-every", "1", "--cpu", "--hr-cond", "--port", "29561", "--patience", "0"]
    pg.main(common+["--output", str(tmp_path/"run"), "--steps", "4", "--cpu-world", "2"])
    summary = json.loads((tmp_path/"run"/"gan_summary.json").read_text())
    assert summary["steps"] == 4 and summary["stop_reason"] == "steps" and summary["hr_cond"]
    lines = [json.loads(l) for l in (tmp_path/"run"/"metrics.jsonl").read_text().splitlines()]
    assert [l["step"] for l in lines if "select" in l] == [0, 2, 4]
    assert all(np.isfinite(l["loss_d"]) and np.isfinite(l["fm"]) for l in lines if "loss_d" in l)
    pg.main(common+["--output", str(tmp_path/"run"), "--steps", "6", "--resume", str(tmp_path/"run"/"last.pt")])
    assert json.loads((tmp_path/"run"/"gan_summary.json").read_text())["steps"] == 6
    x = pg.generate_release(tmp_path/"run"/"gan_release.pt", 5, 0, "cpu")
    assert x.shape == (5, pg.WINDOW) and np.isfinite(x).all() and x.min() >= 0 and x.max() <= 1
    np.testing.assert_array_equal(x, pg.generate_release(tmp_path/"run"/"gan_release.pt", 5, 0, "cpu"))


def test_non_finite_losses_roll_back_instead_of_killing_the_run(tmp_path, monkeypatch, capsys):
    """v1 kernel: a critic loss that stayed non-finite drove both GradScalers to 0 and every later step was NaN."""
    tr.synthetic_shard(tmp_path/"shard")
    calls, clean = [0], pg.d_loss

    def flaky(real_out, fake_out):   # NaN in critic calls 3-5 and from 9 on
        calls[0] += 1
        loss = clean(real_out, fake_out)
        return loss*float("nan") if 3 <= calls[0] <= 5 or calls[0] >= 9 else loss

    monkeypatch.setattr(pg, "d_loss", flaky)
    common = ["--data", str(tmp_path/"shard"), "--config", "tiny", "--batch", "4", "--eval-every", "2",
              "--log-every", "1", "--cpu", "--hr-cond", "--patience", "0", "--nan-patience", "3",
              "--max-rollbacks", "1", "--steps", "40", "--output", str(tmp_path/"run")]
    pg.main(common)
    summary = json.loads((tmp_path/"run"/"gan_summary.json").read_text())
    events = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.startswith('{"step"') and '"rollback":' in l]
    assert [e["rollback"] for e in events] == [1, 2] and events[0]["lr_factor"] == .5
    assert summary["stop_reason"] == "nonfinite" and summary["rollbacks"] == 2 and summary["steps"] < 40
    x = pg.generate_release(tmp_path/"run"/"gan_release.pt", 3, 0, "cpu")
    assert np.isfinite(x).all()


def test_kernel_evaluation_reports_percentages_against_real_people(tmp_path):
    people_shard(tmp_path/"shard")
    sizes = dict(fit=60, inner=20, eval=40)
    windows = kernel_eval.generated_sets(lambda n, seed: _pulse_set(seed % 1000, n), sizes)
    summary = kernel_eval.evaluate(windows, [str(tmp_path/"shard")], tmp_path/"eval", sizes=sizes, threads=2)
    assert summary["verdict"] in ("pass", "fail", "inconclusive")
    assert 0 <= summary["mean_similarity_percent"] <= 100 and 0 <= summary["real_vs_real_percent"] <= 100
    assert len(summary["feature_percent"]) == 22 and (tmp_path/"eval"/"target.json").exists()
    assert json.loads((tmp_path/"eval"/"summary.json").read_text()) == summary


def test_puregan_and_gan_kernels_train_then_evaluate(tmp_path):
    common = ["--owner", "charlesday2612", "--source-owner", "halovie2412", "--shards", "1", "2", "--solos", "0",
              "--datasets", "ppg-physigpt-shard0-data-v1"]
    st.main([str(tmp_path/"p"), "puregan", *common, "--tag", "psf-gan", "--gan-extra=--hr-cond"])
    meta = json.loads((tmp_path/"p"/"kernel-metadata.json").read_text())
    run = (tmp_path/"p"/"run.py").read_text()
    assert meta["id"] == "charlesday2612/ppg-physigpt-psf-gan-v1" and meta["enable_gpu"]
    assert all(s.startswith("halovie2412/") for s in meta["kernel_sources"])
    assert meta["dataset_sources"] == ["halovie2412/ppg-physigpt-shard0-data-v1"]
    assert "'--hr-cond'" in run and "generate_release(release" in run and "evaluate(generated_sets(sample)" in run
    st.main([str(tmp_path/"g"), "gan", *common, "--config", "large", "--from-slug", "ppg-physigpt-decay0-large-v1",
             "--tag", "apft-gan-v3", "--strict-seeds"])
    run = (tmp_path/"g"/"run.py").read_text()
    assert "evaluate(generated_sets(sample), data, '/kaggle/working/eval', 'cuda', [])" in run


def test_cached_sampler_draws_the_windows_of_the_uncached_one():
    torch.manual_seed(0)
    model = PhysiGPT(replace(CONFIGS["tiny"], hr_cond=True)).eval()
    with torch.no_grad():
        for p in model.parameters():
            p.add_(.05*torch.randn_like(p))   # the zero-initialised heads would hide a mismatch
    hr = torch.tensor([60., 90., 140.])
    cached = model.generate(3, steps=3, seed=5, hr=hr)
    g, d = torch.Generator().manual_seed(5), torch.zeros(3, dtype=torch.long)
    patches = torch.zeros(3, 30, 40)
    with torch.no_grad():
        for i in range(30):
            patches[:, i] = model.sample_patch(model.hidden(patches[:, :i+1], d, hr)[:, i], 3, g)
    x = patches.reshape(3, -1)
    x = (x-x.min(1, keepdim=True).values)/(x.max(1, keepdim=True).values-x.min(1, keepdim=True).values)
    torch.testing.assert_close(cached, x, atol=1e-5, rtol=1e-5)
