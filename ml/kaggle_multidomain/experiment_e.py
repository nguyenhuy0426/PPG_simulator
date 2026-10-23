"""Step E: does step D's PhysioFlow recipe replace the app's PhysioMix (round 9) for the everyday wrist?

Step D's pilot (seed 42) passed the original validation, but its everyday-wrist gain over the app (28.8 points) sat
below the locked margin (2 x 16.4) set by 3 halvings of only 4 validation people (2 vs 2). Step E re-derives the pack
with 6 of the 12 GalaxyPPG training people as everyday-wrist validation (ppg_physiomix_v3e, fresh_galaxy.DAILY_SPLITS;
6 train), uses 5 halvings (3 vs 3) and trains the step-D PhysioFlow recipe at 3 seeds directly. RULE_E is fixed in code
before training and decides on validation only; the 12 GalaxyPPG test people are scored for the report only, after the
decision is written. Run with PPG_PACK_PROTOCOL=ppg_physiomix_v3e so spawned workers derive the same pack.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import shutil
import time

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import save_json
from ml.kaggle_multidomain.data_gxu import load_input
from ml.kaggle_multidomain.experiment_daily import seed_mean
from ml.kaggle_multidomain.experiment_galaxy import OLD_VALIDATION_LIMITS, old_validation
from ml.kaggle_multidomain.experiment_v3 import DERIVED_CONTENT_SHA256, PROTOCOL, check_pack, worker
from ml.kaggle_multidomain.fresh_galaxy import (DAILY_DOMAIN, DAILY_SPLITS, app_sources, checkpoint_source, evaluate,
                                                load_galaxy, rate_not_worse)

E_PROTOCOL = "ppg_physiomix_v3e"
RECIPE_KEY = "physioflow_e"
RECIPE = dict(arm="F10_flow_unif_stop01", sampler="F10_flow_unif_stop01_s16_w1", steps=20000, batch=128,
              interval=2000, frozen=dict(samplers=["F10_flow_unif_stop01_s16_w1"]))
SEEDS = (42, 123, 2026)
HALVINGS = 5
C2ST_STEPS = 600
VALIDATION_PEOPLE, SPLIT_SEED = DAILY_SPLITS[E_PROTOCOL]
RULE_E = (
    f"Step E, fixed before training. Pack {E_PROTOCOL}: the verified v3g pack with GalaxyPPG as domain "
    f"'{DAILY_DOMAIN}', {VALIDATION_PEOPLE} of the 12 GalaxyPPG training people (seed {SPLIT_SEED}) as everyday-wrist "
    f"validation and the rest training, content sha256 {DERIVED_CONTENT_SHA256[E_PROTOCOL]}. Recipe {RECIPE['arm']} "
    f"(sampler {RECIPE['sampler']}, {RECIPE['steps']} steps, batch {RECIPE['batch']}) at seeds "
    f"{', '.join(map(str, SEEDS))}. Selection on validation only. PhysioFlow replaces the app's PhysioMix round 9 "
    "only if (1) every seed passes every gate on the original validation and the seed means satisfy S_arm <= "
    f"{OLD_VALIDATION_LIMITS['S_arm']:.3f} and wrist-exercise Q <= {OLD_VALIDATION_LIMITS['wrist_Q']:.3f}; (2) on the "
    f"{VALIDATION_PEOPLE} everyday-wrist validation people ({HALVINGS} halvings), prompted as the everyday-wrist "
    "domain, the seed-mean 'indistinguishable' exceeds the app PhysioMix's (prompted as wrist) by more than 2x the "
    "largest of the seed SD, the mean per-seed halving SD and the app's halving SD; (3) the seed-mean Q is lower than "
    "the app PhysioMix's; (4) the seed-mean median |rate error| is not worse by more than 2 bpm. The shipped seed is "
    "the one with the highest everyday-wrist validation 'indistinguishable' among the seeds that pass the "
    "original-validation limits on their own. The 12 GalaxyPPG test people are reported only.")


def name(seed):
    return f"{RECIPE_KEY}_seed{seed}"


def run_dir(output, seed):
    return Path(output)/name(seed)/f"{RECIPE['arm']}_seed{seed}"


def train_seeds(input_root, output, seeds, devices, n, steps=None):
    """One seed per device at a time (waves of len(devices)), through the worker every earlier round used."""
    rows, total = {}, steps or RECIPE["steps"]
    context = multiprocessing.get_context("spawn")
    for start in range(0, len(seeds), len(devices)):
        wave = seeds[start:start+len(devices)]
        with ProcessPoolExecutor(max_workers=len(wave), mp_context=context) as pool:
            futures = {}
            for seed, device in zip(wave, devices):
                folder = Path(output)/name(seed)
                folder.mkdir(parents=True)
                futures[seed] = (folder, pool.submit(worker, device, [(RECIPE["arm"], seed)], input_root, folder, total,
                                                     RECIPE["batch"], min(RECIPE["interval"], total), n,
                                                     RECIPE["frozen"], 2))
            for seed, (folder, future) in futures.items():
                rows[seed] = future.result()[0]
                save_json(folder/"row.json", rows[seed])
    return rows


def decide(summary, validation, seeds=SEEDS):
    """RULE_E on the everyday-wrist validation summary (fresh_galaxy.evaluate: one entry per seed plus the app's) and
    the per-seed original-validation rows (experiment_galaxy.old_validation). An unmeasurable value fails its check."""
    names = [name(s) for s in seeds]
    app = summary["physiomix"]
    pooled = {k: seed_mean(summary, names, k) for k in ("indistinguishable", "Q", "rate_error_median_bpm")}
    halving = [summary[n]["indistinguishable"]["sd"] for n in names]
    sds = dict(seed=pooled["indistinguishable"]["sd"], halving=None if None in halving else float(np.mean(halving)),
               app_halving=app["indistinguishable"]["sd"])
    measurable = None not in sds.values() and None not in (pooled["indistinguishable"]["mean"],
                                                          app["indistinguishable"]["mean"])
    margin = 2*max(sds.values()) if measurable else None
    gap = pooled["indistinguishable"]["mean"]-app["indistinguishable"]["mean"] if measurable else None
    old = dict(eligible=all(validation[n]["eligible"] for n in names),
               S_arm=float(np.mean([validation[n]["S_arm"] for n in names])),
               wrist_Q=float(np.mean([validation[n]["wrist_Q"] for n in names])))
    old["ok"] = bool(old["eligible"] and old["S_arm"] <= OLD_VALIDATION_LIMITS["S_arm"]
                     and old["wrist_Q"] <= OLD_VALIDATION_LIMITS["wrist_Q"])
    q, app_q = pooled["Q"]["mean"], app["Q"]["mean"]
    checks = dict(old_validation=old["ok"], realism=bool(measurable and gap > margin),
                  q=bool(q is not None and app_q is not None and q < app_q), rate=rate_not_worse(pooled, app))
    passing = [n for n in names if validation[n]["ok"]]
    shipped = (max(passing, key=lambda n: summary[n]["indistinguishable"]["mean"])
               if all(checks.values()) and passing else None)
    return dict(rule=RULE_E, recipe=RECIPE_KEY, seeds=list(seeds), gap=gap, margin=margin, margin_sds=sds,
                pooled=pooled, old_validation=old, checks=checks, ship=shipped is not None, shipped=shipped)


def sources_for(bundle, development, output, seeds):
    """App PhysioMix and PhysioFlow (prompted as wrist) and each trained seed (prompted as the everyday wrist)."""
    app = app_sources(bundle)
    sources = dict(physiomix=app["physiomix"], physioflow=app["physioflow"])
    for seed in seeds:
        sources[name(seed)] = checkpoint_source(development, run_dir(output, seed), RECIPE["sampler"],
                                                prompt_domain=DAILY_DOMAIN)
    return sources


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="Holds the v3g pack, galaxyppg_windows.npz and app models")
    parser.add_argument("--output", required=True)
    parser.add_argument("--eval-samples", type=int, default=256)
    parser.add_argument("--galaxy-samples", type=int, default=256)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--steps", type=int, help="Override the step count (CPU smoke tests only)")
    parser.add_argument("--c2st-steps", type=int, default=C2ST_STEPS, help="Lower only for CPU smoke tests")
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    if PROTOCOL != E_PROTOCOL:
        raise RuntimeError(f"Set PPG_PACK_PROTOCOL={E_PROTOCOL} before importing the training modules")
    # A smoke run never ships and is marked as such in every output file.
    smoke = a.allow_cpu or a.steps is not None or a.c2st_steps != C2ST_STEPS or a.galaxy_samples != 256 \
        or a.eval_samples != 256
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and (len(names) != 2 or any("T4" not in n for n in names)):
        raise RuntimeError(f"Two T4 GPUs required, allocated {names}")
    devices = ["cpu", "cpu"] if a.allow_cpu else ["cuda:0", "cuda:1"]
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    # The derived content is checked on CPU too: the smoke run must use the same pack as the GPU run.
    if manifest["content_sha256"] != DERIVED_CONTENT_SHA256[E_PROTOCOL]:
        raise ValueError(f"Derived {E_PROTOCOL} pack content mismatch")
    people = manifest["galaxyppg"]["people"]
    if len(people["validation"]) != VALIDATION_PEOPLE or len(people["external"]) != 12:
        raise ValueError("Unexpected GalaxyPPG people split")
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    save_json(output/"FROZEN_E.json", dict(rule=RULE_E, rule_sha256=hashlib.sha256(RULE_E.encode()).hexdigest(),
              recipe=RECIPE, seeds=SEEDS, halvings=HALVINGS, c2st_steps=a.c2st_steps, galaxy_samples=a.galaxy_samples,
              eval_samples=a.eval_samples, steps=a.steps or RECIPE["steps"], data_sha256=manifest["windows_sha256"],
              content_sha256=manifest["content_sha256"], galaxy_people=people, smoke=smoke,
              python=platform.python_version(), torch=torch.__version__, gpus=names, cpu_count=os.cpu_count()))
    rows = train_seeds(a.input_root, output, SEEDS, devices, a.eval_samples, steps=a.steps)
    validation = {name(s): old_validation(r) for s, r in rows.items()}
    print("OLD VALIDATION", json.dumps(validation), flush=True)
    torch.set_num_threads(a.threads)
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    # Feature scales from the v3g pack's development windows, as in steps B and D, so the numbers stay comparable.
    judge_pack, _ = load_input(a.input_root, "ppg_physiomix_v3g")
    judge_pack = {k: v[np.isin(judge_pack["split"], ["train", "validation"])] for k, v in judge_pack.items()}
    bundle = next(p.parent for p in Path(a.input_root).rglob("manifest.json") if (p.parent/"physiomix_generator.ts").exists())
    sources = sources_for(bundle, development, output, SEEDS)
    galaxy = load_galaxy(next(Path(a.input_root).rglob("galaxyppg_windows.npz")).parent)
    daily, daily_halvings = evaluate(galaxy, judge_pack, sources, a.galaxy_samples, HALVINGS, steps=a.c2st_steps,
                                     people=people["validation"])
    decision = decide(daily, validation)
    # Written before the test is scored: the decision cannot depend on it.
    save_json(output/"DECISION_E.json", dict(decision, smoke=smoke, daily_validation_summary=daily,
                                             old_validation_per_seed=validation,
                                             daily_validation_per_halving=daily_halvings))
    print("DECISION E", json.dumps({k: decision[k] for k in ("gap", "margin", "checks", "ship", "shipped")}), flush=True)
    test, test_halvings = evaluate(galaxy, judge_pack, sources, a.galaxy_samples, HALVINGS, steps=a.c2st_steps,
                                   people=people["external"])
    save_json(output/"TEST_REPORT_E.json", dict(
        summary=test, per_halving=test_halvings, people=people["external"], wall_seconds=time.monotonic()-started,
        smoke=smoke, scope="Report only, never used for a decision. Engineering evaluation of normalised 30 s wrist "
                           "PPG shape and rate following; not clinical"))
    if decision["ship"] and not smoke:
        ship = output/"ship"
        ship.mkdir()
        source = run_dir(output, int(decision["shipped"].rsplit("seed", 1)[1]))
        for file in ("generator_cpu.ts", "conditions.json", "training_result.json", "best.pt"):
            shutil.copy2(source/file, ship/file)
    return decision


if __name__ == "__main__":
    main()
