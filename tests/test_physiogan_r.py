"""P5 PhysioGAN-R: the record generator through the v3 view, the relativistic loss and penalties, the copy gate,
the round's decision rule and the round end to end on CPU."""
import json

import numpy as np
import pytest
import torch

from ml.kaggle_lsm.train_lsm import LENGTH
from ml.kaggle_multidomain import experiment_v3, flow_r, physiogan_r
from ml.kaggle_multidomain.data_r import R_LENGTH
from tests.test_physioflow_r import p1_output, r_round_input, records
from tests.test_physiomix_v2 import v3_pack

TINY = dict(latent=8, wdim=16, channels=(16, 16, 8, 8, 8, 8, 8))


def tiny(seed=0, domains=6):
    torch.manual_seed(seed)
    return physiogan_r.PhysioGANR(domains, **TINY)


def test_generator_writes_a_record_that_the_view_turns_into_a_v3_window():
    g = tiny()
    z, condition = torch.randn(4, 8), torch.rand(4, 8)
    context = torch.tensor([[0, 80], [200, 200], [120, 0], [200, 37]])
    record = g.record(z, condition, torch.Generator().manual_seed(1))
    assert record.shape == (4, R_LENGTH)
    y = g(z, condition, context, torch.Generator().manual_seed(1))
    assert y.shape == (4, 1, LENGTH) and torch.allclose(y.amin(-1), torch.zeros(4)) and torch.allclose(y.amax(-1), torch.ones(4))
    torch.testing.assert_close(y, flow_r.RView()(record[:, None], context))
    y.square().mean().backward()                      # the view is differentiable back to the first layer
    assert g.mapping[0].weight.grad.abs().sum() > 0


def test_blocks_start_as_their_upsampled_skip_path():
    block = physiogan_r.GenBlock(4, 4, 6)
    x = torch.randn(2, 4, 10)
    torch.testing.assert_close(block(x, torch.randn(2, 6), torch.randn(2, 1, 20)),
                               torch.nn.functional.interpolate(x, scale_factor=2, mode="linear", align_corners=False))


def test_windows_are_reproducible_and_follow_the_domain_context_table():
    g = tiny()
    contexts = torch.tensor([[0, 80], [200, 200]])
    cdf = torch.tensor([[1., 1.], [0., 1.]]+[[0., 1.]]*4)   # domain 0: context 0 only; the others: context 1
    onehot = np.eye(6, dtype=np.float32)[[0, 0, 1, 3]]
    a = physiogan_r.windows(g, onehot, contexts, cdf, 5, "cpu")
    b = physiogan_r.windows(g, onehot, contexts, cdf, 5, "cpu")
    assert np.array_equal(a, b) and a.shape == (4, LENGTH)
    gen = torch.Generator().manual_seed(0)
    assert physiogan_r.draw_context(torch.tensor([0, 0, 1, 3]), contexts, cdf, gen).tolist() == \
        [[0, 80], [0, 80], [200, 200], [200, 200]]


def test_relativistic_losses_and_the_zero_centred_penalty():
    real, fake = torch.tensor([[2., 0.]]), torch.tensor([[1., 1.]])
    sp = torch.nn.functional.softplus
    assert float(physiogan_r.d_loss(real, fake)) == pytest.approx(float((sp(torch.tensor(-1.))+sp(torch.tensor(1.)))/2))
    assert float(physiogan_r.g_loss(real, fake)) == pytest.approx(float((sp(torch.tensor(1.))+sp(torch.tensor(-1.)))/2))

    class Linear(torch.nn.Module):
        def forward(self, x, c):
            return torch.stack((3*x.sum((1, 2)), x.square().sum((1, 2))), 1)
    x = torch.randn(3, 1, 5)
    expected = ((3+2*x)**2).sum((1, 2)).mean()
    torch.testing.assert_close(physiogan_r.penalty(Linear(), x, None), expected)


def test_copy_gate_flags_replayed_training_windows_only():
    rng = np.random.default_rng(0)
    train = rng.standard_normal((800, 50)).astype(np.float32)
    domain, record = np.array(["a"]*400+["b"]*400), np.arange(800)//2
    replayed = physiogan_r.copy_rate(train[::4]+1e-4, domain[::4], train, domain, record)
    # Fresh draws of the same distribution sit below the 1st percentile about 1% of the time.
    fresh = physiogan_r.copy_rate(rng.standard_normal((200, 50)).astype(np.float32), domain[::4], train, domain, record)
    assert replayed["rate"] == 1. and fresh["rate"] <= .05
    assert set(replayed["per_domain"]) == {"a", "b"}


def rows_for(table):
    return [dict(judge="strict", source=n, auc=v) for n, values in table.items() for v in values]


AUC = {"real_other_people": [.45, .46, .44], "r_pipeline": [.5, .52, .51], "r1_s16": [.75, .76, .74],
       "r1_s32": [.70, .71, .69], "r1_s64": [.66, .67, .65], "r1f_s64": [.73, .74, .72]}


def test_decision_keeps_physiogan_r_only_beyond_the_best_r1_and_the_copy_gate():
    from ml.kaggle_multidomain import experiment_p5 as p5
    seeds = [42, 123]
    copies = {n: dict(passed=True) for n in [*p5.R1_SOURCES, *p5.gan_names(seeds)]}
    good = dict(AUC, **{f"{p5.GAN}_seed42": [.53, .52, .54], f"{p5.GAN}_seed123": [.55, .54, .56]})
    d = p5.decide(rows_for(good), copies, seeds)
    assert d["best_r1"] == "r1_s64" and d["kept"] == p5.GAN and d["ship_seed"] == 42 and d["target_met"]
    copies[f"{p5.GAN}_seed123"] = dict(passed=False)
    d = p5.decide(rows_for(good), copies, seeds)
    assert d["kept"] == "r1_s64" and not d["checks"]["copy_gate"] and not d["target_met"]
    copies[f"{p5.GAN}_seed123"] = dict(passed=True)
    close = dict(good, **{f"{p5.GAN}_seed42": [.65, .65, .65], f"{p5.GAN}_seed123": [.65, .65, .65]})
    assert p5.decide(rows_for(close), copies, seeds)["kept"] == "r1_s64"          # within 0.02: no gain


def test_decision_keeps_r1_s16_unless_a_variant_beats_it_and_needs_both_nulls():
    from ml.kaggle_multidomain import experiment_p5 as p5
    seeds = [42]
    copies = {n: dict(passed=True) for n in [*p5.R1_SOURCES, *p5.gan_names(seeds)]}
    table = dict(AUC, r1_s32=[.74, .74, .74], r1_s64=[.74, .75, .73], r1f_s64=[.76, .75, .77],
                 **{f"{p5.GAN}_seed42": [.9, .9, .9]})
    assert p5.decide(rows_for(table), copies, seeds)["best_r1"] == "r1_s16"
    table["r_pipeline"] = [.7, .7, .7]
    d = p5.decide(rows_for(dict(table, **{f"{p5.GAN}_seed42": [.5, .5, .5]})), copies, seeds)
    assert not d["validity"]["pipeline"] and d["kept"] == "r1_s16" and not d["target_met"]


def test_training_plan_puts_r1f_after_one_physiogan_seed():
    from ml.kaggle_multidomain import experiment_p5 as p5
    work = p5.plan([42, 123, 2026], ["cuda:0", "cuda:1"])
    assert work == {"cuda:0": [(p5.GAN, 42), (p5.GAN, 2026)], "cuda:1": [(p5.GAN, 123), (p5.R1F, p5.R1F_SEED)]}


def test_r1f_starts_from_the_teacher_and_checkpoints_on_s_real_alone():
    cfg = experiment_v3.config("R1F_flowr_ft")
    r1 = experiment_v3.config("R1_flowr")
    assert cfg["init_r1"] and cfg["select_s_real"] and cfg["r"] and cfg["lr"] == r1["lr"]/4
    assert {k: v for k, v in cfg.items() if k not in ("init_r1", "select_s_real", "lr", "schedule")} == \
        {k: v for k, v in r1.items() if k not in ("lr", "schedule")}


def test_p5_round_trains_judges_validation_before_test_and_ships_on_cpu(tmp_path, monkeypatch):
    from ml.kaggle_multidomain import experiment_flow, experiment_p5 as p5
    root = r_round_input(tmp_path, monkeypatch)
    monkeypatch.setitem(experiment_v3.ARMS, "R1F_flowr_ft", dict(experiment_v3.ARMS["R1_flowr"], init_r1=True,
                                                                 select_s_real=True))
    monkeypatch.setattr(physiogan_r, "CONFIG", TINY)
    monkeypatch.setattr(physiogan_r, "CRITIC", dict(physiogan_r.CRITIC, width=4))
    monkeypatch.setattr(physiogan_r, "TRAIN", dict(physiogan_r.TRAIN, max_steps=3, lazy=2, batch=4, warmup_ema=2,
                                                   select_every_s=0.))
    monkeypatch.setattr(physiogan_r, "SELECT", dict(physiogan_r.SELECT, steps=2, batch=4))
    monkeypatch.setattr(physiogan_r, "SELECT_SIZES", dict(fit=4, inner=2, eval=2))
    monkeypatch.setattr(p5, "R1_SOURCES", {"r1_s16": ("r1", 2), "r1_s32": ("r1", 3), "r1_s64": ("r1", 4),
                                           "r1f_s64": ("r1f", 4)})
    monkeypatch.setattr(p5, "COPY_PER_DOMAIN", 3)
    monkeypatch.setattr(p5, "VALID_RANGE", (0., 1.))
    loaded = []
    real_state = flow_r.teacher_state_r
    monkeypatch.setattr(flow_r, "teacher_state_r", lambda roots: loaded.append(list(roots)) or real_state(roots))
    teacher = p1_output(root/"p1", *records(v3_pack()))
    out = tmp_path/"round"
    args = ["--allow-cpu", "--steps", "2", "--interval", "2", "--eval-samples", "12", "--seeds", "42", "123",
            "--judge-seeds", "0"]
    summary = p5.main(["--input-root", str(root), "--output", str(out), *args])
    frozen = json.loads((out/"FROZEN_P5.json").read_text())
    assert frozen["rule_sha256"] == p5.rule_sha256() and frozen["teacher"]["seed"] == 42
    # R1F loaded its U-Net from the teacher folder (the last root), not from the input root.
    assert [str(out/"teacher")] in loaded
    for a, b in (("FROZEN_P5.json", "training_execution.json"), ("training_execution.json", "COPY_P5.json"),
                 ("COPY_P5.json", "DECISION_P5.json"), ("DECISION_P5.json", "test/judges.json")):
        assert (out/a).stat().st_mtime <= (out/b).stat().st_mtime
    expected = {"real_other_people", "r_pipeline", *p5.R1_SOURCES, f"{p5.GAN}_seed42", f"{p5.GAN}_seed123"}
    assert set(summary["validation"]) == expected and set(summary["test"]) == expected
    copies = json.loads((out/"COPY_P5.json").read_text())
    assert set(copies) >= {"validation_people", *p5.R1_SOURCES, f"{p5.GAN}_seed42"}
    d = summary["decision"]
    assert set(d["checks"]) == {"valid", "copy_gate", "auc_gain"} and d["kept"] in (p5.GAN, *p5.R1_SOURCES)
    info = json.loads((out/"ship"/"SHIP.json").read_text())
    assert info["source"] == d["kept"] and (out/"ship"/info["file"]).exists()
    assert json.loads((out/"COMPLETE.json").read_text())["status"] == "complete"
    assert teacher.exists()


def test_p5_kernel_carries_physiogan_r_and_mounts_the_p1_round(tmp_path):
    from ml.kaggle_multidomain import stage_kernel
    out = stage_kernel.stage(tmp_path/"p5", "p5_round", steps=2)
    files = json.loads((out/"source_manifest.json").read_text())["files"]
    assert {"ml/kaggle_multidomain/physiogan_r.py", "ml/kaggle_multidomain/experiment_p5.py",
            "ml/kaggle_multidomain/experiment_p4.py", "ml/kaggle_multidomain/flow_r.py"} <= set(files)
    meta = json.loads((out/"kernel-metadata.json").read_text())
    assert meta["kernel_sources"] == ["charlesday2612/ppg-physioflow-r-round-v1"] and meta["enable_gpu"]
    assert meta["machine_shape"] == "NvidiaTeslaT4" and "charlesday2612/ppg-physioflow-r-data-v1" in meta["dataset_sources"]
    assert "experiment_p5 import main" in (out/"run.py").read_text()
