"""PhysioMix v2 round: robust labels, v3 view, constructed-rate generator, derivative critic,
condition schema, holdout isolation and the full pilot -> frozen benchmark flow on CPU."""
import json
import math
from pathlib import Path

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


def test_c2st_floor_uses_subject_disjoint_domain_complete_halves(monkeypatch):
    from ml.kaggle_multidomain import evaluate_v3
    for name, value in (("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
        monkeypatch.setattr(experiment_v3, name, value)
    pack = v3_pack()
    dev = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    for split in ("train", "validation"):
        half = evaluate_v3.subject_halves(dev, split, np.random.default_rng(0))
        rows = dev["split"] == split
        assert not set(dev["subject"][half]) & set(dev["subject"][rows & ~half])
        assert set(dev["domain"][half]) == set(dev["domain"][rows & ~half]) == set(DOMAIN_RATE)
    floor = evaluate_v3.c2st_floor(experiment_v3.PromptedEvaluator(dev, 8), "cpu", repeats=2)
    assert len(floor["values"]) == 2 and 0 <= floor["min"] <= floor["mean"] <= floor["max"] <= 1


# Round 4: scale-anchored pulse, physiological beat timing, learning-rate schedule and selection rule.
CENTER, SCALE = np.array([85., .05, .2], np.float32), np.array([20., .08, .06], np.float32)


def collapse_amplitude(model):
    """The late-training v2 failure: harmonic amplitudes shrink while the bounded residual stays active."""
    with torch.no_grad():
        shrunk = .01*torch.tensor([1., .35, .12, .05, .02, .01])  # same pulse shape, 1% of the initial size
        model.head.bias[:model.k] = torch.log(torch.expm1(shrunk))
        torch.nn.init.normal_(model.out.weight, std=.5, generator=torch.Generator().manual_seed(1))
    return model.eval()


def test_scale_anchored_pulse_keeps_rate_when_harmonic_amplitude_collapses():
    torch.manual_seed(0)
    old, new = (collapse_amplitude(cls(10, CENTER, SCALE)) for cls in (physio.PhysioMixH, physio.PhysioMixR))
    new.load_state_dict({k: v for k, v in old.state_dict().items() if not k.startswith("head.")}, strict=False)
    errors = {}
    for name, model in (("old", old), ("new", new)):
        rates = []
        for bpm in (60, 150):
            z = torch.randn(8, LENGTH, generator=torch.Generator().manual_seed(bpm))
            with torch.no_grad():
                y = model(z, condition_rows(10, 5, bpm, .02, 8, CENTER, SCALE)).numpy()[:, 0]
            rates.append(np.abs(np.nan_to_num(labels.beat_stats(y)[:, 0], nan=0.)-bpm))
        errors[name] = float(np.median(np.concatenate(rates)))
    assert errors["old"] > 10 and errors["new"] < 2, errors


def test_beat_timing_reports_commanded_irregularity_and_matches_sinus_phase():
    torch.manual_seed(0)
    warped, timed = physio.PhysioMixR(10, CENTER, SCALE).eval(), physio.PhysioMixR(10, CENTER, SCALE, beat=True).eval()
    cv = {}
    for name, model in (("warped", warped), ("timed", timed)):
        z = torch.randn(48, LENGTH, generator=torch.Generator().manual_seed(4))
        with torch.no_grad():
            y = model(z, condition_rows(10, 5, 90, .2, 48, CENTER, SCALE)).numpy()[:, 0]
        cv[name] = float(np.nanmedian(labels.beat_stats(y)[:, 1]))
    assert abs(cv["timed"]-.2) < .02 and cv["warped"] < .18, cv
    z, hz = torch.randn(3, LENGTH), torch.full((3,), 1.4)
    for a, b in zip(warped.beats_of(z, hz, torch.zeros(3)), timed.beats_of(z, hz, torch.zeros(3))):
        torch.testing.assert_close(a, b)


def test_pulse_amplitude_follows_the_preceding_interval_when_coupled():
    torch.manual_seed(0)
    model = physio.PhysioMixR(10, CENTER, SCALE, beat=True).eval()
    with torch.no_grad():
        model.coupling.bias.fill_(8.)  # beta ~ 1
    z = torch.randn(1, LENGTH, generator=torch.Generator().manual_seed(2))
    raw = torch.tensor([[95., .3]])
    hz = raw[:, 0]/60
    index, fraction, ibi = model.beats_of(z, hz, raw[:, 1])
    with torch.no_grad():
        y = model(z, condition_rows(10, 5, 95, .3, 1, CENTER, SCALE)).numpy()[0, 0]
    beat = index.numpy()[0]
    previous = torch.cat((ibi[:, :1], ibi[:, :-1]), 1).numpy()[0]
    complete = [k for k in np.unique(beat)[1:-1]]
    heights = [y[beat == k].max()-y[beat == k].min() for k in complete]
    assert np.corrcoef(previous[complete], heights)[0, 1] > .6
    traced = torch.jit.trace(model, (torch.randn(2, LENGTH), condition_rows(10, 5, 70, .02, 2, CENTER, SCALE)))
    z, c = torch.randn(3, LENGTH), condition_rows(10, 5, 160, .3, 3, CENTER, SCALE)
    torch.testing.assert_close(traced(z, c), model(z, c))


def test_learning_rate_schedule_and_domain_distribution_loss():
    cfg = experiment_v3.config("L1_v2_lr")
    assert experiment_v3.learning_rate(cfg, 0, 100) == pytest.approx(1e-4)
    assert experiment_v3.learning_rate(cfg, 100, 100) == pytest.approx(1e-5)
    assert experiment_v3.learning_rate(experiment_v3.config("P4_v2_osc_dc"), 50, 100) == 2e-4
    real = torch.tensor(np.stack([ppg(60+10*i, i) for i in range(8)]))[:, None]
    domain = torch.tensor([0, 0, 0, 0, 1, 1, 1, 1])
    assert experiment_v3.domain_distribution_loss(real, real, domain) == 0
    swapped = real[[4, 5, 6, 7, 0, 1, 2, 3]]
    # The pooled batch is identical, so only the per-domain term sees the mismatch.
    from ml.kaggle_multidomain.models import distribution_loss
    assert float(distribution_loss(swapped, real)) < 1e-6
    assert float(experiment_v3.domain_distribution_loss(swapped, real, domain)) > 1e-3


def test_round4_rule_prefers_fewer_changes_within_tie_and_ships_only_a_clear_gain():
    from ml.kaggle_multidomain import experiment_v4

    def rows(scores, eligible=True, real=.35):
        return [dict(arm=arm, seed=seed, S_arm=value+.01*i, S_real_fresh=real, eligible=eligible)
                for arm, value in scores.items() for i, seed in enumerate((42, 123, 2026))]
    selection = experiment_v4.select_round4(rows({"L1_v2_lr": .55, "L2_rel_lr": .545, "L3_rel_beat_lr": .50,
                                                  "L4_rel_beat_dom_lr": .495}))
    assert selection["winner"] == "L3_rel_beat_lr" and selection["ship"] and selection["ship_seed"] == 42
    selection = experiment_v4.select_round4(rows({a: .58 for a in experiment_v4.ROUND4}))
    assert selection["winner"] == "L1_v2_lr" and not selection["ship"]
    selection = experiment_v4.select_round4(rows({a: .45 for a in experiment_v4.ROUND4}, real=.5))
    assert not selection["non_inferior"] and not selection["ship"]
    assert experiment_v4.select_round4(rows({a: .4 for a in experiment_v4.ROUND4}, eligible=False))["winner"] is None


def test_round4_runs_end_to_end_on_cpu_and_freezes_the_rule_first(tmp_path, monkeypatch):
    from ml.kaggle_multidomain import experiment_v4
    for name, value in (("CONTROL_N", 1), ("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
        monkeypatch.setattr(experiment_v3, name, value)
    save_v3(tmp_path/"input"/"pack", v3_pack())
    experiment_v4.main(["--input-root", str(tmp_path/"input"), "--allow-cpu", "--batch", "4", "--interval", "2",
                        "--eval-samples", "12", "--bootstrap", "2", "--seeds", "42", "--steps", "2",
                        "--output", str(tmp_path/"r4")])
    out = tmp_path/"r4"
    frozen = json.loads((out/"FROZEN_ROUND4.json").read_text())
    assert frozen["rule_sha256"] == experiment_v4.RULE_SHA256 and set(frozen["arms"]) == set(experiment_v4.ROUND4)
    assert frozen["arms"]["L3_rel_beat_lr"]["beat"] and not frozen["arms"]["L1_v2_lr"]["rel"]
    assert (out/"FROZEN_ROUND4.json").stat().st_mtime <= (out/"SELECTION_ROUND4.json").stat().st_mtime
    assert (out/"SELECTION_ROUND4.json").stat().st_mtime <= (out/"benchmark"/"results.json").stat().st_mtime
    summary = json.loads((out/"summary.json").read_text())
    assert set(summary["arms"]) == set(experiment_v4.ROUND4)
    for arm in experiment_v4.ROUND4:
        assert (out/"benchmark"/f"{arm}_seed42"/"generator_cpu.ts").exists()
    assert (out/"REPORT_ROUND4.md").exists()


def realism_pack():
    """Toy pack whose states differ in rate, so a waveform CNN can tell them apart."""
    pack = v3_pack()
    rates = {"bidmc": 60, "perform_af": 150, "perform_non_af": 90, "perform_large": 45, "wrist": 170, "gxu_finger": 120}
    for i, domain in enumerate(pack["domain"]):
        if domain in rates:
            bpm = rates[domain]-60*(domain == "gxu_finger" and pack["activity_label"][i] == 4)
            pack["signal"][i] = ppg(bpm, i, sigma=.2 if domain == "perform_af" else .01)
    return pack


def test_realism_compares_unseen_people_with_training_people_and_generators(monkeypatch):
    from ml.kaggle_multidomain import realism
    pack = realism_pack()
    development, to_dev = realism.development_of(pack)
    seen = []

    def replay(ids, seed):
        seen.append(set(pack["split"][ids]))
        assert np.all(development["split"][to_dev(ids)] == "train")
        return pack["signal"][ids]
    result = realism.realism(pack, experiment_v3.PromptedEvaluator(development, 8), dict(replay=replay), n=12,
                             folds=2, steps=5)
    assert set(result) == set(realism.DATASETS) and seen and all(s == {"train"} for s in seen)
    for entry in result.values():
        assert entry["people"] >= 2
        for name in ("real_other_people", "replay"):
            assert 0 <= entry[name]["fidelity"] <= 1 and 0 <= entry[name]["indistinguishable"] <= 1


def test_condition_following_separates_obedient_from_command_blind_sources():
    from ml.kaggle_multidomain import realism
    pack = realism_pack()

    def obedient(ids, seed):
        return pack["signal"][ids]

    def blind(ids, seed):
        return pack["signal"][np.random.default_rng(seed).choice(np.flatnonzero(pack["split"] == "train"), len(ids))]
    result = realism.condition_following(pack, dict(obedient=obedient, blind=blind), steps=150, n=12, swap=12)
    assert result["real_unseen"]["balanced_accuracy"] > .6
    assert result["obedient"]["swap_following"] > .6 and result["blind"]["swap_following"] < .3
    assert result["blind"]["swap_distinct_answers_per_noise"] == 1
    assert set(result["physiology"]["obedient"]) == set(realism.STATES)


def test_cropped_output_is_not_circular_and_keeps_rate_control():
    torch.manual_seed(0)
    circular = physio.PhysioMixR(10, CENTER, SCALE, beat=True).eval()
    cropped = physio.PhysioMixR(10, CENTER, SCALE, beat=True, pad=physio.CROP_PAD).eval()
    # Same weights; the time grid and long band mask differ by construction.
    cropped.load_state_dict({k: v for k, v in circular.state_dict().items() if k != "time"}, strict=False)
    z = torch.randn(64, LENGTH, generator=torch.Generator().manual_seed(1))
    jump = {}
    with torch.no_grad():
        for name, model in (("circular", circular), ("cropped", cropped)):
            y = model(z, condition_rows(10, 5, 80, .03, 64, CENTER, SCALE)).numpy()[:, 0]
            jump[name] = float(np.median(np.abs(y[:, -1]-y[:, 0])))
    assert jump["cropped"] > 1.5*jump["circular"], jump
    traced = torch.jit.trace(cropped, (torch.randn(2, LENGTH), condition_rows(10, 5, 70, .02, 2, CENTER, SCALE)))
    for n, bpm in ((1, 40), (3, 120), (5, 175)):
        z, c = torch.randn(n, LENGTH), condition_rows(10, 5, bpm, .02, n, CENTER, SCALE)
        out = traced(z, c)
        torch.testing.assert_close(out, cropped(z, c))
        assert out.shape == (n, 1, LENGTH) and float(out.min()) >= 0 and float(out.max()) <= 1
        rate = labels.beat_stats(out.detach().numpy()[:, 0])[:, 0]
        assert np.all(np.abs(rate-bpm) <= .03*bpm), rate


def fake_round4(root, winner="L3_rel_beat_lr", ship=True):
    (root/"benchmark").mkdir(parents=True)
    (root/"SELECTION_ROUND4.json").write_text(json.dumps(dict(winner=winner, ship=ship)))
    runs = [dict(arm=winner, seed=s, S_arm=.5+.01*i, S_real_fresh=.33) for i, s in enumerate((42, 123, 2026))]
    (root/"benchmark"/"training_execution.json").write_text(json.dumps(dict(runs=runs)))


def test_round5_incumbent_is_round4_winner_only_if_it_shipped(tmp_path):
    from ml.kaggle_multidomain import experiment_v5
    fake_round4(tmp_path/"shipped")
    base, incumbent = experiment_v5.round4_reference(tmp_path/"shipped")
    assert base["arm"] == incumbent["name"] == "L3_rel_beat_lr" and incumbent["S_arm"] == [.5, .51, .52]
    fake_round4(tmp_path/"kept", ship=False)
    _, incumbent = experiment_v5.round4_reference(tmp_path/"kept")
    assert incumbent["name"] == "round3_physiomix_v2"
    later = tmp_path/"r6"/"benchmark"
    later.mkdir(parents=True)
    (later.parent/"DECISION_ROUND5.json").write_text(json.dumps(dict(arm="L3_rel_beat_lr_crop_r1", ship=True)))
    (later/"training_execution.json").write_text(json.dumps(dict(runs=[
        dict(arm="L3_rel_beat_lr_crop_r1", seed=s, S_arm=.45, S_real_fresh=.3) for s in (42, 123, 2026)])))
    base, incumbent = experiment_v5.round4_reference(tmp_path/"kept", tmp_path/"r6")
    assert base["arm"] == "L3_rel_beat_lr" and incumbent["name"] == "L3_rel_beat_lr_crop_r1"
    assert incumbent["S_arm"] == [.45, .45, .45]
    assert experiment_v3.config("L3_rel_beat_lr_crop_r1w")["r1_weight"] == .1
    rows = [dict(arm="L3_rel_beat_lr_crop", seed=s, S_arm=v, S_real_fresh=.3, eligible=True)
            for s, v in ((42, .40), (123, .41), (2026, .42))]
    assert experiment_v5.decide(rows, "L3_rel_beat_lr_crop", base | dict(name="r4"))["ship"]
    rows[0]["eligible"] = False
    assert not experiment_v5.decide(rows, "L3_rel_beat_lr_crop", base | dict(name="r4"))["ship"]


def test_round5_runs_end_to_end_on_cpu(tmp_path, monkeypatch):
    from ml.kaggle_multidomain import experiment_v5
    for name, value in (("CONTROL_N", 1), ("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
        monkeypatch.setattr(experiment_v3, name, value)
    save_v3(tmp_path/"input"/"pack", v3_pack())
    fake_round4(tmp_path/"r4")
    experiment_v5.main(["--input-root", str(tmp_path/"input"), "--round4-root", str(tmp_path/"r4"), "--allow-cpu",
                        "--batch", "4", "--interval", "2", "--eval-samples", "12", "--bootstrap", "2", "--seeds", "42",
                        "--steps", "2", "--output", str(tmp_path/"r5")])
    out = tmp_path/"r5"
    frozen = json.loads((out/"FROZEN_ROUND5.json").read_text())
    assert frozen["arm"] == "L3_rel_beat_lr_crop" and frozen["config"]["pad"] == physio.CROP_PAD
    assert (out/"FROZEN_ROUND5.json").stat().st_mtime <= (out/"DECISION_ROUND5.json").stat().st_mtime
    assert (out/"benchmark"/"L3_rel_beat_lr_crop_seed42"/"generator_cpu.ts").exists()
    assert (out/"REPORT_ROUND5.md").exists()
    # The app bundle script rebuilds the cropped generator from source and the app loads its TorchScript.
    import shutil
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root/"scripts"))
    import prepare_physiomix_bundle
    from core.neural_preview import PhysioMixGenerator
    assets = tmp_path/"assets"
    assets.mkdir()
    shutil.copy(root/"assets"/"neural"/"manifest.json", assets/"manifest.json")
    meta = prepare_physiomix_bundle.prepare(out/"benchmark", "L3_rel_beat_lr_crop", tmp_path/"input"/"pack", assets,
                                            None, "physiomix_round5_test")
    assert meta["architecture"]["pad"] == physio.CROP_PAD and meta["hr_support_bpm"] == [40., 180.]
    app = PhysioMixGenerator(assets)
    preview = app.generate(7, 95, "gxu_finger", .02)
    assert len(preview.samples) == 1200 and preview.provenance["measured_rate_bpm"] == pytest.approx(95, abs=5)


def test_round6_scales_the_critic_clip_on_lazy_r1_steps(tmp_path, monkeypatch):
    from ml.kaggle_multidomain import experiment_v5
    assert experiment_v3.config("L3_rel_beat_lr_crop_r1")["r1_scaled_clip"]
    assert not experiment_v3.config("L3_rel_beat_lr_crop")["r1_scaled_clip"]
    for name, value in (("CONTROL_N", 1), ("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
        monkeypatch.setattr(experiment_v3, name, value)
    save_v3(tmp_path/"input"/"pack", v3_pack())
    fake_round4(tmp_path/"r4", ship=False)
    experiment_v5.main(["--input-root", str(tmp_path/"input"), "--round4-root", str(tmp_path/"r4"), "--allow-cpu",
                        "--batch", "4", "--interval", "16", "--eval-samples", "12", "--bootstrap", "2", "--seeds", "42",
                        "--steps", "16", "--variant", "crop_r1", "--output", str(tmp_path/"r6")])
    frozen = json.loads((tmp_path/"r6"/"FROZEN_ROUND5.json").read_text())
    assert frozen["arm"] == "L3_rel_beat_lr_crop_r1" and "x16" in frozen["rule"]
    assert frozen["incumbent"]["name"] == "round3_physiomix_v2"
    result = json.loads((tmp_path/"r6"/"benchmark"/"L3_rel_beat_lr_crop_r1_seed42"/"training_result.json").read_text())
    assert result["stability"]["r1_updates"] == 1 and "r1_clipped" in result["stability"]


@pytest.mark.parametrize("mode", ["physio3_pilot", "physio3_final", "physio4", "physio5", "physio6", "physio7", "physio8", "physio9",
                                  "flow10_pilot", "flow10_final", "flow10b_pilot", "flow10b_final", "flow10c_pilot",
                                  "flow10c_final", "flow10c_resume", "flow10d_pilot", "flow10d_final",
                                  "flow10e_pilot", "flow10e_final", "flow10f_pilot", "flow10f_final", "fresh_galaxy",
                                  "galaxy_b_pilot", "lsm_galaxy", "galaxy_d_pilot", "galaxy_d_final", "galaxy_e"])
def test_staged_kernel_carries_its_entry_module(tmp_path, mode):
    from ml.kaggle_multidomain import stage_kernel
    out = stage_kernel.stage(tmp_path/mode, mode, steps=2)
    manifest = json.loads((out/"source_manifest.json").read_text())
    entry = (out/"run.py").read_text().rsplit("from ml.kaggle_multidomain.", 1)[1].split(" import")[0]
    assert f"ml/kaggle_multidomain/{entry}.py" in manifest["files"]
    if mode.startswith(("flow10d_", "flow10e_", "flow10f_")):
        # Loops 5-6 always apply the pre-registered go limits; a final mounts its own loop's pilot and round 9.
        loop = mode.split("_")[0]
        assert "'--go'" in (out/"run.py").read_text()
        sources = json.loads((out/"kernel-metadata.json").read_text())["kernel_sources"]
        assert mode.endswith("_pilot") or (f"charlesday2612/ppg-physio{loop}-pilot-v1" in sources
                                           and "charlesday2612/ppg-physiomix9-motion-dom-v1" in sources)
    if mode == "flow10e_pilot":
        run = (out/"run.py").read_text()
        assert "'F9_flow_unif_stop03_s16_w1'" in run and "'F10_flow_unif_stop01_s16_w1'" in run
    if mode.startswith("flow10f_"):
        # Loop 7 applies its own, tighter go limits in the pilot and the final.
        assert "'--go', 'loop7'" in (out/"run.py").read_text()


@pytest.mark.parametrize("mode", ["flow10f_pilot", "flow10f_final"])
def test_loop7_kernel_on_another_account_mounts_only_its_own_sources(tmp_path, mode):
    from ml.kaggle_multidomain import stage_kernel
    meta = json.loads((stage_kernel.stage(tmp_path/mode, mode, steps=2, owner="other")/"kernel-metadata.json").read_text())
    sources = meta["kernel_sources"]+meta["dataset_sources"]
    assert meta["id"] == f"other/ppg-physioflow10f-{mode.split('_')[1]}-v1"
    assert all(s.startswith("other/") for s in sources)
    assert "other/ppg-physio3-data-v1" in sources
    assert mode.endswith("_pilot") or {"other/ppg-physioflow10f-pilot-v1", "other/ppg-physiomix9-incumbent-v1"} <= set(sources)


def test_fresh_galaxy_kernel_is_cpu_only_and_mounts_its_own_datasets(tmp_path):
    from ml.kaggle_multidomain import stage_kernel
    out = stage_kernel.stage(tmp_path/"fresh", "fresh_galaxy", steps=2, owner="other")
    meta = json.loads((out/"kernel-metadata.json").read_text())
    assert meta["enable_gpu"] is False and meta["enable_internet"] is True
    assert meta["dataset_sources"] == ["other/ppg-physio3-data-v1", "other/ppg-app-models-v1"]
    # Kaggle derives the kernel slug from the title; they must agree or status/output use another slug.
    assert meta["id"].split("/")[1] == meta["title"].lower().replace(" ", "-")
    run = (out/"run.py").read_text()
    assert "ZIP_MD5" in run and "'--stage'" not in run


@pytest.mark.parametrize("mode,module", [("galaxy_b_pilot", "experiment_galaxy"), ("lsm_galaxy", "experiment_lsm_galaxy"),
                                         ("galaxy_d_pilot", "experiment_daily"), ("galaxy_d_final", "experiment_daily"),
                                         ("galaxy_e", "experiment_e")])
def test_galaxy_kernels_select_the_v3g_pack_before_importing_training_code(tmp_path, mode, module):
    from ml.kaggle_multidomain import stage_kernel
    out = stage_kernel.stage(tmp_path/mode, mode, steps=2, owner="other")
    meta = json.loads((out/"kernel-metadata.json").read_text())
    assert meta["enable_gpu"] is True
    assert meta["dataset_sources"] == ["other/ppg-physio3g-data-v1", "other/ppg-app-models-v1"]
    assert meta["id"].split("/")[1] == meta["title"].lower().replace(" ", "-")
    run = (out/"run.py").read_text()
    assert run.index("PPG_PACK_PROTOCOL") < run.index(f"from ml.kaggle_multidomain.{module} import main")
    if mode.startswith("galaxy_d_"):
        # The daily-wrist pack is derived from the v3g pack; the final mounts its own pilot's output.
        assert "ppg_physiomix_v3d" in run and f"'--stage', '{mode.split('_')[2]}'" in run
        assert meta["kernel_sources"] == ([] if mode.endswith("pilot") else ["other/ppg-galaxy-d-pilot-v1"])
    if mode == "galaxy_e":
        # Step E derives the v3e pack (6 everyday-wrist validation people) and trains all 3 seeds in one kernel.
        assert "ppg_physiomix_v3e" in run and meta["kernel_sources"] == [] and meta["id"] == "other/ppg-galaxy-e-v1"


def test_staged_datasets_hold_one_pack_and_the_round9_decision(tmp_path):
    from ml.kaggle_multidomain import stage_kernel
    from ml.kaggle_multidomain.experiment_flow import incumbent_scores
    if not (Path(stage_kernel.__file__).resolve().parents[2]/stage_kernel.INCUMBENT_RUN).exists():
        pytest.skip("local round-9 output not present")
    data, incumbent = stage_kernel.stage_datasets(tmp_path, "other")
    assert len(list(data.rglob("windows.npz"))) == 1
    assert json.loads((incumbent/"dataset-metadata.json").read_text())["id"] == "other/ppg-physiomix9-incumbent-v1"
    assert len(incumbent_scores(incumbent)["S_arm"]) == 3


def test_motion_component_starts_near_off_and_can_add_a_cadence_line():
    torch.manual_seed(0)
    plain = physio.PhysioMixR(10, CENTER, SCALE, beat=True, pad=physio.CROP_PAD).eval()
    moving = physio.PhysioMixR(10, CENTER, SCALE, beat=True, pad=physio.CROP_PAD, motion=True).eval()
    # A round-7 checkpoint has no motion head; the shared weights load unchanged.
    missing = moving.load_state_dict(plain.state_dict(), strict=False).missing_keys
    assert set(missing) == {"motion.weight", "motion.bias", "motion_orders"}
    z, c = torch.randn(16, LENGTH, generator=torch.Generator().manual_seed(3)), condition_rows(10, 5, 70, .02, 16, CENTER, SCALE)
    with torch.no_grad():
        before, after = plain(z, c).numpy()[:, 0], moving(z, c).numpy()[:, 0]
    assert np.median(np.abs(after-before)) < .05
    assert np.all(np.abs(labels.beat_stats(after)[:, 0]-70) <= .03*70)
    with torch.no_grad():
        moving.motion.bias[0] = math.log((2.5-physio.MOTION_HZ[0])/(physio.MOTION_HZ[1]-2.5))  # 2.5 Hz cadence
        moving.motion.bias[1] = 8.  # full amplitude
        y = moving(z, c).numpy()[:, 0]
    freq = np.fft.rfftfreq(LENGTH, 1/FS)
    power = np.abs(np.fft.rfft(y-y.mean(1, keepdims=True)))**2
    assert np.all(np.abs(freq[power.argmax(1)]-2.5) <= .15), freq[power.argmax(1)]
    traced = torch.jit.trace(moving, (torch.randn(2, LENGTH), condition_rows(10, 5, 70, .02, 2, CENTER, SCALE)))
    torch.testing.assert_close(traced(z, c), moving(z, c))


def fake_round7(root, wrist=(.62, .62, .72)):
    (root/"benchmark").mkdir(parents=True)
    (root/"DECISION_ROUND5.json").write_text(json.dumps(dict(arm="L3_rel_beat_lr_crop_r1w", ship=True)))
    runs = [dict(arm="L3_rel_beat_lr_crop_r1w", seed=s, S_arm=v, S_real_fresh=.36,
                 prompted_validation=dict(pools=dict(wrist=dict(Q=q))))
            for s, v, q in zip((42, 123, 2026), (.46, .51, .56), wrist)]
    (root/"benchmark"/"training_execution.json").write_text(json.dumps(dict(runs=runs)))


def test_round8_rule_ships_on_a_clear_wrist_gain_without_an_overall_loss(tmp_path):
    from ml.kaggle_multidomain import experiment_v5
    assert experiment_v3.config("L3_rel_beat_lr_crop_r1w_motion")["motion"]
    assert not experiment_v3.config("L3_rel_beat_lr_crop_r1w")["motion"]
    nine = experiment_v3.config("L3_rel_beat_lr_crop_r1w_motion_dom")
    assert nine["motion"] and nine["domloss"] and experiment_v5.TARGETED["crop_r1w_motion_dom"] == "wrist"
    fake_round4(tmp_path/"r4", ship=False)
    fake_round7(tmp_path/"r7")
    base, incumbent = experiment_v5.round4_reference(tmp_path/"r4", tmp_path/"r7")
    assert incumbent["wrist_Q"] == [.62, .62, .72]
    rule = experiment_v5.rule_text(base, incumbent, "crop_r1w_motion")
    assert "validation wrist Q [0.62, 0.62, 0.72]" in rule and "motion component" in rule
    with pytest.raises(ValueError):
        experiment_v5.rule_text(base, dict(incumbent, wrist_Q=[None]*3), "crop_r1w_motion")
    arm = "L3_rel_beat_lr_crop_r1w_motion"

    def rows(s_arm, wrist):
        return [dict(arm=arm, seed=s, S_arm=a, S_real_fresh=.36, eligible=True,
                     prompted_validation=dict(pools=dict(wrist=dict(Q=q)))) for s, a, q in zip((42, 123, 2026), s_arm, wrist)]
    better_wrist = (.45, .48, .50)
    decision = experiment_v5.decide(rows((.49, .52, .55), better_wrist), arm, incumbent, "wrist")
    assert decision["ship"] and decision["target_gap"] > decision["target_pooled_sd"]
    # Same wrist gain but S_arm worse than the incumbent beyond the pooled SD: not shipped.
    assert not experiment_v5.decide(rows((.60, .62, .64), better_wrist), arm, incumbent, "wrist")["ship"]
    # Within-noise wrist change: not shipped even with a better S_arm.
    assert not experiment_v5.decide(rows((.40, .41, .42), (.60, .63, .70)), arm, incumbent, "wrist")["ship"]


@pytest.mark.parametrize("variant", ["crop_r1w_motion", "crop_r1w_motion_dom"])
def test_round8_runs_end_to_end_on_cpu(tmp_path, monkeypatch, variant):
    from ml.kaggle_multidomain import experiment_v5
    for name, value in (("CONTROL_N", 1), ("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
        monkeypatch.setattr(experiment_v3, name, value)
    save_v3(tmp_path/"input"/"pack", v3_pack())
    fake_round4(tmp_path/"r4", ship=False)
    fake_round7(tmp_path/"r7")
    experiment_v5.main(["--input-root", str(tmp_path/"input"), "--round4-root", str(tmp_path/"r4"), "--allow-cpu",
                        "--incumbent-root", str(tmp_path/"r7"), "--batch", "4", "--interval", "2", "--eval-samples", "12",
                        "--bootstrap", "2", "--seeds", "42", "--steps", "2", "--variant", variant,
                        "--output", str(tmp_path/"r8")])
    out = tmp_path/"r8"
    frozen = json.loads((out/"FROZEN_ROUND5.json").read_text())
    arm = f"L3_rel_beat_lr_{variant}"
    assert frozen["arm"] == arm and frozen["config"]["motion"]
    assert frozen["incumbent"]["name"] == "L3_rel_beat_lr_crop_r1w"
    decision = json.loads((out/"DECISION_ROUND5.json").read_text())
    assert decision["target"] == "wrist"
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root/"scripts"))
    import prepare_physiomix_bundle
    import shutil
    assets = tmp_path/"assets"
    assets.mkdir()
    shutil.copy(root/"assets"/"neural"/"manifest.json", assets/"manifest.json")
    meta = prepare_physiomix_bundle.prepare(out/"benchmark", arm, tmp_path/"input"/"pack",
                                            assets, None, "physiomix_round8_test")
    assert meta["architecture"]["motion"]
