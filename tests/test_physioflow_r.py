"""P1 PhysioFlow-R: resample-only targets, the exact record-context v3 view, and the R1 arm end to end on CPU."""
import hashlib
import json

import numpy as np
import pytest
from scipy.signal import sosfiltfilt
import torch

from ml.kaggle_lsm.train_lsm import LENGTH, make_networks, normalize
from ml.kaggle_multidomain import data, data_r, experiment_v3, flow_r, physio
from ml.kaggle_multidomain.flow import FlowGenerator
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


def flow_bundle(folder, pack):
    """App-like bundle as the P1 round judged it (PhysioFlow was its incumbent): traced untrained round-9 PhysioMix, untrained author LSM-GAN, an exported untrained PhysioFlow."""
    folder.mkdir(parents=True)
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    c = physio.Conditions(development, "v2")
    size = c.bank.shape[1]
    z, rows = torch.randn(2, LENGTH), torch.tensor(c.bank[:2])
    generator, _ = experiment_v3.build(experiment_v3.config("L3_rel_beat_lr_crop_r1w_motion_dom"), c)
    torch.jit.trace(generator.eval(), (z, rows)).save(str(folder/"physiomix_generator.ts"))
    torch.jit.trace(make_networks()[0].eval(), z).save(str(folder/"lsm_generator.ts"))
    torch.manual_seed(5)
    flow = FlowGenerator(size, c.center, c.scale, sample_steps=2, flag_scaffold=True).eval()
    flow.export(z, rows).save(str(folder/"physioflow_generator.ts"))
    sha = lambda name: hashlib.sha256((folder/name).read_bytes()).hexdigest()
    schema = dict(domains=c.domains, center=c.center.tolist(), scale=c.scale.tolist())
    manifest = dict(models={k: dict(file=f"{k}.ts", sha256=sha(f"{k}.ts"))
                            for k in ("physiomix_generator", "physioflow_generator", "lsm_generator")},
                    physiomix=schema, physioflow=schema)
    (folder/"manifest.json").write_text(json.dumps(manifest))
    return flow


def r_round_input(tmp_path, monkeypatch):
    """A tiny v3 pack, its R pack and app bundle with judges and training cut to a few steps."""
    from ml.kaggle_multidomain import experiment_flow
    from ml.kaggle_multidomain import strict_judge as sj
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


def test_scoring_slot_admits_one_worker_at_a_time(tmp_path):
    import subprocess
    import sys
    probe = ("import fcntl, sys\n"
             "with open(sys.argv[1], 'w') as f:\n"
             "    try:\n"
             "        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
             "    except BlockingIOError:\n"
             "        sys.exit(3)\n")
    lock = str(tmp_path/".scoring.lock")
    with experiment_v3.scoring_slot(tmp_path):
        assert subprocess.run([sys.executable, "-c", probe, lock]).returncode == 3
    assert subprocess.run([sys.executable, "-c", probe, lock]).returncode == 0


def test_r_round_trains_with_one_worker_per_gpu(tmp_path, monkeypatch):
    from concurrent.futures import Future
    from ml.kaggle_multidomain import experiment_r
    calls = []

    class Pool:
        def __init__(self, workers, mp_context=None):
            calls.append(("workers", workers))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, fn, device, seeds, *args):
            calls.append((device, list(seeds)))
            future = Future()
            future.set_result([dict(seed=s) for s in seeds])
            return future

    monkeypatch.setattr(experiment_r, "ProcessPoolExecutor", Pool)
    rows = experiment_r.train_all([42, 123, 2026], ["cuda:0", "cuda:1"], "in", tmp_path, 2, 2, 4, None)
    assert calls == [("workers", 2), ("cuda:0", [42, 2026]), ("cuda:1", [123])]
    assert sorted(r["seed"] for r in rows) == [42, 123, 2026]


def test_deployment_gates_compare_without_an_autograd_graph(tmp_path, monkeypatch):
    # A graph through every sampler step held ~10 GB of host RAM for 5 samples and killed the P1 scoring workers.
    pack, recs = records(v3_pack())
    g, c = r1_teacher(tmp_path/"teacher", pack, recs)
    seen = []
    compare = torch.testing.assert_close

    def check(a, b, **kwargs):
        seen.append((a.requires_grad, b.requires_grad))
        compare(a, b, **kwargs)

    monkeypatch.setattr(torch.testing, "assert_close", check)
    experiment_v3.deployment_gates(g, c)
    assert len(seen) >= 3 and not any(a or b for a, b in seen)


def p1_output(folder, pack, recs, ship_seed=42, winner=None):
    """The P1 round's output as P4 mounts it: DECISION_R.json and the ship seed's export (an untrained R1)."""
    from ml.kaggle_multidomain import experiment_r
    run = folder/"benchmark"/f"{experiment_r.ARM}_seed{ship_seed}"
    r1_teacher(run, pack, recs)
    (run/flow_r.TEACHER_R_FILE).rename(run/"generator_cpu.ts")
    (folder/"DECISION_R.json").write_text(json.dumps(dict(
        ship_seed=ship_seed, winner=winner, rule_sha256=experiment_r.rule_sha256(), auc_by_seed={"42": .9}, C=.2)))
    return run/"generator_cpu.ts"


def test_resolve_teacher_needs_an_eligible_p1_seed_and_its_own_ship_file(tmp_path):
    from ml.kaggle_multidomain import experiment_r
    pack, recs = records(v3_pack())
    (tmp_path/"a").mkdir()
    (tmp_path/"a"/"DECISION_R.json").write_text(json.dumps(dict(ship_seed=None)))
    with pytest.raises(ValueError, match="no eligible seed"):
        experiment_r.resolve_teacher(tmp_path/"a", tmp_path/"ta")
    p1_output(tmp_path/"b", pack, recs, winner="R1_flowr")
    (tmp_path/"b"/"ship").mkdir()
    (tmp_path/"b"/"ship"/flow_r.TEACHER_R_FILE).write_bytes(b"other")
    with pytest.raises(ValueError, match="not its ship seed"):
        experiment_r.resolve_teacher(tmp_path/"b", tmp_path/"tb")
