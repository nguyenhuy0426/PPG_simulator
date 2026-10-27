"""Strict-judge helpers shared by the rounds that are still studied (experiment_r: R1, experiment_p5: P5).

Sources (the app bundle's TorchScript generators, a checkpoint's sampler, an unconditional TorchScript generator, the
sensor-noise diagnostic), the per-split judge run (judge_family) and the summaries (mean AUC, seed SD, null control,
indistinguishable). The strict round that used them first (PhysioMix with the strict critic, LSM-GAN-S and the LSM
author topology, DECISION_STRICT.json) was removed with its arms: none improved on the app models (validation AUC
0.99-1.00); its results stay in ml/runs/strict-*-result-v1 and docs/model-report, its code in git history.
Engineering evaluation of normalised 30 s PPG shape; not clinical validation, not measured on the Pi/DAC/OPT101.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import LENGTH, save_json
from ml.kaggle_multidomain import strict_judge as sj

# build_sets draw (strict_judge seed 0 was the selection kernel's) and judge-seed offsets per split.
SET_SEEDS, JUDGE_SEED_OFFSETS = dict(validation=1, test=2), dict(validation=10, test=20)
NULL_RANGE = (.4, .6)
# Diagnostic only (no decision): the app's PhysioFlow as shipped, and with white noise of this level (on its [0, 1]
# window) added before the reflection-padded data-view filter. The strict judge separated it only in 8-20 Hz (band-stop
# AUC 0.502); the level matches real training windows' 8-20 Hz power within 0.2 dB (training windows only).
FLOW_SENSOR_SIGMA = .03
# Round 9 (the shipped PhysioMix) per-seed validation scores at its chosen checkpoints, seeds 42/123/2026
# (ml/runs/physiomix9-motion-dom-result-v1/physiomix9/benchmark/training_execution.json).
INCUMBENT = dict(seeds=[42, 123, 2026], S_real=[0.3367, 0.3349, 0.3597], C=[0.0469, 0.0314, 0.0584])


def app_sources(bundle, bank, device):
    """The app's TorchScript files (physiomix_app, lsm_app, and physioflow_app when the bundle has it), checked against
    the manifest's sha256 and condition schema."""
    bundle = Path(bundle)
    manifest = json.loads((bundle/"manifest.json").read_text())
    conditional = [s for s in ("physiomix", "physioflow") if f"{s}_generator" in manifest["models"]]
    for slot in conditional:
        meta = manifest[slot]
        if meta["domains"] != bank.domains or not np.allclose(meta["center"], bank.center, rtol=1e-5) \
                or not np.allclose(meta["scale"], bank.scale, rtol=1e-5):
            raise ValueError(f"{slot}: app condition schema differs from the v3 pack's")
    for slot in conditional+["lsm"]:
        entry = manifest["models"][f"{slot}_generator"]
        if hashlib.sha256((bundle/entry["file"]).read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"{slot}_generator checksum mismatch")
    out = {f"{s}_app": sj.torchscript_generator(bundle/manifest["models"][f"{s}_generator"]["file"], device,
                                                len(bank.domains)+5) for s in conditional}
    # The app emits the LSM-GAN's raw output (core/neural_preview.py); it is judged as emitted, like the candidates.
    out["lsm_app"] = unconditional_generator(bundle/manifest["models"]["lsm_generator"]["file"])
    return out


def sensor_finished(generate, sigma=FLOW_SENSOR_SIGMA):
    """generate's windows plus white noise of level sigma, through the reflection-padded data-view filter, renormalised."""
    from ml.kaggle_multidomain.flow import FINISH_PAD, finish
    from ml.kaggle_multidomain.physio import view_mask
    band = torch.tensor(view_mask("v3", LENGTH+2*FINISH_PAD))

    def wrapped(ids, conditions, seed):
        x = torch.from_numpy(generate(ids, conditions, seed))[:, None]
        noise = torch.randn(x.shape, generator=torch.Generator().manual_seed(seed+7))
        return sj.normalise(finish(x+sigma*noise, band)[:, 0].numpy())
    return wrapped


def checkpoint_generator(run_dir, arm, bank, device):
    from ml.kaggle_multidomain.experiment_v3 import load_best, sampler
    model, cfg = load_best(arm, Path(run_dir), bank.conditions, None, device)
    run = sampler(model, cfg, device)

    def generate(ids, conditions, seed):
        z = torch.randn(len(ids), LENGTH, generator=torch.Generator().manual_seed(seed))
        return run(z, conditions.for_ids(ids)).astype(np.float32)
    return generate


def unconditional_generator(path):
    model = torch.jit.load(str(path), map_location="cpu").eval()

    def generate(ids, conditions, seed):
        z = torch.randn(len(ids), LENGTH, generator=torch.Generator().manual_seed(seed))
        with torch.inference_mode():
            return torch.cat([model(part) for part in z.split(256)])[:, 0].numpy().astype(np.float32)
    return generate


def judge_family(pack, bank, generators, split, domains, kinds, seeds, devices, folder):
    folder.mkdir(parents=True)
    arrays, info = sj.build_sets(pack, bank, generators, split, seed=SET_SEEDS[split], domains=domains,
                                 controls=("real_other_people",), eval_prompts="control_eval")
    save_json(folder/"sets.json", dict(counts=info["counts"], people={k: len(v) for k, v in info["people"].items()},
                                       set_seed=SET_SEEDS[split]))
    path = Path("/tmp" if Path("/tmp").exists() and devices != ["cpu"] else folder)/f"strict_{folder.name}.npz"
    np.savez(path, **arrays)
    jobs = [(kind, name, s+JUDGE_SEED_OFFSETS[split]) for s in seeds for kind in kinds
            for name in [*generators, "real_other_people"]]
    jobs.sort(key=lambda j: j[0] == "probe")
    rows = sj.run_jobs(jobs, devices, path, folder, bands=False)
    path.unlink()
    save_json(folder/"judges.json", rows)
    return rows


# ---------------------------------------------------------------- decision
def mean_auc(rows, judge, name):
    values = [r["auc"] for r in rows if r["judge"] == judge and r["source"] == name]
    if not values:
        raise ValueError(f"No {judge} rows for {name}")
    return float(np.mean(values))


def spread(values):
    return float(np.std(values, ddof=1)) if len(values) > 1 else 0.


def null_control(rows, judge):
    value = mean_auc(rows, judge, "real_other_people")
    return dict(auc=value, valid=bool(NULL_RANGE[0] <= value <= NULL_RANGE[1]))


def indistinguishable(rows, judge):
    names = sorted({r["source"] for r in rows if r["judge"] == judge})
    return {n: dict(auc=mean_auc(rows, judge, n), auc_sd=spread([r["auc"] for r in rows if r["judge"] == judge
                                                                  and r["source"] == n]),
                    indistinguishable=100*(1-abs(2*mean_auc(rows, judge, n)-1))) for n in names}
