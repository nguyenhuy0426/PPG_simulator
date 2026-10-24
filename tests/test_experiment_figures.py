"""experiment_figures on CPU: it rebuilds a finished flow-GAN round's judge sets and reproduces its judge exactly."""
import json

import numpy as np
import pytest
import torch

from ml.kaggle_multidomain import experiment_figures as xf, experiment_flowgan as ef, experiment_v3, strict_judge as sj
from test_flowgan import flow_bundle
from test_physiomix_v2 import save_v3, v3_pack

torch.set_num_threads(2)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """A tiny CPU flow-GAN round, then the figure kernel on it (tiny budgets, kept for the module's tests)."""
    tmp_path = tmp_path_factory.mktemp("figures")
    with pytest.MonkeyPatch.context() as monkeypatch:
        for name, value in (("CONTROL_N", 1), ("C2ST_TRAIN", 20), ("C2ST_VALID", 10), ("C2ST_STEPS", 3)):
            monkeypatch.setattr(experiment_v3, name, value)
        for name, value in (("PER_DOMAIN_TRAIN", 8), ("PER_DOMAIN_INNER", 4), ("PER_DOMAIN_EVAL", 4), ("EVAL_EVERY", 2)):
            monkeypatch.setattr(sj, name, value)
        for kind in ("probe", "strict"):
            monkeypatch.setitem(sj.JUDGES, kind, dict(sj.JUDGES[kind], steps=2, batch=4))
        monkeypatch.setitem(experiment_v3.ARMS, "G1_flowgan", dict(experiment_v3.ARMS["G1_flowgan"], distill_every=1))
        pack = v3_pack()
        save_v3(tmp_path/"input"/"pack", pack)
        flow_bundle(tmp_path/"input"/"app", {k: v[pack["split"] != "external"] for k, v in pack.items()})
        ef.main(["--input-root", str(tmp_path/"input"), "--output", str(tmp_path/"rounds"/"flowgan"), "--allow-cpu",
                 "--steps", "2", "--interval", "2", "--eval-samples", "12", "--seeds", "42", "123", "--judge-seeds", "0"])
        index = xf.main(["--input-root", str(tmp_path), "--output", str(tmp_path/"figures"), "--allow-cpu",
                         "--seeds", "42", "123"])
        yield tmp_path, index


def test_figure_kernel_reproduces_the_rounds_judge_on_cpu(run):
    tmp_path, index = run
    out = tmp_path/"figures"
    decision = json.loads((tmp_path/"rounds"/"flowgan"/"DECISION_FLOWGAN.json").read_text())
    assert {(e["slot"], e["source"]) for e in index} == {(slot, n) for slot, names in
                                                         xf.chosen("flowgan", decision, [42, 123]).items() for n in names}
    # Same sets, prompts, noise and judge seed on the CPU: the round's validation AUC exactly.
    for e in index:
        assert e["official_auc"] == pytest.approx(e["auc"], abs=1e-9), e["source"]
        scores = np.load(out/e["file"])
        assert len(scores["logits_real"]) == len(scores["sqi_real"]) and scores["sqi_fake"].min() >= 0
        assert (out/e["file"]).with_suffix(".pt").exists()
    # Rebuilding the eval windows only (train/inner stubbed) gives the same eval fakes.
    roots = [tmp_path]
    full, _ = xf.build(*bank_of(tmp_path), "flowgan", "physiomix", ["physioflow_app"], [42, 123], roots, apps_of(tmp_path), "cpu")
    light, _ = xf.build(*bank_of(tmp_path), "flowgan", "physiomix", ["physioflow_app"], [42, 123], roots,
                        apps_of(tmp_path), "cpu", only_eval=True)
    np.testing.assert_array_equal(full["physioflow_app_eval"], light["physioflow_app_eval"])
    np.testing.assert_array_equal(full["real_eval"], light["real_eval"])
    assert not light["physioflow_app_train"].any()
    with pytest.raises(ValueError, match="not judged"):
        xf.build(*bank_of(tmp_path), "flowgan", "lsm", ["G1_flowgan_seed42"], [42, 123], roots, apps_of(tmp_path), "cpu")


def bank_of(root):
    from ml.kaggle_multidomain.data_gxu import load_input
    pack, _ = load_input(str(root/"input"), experiment_v3.PROTOCOL)
    pack = {k: v[pack["split"] != "external"] for k, v in pack.items()}
    keep = np.flatnonzero(np.isin(pack["split"], ["train", "validation"]))
    return pack, sj.ConditionsView(experiment_v3.conditions_for({k: v[keep] for k, v in pack.items()}, "v2"), keep)


def apps_of(root):
    from ml.kaggle_multidomain.experiment_strict import app_sources
    return app_sources(root/"input"/"app", bank_of(root)[1], "cpu")


def test_report_reads_the_figure_kernel(run):
    """scripts/build_gan_report.figures_section: AUC by artifact group, and saliency on rebuilt eval windows whose CPU
    logits match the kernel's (fp16 judge state)."""
    import importlib.util
    from pathlib import Path
    tmp_path, index = run
    spec = importlib.util.spec_from_file_location("build_gan_report",
                                                  Path(__file__).resolve().parents[1]/"scripts/build_gan_report.py")
    gr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gr)
    bank = gr.Bank(tmp_path/"input")
    section = gr.figures_section(tmp_path/"figures", [tmp_path], bank, tmp_path/"input"/"app", 40)
    assert len(section["entries"]) == len(index)
    for e in section["entries"]:
        assert set(e["by_group"]) == set(section["groups"]) and e["auc"] == pytest.approx(e["official_auc"], abs=1e-4)
        assert sum(e["fake_groups"].values()) == pytest.approx(100, abs=.5)
        for side in ("real", "fake"):
            view = e["saliency"][side]
            assert len(view["values"]) == 1200 and view["spans"] and 0 <= view["p_fake"] <= 1
        assert e["logit_gap"] < .05, e["source"]
