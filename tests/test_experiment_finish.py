"""experiment_finish on CPU with tiny judge budgets: every source judged on both splits, rule saved before the test."""
import json

import pytest
import torch

from ml.kaggle_multidomain import experiment_finish as ef, experiment_v3, strict_judge as sj
from test_flowgan import flow_bundle
from test_physiomix_v2 import save_v3, v3_pack

torch.set_num_threads(2)


@pytest.mark.parametrize("round_", ["v1", "v2"])
def test_round_on_cpu(tmp_path, monkeypatch, round_):
    for name, value in (("PER_DOMAIN_TRAIN", 8), ("PER_DOMAIN_INNER", 4), ("PER_DOMAIN_EVAL", 4), ("EVAL_EVERY", 2)):
        monkeypatch.setattr(sj, name, value)
    for kind in ("probe", "strict"):
        monkeypatch.setitem(sj.JUDGES, kind, dict(sj.JUDGES[kind], steps=2, batch=4))
    pack = v3_pack()
    save_v3(tmp_path/"input"/"pack", pack)
    flow_bundle(tmp_path/"input"/"app", {k: v[pack["split"] != "external"] for k, v in pack.items()})
    summary = ef.main(["--input-root", str(tmp_path/"input"), "--output", str(tmp_path/"out"), "--allow-cpu",
                       "--judge-seeds", "0", "--round", round_])
    out = tmp_path/"out"
    frozen = json.loads((out/"FROZEN_FINISH.json").read_text())
    decision = json.loads((out/"DECISION_FINISH.json").read_text())
    assert frozen["rule_sha256"] == decision["rule_sha256"] == ef.rule_sha256()
    assert set(decision["candidates"]) == set(ef.ROUNDS[round_]) and decision["round"] == round_
    expected = {*ef.REFERENCES, *ef.ROUNDS[round_], "real_other_people"}
    for split in ("validation", "test"):
        rows = json.loads((out/split/"physiomix"/"judges.json").read_text())
        assert {r["source"] for r in rows if r["judge"] == "strict"} == expected
        assert set(summary[split]["strict"]) == expected
    for v in decision["candidates"].values():
        assert v["finish_gain"] == pytest.approx(decision["references"][v["base"]]-v["mean_auc"])
    assert json.loads((out/"COMPLETE.json").read_text())["deployment"] == "research_only"
