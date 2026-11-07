"""experiment_strict: the strict-judge helpers the R1 and P5 rounds share (sources, summaries) and the strict critic."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest
import torch

from ml.kaggle_lsm.train_lsm import LENGTH, make_networks
from ml.kaggle_multidomain import experiment_strict as es, experiment_v3, physio, strict_judge as sj
from ml.kaggle_multidomain.experiment_flow import INCUMBENT_ARM
from test_physiomix_v2 import v3_pack

torch.set_num_threads(1)


def fake_bundle(folder, pack):
    """App-like manifest with a traced round-9 PhysioMix (untrained) and an untrained author LSM-GAN."""
    folder.mkdir(parents=True)
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    conditions = physio.Conditions(development, "v2")
    generator, _ = experiment_v3.build(experiment_v3.config(INCUMBENT_ARM), conditions)
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


def test_summaries_average_judge_seeds_and_check_the_null_range():
    out = rows("a", .7)+rows("real_other_people", .45)+rows("a", .99, judge="probe")
    assert es.mean_auc(out, "strict", "a") == pytest.approx(.701)
    assert es.spread([.7, .8]) == pytest.approx(math.sqrt(.005)) and es.spread([.7]) == 0.
    assert es.null_control(out, "strict")["valid"] and not es.null_control(rows("real_other_people", .7), "strict")["valid"]
    table = es.indistinguishable(out, "strict")
    assert set(table) == {"a", "real_other_people"}
    assert table["a"]["indistinguishable"] == pytest.approx(100*(1-abs(2*.701-1)))
    with pytest.raises(ValueError):
        es.mean_auc(out, "strict", "missing")


def test_app_sources_check_the_manifest_and_offer_only_the_packaged_slots(tmp_path):
    pack = v3_pack()
    fake_bundle(tmp_path/"app", pack)
    bank = physio.Conditions({k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}, "v2")
    sources = es.app_sources(tmp_path/"app", bank, "cpu")
    assert set(sources) == {"physiomix_app", "physioflow_app", "lsm_app"}
    # The current app ships LSM-GAN only: a manifest without the conditional slots offers lsm_app alone.
    manifest = json.loads((tmp_path/"app"/"manifest.json").read_text())
    for key in ("physiomix_generator", "physioflow_generator"):
        manifest["models"].pop(key)
    manifest.pop("physiomix"), manifest.pop("physioflow")
    (tmp_path/"app"/"manifest.json").write_text(json.dumps(manifest))
    assert set(es.app_sources(tmp_path/"app", bank, "cpu")) == {"lsm_app"}
    (tmp_path/"app"/"lsm_generator.ts").write_bytes(b"x")
    with pytest.raises(ValueError, match="checksum"):
        es.app_sources(tmp_path/"app", bank, "cpu")
