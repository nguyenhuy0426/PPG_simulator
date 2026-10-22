"""PhysioFlow-GAN (flow_gan) and the flow-GAN round (experiment_flowgan) on CPU."""
import hashlib
import json

import numpy as np
import pytest
import torch

from ml.kaggle_lsm.train_lsm import LENGTH, make_networks
from ml.kaggle_multidomain import experiment_flowgan as ef, experiment_v3, flow_gan, physio, strict_judge as sj
from ml.kaggle_multidomain.flow import FlowGenerator
from test_physiomix_v2 import save_v3, v3_pack

torch.set_num_threads(2)


def conditions():
    pack = v3_pack()
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    return physio.Conditions(development, "v2")


def flow_bundle(folder, pack):
    """App-like bundle: traced untrained round-9 PhysioMix, untrained author LSM-GAN, an exported untrained PhysioFlow."""
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


def test_flowgan_starts_at_the_teacher_and_its_sensor_term_trains(tmp_path):
    c = conditions()
    pack = v3_pack()
    teacher_flow = flow_bundle(tmp_path/"app", {k: v[pack["split"] != "external"] for k, v in pack.items()})
    g, d = experiment_v3.build(experiment_v3.config("G1_flowgan"), c)
    assert isinstance(d, sj.StrictCritic)
    g.load_teacher(flow_gan.teacher_state([tmp_path]))
    for name, value in teacher_flow.net.state_dict().items():
        assert torch.equal(g.flow.net.state_dict()[name], value)
    teacher = g.teacher()
    assert teacher.sample_steps == flow_gan.TEACHER_STEPS and not any(p.requires_grad for p in teacher.parameters())
    z, rows = torch.randn(3, LENGTH), torch.tensor(c.bank[:3])
    assert torch.allclose(g.sensor_sigma(rows), torch.full((3,), flow_gan.SENSOR_INIT))
    fake, clean = g.parts(z, rows)
    assert fake.shape == clean.shape == (3, 1, LENGTH)
    assert float(fake.amin()) >= 0 and float(fake.amax()) <= 1 and not torch.equal(fake, clean)
    fake.square().mean().backward()
    assert g.sensor_raw.grad.abs().sum() > 0
    assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in g.flow.net.parameters())
    # A tampered teacher file is refused.
    (tmp_path/"app"/"physioflow_generator.ts").write_bytes(b"x")
    with pytest.raises(ValueError, match="checksum"):
        flow_gan.teacher_state([tmp_path])


def test_flowgan_export_matches_the_eager_generator():
    c = conditions()
    g, _ = experiment_v3.build(experiment_v3.config("G1_flowgan"), c)
    g.eval()
    with torch.no_grad():
        g.sensor_raw.copy_(torch.linspace(-3, 1, len(g.sensor_raw)))
    z, rows = torch.randn(2, LENGTH), torch.tensor(c.bank[:2])
    traced = g.export(z, rows)
    for n in (1, 3):
        z, rows = torch.randn(n, LENGTH), torch.tensor(c.bank[-n:])
        with torch.no_grad():
            torch.testing.assert_close(traced(z, rows), g(z, rows))


def test_flowgan_lsm_arm_trains_on_bidmc_only_with_the_lsm_loss():
    cfg = experiment_v3.config(ef.ARMS["lsm"])
    base = experiment_v3.config(ef.ARMS["physiomix"])
    assert cfg["train_domains"] == ("bidmc",) and cfg["lsm_loss"]
    assert {k for k in cfg if cfg[k] != base.get(k)} == {"train_domains", "lsm_loss"}
    assert experiment_v3.POOL_OF["bidmc"] == "bidmc"


def rows_for(names_auc):
    return [dict(judge="strict", source=n, seed=s, auc=v) for n, v in names_auc.items() for s in (10, 11)]


def test_decision_needs_gates_a_clear_gain_a_valid_null_and_rate_control():
    seeds = [42, 123]
    base = {"physioflow_app": .9, "physioflow_sensor": .7, "real_other_people": .5}
    val = dict(physiomix=rows_for({**base, "physiomix_app": .99, "G1_flowgan_seed42": .6, "G1_flowgan_seed123": .62}),
               lsm=rows_for({**base, "lsm_app": 1., "G2_flowgan_lsm_bidmc_seed42": .99,
                             "G2_flowgan_lsm_bidmc_seed123": .995}))
    run = lambda arm, s, **k: dict(arm=arm, seed=s, eligible=True, C_fresh=.05, **k)
    training = [run(a, s) for a in ef.ARMS.values() for s in seeds]
    decision = ef.decide(val, training, seeds)
    assert decision["physiomix"]["winner"] == "G1_flowgan" and decision["physiomix"]["ship_seed"] == 42
    assert decision["lsm"]["winner"] is None and not decision["lsm"]["checks"]["auc_gain"]
    assert decision["physiomix"]["references"] == {"physioflow_app": .9, "physioflow_sensor": .7}
    slow = [run(a, s, ) if a != "G1_flowgan" else dict(run(a, s), C_fresh=.2) for a in ef.ARMS.values() for s in seeds]
    assert ef.decide(val, slow, seeds)["physiomix"]["winner"] is None
    bad_null = dict(val, physiomix=[dict(r, auc=.8) if r["source"] == "real_other_people" else r
                                    for r in val["physiomix"]])
    assert ef.decide(bad_null, training, seeds)["physiomix"]["winner"] is None


def test_flowgan_round_runs_end_to_end_on_cpu(tmp_path, monkeypatch):
    for name, value in (("CONTROL_N", 1), ("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
        monkeypatch.setattr(experiment_v3, name, value)
    for name, value in (("PER_DOMAIN_TRAIN", 8), ("PER_DOMAIN_INNER", 4), ("PER_DOMAIN_EVAL", 4), ("EVAL_EVERY", 2)):
        monkeypatch.setattr(sj, name, value)
    for kind in ("probe", "strict"):
        monkeypatch.setitem(sj.JUDGES, kind, dict(sj.JUDGES[kind], steps=2, batch=4))
    monkeypatch.setitem(experiment_v3.ARMS, "G1_flowgan", dict(experiment_v3.ARMS["G1_flowgan"], distill_every=1))
    pack = v3_pack()
    root = tmp_path/"input"
    save_v3(root/"pack", pack)
    flow_bundle(root/"app", {k: v[pack["split"] != "external"] for k, v in pack.items()})
    out = tmp_path/"flowgan"
    summary = ef.main(["--input-root", str(root), "--output", str(out), "--allow-cpu", "--steps", "2", "--interval",
                       "2", "--eval-samples", "12", "--seeds", "42", "123", "--judge-seeds", "0"])
    assert (out/"FROZEN_FLOWGAN.json").stat().st_mtime <= (out/"DECISION_FLOWGAN.json").stat().st_mtime
    assert (out/"DECISION_FLOWGAN.json").stat().st_mtime <= (out/"test"/"lsm"/"judges.json").stat().st_mtime
    training = json.loads((out/"training_execution.json").read_text())
    assert sorted((r["arm"], r["seed"]) for r in training) == sorted((a, s) for a in ef.ARMS.values() for s in (42, 123))
    assert all(r["gates"]["trace_ok"] for r in training)
    names = set(summary["validation"]["strict"]["physiomix"])
    assert names == {"physiomix_app", "physioflow_app", "physioflow_sensor", "real_other_people",
                     "G1_flowgan_seed42", "G1_flowgan_seed123"}
    assert set(json.loads((out/"validation"/"lsm"/"sets.json").read_text())["counts"]["eval"]) == {"bidmc"}
    val_rows = json.loads((out/"validation"/"lsm"/"judges.json").read_text())
    test_rows = json.loads((out/"test"/"lsm"/"judges.json").read_text())
    assert {r["seed"] for r in val_rows}.isdisjoint({r["seed"] for r in test_rows})
    assert (out/"COMPLETE.json").exists()


def test_checkpointed_student_matches_the_plain_sampler_and_its_gradients():
    """Regression (flow-GAN kernel v1 ran out of GPU memory): the checkpointed sampler is the same function."""
    import copy
    c = conditions()
    g, _ = experiment_v3.build(experiment_v3.config("G1_flowgan"), c)
    torch.manual_seed(1)
    for p in g.flow.net.out.parameters():
        p.data.normal_(0, .02)
    plain = copy.deepcopy(g)
    z, rows = torch.randn(2, LENGTH), torch.tensor(c.bank[:2])
    g.integrate(z, rows).square().mean().backward()
    plain.flow(z, rows).square().mean().backward()
    for a, b in zip(g.flow.parameters(), plain.flow.parameters()):
        if b.grad is not None:
            torch.testing.assert_close(a.grad, b.grad)
