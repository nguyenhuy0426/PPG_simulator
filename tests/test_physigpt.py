import json

import numpy as np
import pytest
import torch

from ml.kaggle_physigpt import mimic_wdb as mw
from ml.kaggle_physigpt import train as tr
from ml.kaggle_physigpt.model import CONFIGS, PhysiGPT

BASE = "https://fake/"


def pulse(frames, bpm=72., seed=0):
    t = np.arange(frames)/mw.SRC_FS
    phase = 2*np.pi*bpm/60*t
    rng = np.random.default_rng(seed)
    return np.sin(phase)+.4*np.sin(2*phase+.6)+.02*rng.standard_normal(frames)


def fake_record(store, rec, segments):
    """segments: list of (name, frames, fmt, signal names, pleth array or None)."""
    root = f"{BASE}3{rec[1]}/{rec}/"
    lines = [f"{rec}/{len(segments)} 3 125 {sum(s[1] for s in segments)}"]+[f"{s[0]} {s[1]}" for s in segments]
    store[root+rec+".hea"] = "\n".join(lines).encode()
    for name, frames, fmt, names, pleth in segments:
        if name == "~":
            continue
        width, dtype = mw.FORMATS[fmt]
        data = np.zeros((frames, len(names)), dtype)
        if pleth is not None:
            lo, hi = (1, 255) if fmt == "80" else (-500, 500)
            data[:, names.index("PLETH")] = np.round(lo+(hi-lo)*(pleth-pleth.min())/np.ptp(pleth)).astype(dtype)
        store[root+name+".dat"] = data.tobytes()
        sig = "\n".join(f"{name}.dat {fmt} 100/NU 8 0 0 0 0 {n}" for n in names)
        store[root+name+".hea"] = f"{name} {len(names)} 125 {frames}\n{sig}".encode()
    return f"3{rec[1]}/{rec}/"


def fetcher(store, log=None):
    def fetch(url, byte_range=None):
        data = store[url]
        if log is not None:
            log.append((url, byte_range))
        return data if byte_range is None else data[byte_range[0]:byte_range[1]]
    return fetch


def test_record_windows_use_only_pleth_segments_and_drop_invalid_samples():
    store, log = {}, []
    frames = 25*mw.WINDOW+300
    bad = pulse(frames, seed=1)
    name = fake_record(store, "3000001", [
        ("3000001_0001", frames, "80", ["II", "PLETH", "ABP"], pulse(frames)),
        ("~", 500, None, [], None),
        ("3000001_0002", 4*mw.WINDOW, "80", ["II", "ABP"], None),
        ("3000001_0003", frames, "16", ["RESP", "PLETH"], bad),
        ("3000001_0004", 2000, "80", ["PLETH"], pulse(2000))])          # shorter than one window: never fetched
    raw = np.frombuffer(store[f"{BASE}30/3000001/3000001_0003.dat"], "<i2").reshape(-1, 2).copy()
    raw[5*mw.WINDOW+100, 1] = mw.INVALID["16"]                          # one invalid sample in window 5 of 0003
    store[f"{BASE}30/3000001/3000001_0003.dat"] = raw.tobytes()
    signal, rows, counts = mw.process_record(name, cap=1000, fetch=fetcher(store, log), base=BASE)
    assert signal.shape == (49, mw.LENGTH) and counts["windows"] == 49 and counts["invalid"] == 1
    assert counts["segments_pleth"] == 2 and counts["segments_skipped"] == 1
    assert {seg for seg, _ in rows} == {"3000001_0001", "3000001_0003"}
    assert (signal.min(1) == 0).all() and np.allclose(signal.max(1), 1)
    assert not any("0004" in url for url, _ in log)
    assert all(r is not None for url, r in log if url.endswith(".dat"))   # only byte ranges of .dat files
    # The filtered window matches the v3 view of the same 30 s cut from the clean record (margins hide edges).
    w = [i for i, (seg, s) in enumerate(rows) if seg == "3000001_0001" and s == 12*mw.WINDOW][0]
    assert np.corrcoef(signal[w][100:-100], np.sin(2*np.pi*72/60*(12*mw.WINDOW/125+np.arange(1200)/40))[100:-100]
                       )[0, 1] > .9
    capped, rows2, _ = mw.process_record(name, cap=7, fetch=fetcher(store), base=BASE)
    assert len(capped) == len(rows2) == 7
    again, rows3, _ = mw.process_record(name, cap=7, fetch=fetcher(store), base=BASE)
    assert rows3 == rows2 and np.array_equal(again, capped)


def test_shards_take_disjoint_record_ranges_and_skip_excluded_records(tmp_path):
    store, names = {}, []
    for i in range(6):
        rec = f"30000{i+10}"
        names.append(fake_record(store, rec, [(rec+"_0001", 3*mw.WINDOW, "80", ["PLETH"], pulse(3*mw.WINDOW, 60+5*i))]))
    order = mw.record_order(names)
    excluded = mw.record_number(order[1])
    a = mw.build_shard(tmp_path/"a", 0, 3, cap=10, target=10**6, hours=1, workers=2, records=names,
                       exclude=[excluded], fetch=fetcher(store), base=BASE)
    b = mw.build_shard(tmp_path/"b", a["next_record"], 6, cap=10, target=10**6, hours=1, workers=2, records=names,
                       fetch=fetcher(store), base=BASE)
    assert a["record_range"] == [0, 3] and b["record_range"] == [3, 6]
    assert a["counts"]["excluded_records"] == 1 and a["windows"] == 6 and b["windows"] == 9
    meta = np.concatenate([np.load(tmp_path/d/"chunk_0000_meta.npy") for d in ("a", "b")])
    assert int(excluded) not in meta["record"] and len(set(meta["record"])) == 5
    data = tr.Windows([tmp_path])
    assert len(data.train)+len(data.valid) == 15
    rows = data.rows(np.array([14, 0, 7]))
    assert rows.dtype == np.uint16 and rows.shape == (3, mw.LENGTH)
    assert np.array_equal(rows[1], np.load(tmp_path/"a"/"chunk_0000_signal.npy")[0])


def test_hidden_state_is_causal_over_patches():
    torch.manual_seed(0)
    model = PhysiGPT(CONFIGS["tiny"]).eval()
    x = torch.rand(2, 30, 40)
    domain = torch.zeros(2, dtype=torch.long)
    h = model.hidden(x, domain)
    y = x.clone()
    y[:, 10] = torch.rand(2, 40)
    g = model.hidden(y, domain)
    assert torch.allclose(h[:, :11], g[:, :11], atol=1e-6)   # h_i sees patches < i only
    assert not torch.allclose(h[:, 11], g[:, 11])
    assert not torch.allclose(h[:, 0], model.hidden(x, torch.ones(2, dtype=torch.long))[:, 0])


def test_laplace_head_density_carries_the_jacobian_of_the_logit_map():
    # x in [0, 1] -> y = 0.1 + 0.8 x -> u = logit(y): the density over x integrates to the Laplace mass of u on
    # [logit 0.1, logit 0.9] (GPT-PPG's map truncates the Laplace; it is not renormalised).
    torch.manual_seed(0)
    model = PhysiGPT(CONFIGS["tiny"])
    grid = torch.linspace(0, 1, 20001)[1:-1]
    h = torch.randn(1, 1, model.cfg.dim)
    patches = grid.view(-1, 1, 1).expand(-1, 1, 40)
    nll = model.laplace_nll(h.expand(len(grid), 1, -1), patches)[:, 0]
    mass = torch.trapezoid(torch.exp(-nll.double()), grid.double(), dim=0)
    mu, log_b = model.laplace(h[0, 0]).double().chunk(2)
    b = torch.exp(log_b.clamp(-7, 5))
    cdf = lambda u: torch.where(u < mu, .5*torch.exp((u-mu)/b), 1-.5*torch.exp(-(u-mu)/b))
    edge = torch.logit(torch.tensor(.9, dtype=torch.float64))
    assert torch.allclose(mass, cdf(edge)-cdf(-edge), atol=1e-4)


def test_generated_windows_are_normalised_and_seeded():
    model = PhysiGPT(CONFIGS["tiny"])
    a, b = model.generate(3, steps=3, seed=5), model.generate(3, steps=3, seed=5)
    assert a.shape == (3, 1200) and torch.equal(a, b)
    assert torch.allclose(a.min(1).values, torch.zeros(3)) and torch.allclose(a.max(1).values, torch.ones(3))


def test_schedule_warms_holds_and_decays_to_zero():
    total, decay_start = tr.plan_steps(1000, 2, 100, .0, .2)
    assert (total, decay_start) == (20, 16)
    lrs = [tr.lr_at(s, total, decay_start, 1., 4) for s in range(total+1)]
    assert lrs[0] == .25 and lrs[3] == 1 and lrs[15] == 1 and lrs[20] == 0 and all(np.diff(lrs[16:]) < 0)


def test_batches_are_a_function_of_step_and_cover_each_epoch_once():
    new, replay = np.arange(10, 20), np.arange(5)
    seen = np.concatenate([tr.batch_index(new, np.zeros(0, int), s, 4, .25, 1) for s in range(5)])
    assert sorted(seen[:10]) == list(range(10, 20))           # first epoch: each new row exactly once
    b = tr.batch_index(new, replay, 3, 8, .25, 1)
    assert len(b) == 8 and np.isin(b[-2:], replay).all() and np.array_equal(b, tr.batch_index(new, replay, 3, 8, .25, 1))


def _shard(root, n=48, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(mw.LENGTH)/mw.FS
    x = np.stack([.5+.5*np.sin(2*np.pi*rng.uniform(1, 2)*t+rng.uniform(0, 6)) for _ in range(n)])
    writer = mw.ShardWriter(root)
    rows = [("s", i) for i in range(n)]
    writer.add(x, 3000000+seed, rows, False, *mw.rate_features(x))
    writer.add(x[:8], 3999999, rows[:8], True, *mw.rate_features(x[:8]))
    writer.flush()
    (root/"manifest.json").write_text(json.dumps(dict(protocol=mw.PROTOCOL, record_range=[seed, seed+1], windows=n+8,
                                                      chunks=writer.chunks)))


@pytest.mark.parametrize("split", [3])
def test_a_stopped_stage_resumes_exactly_and_a_new_stage_continues_from_stable(tmp_path, split):
    _shard(tmp_path/"shard0")
    common = ["--data", str(tmp_path/"shard0"), "--config", "tiny", "--batch", "8", "--steps", "6", "--warmup", "2",
              "--decay-frac", ".34", "--cpu", "--log-every", "1", "--eval-every", "3", "--sample-steps", "2"]
    tr.main(common+["--output", str(tmp_path/"full")])
    tr.main(common+["--output", str(tmp_path/"part"), "--stop-at", str(split)])
    first = torch.load(tmp_path/"part"/"last.pt", weights_only=False)
    assert first["step"] == split and first["plan"] == [6, 4] and not (tmp_path/"part"/"release.pt").exists()
    # Same stage, resumed from last.pt: identical weights at the end.
    tr.main(common+["--output", str(tmp_path/"part"), "--resume", str(tmp_path/"part"/"last.pt")])
    a = torch.load(tmp_path/"full"/"release.pt", weights_only=False)["model"]
    b = torch.load(tmp_path/"part"/"release.pt", weights_only=False)["model"]
    assert all(torch.allclose(a[k], b[k], atol=1e-6) for k in a)
    stable = torch.load(tmp_path/"full"/"stable.pt", weights_only=False)
    assert stable["step"] == 4 and stable["plan"] == [6, 4]
    summary = json.loads((tmp_path/"full"/"stage_summary.json").read_text())
    assert np.isfinite(summary["final"]["valid_flow"]) and summary["samples"]["generated"]["acf_peak_mean"] > -1
    # Stage 2: new shard plus replay of shard 0, from stable.pt, at the peak rate without warmup.
    _shard(tmp_path/"shard1", seed=1)
    tr.main(["--data", str(tmp_path/"shard1"), "--replay", str(tmp_path/"shard0"), "--config", "tiny", "--batch", "8",
             "--steps", "4", "--cpu", "--log-every", "1", "--eval-every", "2", "--sample-steps", "2",
             "--resume", str(tmp_path/"full"/"stable.pt"), "--output", str(tmp_path/"stage2")])
    lines = [json.loads(l) for l in (tmp_path/"stage2"/"metrics.jsonl").read_text().splitlines()]
    config = json.loads((tmp_path/"stage2"/"run_config.json").read_text())
    assert lines[0]["lr"] == pytest.approx(6e-4) and config["new_windows"] == 48 and config["replay_windows"] == 48


def test_format_80_rails_are_clipping_and_long_zero_runs_are_dropouts():
    raw = np.full(4*mw.SRC_FS, 120)
    raw[10:14] = 0                                   # trough on the rail
    raw[200:200+mw.DROPOUT_RUN] = 0                  # 1 s of byte 0: dropout
    mask = mw.invalid_mask(raw, "80")
    assert not mask[10:14].any() and mask[200:200+mw.DROPOUT_RUN].all() and mask.sum() == mw.DROPOUT_RUN
    assert mw.invalid_mask(np.array([-32768, 5]), "16").tolist() == [True, False]


def test_two_process_ddp_stage_runs_and_releases(tmp_path):
    _shard(tmp_path/"shard0")
    tr.main(["--data", str(tmp_path/"shard0"), "--config", "tiny", "--batch", "8", "--steps", "4", "--warmup", "1",
             "--cpu", "--cpu-world", "2", "--port", "29531", "--log-every", "1", "--eval-every", "2",
             "--sample-steps", "2", "--output", str(tmp_path/"ddp")])
    lines = [json.loads(l) for l in (tmp_path/"ddp"/"metrics.jsonl").read_text().splitlines()]
    assert [l["step"] for l in lines] == [1, 2, 3, 4] and (tmp_path/"ddp"/"release.pt").exists()
    assert json.loads((tmp_path/"ddp"/"run_config.json").read_text())["world"] == 2


def test_perform_record_names_read_both_set_layouts():
    af = {"subj_id": "p000946", "rec_id": "p000946-2120-05-14-08-08", "files": np.array(["3462211_0001", "3462211_0002"],
                                                                                         dtype=object)}
    single = {"subj_id": "p004829", "files": "3690110_0001"}
    large = {"mimic_perform_details": {"rec_no": 1}, "mimic_details": {"subj_id": "3000086", "rec_id": "3000086",
                                                                       "file": "3000086_0003m", "group": "a"}}
    assert mw.perform_record_names(af) == {"3462211"}
    assert mw.perform_record_names(single) == {"3690110"}
    assert mw.perform_record_names(large) == {"3000086"}


def test_smoke_runs_a_whole_stage_on_synthetic_windows(tmp_path):
    summary = tr.smoke(tmp_path, config="tiny", steps=12)
    assert summary["steps"] == 12 and np.isfinite(summary["final"]["valid_flow"])
    assert (tmp_path/"run"/"stable.pt").exists() and (tmp_path/"run"/"release.pt").exists()


def test_solo_kernel_builds_data_then_trains_on_two_t4s(tmp_path):
    from ml.kaggle_physigpt import stage as st
    out = st.stage(tmp_path/"solo", "solo", shard=9, start=45000, stop=59344, hours=4.5, config="base", epochs=4.)
    meta = json.loads((out/"kernel-metadata.json").read_text())
    script = (out/"run.py").read_text()
    assert meta["machine_shape"] == "NvidiaTeslaT4" and meta["enable_gpu"] and meta["enable_internet"]
    assert meta["id"].endswith("/ppg-physigpt-solo9-v1")
    assert script.index("smoke(") < script.index("build(") < script.index("train([")
    with pytest.raises(ValueError):
        st.entry_for("solo", hours=10.)
    train_meta = json.loads((st.stage(tmp_path/"train", "train")/"kernel-metadata.json").read_text())
    assert train_meta["machine_shape"] == "NvidiaTeslaT4"


def test_a_shard_without_held_out_windows_fails_before_training(tmp_path):
    root = tmp_path/"shard"
    x = np.full((8, mw.LENGTH), .5)
    writer = mw.ShardWriter(root)
    writer.add(x, 3000000, [("s", i) for i in range(8)], False, *mw.rate_features(x))
    writer.flush()
    (root/"manifest.json").write_text(json.dumps(dict(protocol=mw.PROTOCOL, record_range=[0, 1], windows=8,
                                                      chunks=writer.chunks)))
    with pytest.raises(ValueError, match="held-out"):
        tr.main(["--data", str(root), "--output", str(tmp_path/"out"), "--config", "tiny", "--batch", "4", "--cpu"])
    assert not (tmp_path/"out"/"metrics.jsonl").exists()


def test_tpu_kernels_run_on_the_v3_8_after_a_smoke_run(tmp_path):
    from ml.kaggle_physigpt import stage as st
    smoke = st.stage(tmp_path/"smoke", "tpu", smoke_only=True)
    meta = json.loads((smoke/"kernel-metadata.json").read_text())
    assert meta["machine_shape"] == "Tpu1VmV38" and meta["enable_tpu"] and not meta["enable_gpu"]
    assert meta["kernel_sources"] == [] and meta["id"].endswith("/ppg-physigpt-tpu-smoke-v1")
    assert "main(args" not in (smoke/"run.py").read_text()
    full = st.stage(tmp_path/"full", "tpu", stage=0, shards=(0,))
    meta, script = json.loads((full/"kernel-metadata.json").read_text()), (full/"run.py").read_text()
    assert meta["kernel_sources"] == ["charlesday2612/ppg-physigpt-mimic3-shard0-v1"]
    assert script.index("versions()") < script.index("smoke(") < script.index("main(args")
    assert "*map(mounted, ['ppg-physigpt-mimic3-shard0-v1'])" in script
    assert script.index("smoke(") < script.index("def mounted(") < script.index("main(args")


def test_stage_0_trains_on_every_mounted_shard_and_solo_output_as_new_data(tmp_path):
    from ml.kaggle_physigpt import stage as st
    out = st.stage(tmp_path/"k", "train", owner="halovie2412", stage=0, shards=(1, 2), solos=(0,), epochs=300.,
                   extra=("--plateau", "4"))
    meta, script = json.loads((out/"kernel-metadata.json").read_text()), (out/"run.py").read_text()
    assert meta["id"] == "halovie2412/ppg-physigpt-stage0-v1" and meta["kernel_sources"] == [
        "halovie2412/ppg-physigpt-mimic3-shard1-v1", "halovie2412/ppg-physigpt-mimic3-shard2-v1",
        "halovie2412/ppg-physigpt-solo0-v1"]
    assert ("'--data', *map(mounted, ['ppg-physigpt-mimic3-shard1-v1', 'ppg-physigpt-mimic3-shard2-v1', "
            "'ppg-physigpt-solo0-v1']), '--replay', *map(mounted, [])") in script
    # The mounts are looked up before the compile smoke runs spend GPU time; a missing one stops the kernel.
    assert script.index("args = [") < script.index("pick_compile(") < script.index("train(args")
    assert "/kaggle/input/notebooks/halovie2412" in script
    namespace = dict(pathlib=__import__("pathlib"))
    exec(st.mount_lookup("halovie2412"), namespace)
    with pytest.raises(FileNotFoundError, match="not mounted"):
        namespace["mounted"]("ppg-physigpt-mimic3-shard77-v1")
    later = (st.stage(tmp_path/"k1", "train", owner="halovie2412", stage=1, shards=(1, 2))/"run.py").read_text()
    assert ("*map(mounted, ['ppg-physigpt-mimic3-shard2-v1']), '--replay', "
            "*map(mounted, ['ppg-physigpt-mimic3-shard1-v1'])") in later and "mounted('ppg-physigpt-stage0-v1')" in later


def test_shards_sharing_records_are_refused(tmp_path):
    _shard(tmp_path/"a", seed=0)
    _shard(tmp_path/"b", seed=0)
    with pytest.raises(ValueError, match="overlap"):
        tr.Windows([str(tmp_path/"a"), str(tmp_path/"b")])
    assert len(tr.Windows([str(tmp_path/"a")]).train) == 48


def test_plateau_starts_the_decay_on_every_rank_and_leaves_a_stable_state(tmp_path):
    _shard(tmp_path/"shard0")
    # delta .99: only the first evaluation counts as a gain, so the second (step 4) ends the stable phase.
    tr.main(["--data", str(tmp_path/"shard0"), "--config", "tiny", "--batch", "8", "--epochs", "50", "--warmup", "1",
             "--cpu", "--cpu-world", "2", "--port", "29533", "--log-every", "1", "--eval-every", "2",
             "--plateau", "1", "--plateau-delta", ".99", "--decay-frac", ".2", "--sample-steps", "2",
             "--output", str(tmp_path/"run")])
    lines = [json.loads(l) for l in (tmp_path/"run"/"metrics.jsonl").read_text().splitlines()]
    assert [l["step"] for l in lines if l.get("plateau")] == [4]
    # Rank 1 ends at step 5 too (a rank still on the 300-step plan would hang in its next all-reduce).
    assert lines[-1]["step"] == 5 and lines[-1]["plan"] == [5, 4]
    assert torch.load(tmp_path/"run"/"stable.pt", weights_only=False)["step"] == 4
    assert json.loads((tmp_path/"run"/"stage_summary.json").read_text())["plan"] == [5, 4]


def test_plateau_on_a_rising_held_out_loss_ends_the_stage_at_the_best_state(tmp_path, monkeypatch):
    _shard(tmp_path/"shard0")
    # Scripted held-out losses (evaluation every 3 steps): best at step 6, then rising, so the plateau at step 12
    # is overfitting and the stage ends there with the step-6 state instead of decaying the step-12 one.
    flows = iter([.5, .3, .4, .45])
    monkeypatch.setattr(tr, "evaluate", lambda *a: dict(valid_flow=next(flows, .3), valid_laplace_nll=0.))
    tr.main(["--data", str(tmp_path/"shard0"), "--config", "tiny", "--batch", "8", "--steps", "30", "--warmup", "2",
             "--decay-frac", ".34", "--cpu", "--log-every", "1", "--eval-every", "3", "--sample-steps", "2",
             "--plateau", "2", "--output", str(tmp_path/"run")])
    lines = [json.loads(l) for l in (tmp_path/"run"/"metrics.jsonl").read_text().splitlines()]
    assert lines[-1]["step"] == 12 and lines[-1]["plateau"] == "best" and lines[-1]["best_step"] == 6
    best = torch.load(tmp_path/"run"/"best.pt", weights_only=False)
    assert best["step"] == 6 and best["valid_flow"] == .3
    for name in ("stable.pt", "last.pt"):
        state = torch.load(tmp_path/"run"/name, weights_only=False)
        assert state["step"] == 6 and state["plan"] == [6, 6]
        assert all(torch.equal(state["model"][k], best["model"][k]) for k in best["model"])
    release = torch.load(tmp_path/"run"/"release.pt", weights_only=False)
    assert release["step"] == 6 and all(torch.equal(release["model"][k], best["model"][k]) for k in best["model"])
    summary = json.loads((tmp_path/"run"/"stage_summary.json").read_text())
    assert summary["stopped_at_best"] and summary["best"] == dict(step=6, valid_flow=.3) and summary["steps"] == 6


def test_a_flat_held_out_loss_still_decays_and_keeps_the_best_state(tmp_path, monkeypatch):
    _shard(tmp_path/"shard0")
    flows = iter([.5, .3, .3, .3])   # no gain, no rise: the usual decay from step 12
    monkeypatch.setattr(tr, "evaluate", lambda *a: dict(valid_flow=next(flows, .3), valid_laplace_nll=0.))
    tr.main(["--data", str(tmp_path/"shard0"), "--config", "tiny", "--batch", "8", "--steps", "30", "--warmup", "2",
             "--decay-frac", ".34", "--cpu", "--log-every", "1", "--eval-every", "3", "--sample-steps", "2",
             "--plateau", "2", "--output", str(tmp_path/"run")])
    summary = json.loads((tmp_path/"run"/"stage_summary.json").read_text())
    assert not summary["stopped_at_best"] and summary["plan"] == [18, 12] and summary["steps"] == 18
    assert torch.load(tmp_path/"run"/"stable.pt", weights_only=False)["step"] == 12
    assert torch.load(tmp_path/"run"/"best.pt", weights_only=False)["step"] == 6


def test_compile_is_measured_against_eager_and_keeps_the_checkpoint_format(tmp_path):
    use, report = tr.pick_compile(tmp_path, config="tiny")
    assert report["eager"]["step_seconds"] > 0 and report["eager"]["windows_per_second"] > 0
    assert "step_seconds" in report["compiled"], report["compiled"]
    assert use == (report["compiled"]["step_seconds"] < tr.COMPILE_GAIN*report["eager"]["step_seconds"])
    eager = torch.load(tmp_path/"run"/"release.pt", weights_only=False)["model"]
    compiled = torch.load(tmp_path/"run_compile"/"release.pt", weights_only=False)["model"]
    assert eager.keys() == compiled.keys()
    assert all(torch.allclose(eager[k], compiled[k], atol=1e-3) for k in eager)


def test_solotrain_kernel_retrains_on_the_solo_shard_after_measuring_compile(tmp_path):
    from ml.kaggle_physigpt import stage as st
    out = st.stage(tmp_path/"k", "solotrain", owner="halovie2412", shard=0, config="base", epochs=300.,
                   extra=("--plateau", "4", "--eval-every", "250"))
    meta, script = json.loads((out/"kernel-metadata.json").read_text()), (out/"run.py").read_text()
    assert meta["id"] == "halovie2412/ppg-physigpt-solo0-train-v1" and meta["machine_shape"] == "NvidiaTeslaT4"
    assert meta["kernel_sources"] == ["halovie2412/ppg-physigpt-solo0-v1"] and meta["enable_gpu"]
    assert script.index("pick_compile(") < script.index("train([")
    assert "'--plateau', '4'" in script and "'--epochs', '300.0'" in script and "'/kaggle/input'" in script


def test_stage_0_mounts_datasets_as_new_data_and_takes_its_time_budget_from_the_quota(tmp_path):
    from ml.kaggle_physigpt import stage as st
    out = st.stage(tmp_path/"k", "train", owner="halovie2412", stage=0, shards=(1,), datasets=("ppg-physigpt-shard0-data-v1",),
                   kernel_hours=9.5)
    meta, script = json.loads((out/"kernel-metadata.json").read_text()), (out/"run.py").read_text()
    assert meta["dataset_sources"] == ["halovie2412/ppg-physigpt-shard0-data-v1"]
    assert "*map(mounted, ['ppg-physigpt-mimic3-shard1-v1', 'ppg-physigpt-shard0-data-v1'])" in script
    assert "left = 9.5 -" in script
    # A dataset is found wherever Kaggle mounts it under /kaggle/input (the path is searched, not assumed).
    namespace = dict(pathlib=__import__("pathlib"))
    exec(st.mount_lookup("halovie2412").replace("/kaggle/input", str(tmp_path/"input")), namespace)
    (tmp_path/"input"/"datasets"/"halovie2412"/"ppg-physigpt-shard0-data-v1").mkdir(parents=True)
    assert namespace["mounted"]("ppg-physigpt-shard0-data-v1").endswith("datasets/halovie2412/ppg-physigpt-shard0-data-v1")
    (tmp_path/"input"/"x"/"y"/"other").mkdir(parents=True)
    assert namespace["mounted"]("other").endswith("x/y/other")
    default = (st.stage(tmp_path/"k2", "train", owner="halovie2412", stage=0, shards=(1,))/"run.py").read_text()
    assert "left = 11.5 -" in default


def test_warm_cache_reads_every_signal_chunk_before_the_step_time_is_measured(tmp_path):
    _shard(tmp_path/"shard0")
    data = tr.Windows([str(tmp_path/"shard0")])
    sizes = sum(__import__("os").path.getsize(s.filename) for s in data.signal)
    assert tr.warm_cache(data) == sizes > 0


def test_stage_cli_passes_the_plateau_delta_to_the_train_kernel(tmp_path):
    from ml.kaggle_physigpt import stage as st
    st.main([str(tmp_path/"k"), "train", "--owner", "halovie2412", "--shards", "1", "--plateau", "6",
             "--plateau-delta", "0.001", "--eval-every", "500"])
    script = (tmp_path/"k"/"run.py").read_text()
    assert "'--plateau', '6', '--plateau-delta', '0.001', '--eval-every', '500'" in script


def test_judge_kernel_stages_every_module_the_judge_imports_and_mounts_shards_plus_the_stage_output(tmp_path):
    import ast
    from ml.kaggle_physigpt import stage as st
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    staged, todo, seen = set(st.SOURCES["judge"]), ["ml/kaggle_physigpt/judge_physigpt.py"], set()
    while todo:   # module-level imports only: a lazy import inside a function is not needed to load the judge
        name = todo.pop()
        seen.add(name)
        for node in ast.parse((root/name).read_text()).body:
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("ml"):
                base = node.module.replace(".", "/")
                todo += [c for c in [base+".py"]+[f"{base}/{a.name}.py" for a in node.names]
                         if (root/c).exists() and c not in seen]
    assert seen <= staged, seen-staged
    out = st.stage(tmp_path/"k", "judge", owner="halovie2412", shards=(1, 2), solos=(0,), stage=0,
                   datasets=("ppg-physigpt-shard0-data-v1",))
    meta, script = json.loads((out/"kernel-metadata.json").read_text()), (out/"run.py").read_text()
    assert meta["id"] == "halovie2412/ppg-physigpt-judge0-v1" and meta["enable_gpu"]
    assert meta["kernel_sources"][-1] == "halovie2412/ppg-physigpt-stage0-v1" and len(meta["kernel_sources"]) == 4
    assert meta["dataset_sources"] == ["halovie2412/ppg-physigpt-shard0-data-v1"]
    assert "rglob('release.pt')" in script and "'--mode', mode" in script and "CUDA_VISIBLE_DEVICES" in script


def test_judge_scores_generated_windows_and_controls_against_held_out_people(tmp_path):
    from ml.kaggle_physigpt import judge_physigpt as jp
    root = tmp_path/"shard"
    writer = mw.ShardWriter(root)
    rng = np.random.default_rng(0)
    t = np.arange(tr.LENGTH)/tr.FS
    for valid, records in ((False, range(3000000, 3000040)), (True, range(3900000, 3900006))):
        for record in records:
            x = .5+.5*np.sin(2*np.pi*rng.uniform(.8, 2.5)*t+rng.uniform(0, 6, (60, 1)))
            writer.add(x, record, [("s", i) for i in range(60)], valid, *mw.rate_features(x))
    writer.flush()
    tr.save_json(root/"manifest.json", dict(protocol=mw.PROTOCOL, record_range=[0, 0], windows=46*60, chunks=writer.chunks))
    tr.main(["--data", str(root), "--output", str(tmp_path/"run"), "--steps", "4", "--cpu", "--config", "tiny",
             "--batch", "8", "--warmup", "2", "--decay-frac", ".34", "--log-every", "1", "--eval-every", "3",
             "--sample-steps", "2"])
    common = ["--data", str(root), "--sizes", "60", "20", "40", "--steps", "3", "--threads", "2"]
    jp.main([str(tmp_path/"m"), "--mode", "model", "--checkpoint", str(tmp_path/"run"/"release.pt"), *common])
    result = json.loads((tmp_path/"m"/"generated_judge.json").read_text())["result"]["runs"][0]
    assert 0 <= result["auc"] <= 1 and result["tp"]+result["fn"] == 40 and result["fp"]+result["tn"] == 40
    assert len(np.load(tmp_path/"m"/"generated.npy")) == 120
    jp.main([str(tmp_path/"f"), "--mode", "features", "--generated", str(tmp_path/"m"/"generated.npy"), *common])
    features = json.loads((tmp_path/"f"/"features.json").read_text())
    assert {"rate_bpm", "acf_peak", "power_1.5-3 Hz"} <= set(features)
    jp.main([str(tmp_path/"c"), "--mode", "controls", "--only", "null", "phase_randomized", *common])
    controls = json.loads(next((tmp_path/"c").glob("controls_*.json")).read_text())["results"]
    assert [c["source"] for c in controls] == ["real_other_people", "phase_randomized"]


def test_decay_steps_give_a_best_state_stop_the_decay_it_skipped_and_refuse_another_stage(tmp_path, monkeypatch):
    _shard(tmp_path/"shard0")
    flows = iter([.5, .3, .4, .45])
    monkeypatch.setattr(tr, "evaluate", lambda *a: dict(valid_flow=next(flows, .3), valid_laplace_nll=0.))
    common = ["--config", "tiny", "--batch", "8", "--warmup", "2", "--decay-frac", ".34", "--cpu", "--log-every", "1",
              "--eval-every", "3", "--sample-steps", "2"]
    tr.main(["--data", str(tmp_path/"shard0"), "--steps", "30", "--plateau", "2", "--output", str(tmp_path/"run"), *common])
    stable = torch.load(tmp_path/"run"/"stable.pt", weights_only=False)
    assert stable["step"] == 6 and stable["plan"] == [6, 6]
    tr.main(["--data", str(tmp_path/"shard0"), "--resume", str(tmp_path/"run"/"stable.pt"), "--decay-steps", "4",
             "--output", str(tmp_path/"decay"), *common])
    lines = [json.loads(l) for l in (tmp_path/"decay"/"metrics.jsonl").read_text().splitlines()]
    assert [l["step"] for l in lines] == [7, 8, 9, 10] and lines[0]["plan"] == [10, 6]
    assert lines[0]["lr"] == pytest.approx(6e-4) and lines[-1]["lr"] == pytest.approx(6e-4*(1-(3/4)**.5))
    release = torch.load(tmp_path/"decay"/"release.pt", weights_only=False)
    assert release["step"] == 10 and not all(torch.equal(release["model"][k], stable["model"][k]) for k in stable["model"])
    _shard(tmp_path/"shard1", seed=1)
    with pytest.raises(ValueError, match="own stage"):
        tr.main(["--data", str(tmp_path/"shard1"), "--resume", str(tmp_path/"run"/"stable.pt"), "--decay-steps", "4",
                 "--output", str(tmp_path/"other"), *common])


def test_decay_kernel_resumes_the_stage_output_and_the_judge_can_judge_it(tmp_path):
    from ml.kaggle_physigpt import stage as st
    kw = dict(owner="halovie2412", stage=0, shards=(1, 2), solos=(0,), datasets=("ppg-physigpt-shard0-data-v1",))
    out = st.stage(tmp_path/"d", "decay", decay_steps=3000, epochs=300., **kw)
    meta, script = json.loads((out/"kernel-metadata.json").read_text()), (out/"run.py").read_text()
    assert meta["id"] == "halovie2412/ppg-physigpt-decay0-v1" and meta["kernel_sources"][-1] == "halovie2412/ppg-physigpt-stage0-v1"
    assert meta["dataset_sources"] == ["halovie2412/ppg-physigpt-shard0-data-v1"]
    assert "mounted('ppg-physigpt-stage0-v1')" in script and "'--resume', str(stable[0]), '--decay-steps', '3000'" in script
    assert script.index("args = [") < script.index("pick_compile(") < script.index("train(args")
    with pytest.raises(ValueError, match="at least 1"):
        st.stage(tmp_path/"d0", "decay", **kw)
    judge = st.stage(tmp_path/"j", "judge", from_slug="ppg-physigpt-decay0-v1", **kw)
    meta, script = json.loads((judge/"kernel-metadata.json").read_text()), (judge/"run.py").read_text()
    assert meta["id"] == "halovie2412/ppg-physigpt-judge-decay0-v1" and meta["kernel_sources"][-1] == "halovie2412/ppg-physigpt-decay0-v1"
    assert "mounted('ppg-physigpt-decay0-v1')" in script and "mounted('ppg-physigpt-stage0-v1')" not in script


def test_judge_kernel_can_sample_with_more_ode_steps_and_skip_the_model_independent_controls(tmp_path):
    from ml.kaggle_physigpt import stage as st
    kw = dict(owner="halovie2412", stage=0, shards=(1,), from_slug="ppg-physigpt-decay0-v1")
    plain = (st.stage(tmp_path/"a", "judge", **kw)/"run.py").read_text()
    assert "'--gen-steps', '32'" in plain and "controls = run('controls'" in plain
    out = st.stage(tmp_path/"b", "judge", gen_steps=128, skip_controls=True, **kw)
    meta, script = json.loads((out/"kernel-metadata.json").read_text()), (out/"run.py").read_text()
    assert meta["id"] == "halovie2412/ppg-physigpt-judge-decay0-v1-g128" and meta["title"] == "ppg-physigpt-judge-decay0-v1-g128"
    assert "'--gen-steps', '128'" in script and "controls = None" in script and "run('controls'" not in script
    assert "if controls:" in script


def test_unclamped_sampling_keeps_patch_values_the_clip_removed_and_the_judge_kernel_can_request_it(tmp_path):
    model = PhysiGPT(CONFIGS["tiny"])
    class Push(torch.nn.Module):   # a flow field that drives every sample far outside [-1, 1]
        def forward(self, x, t, h):
            return torch.full_like(x, 5.)
    model.flow = Push()
    h = torch.zeros(2, 8)
    assert model.sample_patch(h, 2).max() <= 1 and model.sample_patch(h, 2, clamp=False).max() > 1.5
    assert torch.equal(model.sample_patch(h, 2, clamp=True), model.sample_patch(h, 2))   # the default is unchanged
    from ml.kaggle_physigpt import stage as st
    out = st.stage(tmp_path/"j", "judge", owner="halovie2412", stage=0, shards=(1,), from_slug="ppg-physigpt-decay0-v1",
                   no_clamp=True, skip_controls=True)
    meta, script = json.loads((out/"kernel-metadata.json").read_text()), (out/"run.py").read_text()
    assert meta["id"] == "halovie2412/ppg-physigpt-judge-decay0-v1-noclamp" and "'--gen-steps', '32', '--no-clamp')" in script
    assert "--no-clamp" not in (st.stage(tmp_path/"k", "judge", owner="halovie2412", stage=0, shards=(1,))/"run.py").read_text()


def test_sharpness_loss_weights_the_difference_error_and_leaves_the_validation_flow_unchanged():
    model = PhysiGPT(CONFIGS["tiny"])
    x, domain = torch.rand(4, 1200), torch.zeros(4, dtype=torch.long)
    _, plain = model(x, domain, generator=torch.Generator().manual_seed(1))
    loss, sharp = model(x, domain, generator=torch.Generator().manual_seed(1), diff=2.)
    assert "sharp" not in plain and sharp["sharp"] > 0 and torch.equal(plain["flow"], sharp["flow"])   # same noise, same flow
    base, _ = model(x, domain, generator=torch.Generator().manual_seed(1))
    assert float(loss) == pytest.approx(float(base)+2.*float(sharp["sharp"]), rel=1e-5)


def test_hold_steps_train_at_the_peak_rate_before_the_decay_and_the_kernel_passes_them_on(tmp_path):
    _shard(tmp_path/"shard0")
    common = ["--config", "tiny", "--batch", "8", "--warmup", "2", "--decay-frac", ".34", "--cpu", "--log-every", "1",
              "--eval-every", "3", "--sample-steps", "2"]
    tr.main(["--data", str(tmp_path/"shard0"), "--steps", "6", "--output", str(tmp_path/"run"), *common])
    tr.main(["--data", str(tmp_path/"shard0"), "--resume", str(tmp_path/"run"/"stable.pt"), "--decay-steps", "3",
             "--hold-steps", "2", "--diff-weight", ".5", "--output", str(tmp_path/"more"), *common])
    lines = [json.loads(l) for l in (tmp_path/"more"/"metrics.jsonl").read_text().splitlines()]
    assert [l["step"] for l in lines] == [5, 6, 7, 8, 9] and lines[0]["plan"] == [9, 6] and lines[0]["sharp"] > 0
    assert lines[0]["lr"] == lines[1]["lr"] == pytest.approx(6e-4) and lines[-1]["lr"] < 6e-4*.5
    from ml.kaggle_physigpt import stage as st
    out = st.stage(tmp_path/"k", "decay", owner="halovie2412", stage=0, shards=(1,), decay_steps=3000, hold_steps=7000,
                   from_slug="ppg-physigpt-decay0-more-v1", tag="more2", extra=("--diff-weight", "0.5"))
    meta, script = json.loads((out/"kernel-metadata.json").read_text()), (out/"run.py").read_text()
    assert meta["id"] == "halovie2412/ppg-physigpt-decay0-more2-v1" and meta["title"] == "ppg-physigpt-decay0-more2-v1"
    assert meta["kernel_sources"][-1] == "halovie2412/ppg-physigpt-decay0-more-v1"
    assert "mounted('ppg-physigpt-decay0-more-v1')" in script and "'--decay-steps', '3000', '--hold-steps', '7000'" in script
    assert "'--diff-weight', '0.5'" in script


def test_fidelity_tier_separates_matching_features_from_shifted_ones_and_keeps_the_people_reference():
    from ml.kaggle_physigpt import judge_physigpt as jp
    t = np.arange(mw.LENGTH)/mw.FS

    def windows(seed, low, high, n=600):
        rng = np.random.default_rng(seed)
        return np.stack([.5+.5*np.sin(2*np.pi*rng.uniform(low, high)*t+rng.uniform(0, 6)) for _ in range(n)]).astype(np.float32)
    fit, held, other = windows(1, 1, 2), windows(2, 1, 2, 1000), windows(3, 1, 2, 1000)
    same = jp.fidelity_report(fit, held, other, windows(4, 1, 2), windows(5, 1, 2, 1000))
    shifted = jp.fidelity_report(fit, held, other, windows(4, 3, 4), windows(5, 3, 4, 1000))
    assert same["generated"]["mean_similarity"] > .9 and same["generated"]["classifier"]["trees"]["accuracy"] < .62
    assert same["generated"]["passes"] and not shifted["generated"]["passes"]
    assert shifted["generated"]["mean_similarity"] < .8 and shifted["generated"]["classifier"]["trees"]["accuracy"] > .9
    assert same["real_other_people"]["mean_similarity"] > .9 and "passes" not in same["real_other_people"]


def test_judge_kernel_with_no_judge_seeds_only_samples_and_compares_features(tmp_path):
    from ml.kaggle_physigpt import stage as st
    out = st.stage(tmp_path/"j", "judge", owner="halovie2412", stage=0, shards=(1,), from_slug="ppg-physigpt-decay0-sharp8-v1",
                   judge_seeds=0)
    meta, script = json.loads((out/"kernel-metadata.json").read_text()), (out/"run.py").read_text()
    assert meta["id"] == "halovie2412/ppg-physigpt-judge-decay0-sharp8-v1-fid" and meta["title"] == meta["id"].split("/")[1]
    assert "run('features', '0', '--checkpoint', str(found[0]), '--gen-steps', '32')" in script
    assert "run('model'" not in script and "run('controls'" not in script and "--generated" not in script
    compile(script.replace("\n", "\n"), "judge.py", "exec")


def test_micro_batches_accumulate_into_one_optimizer_step_and_match_the_unsplit_step(tmp_path, monkeypatch):
    _shard(tmp_path/"shard0")
    # With the noise made independent of the chunk size, a split batch must take the same optimizer step.
    monkeypatch.setattr(PhysiGPT, "flow_loss", lambda self, h, patches, repeats=4, generator=None, diff=0.: (
        (self.flow((2*patches.reshape(-1, patches.shape[-1])-1), torch.full((patches.shape[0]*patches.shape[1],), .5), h.reshape(-1, h.shape[-1])).float()
         - 1.).square().mean(), torch.zeros(())))
    common = ["--data", str(tmp_path/"shard0"), "--config", "tiny", "--batch", "8", "--steps", "3", "--warmup", "1",
              "--decay-frac", ".34", "--cpu", "--log-every", "1", "--eval-every", "3", "--sample-steps", "2", "--aux", "0"]
    tr.main(common+["--output", str(tmp_path/"whole")])
    tr.main(common+["--micro", "2", "--output", str(tmp_path/"split")])
    a = torch.load(tmp_path/"whole"/"release.pt", weights_only=False)["model"]
    b = torch.load(tmp_path/"split"/"release.pt", weights_only=False)["model"]
    assert all(torch.allclose(a[k], b[k], atol=2e-5) for k in a)
    lines = [json.loads(l) for l in (tmp_path/"split"/"metrics.jsonl").read_text().splitlines()]
    assert [l["step"] for l in lines] == [1, 2, 3] and all(np.isfinite(l["loss"]) for l in lines)


def test_colab_supervisor_resumes_on_a_new_vm_from_drive_and_refuses_a_corrupt_copy(tmp_path):
    from ml.kaggle_physigpt import colab_run as cr
    import hashlib
    drive, run = tmp_path/"drive"/"data", tmp_path/"drive"/"run"
    _shard(drive/"shard0"/"shard"); _shard(drive/"shard1"/"shard", seed=1)
    (drive/"SHA256SUMS.txt").write_text("".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.relative_to(drive)}\n"
                                                for f in sorted(drive.rglob("*")) if f.is_file() and f.name != "SHA256SUMS.txt"))
    train = ["--config", "tiny", "--batch", "8", "--steps", "6", "--warmup", "2", "--decay-frac", ".34", "--cpu",
             "--log-every", "1", "--eval-every", "3", "--sample-steps", "2"]
    base = ["--drive-data", str(drive), "--drive-run", str(run), "--sync-seconds", "1"]
    assert cr.main(base+["--local", str(tmp_path/"vm1"), "--", *train, "--stop-at", "3"]) == 0
    assert torch.load(run/"last.pt", weights_only=False)["step"] == 3 and not (run/"release.pt").exists()
    # A new VM (empty disk) continues the same stage from what Drive kept.
    assert cr.main(base+["--local", str(tmp_path/"vm2"), "--", *train]) == 0
    assert torch.load(run/"release.pt", weights_only=False)["step"] == 6
    steps = [json.loads(l)["step"] for l in (run/"metrics.jsonl").read_text().splitlines()]
    assert steps == [1, 2, 3, 4, 5, 6]
    # Done on Drive: a third session trains nothing and copies nothing.
    assert cr.main(base+["--local", str(tmp_path/"vm3"), "--", *train]) == 0 and not (tmp_path/"vm3").exists()
    victim = next((drive/"shard1"/"shard").glob("chunk_*_signal.npy"))
    data = bytearray(victim.read_bytes()); data[-1] ^= 1; victim.write_bytes(bytes(data))
    (run/"release.pt").unlink()
    with pytest.raises(ValueError, match="checksum mismatch"):
        cr.main(base+["--local", str(tmp_path/"vm4"), "--", *train])
    assert not (tmp_path/"vm4"/"data"/"shard1").exists()


def test_tagged_large_stage_keeps_its_own_output_and_smokes_with_its_micro_batch(tmp_path):
    from ml.kaggle_physigpt import stage as st
    st.main([str(tmp_path/"k"), "train", "--owner", "halovie2412", "--shards", "1", "--config", "large", "--tag", "large",
             "--micro", "256", "--lr", "0.0004", "--plateau", "6"])
    meta, script = json.loads((tmp_path/"k"/"kernel-metadata.json").read_text()), (tmp_path/"k"/"run.py").read_text()
    assert meta["id"] == "halovie2412/ppg-physigpt-stage0-large-v1" and meta["title"] == "ppg-physigpt-stage0-large-v1"
    assert "'--plateau', '6', '--micro', '256', '--lr', '0.0004'" in script
    assert "pick_compile('/tmp/physigpt_smoke', 'large', extra=['--micro', '256'])" in script
    untagged = st.stage(tmp_path/"k2", "train", owner="halovie2412", stage=0, shards=(1,))
    assert json.loads((untagged/"kernel-metadata.json").read_text())["id"] == "halovie2412/ppg-physigpt-stage0-v1"
    assert "pick_compile('/tmp/physigpt_smoke', 'base', extra=[])" in (untagged/"run.py").read_text()
