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
    (root/"manifest.json").write_text(json.dumps(dict(protocol=mw.PROTOCOL, record_range=[0, 1], windows=n+8,
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
