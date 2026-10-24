"""Flow-GAN round: PhysioFlow-GAN (flow_gan.FlowGAN) for both app slots, trained and judged in one T4x2 kernel.

PhysioMix slot: G1_flowgan, all six domains, the app's conditional contract. LSM slot: G2_flowgan_lsm_bidmc, BIDMC
windows only with the LSM-GAN log-spectral matching loss, judged on BIDMC prompted with BIDMC labels (as an
unconditional LSM-GAN drawing its own rhythm). Three seeds each, the round-9 gates (experiment_v3.score_arm).
The strict judge (strict_judge "strict", the kind SELECTION_JUDGE.json chose) is retrained from scratch against every
source on validation people, with the app's models, PhysioFlow and PhysioFlow + calibrated sensor noise as references
and the real_other_people null control; RULE and the decision are saved before the test people are judged once with
fresh windows, prompts, generator noise and judge seeds (experiment_strict.SET_SEEDS / JUDGE_SEED_OFFSETS).
Engineering evaluation of normalised 30 s PPG shape; not clinical validation, not measured on the Pi/DAC/OPT101.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
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
from ml.kaggle_multidomain import strict_judge as sj
from ml.kaggle_multidomain.experiment_strict import (LSM_DOMAIN, app_sources, checkpoint_generator, indistinguishable,
                                                     judge_family, mean_auc, null_control, sensor_finished, spread)

ARMS = {"physiomix": "G1_flowgan", "lsm": "G2_flowgan_lsm_bidmc"}
JUDGE = "strict"
RULE = ("Flow-GAN round rule, fixed before training (validation people only). Per slot, the arm's mean strict-judge "
        "AUC over its three seeds (each judged with judge seeds 0-2 + offset) is compared with the app model of the "
        "slot. The arm wins the slot if every seed passes the round-9 gates (eligible), its mean AUC is below the app "
        "model's by more than max(0.02, seed SD), the slot's real_other_people null control lies in [0.40, 0.60], and, "
        "for the PhysioMix slot, its fresh-seed C is at most 0.10 (rate control; the shipped PhysioMix 0.03-0.06). "
        "The ship seed is the eligible seed with the lowest validation AUC. PhysioFlow (raw and with sensor noise "
        "0.03) are references, not candidates. The test people are judged once, after DECISION_FLOWGAN.json, for "
        "the app models, the references and every seed of each arm. indistinguishable = 100(1-|2AUC-1|).")
C_LIMIT = .10


def rule_sha256():
    return hashlib.sha256(RULE.encode()).hexdigest()


def train_one(device, arm, seed, input_root, output, steps, interval, n, deadline):
    from ml.kaggle_multidomain import experiment_v3
    rows = experiment_v3.worker(device, [(arm, seed)], input_root, output, steps, 32, interval, n, None, 1, deadline)
    return rows[0]


def train_all(jobs, devices, input_root, output, steps, interval, n, deadline):
    # Three runs share each T4 (14.6 GiB); spawned workers inherit this, which limits fragmentation between them.
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    if devices == ["cpu"]:
        return [train_one("cpu", arm, seed, input_root, output, steps, interval, n, deadline) for arm, seed in jobs]
    rows = []
    with ProcessPoolExecutor(len(jobs), mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(train_one, devices[i % len(devices)], arm, seed, input_root, output, steps, interval, n,
                               deadline) for i, (arm, seed) in enumerate(jobs)]
        for future in as_completed(futures):
            rows.append(future.result())
            save_json(Path(output)/"training_progress.json", rows)
    return rows


def decide(val, training, seeds):
    out = {}
    for slot, arm in ARMS.items():
        rows = val[slot]
        app = mean_auc(rows, JUDGE, f"{slot}_app")
        mine = {r["seed"]: r for r in training if r["arm"] == arm}
        auc = {s: mean_auc(rows, JUDGE, f"{arm}_seed{s}") for s in seeds}
        values = list(auc.values())
        margin = max(.02, spread(values))
        c = float(np.mean([mine[s]["C_fresh"] for s in seeds]))
        null = null_control(rows, JUDGE)
        checks = dict(eligible=all(mine[s]["eligible"] for s in seeds), auc_gain=app-float(np.mean(values)) > margin,
                      null_valid=null["valid"], c_ok=slot != "physiomix" or c <= C_LIMIT)
        ships = [s for s in seeds if mine[s]["eligible"]]
        out[slot] = dict(arm=arm, app_auc=app, auc_by_seed=auc, mean_auc=float(np.mean(values)), margin=margin, C=c,
                         null_control=null, checks=checks, winner=arm if all(checks.values()) else None,
                         ship_seed=min(ships, key=lambda s: auc[s]) if ships else None,
                         references={n: mean_auc(rows, JUDGE, n) for n in ("physioflow_app", "physioflow_sensor")})
    return dict(judge=JUDGE, rule_sha256=rule_sha256(), **out)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="v3 pack and the app model files (manifest.json)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=4000)
    parser.add_argument("--hours", type=float, default=4.5, help="Training deadline after the start")
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 2026])
    parser.add_argument("--judge-seeds", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--interval", type=int, default=500)
    parser.add_argument("--eval-samples", type=int, default=256)
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    from ml.kaggle_multidomain.data_gxu import load_input
    from ml.kaggle_multidomain.experiment_v3 import PROTOCOL, check_pack, conditions_for
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and len(names) != 2:
        raise RuntimeError(f"Two GPUs required, allocated {names}")
    devices = ["cpu"] if a.allow_cpu else ["cuda:0", "cuda:1"]
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started, deadline = time.monotonic(), time.time()+3600*a.hours
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    save_json(output/"FROZEN_FLOWGAN.json", dict(rule=RULE, rule_sha256=rule_sha256(), arms=ARMS, judge=JUDGE,
                                                 judge_spec=sj.JUDGES[JUDGE], seeds=a.seeds, judge_seeds=a.judge_seeds,
                                                 steps=a.steps, hours=a.hours, data_sha256=manifest["windows_sha256"]))
    save_json(output/"configuration.json", dict(args=vars(a), python=platform.python_version(), torch=torch.__version__,
                                                allocated_gpus=names, cpu_count=os.cpu_count()))
    (output/"benchmark").mkdir()
    jobs = [(arm, s) for arm in ARMS.values() for s in a.seeds]
    training = train_all(jobs, devices, a.input_root, output/"benchmark", a.steps, a.interval, a.eval_samples, deadline)
    save_json(output/"training_execution.json", training)
    print("TRAINING DONE", f"{time.monotonic()-started:.0f}s", flush=True)

    pack = {k: v[pack["split"] != "external"] for k, v in pack.items()}
    keep = np.flatnonzero(np.isin(pack["split"], ["train", "validation"]))
    bank = sj.ConditionsView(conditions_for({k: v[keep] for k, v in pack.items()}, "v2"), keep)
    bundle = next(p.parent for p in Path(a.input_root).rglob("manifest.json") if (p.parent/"physiomix_generator.ts").exists())
    apps = app_sources(bundle, bank, devices[0])
    references = dict(physioflow_app=apps["physioflow_app"], physioflow_sensor=sensor_finished(apps["physioflow_app"]))

    def sources(slot, arm):
        out = {f"{slot}_app": apps[f"{slot}_app"], **references}
        out.update({f"{arm}_seed{s}": checkpoint_generator(output/"benchmark"/f"{arm}_seed{s}", arm, bank, devices[0])
                    for s in a.seeds})
        return out

    domains = dict(physiomix=sj.DOMAINS, lsm=(LSM_DOMAIN,))
    kinds = [JUDGE, "probe"]
    val = {slot: judge_family(pack, bank, sources(slot, arm), "validation", domains[slot], kinds, a.judge_seeds,
                              devices, output/"validation"/slot) for slot, arm in ARMS.items()}
    decision = decide(val, training, a.seeds)
    save_json(output/"DECISION_FLOWGAN.json", decision)
    print("DECISION", json.dumps({s: decision[s]["winner"] for s in ARMS}), flush=True)
    test = {slot: judge_family(pack, bank, sources(slot, arm), "test", domains[slot], kinds, a.judge_seeds, devices,
                               output/"test"/slot) for slot, arm in ARMS.items()}
    ship = output/"ship"
    ship.mkdir()
    for slot in ARMS:
        if decision[slot]["winner"]:
            run = output/"benchmark"/f"{decision[slot]['arm']}_seed{decision[slot]['ship_seed']}"
            shutil.copy2(run/"generator_cpu.ts", ship/f"{slot}_flowgan_generator.ts")
    summary = dict(judge=JUDGE, decision=decision,
                   validation={k: {s: indistinguishable(val[s], k) for s in ARMS} for k in kinds},
                   test={k: {s: indistinguishable(test[s], k) for s in ARMS} for k in kinds},
                   wall_seconds=time.monotonic()-started)
    save_json(output/"summary.json", summary)
    save_json(output/"COMPLETE.json", dict(status="complete", winners={s: decision[s]["winner"] for s in ARMS},
                                           wall_seconds=time.monotonic()-started, deployment="research_only"))
    print("COMPLETE", flush=True)
    return summary


if __name__ == "__main__":
    main()
