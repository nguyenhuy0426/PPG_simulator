"""Step B: retrain the two app recipes with GalaxyPPG wrist data, judged on GalaxyPPG people never trained on.

The fresh GalaxyPPG test (fresh_galaxy) found both app models fully detectable on everyday wrist PPG (C2ST
'indistinguishable' 0.6-0.7% vs 89% for other real people): their wrist training data is 83 exercise windows of
another device. This step retrains PhysioMix (round-9 recipe) and PhysioFlow (loop-6 F10 recipe) on the v3g pack
(v3 + GalaxyPPG windows of 12 training people as wrist; fresh_galaxy.extend_pack), one seed each on one T4 each,
with the same checkpoint selection as before (original validation only). Then the fresh test is repeated on the 12
GalaxyPPG test people for the app models and the retrained ones. RULE_B is fixed in code before training.
Run with PPG_PACK_PROTOCOL=ppg_physiomix_v3g so spawned workers load the same pack.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import time

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import save_json
from ml.kaggle_multidomain.data_gxu import load_input
from ml.kaggle_multidomain.experiment_v3 import PROTOCOL, check_pack, worker
from ml.kaggle_multidomain.fresh_galaxy import app_sources, checkpoint_source, evaluate, load_galaxy, rate_not_worse

RECIPES = {
    "physiomix_g": dict(arm="L3_rel_beat_lr_crop_r1w_motion_dom", sampler="L3_rel_beat_lr_crop_r1w_motion_dom",
                        steps=20000, batch=32, interval=500, frozen=None),
    "physioflow_g": dict(arm="F10_flow_unif_stop01", sampler="F10_flow_unif_stop01_s16_w1", steps=20000, batch=128,
                         interval=2000, frozen=dict(samplers=["F10_flow_unif_stop01_s16_w1"])),
}
# Round-9 PhysioMix on the original validation: S_arm 0.530 +- 0.029, wrist Q 0.527 +- 0.060 (3 seeds).
OLD_VALIDATION_LIMITS = dict(S_arm=.530+.029, wrist_Q=.527+.060)
RULE_B = ("Step B pilot (seed 42), fixed before training. A retrained model goes to a 3-seed final only if, on the 12 "
          "GalaxyPPG test people (never trained on; 3 halvings), its mean 'indistinguishable' exceeds the app "
          "PhysioMix's by more than 2x the larger halving SD, its Q is lower than the app PhysioMix's, and its median "
          "|rate error| is not worse by more than 2 bpm; AND on the original validation it passes every gate with "
          f"S_arm <= {OLD_VALIDATION_LIMITS['S_arm']:.3f} and wrist Q <= {OLD_VALIDATION_LIMITS['wrist_Q']:.3f} "
          "(no regression beyond round 9's seed spread). Otherwise the app models stay.")


def train_both(input_root, output, n, devices, seed=42, steps=None):
    """One recipe per device, concurrently, through the same worker as every earlier round."""
    rows = {}
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=len(RECIPES), mp_context=context) as pool:
        futures = {}
        for (key, r), device in zip(RECIPES.items(), devices):
            (output/key).mkdir(parents=True)
            total = steps or r["steps"]
            futures[key] = pool.submit(worker, device, [(r["arm"], seed)], input_root, output/key, total,
                                       r["batch"], min(r["interval"], total), n, r["frozen"], 2)
        for key, future in futures.items():
            rows[key] = future.result()[0]
            save_json(output/f"{key}_row.json", rows[key])
    return rows


def old_validation(row):
    wrist = row["prompted_validation"]["pools"]["wrist"]["Q"]
    return dict(S_arm=row["S_arm"], wrist_Q=wrist, eligible=row["eligible"],
                ok=bool(row["eligible"] and row["S_arm"] <= OLD_VALIDATION_LIMITS["S_arm"]
                        and wrist <= OLD_VALIDATION_LIMITS["wrist_Q"]))


def decide_b(summary, validation):
    app = summary["physiomix"]
    out = {}
    for key in RECIPES:
        mine = summary[key]
        margin = 2*max(app["indistinguishable"]["sd"], mine["indistinguishable"]["sd"])
        gap = mine["indistinguishable"]["mean"]-app["indistinguishable"]["mean"]
        checks = dict(realism=gap > margin, q=mine["Q"]["mean"] < app["Q"]["mean"],
                      rate=rate_not_worse(mine, app),
                      old_validation=validation[key]["ok"])
        out[key] = dict(gap=gap, margin=margin, checks=checks, go_final=all(checks.values()))
    return dict(rule=RULE_B, candidates=out, go=[k for k, v in out.items() if v["go_final"]])


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="Holds the v3g pack, galaxyppg_windows.npz and app models")
    parser.add_argument("--output", required=True)
    parser.add_argument("--eval-samples", type=int, default=256)
    parser.add_argument("--galaxy-samples", type=int, default=256)
    parser.add_argument("--halvings", type=int, default=3)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--steps", type=int, help="Override every recipe's step count (CPU smoke tests only)")
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    if PROTOCOL != "ppg_physiomix_v3g":
        raise RuntimeError("Set PPG_PACK_PROTOCOL=ppg_physiomix_v3g before importing the training modules")
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and (len(names) != 2 or any("T4" not in name for name in names)):
        raise RuntimeError(f"Two T4 GPUs required, allocated {names}")
    devices = ["cpu", "cpu"] if a.allow_cpu else ["cuda:0", "cuda:1"]
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    test_people = manifest["galaxyppg"]["people"]["external"]
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    save_json(output/"FROZEN_GALAXY_B.json", dict(rule=RULE_B, rule_sha256=hashlib.sha256(RULE_B.encode()).hexdigest(),
              recipes=RECIPES, data_sha256=manifest["windows_sha256"], galaxy_test_people=test_people,
              python=platform.python_version(), torch=torch.__version__, gpus=names, cpu_count=os.cpu_count()))
    rows = train_both(a.input_root, output, a.eval_samples, devices, steps=a.steps)
    validation = {k: old_validation(r) for k, r in rows.items()}
    print("OLD VALIDATION", json.dumps(validation), flush=True)
    torch.set_num_threads(a.threads)
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    bundle = next(p.parent for p in Path(a.input_root).rglob("manifest.json") if (p.parent/"physiomix_generator.ts").exists())
    app = app_sources(bundle)
    sources = dict(physiomix=app["physiomix"], physioflow=app["physioflow"])
    for key, r in RECIPES.items():
        sources[key] = checkpoint_source(development, output/key/f"{r['arm']}_seed42", r["sampler"])
    galaxy = load_galaxy(next(Path(a.input_root).rglob("galaxyppg_windows.npz")).parent)
    summary, per_halving = evaluate(galaxy, development, sources, a.galaxy_samples, a.halvings, people=test_people)
    decision = decide_b(summary, validation)
    save_json(output/"DECISION_GALAXY_B.json", dict(decision, summary=summary, old_validation=validation,
              per_halving=per_halving, wall_seconds=time.monotonic()-started,
              scope="Engineering evaluation of normalised 30 s wrist PPG shape and rate following; not clinical"))
    print("DECISION B go:", decision["go"], flush=True)
    return decision


if __name__ == "__main__":
    main()
