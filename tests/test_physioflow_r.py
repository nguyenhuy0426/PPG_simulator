"""P1 PhysioFlow-R: resample-only targets, the exact record-context v3 view, and the R1 arm end to end on CPU."""
import json

import numpy as np
import pytest
from scipy.signal import sosfiltfilt
import torch

from ml.kaggle_lsm.train_lsm import LENGTH, normalize
from ml.kaggle_multidomain import data, data_r, experiment_v3, flow_r
from ml.kaggle_multidomain.data_r import CONTEXT, R_LENGTH
from tests.test_physiomix_v2 import save_v3, v3_pack


def records(pack, seed=0):
    """A resample-only record behind every non-external window of a v3 test pack, and the pack rebuilt from them."""
    rng = np.random.default_rng(seed)
    pack = {k: v.copy() for k, v in pack.items()}
    out = {}
    for i in np.flatnonzero(pack["split"] != "external"):
        # PERform-Large-like rows: a 32 s record holding one window at 0; the others sit inside a 50 s record.
        short = pack["domain"][i] == "perform_large"
        start = 0 if short else CONTEXT+int(rng.integers(0, 2*CONTEXT))
        n = LENGTH+81 if short else start+LENGTH+CONTEXT+int(rng.integers(0, 40))
        # The window's own pulse train continued periodically around it (keeps each row's rate), plus drift.
        wave = np.resize(np.roll(pack["signal"][i], start), n)+.2*np.sin(2*np.pi*.1*np.arange(n)/40)
        out[i] = (wave, start)
        pack["signal"][i] = normalize(sosfiltfilt(flow_r.v3_sos(), wave)[start:start+LENGTH])
        pack["start"][i] = start
    return pack, out


def save_r(path, pack, recs):
    rows = np.array(sorted(recs))
    signal, context = zip(*(data_r.cut(*recs[i]) for i in rows))
    path.mkdir(parents=True)
    np.savez_compressed(path/"r_windows.npz", index=rows, record=pack["record"][rows],
                        start=np.array([recs[i][1] for i in rows]), signal=np.array(signal, np.float32),
                        context=np.array(context, np.int16))
    (path/"manifest.json").write_text(json.dumps(dict(
        protocol=data_r.PROTOCOL, base_windows_sha256=data.digest(path.parent/"pack"/"windows.npz"),
        windows_sha256=data.digest(path/"r_windows.npz"))))


def test_sosfiltfilt_matches_scipy_for_rows_of_different_lengths():
    rng = np.random.default_rng(0)
    lengths = np.array([LENGTH, LENGTH+81, LENGTH+200, LENGTH+201, R_LENGTH])
    x = np.zeros((len(lengths), R_LENGTH))
    for i, n in enumerate(lengths):
        x[i, :n] = np.cumsum(rng.normal(size=n))*.1+rng.normal(size=n)
    y = flow_r.SosFiltFilt(flow_r.v3_sos(), R_LENGTH).double()(torch.tensor(x), torch.tensor(lengths)).numpy()
    for i, n in enumerate(lengths):
        reference = sosfiltfilt(flow_r.v3_sos(), x[i, :n])
        assert np.abs(y[i, :n]-reference).max() < 1e-6*np.abs(reference).max()
        assert np.all(y[i, n:] == 0)


def test_r_view_of_the_real_record_context_reproduces_the_v3_window():
    pack, recs = records(v3_pack())
    rows = sorted(recs)
    signal, context = zip(*(data_r.cut(*recs[i]) for i in rows))
    view = flow_r.RView().double()
    y = view(torch.tensor(np.array(signal))[:, None], torch.tensor(np.array(context)))[:, 0].numpy()
    short = pack["domain"][rows] == "perform_large"
    assert (np.array(context)[short] == (0, 81)).all()
    # Exact where the record holds all of it (short records); within the 40 s truncation of the band-pass otherwise.
    assert np.abs(y[short]-pack["signal"][rows][short]).max() < 1e-6
    assert np.abs(y[~short]-pack["signal"][rows][~short]).max() < 1e-2


def test_targets_are_scaled_by_the_band_sd_with_a_cap():
    pack, recs = records(v3_pack())
    signal, context = map(np.array, zip(*(data_r.cut(*recs[i]) for i in sorted(recs))))
    drift = signal+50*np.linspace(0, 1, R_LENGTH)            # a baseline far above the pulse band
    for x, cap in ((signal, False), (drift, True)):
        target = flow_r.r_targets(x, context)
        assert np.allclose(target.mean(1), 0, atol=1e-5)
        sd = target.std(1)
        assert (sd <= flow_r.SCALE_CAP+1e-4).all() and (np.isclose(sd, flow_r.SCALE_CAP, rtol=1e-3).all() == cap)


def test_context_types_follow_each_domain():
    pack, recs = records(v3_pack())
    rows = np.array(sorted(recs))
    context = np.array([data_r.cut(*recs[i])[1] for i in rows])
    domains = sorted(set(pack["domain"][rows]))
    contexts, cdf = flow_r.context_table(context, pack["domain"][rows], domains)
    choice = flow_r.ContextChoice(contexts, cdf, len(domains))
    condition = torch.zeros(400, len(domains)+5)
    large = domains.index("perform_large")
    condition[:, large] = 1
    z = torch.randn(400, LENGTH, generator=torch.Generator().manual_seed(1))
    assert (choice.context(z, condition) == torch.tensor([0, 81])).all()
    assert torch.equal(choice.extend(z)[:, CONTEXT:CONTEXT+LENGTH], z)


def test_r1_arm_trains_scores_and_exports_on_cpu(tmp_path, monkeypatch):
    for name, value in (("CONTROL_N", 1), ("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
        monkeypatch.setattr(experiment_v3, name, value)
    from ml.kaggle_multidomain import experiment_flow
    monkeypatch.setattr(experiment_flow, "CONTROL_N", 1)
    monkeypatch.setitem(experiment_v3.ARMS, "R1_flowr", dict(experiment_v3.ARMS["R1_flowr"], width=.25, sample_steps=2))
    seen = []
    real_loss = experiment_flow.flow_loss

    def spy(net, real, phase, *args, **kwargs):
        seen.append((tuple(real.shape), tuple(phase.shape), kwargs["prescaled"]))
        return real_loss(net, real, phase, *args, **kwargs)
    monkeypatch.setattr(experiment_flow, "flow_loss", spy)
    pack, recs = records(v3_pack())
    save_v3(tmp_path/"input"/"pack", pack)
    save_r(tmp_path/"input"/"r", pack, recs)
    (tmp_path/"out").mkdir()
    rows = experiment_v3.worker("cpu", [("R1_flowr", 42)], str(tmp_path/"input"), tmp_path/"out", 2, 4, 2, 12, None)
    assert seen and all(s == ((4, 1, R_LENGTH), (4, R_LENGTH), True) for s in seen)
    row = rows[0]
    assert row["gates"]["trace_ok"] and row["gates"]["finite"] and not row["gates"]["flat"]
    scripted = torch.jit.load(str(tmp_path/"out"/"R1_flowr_seed42"/"generator_cpu.ts"))
    conditions = experiment_v3.conditions_for({k: v[np.isin(pack["split"], ["train", "validation"])]
                                               for k, v in pack.items()}, "v2")
    y = scripted(torch.randn(3, LENGTH), torch.tensor(conditions.prompt("perform_large", 80., .02, 3)))
    assert y.shape == (3, 1, LENGTH) and float(y.min()) == 0. and float(y.max()) == 1.


def test_r_pack_must_come_from_the_v3_pack(tmp_path):
    pack, recs = records(v3_pack())
    save_v3(tmp_path/"pack", pack)
    save_r(tmp_path/"r", pack, recs)
    r, _ = data_r.load_r(tmp_path, dict(windows_sha256=data.digest(tmp_path/"pack"/"windows.npz")))
    assert r["signal"].shape[1] == R_LENGTH
    with pytest.raises(ValueError, match="another v3 pack"):
        data_r.load_r(tmp_path, dict(windows_sha256="0"*64))


def r_round_input(tmp_path, monkeypatch):
    """A tiny v3 pack, its R pack and app bundle with judges and training cut to a few steps."""
    from ml.kaggle_multidomain import experiment_flow
    from ml.kaggle_multidomain import strict_judge as sj
    from tests.test_flowgan import flow_bundle
    for name, value in (("CONTROL_N", 1), ("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
        monkeypatch.setattr(experiment_v3, name, value)
    monkeypatch.setattr(experiment_flow, "CONTROL_N", 1)
    for name, value in (("PER_DOMAIN_TRAIN", 8), ("PER_DOMAIN_INNER", 4), ("PER_DOMAIN_EVAL", 4), ("EVAL_EVERY", 2)):
        monkeypatch.setattr(sj, name, value)
    for kind in ("probe", "strict"):
        monkeypatch.setitem(sj.JUDGES, kind, dict(sj.JUDGES[kind], steps=2, batch=4))
    monkeypatch.setitem(experiment_v3.ARMS, "R1_flowr", dict(experiment_v3.ARMS["R1_flowr"], width=.25, sample_steps=2))
    pack, recs = records(v3_pack())
    root = tmp_path/"input"
    save_v3(root/"pack", pack)
    save_r(root/"r", pack, recs)
    flow_bundle(root/"app", {k: v[pack["split"] != "external"] for k, v in pack.items()})
    return root


R_ROUND_ARGS = ["--allow-cpu", "--steps", "2", "--interval", "2", "--eval-samples", "12", "--seeds", "42", "123",
                "--judge-seeds", "0"]


def test_r_round_freezes_its_rule_then_judges_validation_before_test_on_cpu(tmp_path, monkeypatch):
    from ml.kaggle_multidomain import experiment_r
    root = r_round_input(tmp_path, monkeypatch)
    # A 2-step judge's null is noise; open the gate so the whole round runs.
    monkeypatch.setattr(experiment_r, "VALID_RANGE", (0., 1.))
    out = tmp_path/"round"
    summary = experiment_r.main(["--input-root", str(root), "--output", str(out), *R_ROUND_ARGS])
    gate = json.loads((out/"NULL_R.json").read_text())
    assert gate["passed"] and set(gate["auc"]) == {"r_pipeline", "real_other_people"}
    assert (out/"NULL_R.json").stat().st_mtime <= (out/"training_execution.json").stat().st_mtime
    frozen = json.loads((out/"FROZEN_R.json").read_text())
    assert frozen["rule_sha256"] == experiment_r.rule_sha256()
    assert (out/"FROZEN_R.json").stat().st_mtime <= (out/"DECISION_R.json").stat().st_mtime \
        <= (out/"test"/"judges.json").stat().st_mtime
    names = set(summary["validation"]["strict"])
    assert names == {"physioflow_app", "r_pipeline", "real_other_people", "R1_flowr_seed42", "R1_flowr_seed123"}
    decision = summary["decision"]
    assert set(decision["checks"]) == {"null_valid", "pipeline_valid", "eligible", "auc_gain", "c_ok"}
    assert decision["targets"]["pooled"]["target"] == .75 and "wrist" in decision["targets"]


def test_r_round_stops_before_training_when_the_null_gate_fails(tmp_path, monkeypatch):
    from ml.kaggle_multidomain import experiment_r
    root = r_round_input(tmp_path, monkeypatch)
    monkeypatch.setattr(experiment_r, "VALID_RANGE", (2., 3.))
    out = tmp_path/"round"
    summary = experiment_r.main(["--input-root", str(root), "--output", str(out), *R_ROUND_ARGS])
    assert summary["decision"] is None and not summary["null_gate"]["passed"]
    assert json.loads((out/"COMPLETE.json").read_text())["status"] == "stopped_at_null_gate"
    assert not (out/"benchmark").exists() and not (out/"DECISION_R.json").exists()


def r1_teacher(folder, pack, recs, steps=2):
    """An exported untrained R1 generator with the test pack's context table, as the P1 round ships it."""
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    c = experiment_v3.conditions_for(development, "v2")
    rows = np.flatnonzero(np.isin(pack["split"], ["train"]))
    context = np.array([data_r.cut(*recs[i])[1] for i in rows])
    contexts, cdf = flow_r.context_table(context, pack["domain"][rows], c.domains)
    torch.manual_seed(3)
    g = flow_r.FlowGeneratorR(c.bank.shape[1], c.center, c.scale, len(c.domains), contexts, cdf, sample_steps=steps,
                              width=.25).eval()
    folder.mkdir(parents=True)
    g.export(torch.randn(2, LENGTH), torch.tensor(c.bank[:2])).save(str(folder/flow_r.TEACHER_R_FILE))
    return g, c


def test_g3_starts_at_the_r1_teacher_with_the_band_critic(tmp_path, monkeypatch):
    from ml.kaggle_multidomain import strict_judge as sj
    pack, recs = records(v3_pack())
    teacher, c = r1_teacher(tmp_path/"r1", pack, recs)
    monkeypatch.setitem(experiment_v3.ARMS, "G3_flowgan_r", dict(experiment_v3.ARMS["G3_flowgan_r"], student_steps=2,
                                                                 width=.25))
    cfg = experiment_v3.config("G3_flowgan_r")
    assert cfg["flowgan_r"] and not cfg["flowgan_sensor"] and cfg["critic_band"]
    g, d = experiment_v3.build(cfg, c)
    assert isinstance(d, sj.StrictCritic) and len(d.branches) == 4
    g.load_teacher(flow_r.teacher_state_r([tmp_path]))
    assert torch.equal(g.gen.choice.cdf, teacher.choice.cdf)
    z, rows = torch.randn(4, LENGTH), torch.tensor(c.bank[:4])
    with torch.no_grad():
        fake, clean = g.parts(z, rows)
        torch.testing.assert_close(fake, teacher(z, rows))       # same steps: the student is the teacher
        assert fake is clean
    student_teacher = g.teacher()
    assert student_teacher.flow.sample_steps == flow_r.TEACHER_STEPS
    fake = g(z, rows)
    fake.mean().backward()                                         # through the checkpointed passes and RView
    assert all(p.grad is not None for p in g.gen.flow.net.parameters() if p.requires_grad)


def test_g3_arm_trains_adversarially_and_exports_on_cpu(tmp_path, monkeypatch):
    for name, value in (("CONTROL_N", 1), ("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
        monkeypatch.setattr(experiment_v3, name, value)
    monkeypatch.setitem(experiment_v3.ARMS, "G3_flowgan_r", dict(experiment_v3.ARMS["G3_flowgan_r"], student_steps=2,
                                                                 width=.25, distill_every=1))
    pack, recs = records(v3_pack())
    root = tmp_path/"input"
    save_v3(root/"pack", pack)
    r1_teacher(root/"r1", pack, recs)
    (tmp_path/"out").mkdir()
    row = experiment_v3.worker("cpu", [("G3_flowgan_r", 42)], str(root), tmp_path/"out", 2, 4, 2, 12, None)[0]
    assert row["gates"]["trace_ok"] and row["gates"]["finite"] and not row["gates"]["flat"]
    scripted = torch.jit.load(str(tmp_path/"out"/"G3_flowgan_r_seed42"/"generator_cpu.ts"))
    assert scripted(torch.randn(2, LENGTH), torch.tensor(experiment_v3.conditions_for(
        {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}, "v2").bank[:2])).shape == \
        (2, 1, LENGTH)
