"""PhysioMix v2 round: robust labels, v3 view, constructed-rate generator, derivative critic,
condition schema, holdout isolation and the full pilot -> frozen benchmark flow on CPU."""
import json

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
pytest.importorskip("scipy")

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain import control, data, data_gxu, experiment_v3, labels, physio

torch.set_num_threads(1)


def ppg(bpm, seed=0, notch=.45, sigma=0.):
    """Harmonic-rich pulse train with optional log-normal IBI jitter, in the v3 view."""
    rng = np.random.default_rng(seed)
    t = np.arange(LENGTH)/FS
    ibi = np.exp(sigma*rng.normal(size=200)-sigma**2/2)*60/bpm
    onsets = np.cumsum(ibi)-ibi[0]*rng.uniform()
    k = np.clip(np.searchsorted(onsets, t, side="right")-1, 0, 199)
    phase = 2*np.pi*(k+(t-onsets[k])/ibi[k])
    wave = np.sin(phase)+notch*np.sin(2*phase-1.1)+.12*np.sin(3*phase-2.2)+.005*rng.normal(size=LENGTH)
    wave = np.fft.irfft(np.fft.rfft(wave)*physio.view_mask("v3"), n=LENGTH)
    return data.normalize(wave)


@pytest.mark.parametrize("bpm", [40, 60, 120, 180])
def test_robust_labels_track_rate_without_half_rate_lock(bpm):
    rate, irr, source = labels.robust_labels(np.stack([ppg(bpm, s) for s in range(3)]))
    assert np.all(np.abs(rate-bpm) <= 2), rate
    assert np.all(irr < .05) and set(source) == {"ppg_consensus"}


def test_ecg_gating_keeps_ecg_rate_or_masks_disagreement():
    x = np.stack([ppg(75, 1), ppg(75, 2)])
    rate, _, source = labels.robust_labels(x, np.array([76., 110.]))
    assert rate[0] == 76. and np.isnan(rate[1]) and list(source) == ["ecg_gated", "masked"]


def test_v3_view_keeps_slow_fundamentals_and_v1_is_unchanged():
    freq = np.fft.rfftfreq(LENGTH, 1/FS)
    v3, v1 = physio.view_mask("v3"), physio.view_mask("v1")
    assert v3[np.argmin(abs(freq-40/60))] > .85 and v1[np.argmin(abs(freq-40/60))] == 0
    x = torch.rand(2, 1, LENGTH)
    freq_t = torch.fft.rfftfreq(LENGTH, 1/FS)
    legacy = torch.fft.irfft(torch.fft.rfft(x, dim=-1)*((freq_t >= .9) & (freq_t <= 5)), n=LENGTH, dim=-1)
    legacy = (legacy-legacy.amin(-1, keepdim=True))/(legacy.amax(-1, keepdim=True)-legacy.amin(-1, keepdim=True))
    torch.testing.assert_close(physio.bandlimit(x), legacy)


def condition_rows(size, domains, bpm, sigma, n, center, scale):
    c = np.zeros((n, size), np.float32)
    c[:, 0] = 1
    c[:, domains:domains+2] = 1
    c[:, -3] = (bpm-center[0])/scale[0]
    c[:, -2] = (sigma-center[1])/scale[1]
    return torch.tensor(c)


def test_constructed_rate_generator_traces_controls_rate_and_is_fast():
    center, scale = np.array([85., .05, .2], np.float32), np.array([20., .08, .06], np.float32)
    model = physio.PhysioMixH(10, center, scale).eval()
    traced = torch.jit.trace(model, (torch.randn(2, LENGTH), condition_rows(10, 5, 70, .02, 2, center, scale)))
    for n, bpm in ((1, 40), (2, 100), (5, 150)):
        z, c = torch.randn(n, LENGTH), condition_rows(10, 5, bpm, .02, n, center, scale)
        torch.testing.assert_close(traced(z, c), model(z, c))
        rate = labels.beat_stats(traced(z, c).detach().numpy()[:, 0])[:, 0]
        assert np.all(np.abs(rate-bpm) <= .03*bpm), rate
    z, c = torch.randn(1, LENGTH), condition_rows(10, 5, 80, .02, 1, center, scale)
    import time
    with torch.no_grad():
        traced(z, c)
        start = time.perf_counter()
        for _ in range(10):
            traced(z, c)
    assert (time.perf_counter()-start)/10 < .05


def test_derivative_critic_r1_double_backward_is_finite():
    critic = physio.DerivCritic(10)
    x = torch.rand(4, 1, LENGTH, requires_grad=True)
    out = critic(x, torch.randn(4, 10))
    grad = torch.autograd.grad(out.mean(1).sum(), x, create_graph=True)[0]
    penalty = grad.square().sum()
    penalty.backward()
    assert out.shape == (4, 3) and torch.isfinite(penalty)
    assert all(torch.isfinite(p.grad).all() for p in critic.parameters() if p.grad is not None)


DOMAIN_RATE = {"bidmc": 85, "perform_af": 95, "perform_non_af": 75, "perform_large": 80, "wrist": 110, "gxu_finger": 68}


def v3_pack():
    rows, extra = [], dict(rhythm_label=[], activity_label=[], reference_hr_bpm=[])
    for domain, base in DOMAIN_RATE.items():
        for split in ("train", "validation", "test"):
            for person in range(4):
                for window in range(3):
                    seed = hash((domain, split, person, window)) % 2**32
                    bpm = base+6*person+2*window
                    wave = ppg(bpm, seed, sigma=.15 if domain == "perform_af" else .01)
                    rows.append((wave, f"{domain}:{split}:{person}", domain, split, f"{domain}:{split}:{person}", window*LENGTH))
                    extra["rhythm_label"].append(1 if domain == "perform_af" else -1)
                    extra["activity_label"].append(4+window if domain == "gxu_finger" else -1)
                    extra["reference_hr_bpm"].append(bpm+.5 if domain in ("gxu_finger", "wrist") else np.nan)
    for person in range(3):
        rows.append((ppg(70+5*person, 900+person), f"capno:{person}", "capnobase", "external", f"c{person}", 0))
        for key, value in (("rhythm_label", -1), ("activity_label", -1), ("reference_hr_bpm", np.nan)):
            extra[key].append(value)
    pack = {k: np.asarray(v) for k, v in zip(("signal", "subject", "domain", "split", "record", "start"), zip(*rows))}
    pack.update(rhythm_label=np.asarray(extra["rhythm_label"], np.int8),
                activity_label=np.asarray(extra["activity_label"], np.int8),
                reference_hr_bpm=np.asarray(extra["reference_hr_bpm"], np.float32))
    data.validate_pack(pack)
    return pack


def save_v3(path, pack):
    path.mkdir(parents=True)
    np.savez_compressed(path/"windows.npz", **pack)
    (path/"manifest.json").write_text(json.dumps(dict(protocol=experiment_v3.PROTOCOL, view="v3",
                                                      windows_sha256=data.digest(path/"windows.npz"))))


def test_conditions_v2_are_training_only_flagged_and_promptable():
    pack = v3_pack()
    conditions = physio.Conditions(pack, "v2")
    d = len(conditions.domains)
    assert conditions.bank.shape[1] == d+5 and set(conditions.domains) == set(DOMAIN_RATE)
    assert conditions.known.mean() > .8
    with pytest.raises(ValueError):
        conditions.for_ids(np.flatnonzero(pack["split"] == "validation")[:2])
    gxu = conditions.metadata()["label_source"]["gxu_finger"]
    assert gxu.get("ecg_gated", 0) > 0
    prompt = conditions.prompt("gxu_finger", 120, .2, 3)
    raw = prompt[:, -3:]*conditions.scale+conditions.center
    assert np.allclose(raw[:, :2], [120, .2], atol=1e-4) and np.all(prompt[:, d:d+2] == 1)


def test_unlabelled_domain_raises():
    pack = v3_pack()
    noise = np.random.default_rng(5).uniform(size=((pack["domain"] == "wrist").sum(), LENGTH)).astype(np.float32)
    pack["signal"][pack["domain"] == "wrist"] = noise
    with pytest.raises(ValueError, match="coverage"):
        physio.Conditions(pack, "v2")


def test_motion_dominated_domain_keeps_masked_labels_and_is_flagged(monkeypatch):
    monkeypatch.setattr(physio, "MIN_KNOWN_WINDOWS", 2)  # the toy pack has 12 wrist training windows
    pack = v3_pack()
    rows = np.flatnonzero((pack["domain"] == "wrist") & (pack["split"] == "train"))
    pack["reference_hr_bpm"][rows[:-2]] = 180.  # ECG disagrees with PPG periodicity, as in exercise wrist data
    conditions = physio.Conditions(pack, "v2")
    coverage = conditions.metadata()["coverage"]["wrist"]
    assert coverage["low"] and coverage["rate"] == pytest.approx(2/len(rows))
    pack["reference_hr_bpm"][rows[-2:]] = 180.
    with pytest.raises(ValueError, match="coverage"):
        physio.Conditions(pack, "v2")
    assert not conditions.metadata()["coverage"]["bidmc"]["low"]


def test_prompted_references_use_validation_only_and_controllability_is_finite():
    pack = v3_pack()
    dev = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    evaluator = experiment_v3.PromptedEvaluator(dev, 16)
    for pool in evaluator.pools.values():
        assert set(dev["split"][pool["reference_ids"]]) == {"validation"}
    conditions = physio.Conditions(dev, "v2")
    model = physio.PhysioMixH(conditions.bank.shape[1], conditions.center, conditions.scale).eval()
    run = experiment_v3.sampler(model, experiment_v3.config("P2_v2_osc"), "cpu")
    result = control.controllability(run, conditions, n=2)
    assert np.isfinite(result["C"]) and result["mae_in"] < 5 and result["spearman"] > .9


def test_pilot_rule_prefers_simpler_variant_within_margin_and_enforces_non_inferiority():
    def row(arm, s_arm, s_real, eligible=True):
        return dict(arm=arm, S_arm=s_arm, S_real_fresh=s_real, c2st_derivative_auc=.7, eligible=eligible, gates={})
    rows = [row("P0_physiomix_no_div_v3", 1., 1.), row("P1_v2_lab", .91, 1.), row("P2_v2_osc", .90, 1.01),
            row("P3_v2_dc", .80, 1.2), row("P4_v2_osc_dc", .5, 1.0, False)]
    selection = experiment_v3.select_pilot(rows)
    assert selection["winner"] == "P1_v2_lab"
    assert not next(c for c in selection["candidates"] if c["arm"] == "P3_v2_dc")["eligible"]
    rows[1]["eligible"] = rows[2]["eligible"] = False
    assert experiment_v3.select_pilot(rows)["winner"] == "P1_v2_lab"


def test_full_pilot_then_frozen_benchmark_on_cpu(tmp_path, monkeypatch):
    for name, value in (("CONTROL_N", 1), ("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
        monkeypatch.setattr(experiment_v3, name, value)
    pack = v3_pack()
    save_v3(tmp_path/"input"/"pack", pack)
    common = ["--input-root", str(tmp_path/"input"), "--allow-cpu", "--batch", "4", "--interval", "2",
              "--eval-samples", "12", "--bootstrap", "2", "--seeds", "42"]
    experiment_v3.main(common+["--output", str(tmp_path/"pilot"), "--stage", "pilot", "--pilot-steps", "2"])
    selection = json.loads((tmp_path/"pilot"/"PILOT_SELECTION.json").read_text())
    assert selection["winner"] in experiment_v3.COMPLEXITY
    experiment_v3.main(common+["--output", str(tmp_path/"final"), "--stage", "final", "--steps", "2",
                               "--pilot-root", str(tmp_path/"pilot")])
    frozen = json.loads((tmp_path/"final"/"FROZEN_PROTOCOL.json").read_text())
    assert frozen["aliases"]["physiomix_v2"] == selection["winner"]
    summary = json.loads((tmp_path/"final"/"summary.json").read_text())
    assert set(summary["arms"]) == {"lsm_multi", "hybrid_multi", "physiomix_no_div", "physiodiffusion", "physiomix_v2"}
    assert summary["arms"]["physiomix_v2"]["gxu_test_Q"] is not None
    assert (tmp_path/"final"/"REPORT_VI.md").exists() and (tmp_path/"final"/"control_and_fresh_test.png").exists()
    assert (tmp_path/"final"/"benchmark"/"physiomix_v2_seed42"/"generator_cpu.ts").exists()
