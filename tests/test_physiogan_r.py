"""P5 PhysioGAN-R: the record generator through the v3 view, the relativistic loss and penalties, the copy gate,
the round's decision rule and the round end to end on CPU."""
import json
from pathlib import Path

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


def test_ada_augment_is_identity_at_zero_and_p_follows_the_critic():
    aug = physiogan_r.Augment()
    x = torch.rand(8, 1, 64, requires_grad=True)
    assert torch.equal(aug(x), x)
    aug.adjust(1., 50_000)                                    # the critic always ranks the pair: more augmentation
    assert float(aug.p) == pytest.approx(.5)
    aug.adjust(1., 10**6)
    assert float(aug.p) == pytest.approx(physiogan_r.ADA_MAX)
    torch.manual_seed(0)
    y = aug(x)
    assert y.shape == x.shape and not torch.equal(y, x)
    y.sum().backward()                                        # differentiable for the generated windows
    assert x.grad.abs().sum() > 0
    aug.adjust(-1., 10**7)
    assert float(aug.p) == 0.


def test_penalties_differentiate_twice_through_the_augmentation():
    # grid_sample's backward has no derivative: the first P5 v2 kernel failed at its first R1 step with p > 0.
    from ml.kaggle_multidomain import strict_judge as sj
    d = physiogan_r.Balanced(sj.StrictCritic(8, **dict(physiogan_r.CRITIC, width=4))).train()
    d.augment.p.fill_(physiogan_r.ADA_MAX)
    x, c = torch.rand(4, 1, LENGTH), torch.rand(4, 8)
    value = physiogan_r.penalty(d, x, c)
    value.backward()
    assert torch.isfinite(value) and any(p.grad is not None for p in d.critic.parameters())


def test_stretch_is_identity_at_one_and_holds_the_centre():
    x = torch.randn(3, 1, 101)
    torch.testing.assert_close(physiogan_r.stretch(x, torch.ones(3, 1, 1)), x)
    y = physiogan_r.stretch(x, torch.full((3, 1, 1), 1.1))
    torch.testing.assert_close(y[..., 50], x[..., 50])
    assert torch.equal(y[..., 0], x[..., 0]) and torch.equal(y[..., -1], x[..., -1])


def test_direct_comparison_reports_each_distance_next_to_real_vs_real():
    from ml.kaggle_multidomain import waveform_compare
    rng = np.random.default_rng(0)
    t = np.arange(LENGTH)/40
    real = lambda n, hz: np.array([np.sin(2*np.pi*(hz+.1*rng.standard_normal())*t)+.05*rng.standard_normal(LENGTH)
                                   for _ in range(n)])
    norm = lambda x: ((x-x.min(1, keepdims=True))/np.ptp(x, 1, keepdims=True)).astype(np.float32)
    target, reference = norm(real(20, 1.2)), norm(real(20, 1.2))
    close, far = norm(real(20, 1.2)), norm(real(20, 2.5))
    dom = np.array(["bidmc"]*20)
    out = waveform_compare.compare(dict(close=(close, dom), far=(far, dom)), target, dom, reference, dom)
    s = out["summary"]
    assert set(s) == {"real_train_people", "close", "far"}
    assert s["far"]["psd_pulse"] > s["close"]["psd_pulse"] and s["far"]["acf"] > s["close"]["acf"]
    assert s["far"]["ratio_to_real"]["acf"] > 2


def test_p5_train_stage_previews_then_the_judge_stage_judges_validation_before_test_on_cpu(tmp_path, monkeypatch):
    from ml.kaggle_multidomain import experiment_p5 as p5
    root = r_round_input(tmp_path, monkeypatch)
    monkeypatch.setitem(experiment_v3.ARMS, "R1F_flowr_ft", dict(experiment_v3.ARMS["R1_flowr"], init_r1=True,
                                                                 select_s_real=True))
    monkeypatch.setattr(physiogan_r, "CONFIG", TINY)
    monkeypatch.setattr(physiogan_r, "CRITIC", dict(physiogan_r.CRITIC, width=4))
    monkeypatch.setattr(physiogan_r, "TRAIN", dict(physiogan_r.TRAIN, max_steps=4, lazy=2, batch=4, warmup_ema=2,
                                                   select_every_s=0., log_every=2))
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
    train = root/"p5_train"
    args = ["--allow-cpu", "--steps", "2", "--interval", "2", "--eval-samples", "12", "--seeds", "42", "123",
            "--judge-seeds", "0"]
    with pytest.raises(ValueError, match="Expected one FROZEN_P5"):
        p5.main(["--input-root", str(root), "--output", str(tmp_path/"early"), "--stage", "judge", *args])
    result = p5.main(["--input-root", str(root), "--output", str(train), "--stage", "train", *args])
    frozen = json.loads((train/"FROZEN_P5.json").read_text())
    assert frozen["rule_sha256"] == p5.rule_sha256() and frozen["teacher"]["seed"] == 42
    assert [str(train/"teacher")] in loaded          # R1F's U-Net from the teacher folder, not the input root
    assert not (train/"validation").exists() and not (train/"DECISION_P5.json").exists()   # no judge before review
    names = {*p5.R1_SOURCES, f"{p5.GAN}_seed42", f"{p5.GAN}_seed123"}
    assert set(result["summary"]) == {"real_train_people", *names} and set(result["copy"]) == names
    assert all(Path(f).exists() for f in result["figures"]) and (train/"preview"/"samples.npz").exists()
    balance = json.loads((train/"benchmark"/f"{p5.GAN}_seed42"/"balance.json").read_text())
    assert balance and {"rt", "p", "loss_d", "loss_g", "margin"} <= set(balance[-1])
    assert json.loads((train/"COMPLETE.json").read_text())["status"] == "train_complete"

    out = tmp_path/"judge"
    summary = p5.main(["--input-root", str(root), "--output", str(out), "--stage", "judge", *args])
    for a, b in (("FROZEN_P5.json", "DECISION_P5.json"), ("DECISION_P5.json", "test/judges.json")):
        assert (out/a).stat().st_mtime <= (out/b).stat().st_mtime
    expected = {"real_other_people", "r_pipeline", *names}
    assert set(summary["validation"]) == expected and set(summary["test"]) == expected
    d = summary["decision"]
    assert set(d["checks"]) == {"valid", "copy_gate", "auc_gain"} and d["kept"] in (p5.GAN, *p5.R1_SOURCES)
    info = json.loads((out/"ship"/"SHIP.json").read_text())
    assert info["source"] == d["kept"] and (out/"ship"/info["file"]).exists()
    assert json.loads((out/"COMPLETE.json").read_text())["status"] == "complete"
    assert teacher.exists()


@pytest.mark.parametrize("mode", ["p5_train", "p5_judge"])
def test_p5_kernels_run_on_one_account_with_the_p1_output_as_a_dataset(tmp_path, mode):
    from ml.kaggle_multidomain import stage_kernel
    out = stage_kernel.stage(tmp_path/mode, mode, steps=2, owner="halovie2412")
    files = json.loads((out/"source_manifest.json").read_text())["files"]
    assert {"ml/kaggle_multidomain/physiogan_r.py", "ml/kaggle_multidomain/experiment_p5.py",
            "ml/kaggle_multidomain/waveform_compare.py", "ml/kaggle_multidomain/experiment_p4.py"} <= set(files)
    meta = json.loads((out/"kernel-metadata.json").read_text())
    sources = meta["kernel_sources"]+meta["dataset_sources"]
    assert all(s.startswith("halovie2412/") for s in sources) and meta["enable_gpu"]
    assert meta["machine_shape"] == "NvidiaTeslaT4" and "halovie2412/ppg-physioflow-r-data-v1" in sources
    stage = mode.split("_")[1]
    assert f"'--stage', '{stage}'" in (out/"run.py").read_text()
    if stage == "train":
        assert meta["kernel_sources"] == [] and "halovie2412/ppg-physioflow-r-p1-output-v1" in sources
    else:
        assert meta["kernel_sources"] == ["halovie2412/ppg-physiogan-r-p5-train-v1"]


def test_p1_output_dataset_keeps_the_layout_resolve_teacher_reads(tmp_path):
    import hashlib
    from ml.kaggle_multidomain import experiment_p4, stage_kernel
    pack, recs = records(v3_pack())
    export = p1_output(tmp_path/"r_round", pack, recs)
    (tmp_path/"r_round"/"FROZEN_R.json").write_text("{}")
    folder = stage_kernel.stage_p1_output(tmp_path/"staged", "halovie2412", tmp_path/"r_round")
    teacher = experiment_p4.resolve_teacher(folder, tmp_path/"teacher")
    assert teacher["seed"] == 42 and teacher["sha256"] == hashlib.sha256(export.read_bytes()).hexdigest()
    assert json.loads((folder/"dataset-metadata.json").read_text())["id"] == "halovie2412/ppg-physioflow-r-p1-output-v1"
