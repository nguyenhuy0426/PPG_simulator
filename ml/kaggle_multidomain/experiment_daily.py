"""Step D: everyday wrist (GalaxyPPG, Empatica E4) as its own domain, next to the original wrist-exercise domain.

Step B put the GalaxyPPG windows into the existing 'wrist' domain: 1210 of 1293 wrist training windows became E4
everyday windows, the retrained models drifted towards them and the original wrist-exercise validation regressed
(PhysioFlow wrist Q 0.95). Here the ppg_physiomix_v3d pack (fresh_galaxy.daily_wrist) keeps 'wrist' as before and adds
'wrist_daily': 8 GalaxyPPG people train, 4 are validation (fixed seed), the 12 GalaxyPPG test people stay untouched.

Selection uses validation only: the original validation (every gate, S_arm and wrist-exercise Q, unchanged
criterion) and the 4 everyday-wrist validation people (C2ST 'indistinguishable', Q and rate error, as the fresh test).
The 12 GalaxyPPG test people are scored for the report only, never for a decision. RULE_D and RULE_D_FINAL are fixed
in code before training. Run with PPG_PACK_PROTOCOL=ppg_physiomix_v3d so spawned workers derive the same pack.
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
from ml.kaggle_multidomain.experiment_galaxy import OLD_VALIDATION_LIMITS, old_validation
from ml.kaggle_multidomain.experiment_v3 import PROTOCOL, check_pack, worker
from ml.kaggle_multidomain.fresh_galaxy import (DAILY_DOMAIN, app_sources, checkpoint_source, evaluate, load_galaxy,
                                                rate_not_worse)

RECIPES = {
    "physiomix_d": dict(arm="L3_rel_beat_lr_crop_r1w_motion_dom", sampler="L3_rel_beat_lr_crop_r1w_motion_dom",
                        steps=20000, batch=32, interval=500, frozen=None),
    "physioflow_d": dict(arm="F10_flow_unif_stop01", sampler="F10_flow_unif_stop01_s16_w1", steps=20000, batch=128,
                         interval=2000, frozen=dict(samplers=["F10_flow_unif_stop01_s16_w1"])),
}
PILOT_SEED, FINAL_SEEDS = 42, (123, 2026)
RULE_D = ("Step D pilot (seed 42), fixed before training. Selection on validation only. A retrained model goes to a "
          "3-seed final only if (1) on the original validation it passes every gate with S_arm <= "
          f"{OLD_VALIDATION_LIMITS['S_arm']:.3f} and wrist-exercise Q <= {OLD_VALIDATION_LIMITS['wrist_Q']:.3f}, and "
          "(2) on the 4 everyday-wrist validation people (3 halvings), prompted as the everyday-wrist domain, its mean "
          "'indistinguishable' exceeds the app PhysioMix's (prompted as wrist) by more than 2x the larger halving SD, "
          "its Q is lower and its median |rate error| is not worse by more than 2 bpm. If both recipes pass, the final "
          "trains the one with the higher everyday-wrist validation 'indistinguishable'. The 12 GalaxyPPG test people "
          "are reported only.")
RULE_D_FINAL = ("Step D final, fixed before training: seeds 42 (the pilot run), 123 and 2026 of the pilot's chosen "
                "recipe. It ships only if every seed is eligible, the seed means satisfy S_arm <= "
                f"{OLD_VALIDATION_LIMITS['S_arm']:.3f} and wrist-exercise Q <= {OLD_VALIDATION_LIMITS['wrist_Q']:.3f} on "
                "the original validation, and on the 4 everyday-wrist validation people the seed-mean "
                "'indistinguishable' exceeds the app PhysioMix's by more than 2x the larger of the seed SD and the app's "
                "halving SD, the seed-mean Q is lower and the seed-mean median |rate error| is not worse by more than "
                "2 bpm. The shipped seed is the one with the highest everyday-wrist validation 'indistinguishable' among "
                "the seeds that pass the original-validation limits on their own. The 12 GalaxyPPG test people are "
                "reported only.")


def train_jobs(input_root, output, jobs, devices, n, steps=None):
    """jobs: [(recipe key, seed)], one per device, concurrently, through the worker every earlier round used."""
    rows = {}
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=len(jobs), mp_context=context) as pool:
        futures = {}
        for (key, seed), device in zip(jobs, devices):
            r = RECIPES[key]
            folder = output/f"{key}_seed{seed}"
            folder.mkdir(parents=True)
            total = steps or r["steps"]
            futures[(key, seed)] = (folder, pool.submit(worker, device, [(r["arm"], seed)], input_root, folder, total,
                                                        r["batch"], min(r["interval"], total), n, r["frozen"], 2))
        for (key, seed), (folder, future) in futures.items():
            rows[(key, seed)] = future.result()[0]
            save_json(folder/"row.json", rows[(key, seed)])
    return rows


def run_dir(folder, key, seed):
    return Path(folder)/f"{key}_seed{seed}"/f"{RECIPES[key]['arm']}_seed{seed}"


def beats(mine, app, margin_sd):
    """The everyday-wrist validation checks of RULE_D / RULE_D_FINAL for one summary row against the app's."""
    margin = 2*max(margin_sd, app["indistinguishable"]["sd"])
    gap = mine["indistinguishable"]["mean"]-app["indistinguishable"]["mean"]
    return dict(gap=gap, margin=margin, realism=bool(gap > margin), q=bool(mine["Q"]["mean"] < app["Q"]["mean"]),
                rate=rate_not_worse(mine, app))


def decide_pilot(summary, validation):
    app, out = summary["physiomix"], {}
    for key in RECIPES:
        daily = beats(summary[key], app, summary[key]["indistinguishable"]["sd"])
        checks = dict(old_validation=validation[key]["ok"], realism=daily["realism"], q=daily["q"], rate=daily["rate"])
        out[key] = dict(gap=daily["gap"], margin=daily["margin"], checks=checks, go_final=all(checks.values()))
    go = [k for k, v in out.items() if v["go_final"]]
    final = max(go, key=lambda k: summary[k]["indistinguishable"]["mean"]) if go else None
    return dict(rule=RULE_D, candidates=out, go=go, final_recipe=final)


def seed_mean(summary, names, key):
    values = [summary[n][key]["mean"] for n in names]
    if any(v is None for v in values):
        return dict(mean=None, sd=None)
    return dict(mean=float(np.mean(values)), sd=float(np.std(values, ddof=1)) if len(values) > 1 else 0.)


def decide_final(summary, validation, recipe, seeds):
    names = [f"{recipe}_seed{s}" for s in seeds]
    pooled = {k: seed_mean(summary, names, k) for k in ("indistinguishable", "Q", "rate_error_median_bpm")}
    daily = beats(pooled, summary["physiomix"], pooled["indistinguishable"]["sd"])
    old = dict(eligible=all(validation[n]["eligible"] for n in names),
               S_arm=float(np.mean([validation[n]["S_arm"] for n in names])),
               wrist_Q=float(np.mean([validation[n]["wrist_Q"] for n in names])))
    old["ok"] = bool(old["eligible"] and old["S_arm"] <= OLD_VALIDATION_LIMITS["S_arm"]
                     and old["wrist_Q"] <= OLD_VALIDATION_LIMITS["wrist_Q"])
    checks = dict(old_validation=old["ok"], realism=daily["realism"], q=daily["q"], rate=daily["rate"])
    ship = all(checks.values())
    passing = [n for n in names if validation[n]["ok"]]
    seed = max(passing, key=lambda n: summary[n]["indistinguishable"]["mean"]) if ship and passing else None
    return dict(rule=RULE_D_FINAL, recipe=recipe, seeds=list(seeds), daily_validation=dict(daily, pooled=pooled),
                old_validation=old, checks=checks, ship=bool(seed), shipped=seed)


def sources_for(bundle, development, runs):
    """App PhysioMix and PhysioFlow (prompted as wrist) and each trained run (prompted as the everyday wrist)."""
    app = app_sources(bundle)
    sources = dict(physiomix=app["physiomix"], physioflow=app["physioflow"])
    for name, (folder, key, seed) in runs.items():
        sources[name] = checkpoint_source(development, run_dir(folder, key, seed), RECIPES[key]["sampler"],
                                          prompt_domain=DAILY_DOMAIN)
    return sources


def judge(galaxy, judge_pack, sources, people, n, halvings):
    """The fresh-test protocol (fresh_galaxy.evaluate) on these GalaxyPPG people; feature scales from the v3g pack's
    development windows, as in step B, so the numbers stay comparable."""
    return evaluate(galaxy, judge_pack, sources, n, halvings, people=people)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="Holds the v3g pack, galaxyppg_windows.npz and app models")
    parser.add_argument("--output", required=True)
    parser.add_argument("--stage", choices=("pilot", "final"), required=True)
    parser.add_argument("--pilot-root", help="Final: the pilot output (DECISION_D_PILOT.json and the seed-42 run)")
    parser.add_argument("--eval-samples", type=int, default=256)
    parser.add_argument("--galaxy-samples", type=int, default=256)
    parser.add_argument("--halvings", type=int, default=3)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--steps", type=int, help="Override every recipe's step count (CPU smoke tests only)")
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    if PROTOCOL != "ppg_physiomix_v3d":
        raise RuntimeError("Set PPG_PACK_PROTOCOL=ppg_physiomix_v3d before importing the training modules")
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and (len(names) != 2 or any("T4" not in name for name in names)):
        raise RuntimeError(f"Two T4 GPUs required, allocated {names}")
    devices = ["cpu", "cpu"] if a.allow_cpu else ["cuda:0", "cuda:1"]
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    people = manifest["galaxyppg"]["people"]
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    if a.stage == "pilot":
        rule, jobs, frozen_name = RULE_D, [(key, PILOT_SEED) for key in RECIPES], "FROZEN_D_PILOT.json"
    else:
        pilot = json.loads(next(Path(a.pilot_root).rglob("DECISION_D_PILOT.json")).read_text())
        recipe = pilot["final_recipe"]
        if recipe is None or pilot["rule"] != RULE_D:
            raise RuntimeError("The pilot chose no recipe for a final (or ran under another rule)")
        rule, jobs, frozen_name = RULE_D_FINAL, [(recipe, s) for s in FINAL_SEEDS], "FROZEN_D_FINAL.json"
    save_json(output/frozen_name, dict(rule=rule, rule_sha256=hashlib.sha256(rule.encode()).hexdigest(),
              recipes=RECIPES, jobs=jobs, data_sha256=manifest["windows_sha256"],
              content_sha256=manifest["content_sha256"], galaxy_people=people, python=platform.python_version(),
              torch=torch.__version__, gpus=names, cpu_count=os.cpu_count()))
    rows = train_jobs(a.input_root, output, jobs, devices, a.eval_samples, steps=a.steps)
    runs = {f"{key}_seed{seed}": (output, key, seed) for key, seed in jobs}
    if a.stage == "final":
        pilot_root = next(Path(a.pilot_root).rglob("DECISION_D_PILOT.json")).parent
        rows[(recipe, PILOT_SEED)] = json.loads((pilot_root/f"{recipe}_seed{PILOT_SEED}"/"row.json").read_text())
        runs[f"{recipe}_seed{PILOT_SEED}"] = (pilot_root, recipe, PILOT_SEED)
    validation = {f"{key}_seed{seed}": old_validation(r) for (key, seed), r in rows.items()}
    print("OLD VALIDATION", json.dumps(validation), flush=True)
    torch.set_num_threads(a.threads)
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    judge_pack, _ = load_input(a.input_root, "ppg_physiomix_v3g")
    judge_pack = {k: v[np.isin(judge_pack["split"], ["train", "validation"])] for k, v in judge_pack.items()}
    bundle = next(p.parent for p in Path(a.input_root).rglob("manifest.json") if (p.parent/"physiomix_generator.ts").exists())
    sources = sources_for(bundle, development, runs)
    galaxy = load_galaxy(next(Path(a.input_root).rglob("galaxyppg_windows.npz")).parent)
    daily, daily_halvings = judge(galaxy, judge_pack, sources, people["validation"], a.galaxy_samples, a.halvings)
    if a.stage == "pilot":
        summary = dict(daily, **{key: daily[f"{key}_seed{PILOT_SEED}"] for key in RECIPES})
        decision = decide_pilot(summary, {key: validation[f"{key}_seed{PILOT_SEED}"] for key in RECIPES})
        name = "DECISION_D_PILOT.json"
    else:
        decision = decide_final(daily, validation, recipe, (PILOT_SEED, *FINAL_SEEDS))
        name = "DECISION_D_FINAL.json"
    # Written before the test is scored: the decision cannot depend on it.
    save_json(output/name, dict(decision, daily_validation_summary=daily, old_validation=validation,
                                daily_validation_per_halving=daily_halvings))
    print("DECISION D", a.stage, json.dumps({k: decision.get(k) for k in ("go", "final_recipe", "ship", "shipped")}),
          flush=True)
    test, test_halvings = judge(galaxy, judge_pack, sources, people["external"], a.galaxy_samples, a.halvings)
    save_json(output/f"TEST_REPORT_D_{a.stage.upper()}.json", dict(
        summary=test, per_halving=test_halvings, people=people["external"], wall_seconds=time.monotonic()-started,
        scope="Report only, never used for a decision. Engineering evaluation of normalised 30 s wrist PPG shape and "
              "rate following; not clinical"))
    if a.stage == "final" and decision["ship"]:
        ship = output/"ship"
        ship.mkdir()
        key, seed = decision["recipe"], int(decision["shipped"].rsplit("seed", 1)[1])
        source = run_dir(runs[decision["shipped"]][0], key, seed)
        for name in ("generator_cpu.ts", "conditions.json", "training_result.json", "best.pt"):
            shutil.copy2(source/name, ship/name)
    return decision


if __name__ == "__main__":
    main()
