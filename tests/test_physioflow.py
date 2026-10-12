"""PhysioFlow (round 10): beat scaffolds, the flow U-Net/sampler contract, the rule and a CPU pilot -> final run."""
import json

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
pytest.importorskip("scipy")

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain import experiment_v3, flow, labels
from tests.test_physiomix_v2 import CENTER, SCALE, condition_rows, ppg, save_v3, v3_pack

torch.set_num_threads(1)


def test_peak_repair_fills_a_missed_beat_and_merges_a_notch_peak():
    row = ppg(75, seed=1)
    times = flow.window_peaks(row)
    assert abs(60*FS/np.median(np.diff(times))-75) < 1.5
    # Drop one beat's peak region: the gap is filled with a virtual peak, not read as one long beat.
    damaged = row.copy()
    k = int(times[8])
    damaged[k-6:k+7] = np.minimum(damaged[k-6:k+7], np.percentile(row, 30))
    repaired = flow.window_peaks(damaged)
    assert len(repaired) == len(times)
    assert np.max(np.diff(repaired)) < 1.4*np.median(np.diff(times))


@pytest.mark.parametrize("bpm", [45, 75, 150])
def test_real_phase_advances_one_cycle_per_detected_peak(bpm):
    row = ppg(bpm, seed=bpm)
    phase, usable = flow.real_scaffolds(row[None], np.array([bpm], float), np.array([True]))
    assert usable[0]
    cycles = (phase[0, -1]-phase[0, 0])*60/(LENGTH/FS)
    assert abs(cycles-bpm) < .04*bpm
    # Masked rate labels and a label far from the peaks both leave the window unscaffolded.
    assert not flow.real_scaffolds(row[None], np.array([bpm], float), np.array([False]))[1][0]
    assert not flow.real_scaffolds(row[None], np.array([2*bpm], float), np.array([True]))[1][0]


def test_constructed_phase_holds_rate_and_irregularity():
    z = torch.randn(64, LENGTH, generator=torch.Generator().manual_seed(0))
    time = torch.arange(LENGTH, dtype=torch.float32)/FS
    for bpm, sigma in ((60, 0.), (170, 0.), (90, .2)):
        phase = flow.constructed_phase(z, torch.full((64,), bpm/60), torch.full((64,), sigma), time).numpy()
        assert np.all(np.diff(phase, axis=1) > 0)
        rate = (phase[:, -1]-phase[:, 0])*60/((LENGTH-1)/FS)
        assert abs(np.median(rate)-bpm) < .03*bpm
        crossings = [np.flatnonzero(np.diff(np.floor(p)) > 0) for p in phase]
        cv = np.median([np.std(np.diff(c))/np.mean(np.diff(c)) for c in crossings])
        assert cv == pytest.approx(sigma, abs=.04)


def test_generator_follows_the_scaffold_contract_and_traces():
    torch.manual_seed(0)
    g = flow.FlowGenerator(10, CENTER, SCALE, sample_steps=2, guidance=1.5, width=.25).eval()
    z, c = torch.randn(3, LENGTH), condition_rows(10, 5, 80, .02, 3, CENTER, SCALE)
    with torch.no_grad():
        y = g(z, c)
    assert y.shape == (3, 1, LENGTH) and float(y.min()) == 0 and float(y.max()) == 1
    exported = g.export(torch.randn(2, LENGTH), condition_rows(10, 5, 80, .02, 2, CENTER, SCALE))
    torch.testing.assert_close(exported(z, c), y)
    # Same z, other command: a different rhythm scaffold reaches the network.
    s75, s150 = (g.scaffold_of(z, condition_rows(10, 5, bpm, .02, 3, CENTER, SCALE)) for bpm in (75, 150))
    assert not torch.allclose(s75, s150) and torch.all(s75[:, 2] == 1)


def test_flag_gated_scaffold_drops_when_the_rate_is_unknown_and_exports_the_same():
    torch.manual_seed(0)
    g = flow.FlowGenerator(10, CENTER, SCALE, sample_steps=2, width=.25, flag_scaffold=True).eval()
    z, c = torch.randn(4, LENGTH), condition_rows(10, 5, 80, .02, 4, CENTER, SCALE)
    c[2:, flow.RATE_KNOWN] = 0          # masked rate label, as most wrist-exercise training windows
    s = g.scaffold_of(z, c)
    assert torch.all(s[:2, 2] == 1) and torch.all(s[2:] == 0)
    exported = g.export(z[:2], c[:2])
    with torch.no_grad():
        torch.testing.assert_close(exported(z, c), g(z, c))
    # The always-on variant ignores the flag (pilot-1 behaviour).
    assert torch.all(flow.FlowGenerator(10, CENTER, SCALE, width=.25).scaffold_of(z, c)[:, 2] == 1)


def test_flow_loss_learns_a_scaffolded_pulse_quickly():
    """A small net fitted on clean scaffolded pulses: the loss falls well below its starting value."""
    torch.manual_seed(1)
    rows = np.stack([ppg(70+5*i, seed=i) for i in range(16)])
    rates = np.array([70+5*i for i in range(16)], float)
    phase, usable = flow.real_scaffolds(rows, rates, np.ones(16, bool))
    net = flow.UNet1D(10, (16, 16, 16, 16, 16))
    opt = torch.optim.Adam(net.parameters(), 2e-3)
    real, phase, usable = torch.tensor(rows[:, None], dtype=torch.float32), torch.tensor(phase), torch.tensor(usable)
    cond = condition_rows(10, 5, 80, .02, 16, CENTER, SCALE)
    losses = []
    for _ in range(60):
        opt.zero_grad()
        loss = flow.flow_loss(net, real, phase, usable, cond, deriv=1.)
        loss.backward()
        opt.step()
        losses.append(loss.item())
    assert np.mean(losses[-10:]) < .6*np.mean(losses[:5])


def test_flow_times_reach_small_t_unless_logit_normal():
    torch.manual_seed(0)
    small = {d: float((flow.flow_times(20000, "cpu", d) < .05).float().mean()) for d in ("logit", "mix", "uniform")}
    assert small["logit"] < .005 and small["mix"] == pytest.approx(.025, abs=.006) and small["uniform"] == pytest.approx(.05, abs=.006)


def test_stop_and_filter_finish_keeps_the_band_and_exports_the_same():
    torch.manual_seed(0)
    g = flow.FlowGenerator(10, CENTER, SCALE, sample_steps=2, width=.25, flag_scaffold=True, t_end=.04,
                           finish_filter=True).eval()
    z, c = torch.randn(3, LENGTH), condition_rows(10, 5, 80, .02, 3, CENTER, SCALE)
    with torch.no_grad():
        y = g(z, c)
        torch.testing.assert_close(g.export(z[:2], c[:2])(z, c), y)
    power = np.abs(np.fft.rfft(y.numpy()[:, 0]-y.numpy()[:, 0].mean(1, keepdims=True)))**2
    freq = np.fft.rfftfreq(LENGTH, 1/FS)
    assert power[:, freq > 12].sum() < 1e-3*power.sum()
    # The finish band is not a checkpoint entry: earlier PhysioFlow checkpoints still load.
    assert "band" not in g.state_dict()
    assert experiment_v3.config("F5_flow_flag_deriv_mix_s16_w1_f04")["t_end"] == .04


def test_flow_arms_and_samplers_share_one_architecture():
    base = experiment_v3.config("F1_flow")
    variant = experiment_v3.config("F1_flow_s16_w1.5")
    assert base["flow"] and variant["sample_steps"] == 16 and variant["guidance"] == 1.5
    assert experiment_v3.config("F2_flow_deriv")["deriv"] == 1.
    assert experiment_v3.config("L3_rel_beat_lr_crop_r1w")["latency_limit_ms"] == 50.
    pack = v3_pack()
    conditions = experiment_v3.conditions_for({k: v for k, v in pack.items()}, "v2")
    a, _ = experiment_v3.build(base, conditions)
    b, _ = experiment_v3.build(variant, conditions)
    assert a.state_dict().keys() == b.state_dict().keys()


def fake_round9(root, s_arm=(.53, .50, .56), wrist=(.49, .49, .60)):
    from ml.kaggle_multidomain.experiment_flow import INCUMBENT_ARM
    (root/"benchmark").mkdir(parents=True)
    (root/"DECISION_ROUND5.json").write_text(json.dumps(dict(arm=INCUMBENT_ARM, ship=True)))
    runs = [dict(arm=INCUMBENT_ARM, seed=s, S_arm=v, S_real_fresh=.34, prompted_validation=dict(pools=dict(wrist=dict(Q=q))))
            for s, v, q in zip((42, 123, 2026), s_arm, wrist)]
    (root/"benchmark"/"training_execution.json").write_text(json.dumps(dict(runs=runs)))


def test_round10_rule_needs_a_clear_s_arm_gain_and_keeps_the_wrist_gain(tmp_path):
    from ml.kaggle_multidomain import experiment_flow
    fake_round9(tmp_path/"r9")
    incumbent = experiment_flow.incumbent_scores(tmp_path/"r9")
    arm = "F1_flow_s8_w1"
    rule = experiment_flow.rule_text(arm, incumbent)
    assert "wrist Q [0.49, 0.49, 0.6]" in rule and "< 5000 ms" in rule

    def rows(s_arm, wrist, real=.30, eligible=True):
        return [dict(arm=arm, seed=s, S_arm=a, S_real_fresh=real, eligible=eligible,
                     prompted_validation=dict(pools=dict(wrist=dict(Q=q)))) for s, a, q in zip((42, 123, 2026), s_arm, wrist)]
    assert experiment_flow.decide(rows((.40, .42, .44), (.48, .50, .55)), arm, incumbent)["ship"]
    # Clear S_arm gain but the wrist pool falls back: not shipped.
    assert not experiment_flow.decide(rows((.40, .42, .44), (.70, .72, .75)), arm, incumbent)["ship"]
    assert not experiment_flow.decide(rows((.51, .52, .53), (.48, .50, .55)), arm, incumbent)["ship"]
    assert not experiment_flow.decide(rows((.40, .42, .44), (.48, .50, .55), eligible=False), arm, incumbent)["ship"]
    assert not experiment_flow.decide(rows((.40, .42, .44), (.48, .50, .55), real=.45), arm, incumbent)["ship"]


def test_round10_pilot_then_final_on_cpu(tmp_path, monkeypatch):
    from ml.kaggle_multidomain import experiment_flow
    for name, value in (("CONTROL_N", 1), ("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
        monkeypatch.setattr(experiment_v3, name, value)
    monkeypatch.setattr(experiment_flow, "CONTROL_N", 1)
    # A narrow net keeps the CPU run short; the architecture is otherwise the Kaggle one.
    for arm in [a for a in experiment_v3.ARMS if experiment_v3.ARMS[a].get("flow")]:
        monkeypatch.setitem(experiment_v3.ARMS, arm, dict(experiment_v3.ARMS[arm], width=.25))
    # A 4-step CPU net is not data-like, so its diversity gate is a coin toss; this test covers the plumbing
    # (pilot -> frozen final -> bundle -> app), so finite outputs are enough to count as eligible here.
    real_score_arm = experiment_flow.score_arm

    def plumbing_score(*args, **kwargs):
        result = real_score_arm(*args, **kwargs)
        assert result["gates"]["finite"] and result["gates"]["trace_ok"]
        return dict(result, eligible=True)
    monkeypatch.setattr(experiment_flow, "score_arm", plumbing_score)
    save_v3(tmp_path/"input"/"pack", v3_pack())
    common = ["--input-root", str(tmp_path/"input"), "--allow-cpu", "--batch", "4", "--interval", "2",
              "--eval-samples", "12", "--steps", "4"]
    experiment_flow.main(common+["--stage", "pilot", "--arms", "F1_flow", "F3_flow_flag_deriv", "--samplers",
                                 "F1_flow_s8_w1", "F3_flow_flag_deriv_s8_w1.5", "--output", str(tmp_path/"pilot")])
    selection = json.loads((tmp_path/"pilot"/"PILOT_SELECTION_FLOW.json").read_text())
    assert {c["sampler"] for c in selection["candidates"]} == {"F1_flow_s8_w1", "F3_flow_flag_deriv_s8_w1.5"}
    assert (tmp_path/"pilot"/"pilot"/"F1_flow_seed42"/"scaffolds.json").exists()
    assert selection["winner"] in ("F1_flow_s8_w1", "F3_flow_flag_deriv_s8_w1.5")
    fake_round9(tmp_path/"r9")
    experiment_flow.main(common+["--stage", "final", "--pilot-root", str(tmp_path/"pilot"), "--incumbent-root",
                                 str(tmp_path/"r9"), "--seeds", "42", "--bootstrap", "2", "--output", str(tmp_path/"final")])
    out = tmp_path/"final"
    frozen = json.loads((out/"FROZEN_ROUND10.json").read_text())
    assert frozen["arm"] == selection["winner"] and frozen["incumbent"]["S_arm"] == [.53, .50, .56]
    assert (out/"FROZEN_ROUND10.json").stat().st_mtime <= (out/"DECISION_ROUND10.json").stat().st_mtime
    run = out/"benchmark"/f"{selection['winner']}_seed42"
    assert (run/"generator_cpu.ts").exists() and (out/"REPORT_ROUND10.md").exists()
    traced = torch.jit.load(str(run/"generator_cpu.ts"))
    y = traced(torch.randn(2, LENGTH), condition_rows(11, 6, 90, .02, 2, CENTER, SCALE))
    assert y.shape == (2, 1, LENGTH) and np.isfinite(y.detach().numpy()).all()
    # The app bundle script rebuilds the flow from source into its own slot; the app loads it by slot.
    import shutil
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root/"scripts"))
    import prepare_physiomix_bundle
    from core.neural_preview import PhysioMixGenerator, physiomix_metadata
    assets = tmp_path/"assets"
    assets.mkdir()
    shutil.copy(root/"assets"/"neural"/"manifest.json", assets/"manifest.json")
    meta = prepare_physiomix_bundle.prepare(out/"benchmark", selection["winner"], tmp_path/"input"/"pack", assets, None,
                                            "physioflow_round10_test", "physioflow")
    assert meta["architecture"]["flow"] and meta["hr_support_bpm"] == [40., 180.]
    assert physiomix_metadata(assets, "physioflow")["variant"] == "physioflow_round10_test"
    # The copied manifest lists PhysioMix too, but its model file is not in this bundle, so it is not offered.
    assert physiomix_metadata(assets) is None
    preview = PhysioMixGenerator(assets, slot="physioflow").generate(7, 95, "gxu_finger", .02)
    assert preview.name == "PhysioFlow" and len(preview.samples) == 1200 and preview.hr_target == 95
    assert labels.IRR_MAX == .35
    # A final whose workers died while scoring is resumed from its checkpoints with the same score_arm.
    (run/"training_result.json").unlink()
    experiment_flow.main(common+["--stage", "final", "--resume-from", str(out), "--output", str(tmp_path/"resumed")])
    resumed = json.loads((tmp_path/"resumed"/"benchmark"/"training_execution.json").read_text())
    assert resumed["runs"][0]["stability"]["note"].startswith("worker terminated")
    assert resumed["runs"][0]["best_step"] == frozen["steps"] or resumed["runs"][0]["best_step"] > 0
    assert (tmp_path/"resumed"/"DECISION_ROUND10.json").exists() and (tmp_path/"resumed"/"REPORT_ROUND10.md").exists()


def test_copy_check_flags_shifted_training_windows_only():
    from ml.kaggle_multidomain.realism import nearest_train_correlation
    rng = np.random.default_rng(0)
    train = rng.normal(size=(40, LENGTH))
    copies = np.roll(train[:4], 37, axis=1)+.01*rng.normal(size=(4, LENGTH))
    assert np.all(nearest_train_correlation(copies, train) > .99)
    assert np.all(nearest_train_correlation(rng.normal(size=(4, LENGTH)), train) < .3)


def test_log_psd_matches_the_criterion_features():
    from ml.kaggle_lsm.train_lsm import features
    rng = np.random.default_rng(0)
    x = np.stack([ppg(60+10*i, seed=i) for i in range(4)]+[rng.normal(size=LENGTH) for _ in range(2)]).astype(np.float32)
    np.testing.assert_allclose(flow.log_psd(torch.tensor(x[:, None])).numpy(), features(x)[1], atol=1e-3)
    # As a loss it must give finite gradients, also for a flat window (every detrended bin exactly zero).
    windows = torch.tensor(np.r_[x[:1], np.full((1, LENGTH), .5, np.float32)][:, None], requires_grad=True)
    flow.log_psd(windows).sum().backward()
    assert torch.isfinite(windows.grad).all()


class EstimateNet(torch.nn.Module):
    """Returns the velocity whose x0 estimate (x_t - t v) is exactly `target`, whatever the noise draw."""
    def __init__(self, target):
        super().__init__()
        self.target = target

    def forward(self, x, t, scaffold3, condition, cond_flag):
        return (x-self.target)/t[:, None, None]


def spectral_term(estimate, real, t):
    def loss(spectral):
        torch.manual_seed(0)
        return float(flow.flow_loss(EstimateNet(estimate), real, torch.zeros(len(real), LENGTH),
                                    torch.zeros(len(real), dtype=torch.bool), torch.zeros(len(real), 10),
                                    t_dist=t, spectral=spectral))
    return loss(1.)-loss(0.)


def test_spectral_loss_reads_stop_band_noise_only_near_t0(monkeypatch):
    # Real windows pass the data view, so their 12-20 Hz band sits at the log floor.
    real = torch.tensor(np.stack([ppg(70+20*i, seed=i) for i in range(4)])[:, None], dtype=torch.float32)
    x0 = flow.standardize(real)
    rough = x0+1e-2*torch.randn(x0.shape, generator=torch.Generator().manual_seed(1))
    error = (flow.log_psd(rough)-flow.log_psd(x0)).square().mean(0)
    freq = np.arange(1, 201)*FS/400
    stop = (freq < .5) | (freq >= 8)
    # White noise at -40 dB: on the log scale the stop bands carry the error, not the pulse band.
    assert float(error[stop].sum()) > .9*float(error.sum())
    for t, weighted in ((.05, True), (.5, False)):
        monkeypatch.setattr(flow, "flow_times", lambda n, device, t_dist, t=t: torch.full((n,), t))
        assert spectral_term(x0, real, "uniform") == pytest.approx(0, abs=1e-6)
        assert (spectral_term(rough, real, "uniform") > .1) == weighted
    # The ramp: weight 1 - t/SPECTRAL_T.
    monkeypatch.setattr(flow, "flow_times", lambda n, device, t_dist: torch.full((n,), flow.SPECTRAL_T/2))
    half = spectral_term(rough, real, "uniform")
    monkeypatch.setattr(flow, "flow_times", lambda n, device, t_dist: torch.full((n,), 1e-4))
    assert half == pytest.approx(.5*spectral_term(rough, real, "uniform"), rel=.01)


def test_loop5_go_limits_pick_the_winner_and_can_stop_the_final():
    from ml.kaggle_multidomain import experiment_flow

    def row(arm, s_arm, wrist, eligible=True):
        return dict(arm=arm, samplers={f"{arm}_s16_w1": dict(S_arm=s_arm, wrist_Q=wrist, eligible=eligible)})
    go = experiment_flow.GO_LIMITS
    assert go == dict(wrist_Q=.601, S_arm=.487)
    # The lower S_arm fails the wrist limit, so the other arm wins.
    picked = experiment_flow.select_pilot([row("F7_flow_unif_stop1", .45, .70), row("F8_flow_unif_stop3", .47, .58)], go)
    assert picked["winner"] == "F8_flow_unif_stop3_s16_w1" and picked["go_final"]
    stopped = experiment_flow.select_pilot([row("F7_flow_unif_stop1", .49, .55), row("F8_flow_unif_stop3", .45, .62),
                                            row("F6_flow_flag_deriv_unif", .40, .50, eligible=False)], go)
    assert stopped["winner"] is None and not stopped["go_final"]
    # Without limits (loops 1-4) the selection is unchanged and carries no go fields.
    assert "go_final" not in experiment_flow.select_pilot([row("F7_flow_unif_stop1", .45, .70)])


def test_final_runs_at_most_two_seeds_at_a_time():
    from ml.kaggle_multidomain import experiment_flow
    assert experiment_flow.final_devices([42, 123, 2026]) == ["cuda:0", "cuda:1"]
    assert experiment_flow.final_devices([42]) == ["cuda:0"]
    assert experiment_flow.final_devices([42, 123, 2026], allow_cpu=True) == ["cpu"]


def test_loop6_arms_only_lower_the_stop_band_weight():
    from ml.kaggle_multidomain import experiment_flow
    loop5 = experiment_v3.config("F7_flow_unif_stop1")
    for arm, weight in (("F9_flow_unif_stop03", .3), ("F10_flow_unif_stop01", .1)):
        assert experiment_v3.config(arm) == dict(loop5, spectral=weight)
        assert experiment_v3.config(f"{arm}_s16_w1") == dict(experiment_v3.config("F7_flow_unif_stop1_s16_w1"), spectral=weight)
        assert arm in experiment_flow.DESCRIPTION
    # "F10_..." must not resolve to the F1 base by prefix.
    assert experiment_flow.base_of("F10_flow_unif_stop01_s16_w1") == "F10_flow_unif_stop01"
    assert experiment_flow.base_of("F1_flow_s16_w1") == "F1_flow"


def test_loop5_pilot_trains_with_the_spectral_loss_and_gates_the_final(tmp_path, monkeypatch):
    from ml.kaggle_multidomain import experiment_flow
    assert experiment_v3.config("F7_flow_unif_stop1_s16_w1")["spectral"] == 1.
    assert experiment_v3.config("F8_flow_unif_stop3")["spectral"] == 3. and experiment_v3.config("F8_flow_unif_stop3")["spectral_stop"]
    assert experiment_v3.config("F6_flow_flag_deriv_unif_s16_w1")["spectral"] == 0.
    for name, value in (("CONTROL_N", 1), ("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
        monkeypatch.setattr(experiment_v3, name, value)
    monkeypatch.setattr(experiment_flow, "CONTROL_N", 1)
    monkeypatch.setitem(experiment_v3.ARMS, "F7_flow_unif_stop1", dict(experiment_v3.ARMS["F7_flow_unif_stop1"], width=.25))
    monkeypatch.setitem(experiment_v3.ARMS, "F7_flow_unif_stop1_s16_w1",
                        dict(experiment_v3.ARMS["F7_flow_unif_stop1_s16_w1"], width=.25, sample_steps=2))
    seen = []
    real_loss = experiment_flow.flow_loss

    def spy(*args, **kwargs):
        seen.append((kwargs["spectral"], kwargs["spectral_stop"], kwargs["input_noise"]))
        return real_loss(*args, **kwargs)
    monkeypatch.setattr(experiment_flow, "flow_loss", spy)
    save_v3(tmp_path/"input"/"pack", v3_pack())
    common = ["--input-root", str(tmp_path/"input"), "--allow-cpu", "--batch", "4", "--interval", "2",
              "--eval-samples", "12", "--steps", "2"]
    experiment_flow.main(common+["--stage", "pilot", "--arms", "F7_flow_unif_stop1", "--samplers",
                                 "F7_flow_unif_stop1_s16_w1", "--go", "--output", str(tmp_path/"pilot")])
    assert seen == [(1., True, 0.)]*2
    selection = json.loads((tmp_path/"pilot"/"PILOT_SELECTION_FLOW.json").read_text())
    assert selection["go_limits"] == experiment_flow.GO_LIMITS and "wrist_Q" in selection["candidates"][0]
    # A two-step net is far from the wrist limit: no go, and the gated final refuses to start.
    assert not selection["go_final"]
    fake_round9(tmp_path/"r9")
    with pytest.raises(ValueError, match="go limits"):
        experiment_flow.main(common+["--stage", "final", "--pilot-root", str(tmp_path/"pilot"), "--incumbent-root",
                                     str(tmp_path/"r9"), "--seeds", "42", "--go", "--arm", "F7_flow_unif_stop1_s16_w1",
                                     "--output", str(tmp_path/"final")])


class NoiseNet(torch.nn.Module):
    """Predicts x_t / t: the exact velocity when x0 = 0 and the input is unperturbed."""
    def forward(self, x, t, scaffold3, condition, cond_flag):
        return x/t[:, None, None]


def test_input_noise_perturbs_the_input_but_not_the_target(monkeypatch):
    monkeypatch.setattr(flow, "flow_times", lambda n, device, t_dist: torch.full((n,), .5))
    flat = torch.full((64, 1, LENGTH), .5)              # standardises to x0 = 0, so x_t = t * noise (+ perturbation)
    args = (flat, torch.zeros(64, LENGTH), torch.zeros(64, dtype=torch.bool), torch.zeros(64, 10))
    torch.manual_seed(0)
    assert float(flow.flow_loss(NoiseNet(), *args)) < 1e-10
    # The target stays noise - x0, so the extra input noise shows up as an irreducible gamma^2 error.
    torch.manual_seed(0)
    assert float(flow.flow_loss(NoiseNet(), *args, input_noise=.3)) == pytest.approx(.09, rel=.03)


def test_stop_band_loss_ignores_the_pulse_band():
    real = torch.tensor(np.stack([ppg(70+20*i, seed=i) for i in range(4)])[:, None], dtype=torch.float32)
    x0 = flow.standardize(real)
    weight = flow.stop_band_weight().numpy()
    freq = np.arange(1, 201)*FS/400
    assert weight[(freq >= 1) & (freq <= 5)].max() < .01 and weight[freq >= 12].min() > .99
    # A pulse-band change (a 3 Hz tone) moves the full-band error but barely the stop-band one.
    tone = x0+.3*torch.sin(2*np.pi*3*torch.arange(LENGTH)/FS)
    full = (flow.log_psd(tone)-flow.log_psd(x0)).square()
    w = torch.tensor(weight)
    assert float((full*w).sum(-1).mean()/w.sum()) < .1*float(full.mean())
