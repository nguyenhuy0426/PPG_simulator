"""Strict round end to end on CPU (synthetic v3 pack, a fake app bundle, tiny budgets) and its decision rule."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest
import torch

from ml.kaggle_lsm import lsm_multiset
from ml.kaggle_lsm.train_lsm import LENGTH, make_networks
from ml.kaggle_multidomain import experiment_strict as es, experiment_v3, physio, strict_judge as sj
from test_physiomix_v2 import save_v3, v3_pack

torch.set_num_threads(1)


def fake_bundle(folder, pack):
    """App-like manifest with a traced round-9 PhysioMix (untrained) and an untrained author LSM-GAN."""
    folder.mkdir(parents=True)
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    conditions = physio.Conditions(development, "v2")
    generator, _ = experiment_v3.build(experiment_v3.config(es.INCUMBENT_ARM), conditions)
    z, c = torch.randn(2, LENGTH), torch.tensor(conditions.bank[:2])
    torch.jit.trace(generator.eval(), (z, c)).save(str(folder/"physiomix_generator.ts"))
    torch.jit.trace(make_networks()[0].eval(), z).save(str(folder/"lsm_generator.ts"))
    # Any (z, condition) TorchScript stands in for the app's PhysioFlow sampler.
    (folder/"physioflow_generator.ts").write_bytes((folder/"physiomix_generator.ts").read_bytes())
    sha = lambda name: hashlib.sha256((folder/name).read_bytes()).hexdigest()
    schema = dict(domains=conditions.domains, center=conditions.center.tolist(), scale=conditions.scale.tolist())
    manifest = dict(models={k: dict(file=f"{k}.ts", sha256=sha(f"{k}.ts"))
                            for k in ("physiomix_generator", "physioflow_generator", "lsm_generator")},
                    physiomix=schema, physioflow=schema)
    (folder/"manifest.json").write_text(json.dumps(manifest))


def test_strict_arms_are_the_round9_recipe_with_only_the_critic_and_the_quiet_generator_changed():
    old = experiment_v3.config(es.INCUMBENT_ARM)
    changed = lambda arm: {k for k, v in experiment_v3.config(arm).items() if v != old.get(k)}
    assert changed(es.PHYSIOMIX_ARMS[0]) == {"critic", "d_clip"}
    assert changed(es.PHYSIOMIX_ARMS[1]) == {"critic", "d_clip", "quiet", "sensor"}
    conditions = physio.Conditions(v3_pack(), "v2")
    generator, critic = experiment_v3.build(experiment_v3.config(es.PHYSIOMIX_ARMS[1]), conditions)
    assert isinstance(critic, sj.StrictCritic) and generator.quiet and generator.with_sensor
    assert critic(torch.rand(4, 1, LENGTH), torch.tensor(conditions.bank[:4])).shape == (4, 3)


def test_strict_critic_input_gradient_stays_bounded():
    # Lazy R1 penalises ||dD/dx||^2 on real windows; the GroupNorm judge blocks gave ~7e3 at initialisation.
    torch.manual_seed(0)
    critic = sj.StrictCritic(11)
    t = torch.arange(LENGTH)/40
    x = (.5+.4*torch.sin(2*math.pi*1.2*t)+.02*torch.randn(8, 1, LENGTH)).requires_grad_(True)
    # Spectral norm estimates each weight's top singular value by power iteration on training-mode passes, as in training.
    with torch.no_grad():
        for _ in range(20):
            critic(x, torch.zeros(8, 11))
    critic.eval()
    grad = torch.autograd.grad(critic(x, torch.zeros(8, 11)).mean(1).sum(), x)[0]
    assert grad.square().flatten(1).sum(1).mean() < 100


def test_incumbent_constants_match_the_round9_outputs_when_present():
    path = Path(__file__).resolve().parents[1]/"ml/runs/physiomix9-motion-dom-result-v1/physiomix9/benchmark/training_execution.json"
    if not path.exists():
        pytest.skip("round-9 outputs are not on this machine")
    runs = sorted(json.loads(path.read_text())["runs"], key=lambda r: r["seed"])
    by_seed = {r["seed"]: r for r in runs}
    for i, seed in enumerate(es.INCUMBENT["seeds"]):
        assert by_seed[seed]["S_real_fresh"] == pytest.approx(es.INCUMBENT["S_real"][i], abs=1e-4)
        assert by_seed[seed]["C_fresh"] == pytest.approx(es.INCUMBENT["C"][i], abs=1e-4)


def rows(name, value, judge="strict"):
    return [dict(judge=judge, source=name, seed=s, auc=value+.001*s) for s in range(3)]


def test_decision_ships_only_a_clear_gain_that_keeps_realism_and_control():
    arm = es.PHYSIOMIX_ARMS[0]
    other = es.PHYSIOMIX_ARMS[1]
    training = [dict(family="physiomix", arm=a, seed=s, S_real_fresh=.35, C_fresh=.05, eligible=True)
                for a in (arm, other) for s in (1, 2, 3)]
    null = rows("real_other_people", .5)
    pm = rows("physiomix_app", .9)+null+[r for s, v in ((1, .7), (2, .72), (3, .68)) for r in rows(f"{arm}_seed{s}", v)]
    pm += [r for s in (1, 2, 3) for r in rows(f"{other}_seed{s}", .8)]
    lsm = rows("lsm_app", 1.)+null+[r for a, base in (("lsm_author_v3", .99), ("lsm_strict", .8))
                                    for s in (1, 2, 3) for r in rows(f"{a}_seed{s}", base+.01*s)]
    d = es.decide(pm, lsm, training, "strict", (1, 2, 3))
    assert d["physiomix"]["winner"] == arm and d["physiomix"]["arms"][arm]["ship_seed"] == 3
    assert d["lsm"]["winner"] == "lsm_strict" and d["lsm"]["arms"]["lsm_strict"]["ship_seed"] == 1
    worse_control = [dict(r, C_fresh=.2) for r in training]
    assert es.decide(pm, lsm, worse_control, "strict", (1, 2, 3))["physiomix"]["winner"] is None
    small_gain = rows("physiomix_app", .71)+null+[r for a in (arm, other) for s in (1, 2, 3) for r in rows(f"{a}_seed{s}", .7)]
    assert es.decide(small_gain, lsm, training, "strict", (1, 2, 3))["physiomix"]["winner"] is None
    # A judge that separates real people from real people invalidates its family's comparison.
    person_reader = [r for r in lsm if r["source"] != "real_other_people"]+rows("real_other_people", .7)
    d = es.decide(pm, person_reader, training, "strict", (1, 2, 3))
    assert d["lsm"]["winner"] is None and not d["lsm"]["null_control"]["valid"] and d["physiomix"]["winner"] == arm


def test_strict_round_runs_in_stages_on_cpu(tmp_path, monkeypatch):
    for name, value in (("CONTROL_N", 1), ("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
        monkeypatch.setattr(experiment_v3, name, value)
    for name, value in (("PER_DOMAIN_TRAIN", 8), ("PER_DOMAIN_INNER", 4), ("PER_DOMAIN_EVAL", 4), ("EVAL_EVERY", 2)):
        monkeypatch.setattr(sj, name, value)
    for kind in ("probe", "strict"):
        monkeypatch.setitem(sj.JUDGES, kind, dict(sj.JUDGES[kind], steps=2, batch=4))
    monkeypatch.setitem(lsm_multiset.RECIPES, "steps", dict(lsm_multiset.RECIPES["steps"], steps=2, every=1, batch=8))
    pack = v3_pack()
    root = tmp_path/"input"
    save_v3(root/"pack", pack)
    fake_bundle(root/"app", {k: v[pack["split"] != "external"] for k, v in pack.items()})
    common = ["--input-root", str(root), "--judge", "strict", "--allow-cpu", "--steps", "2", "--lsm-steps", "2",
              "--interval", "2", "--eval-samples", "12", "--seeds", "42", "123", "--judge-seeds", "0"]
    # The training stages are separate kernels whose outputs the judge stage mounts.
    for stage in ("train_physiomix", "train_lsm"):
        assert es.main(common+["--output", str(root/stage), "--stage", stage]) is None
    out = tmp_path/"strict"
    summary = es.main(common+["--output", str(out), "--stage", "judge"])
    assert (out/"FROZEN_STRICT.json").stat().st_mtime <= (out/"DECISION_STRICT.json").stat().st_mtime
    assert (out/"DECISION_STRICT.json").stat().st_mtime <= (out/"test"/"physiomix"/"judges.json").stat().st_mtime
    training = es.collect_training(root, json.loads((out/"FROZEN_STRICT.json").read_text()))
    # A training output with another budget is refused.
    with pytest.raises(ValueError, match="differ from this stage's"):
        es.collect_training(root, dict(json.loads((out/"FROZEN_STRICT.json").read_text()), steps=20000))
    assert sorted((r["family"], r["arm"], r["seed"]) for r in training) == sorted(
        [("physiomix", arm, s) for arm in es.PHYSIOMIX_ARMS for s in (42, 123)]+
        [("lsm", a, s) for a in es.LSM_ARMS for s in (42, 123)])
    assert {"physioflow_app", "physioflow_sensor"} <= set(summary["validation"]["strict"]["physiomix"])
    assert "physioflow_app" not in summary["test"]["strict"]["physiomix"]
    assert set(summary["validation"]["strict"]["lsm"]) == {"lsm_app", "real_other_people"}|{
        f"{a}_seed{s}" for a in es.LSM_ARMS for s in (42, 123)}
    lsm_sets = json.loads((out/"validation"/"lsm"/"sets.json").read_text())
    assert set(lsm_sets["counts"]["eval"]) == {"bidmc"}
    # Test judges are fresh: other set draw and other judge seeds than validation.
    val_rows = json.loads((out/"validation"/"lsm"/"judges.json").read_text())
    test_rows = json.loads((out/"test"/"lsm"/"judges.json").read_text())
    assert {r["seed"] for r in val_rows}.isdisjoint({r["seed"] for r in test_rows})
    assert json.loads((out/"test"/"lsm"/"sets.json").read_text())["set_seed"] != lsm_sets["set_seed"]
    assert (out/"COMPLETE.json").exists()


def test_judge_stage_refuses_training_frozen_under_another_rule(tmp_path):
    run = tmp_path/"train_lsm"
    run.mkdir()
    (run/"FROZEN_STRICT.json").write_text(json.dumps(dict(rule_sha256="0"*64)))
    (run/"training_execution.json").write_text("[]")
    with pytest.raises(ValueError, match="different strict rule"):
        es.collect_training(tmp_path)


def test_groups_give_each_physiomix_run_a_process_and_split_lsm_over_gpus():
    jobs = es.training_jobs("all", (1, 2, 3))
    work = es.groups(jobs, ["cuda:0", "cuda:1"])
    physiomix = [w for w in work if w[1][0][0] == "physiomix"]
    assert len(physiomix) == 3*len(es.PHYSIOMIX_ARMS) and all(len(j) == 1 for _, j in physiomix)
    lsm = [w for w in work if w[1][0][0] == "lsm"]
    assert sorted(d for d, _ in lsm) == ["cuda:0", "cuda:1"] and sum(len(j) for _, j in lsm) == 3*len(es.LSM_ARMS)
