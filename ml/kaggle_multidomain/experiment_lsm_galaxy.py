"""Step B-LSM: the app's LSM-GAN recipe retrained on the multi-dataset packs, judged on the GalaxyPPG test people.

The app's LSM-GAN was trained only on BIDMC (0.9-5 Hz view, train_lsm.prepare). Its recipe (lsm_repo_corrected, same
networks, losses and validation-MMD checkpoint choice; train_lsm.train_one) is retrained here on the v3g pack's
train split, in the shared v3 view (0.5-8 Hz):
  lsm_v3_all     every domain, GalaxyPPG people left out (the PhysioMix/PhysioFlow data before step B);
  lsm_v3g_all    every domain with the 12 GalaxyPPG training people;
  lsm_v3g_wrist  wrist only (4 original people + 12 GalaxyPPG), i.e. one unconditioned model per domain.
LSM-GAN takes no condition: it cannot follow a heart rate or pick a domain, so none of these can replace an app
generator. The question is only whether more data makes this simpler GAN more realistic; RULE_LSM is fixed in code
before training. Run with PPG_PACK_PROTOCOL=ppg_physiomix_v3g.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import time
from types import SimpleNamespace

import numpy as np
from scipy.spatial.distance import pdist
import torch

from ml.kaggle_lsm.train_lsm import LENGTH, features, save_json, train_one
from ml.kaggle_multidomain.data_gxu import load_input
from ml.kaggle_multidomain.experiment_v3 import PROTOCOL, check_pack
from ml.kaggle_multidomain.fresh_galaxy import app_sources, evaluate, load_galaxy
from ml.kaggle_multidomain.realism import lsm_source

VARIANT = "lsm_repo_corrected"  # the app's LSM-GAN variant (assets/neural/manifest.json lsm_variant)
ARMS = ("lsm_v3_all", "lsm_v3g_all", "lsm_v3g_wrist")
STEPS, BATCH, SEED = 6000, 64, 42
RULE_LSM = ("Step B-LSM (seed 42), fixed before training. Report only: LSM-GAN has no condition input, so no LSM arm "
            "can replace an app generator. On the 12 GalaxyPPG test people (3 halvings), an arm counts as 'more data "
            "helped' if its mean 'indistinguishable' exceeds the app LSM-GAN's by more than 2x the larger halving SD; "
            "'GalaxyPPG helped' if lsm_v3g_all or lsm_v3g_wrist exceeds lsm_v3_all by the same margin.")


def arm_masks(pack, arm):
    """Boolean train/validation/test row masks of one arm (train_one selects checkpoints on validation)."""
    galaxy = np.char.startswith(pack["subject"].astype(str), "galaxyppg:")
    keep = ~np.isin(pack["split"], ["external"])
    if arm == "lsm_v3_all":
        keep &= ~galaxy
    elif arm == "lsm_v3g_wrist":
        keep &= pack["domain"] == "wrist"
    elif arm != "lsm_v3g_all":
        raise ValueError(f"Unknown arm {arm}")
    return {split: keep & (pack["split"] == split) for split in ("train", "validation", "test")}


def train_arm(pack, arm, output, steps, batch, seed):
    """train_one on this arm's rows; bandwidths from its training features only, as for the BIDMC LSM-GAN."""
    masks = arm_masks(pack, arm)
    rows = np.flatnonzero(masks["train"] | masks["validation"] | masks["test"])
    x = pack["signal"][rows].astype(np.float32)
    local = {k: v[rows] for k, v in masks.items()}
    bandwidths = [max(float(np.median(pdist(f, "sqeuclidean"))), 1e-6) for f in features(x[local["train"]])]
    arm_dir = Path(output)/arm
    arm_dir.mkdir(parents=True)
    _, result = train_one(VARIANT, x, local, arm_dir, SimpleNamespace(steps=steps, batch=batch, seed=seed), bandwidths)
    result.update(counts={k: int(v.sum()) for k, v in local.items()}, bandwidths=bandwidths)
    save_json(arm_dir/"arm.json", result)
    return arm_dir/VARIANT/"generator_cpu.ts", result


def decide_lsm(summary):
    def gain(a, b):
        margin = 2*max(summary[a]["indistinguishable"]["sd"], summary[b]["indistinguishable"]["sd"])
        gap = summary[a]["indistinguishable"]["mean"]-summary[b]["indistinguishable"]["mean"]
        return dict(gap=gap, margin=margin, helped=gap > margin)
    more_data = {arm: gain(arm, "lsm_gan") for arm in ARMS}
    galaxy = {arm: gain(arm, "lsm_v3_all") for arm in ("lsm_v3g_all", "lsm_v3g_wrist")}
    return dict(rule=RULE_LSM, more_data_vs_app_lsm=more_data, galaxy_vs_no_galaxy=galaxy,
                app_eligible=[], galaxy_helped=any(v["helped"] for v in galaxy.values()))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="Holds the v3g pack, galaxyppg_windows.npz and app models")
    parser.add_argument("--output", required=True)
    parser.add_argument("--galaxy-samples", type=int, default=256)
    parser.add_argument("--halvings", type=int, default=3)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--steps", type=int, default=STEPS, help="Lower only for CPU smoke tests")
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    if PROTOCOL != "ppg_physiomix_v3g":
        raise RuntimeError("Set PPG_PACK_PROTOCOL=ppg_physiomix_v3g before importing the training modules")
    if not a.allow_cpu and not torch.cuda.is_available():
        raise RuntimeError("GPU required; refusing silent CPU fallback")
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    test_people = manifest["galaxyppg"]["people"]["external"]
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    save_json(output/"FROZEN_LSM.json", dict(rule=RULE_LSM, rule_sha256=hashlib.sha256(RULE_LSM.encode()).hexdigest(),
              variant=VARIANT, arms=ARMS, steps=a.steps, batch=BATCH, seed=SEED, data_sha256=manifest["windows_sha256"],
              galaxy_test_people=test_people, python=platform.python_version(), torch=torch.__version__,
              gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None, cpu_count=os.cpu_count()))
    torch.set_num_threads(a.threads)
    generators, training = {}, {}
    for arm in ARMS:
        generators[arm], training[arm] = train_arm(pack, arm, output, a.steps, BATCH, SEED)
        print("TRAINED", arm, json.dumps({k: v for k, v in training[arm].items() if not isinstance(v, (list, dict))}),
              flush=True)
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    bundle = next(p.parent for p in Path(a.input_root).rglob("manifest.json") if (p.parent/"physiomix_generator.ts").exists())
    app = app_sources(bundle)
    meta = app["physiomix"][1]
    sources = dict(physiomix=app["physiomix"], lsm_gan=app["lsm_gan"])
    for arm, path in generators.items():
        lsm = lsm_source(path)
        sources[arm] = (lambda rows, rates, seed, lsm=lsm: lsm(np.arange(len(rows)), seed), meta)
    galaxy = load_galaxy(next(Path(a.input_root).rglob("galaxyppg_windows.npz")).parent)
    summary, per_halving = evaluate(galaxy, development, sources, a.galaxy_samples, a.halvings, people=test_people)
    decision = decide_lsm(summary)
    save_json(output/"DECISION_LSM.json", dict(decision, summary=summary, training=training, per_halving=per_halving,
              wall_seconds=time.monotonic()-started,
              scope="Engineering evaluation of normalised 30 s wrist PPG shape; LSM-GAN has no rate control; not clinical"))
    print("DECISION LSM galaxy_helped:", decision["galaxy_helped"], flush=True)
    return decision


if __name__ == "__main__":
    main()
