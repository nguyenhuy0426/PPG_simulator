"""P4 round: adversarial fine-tuning of PhysioFlow-R (P1) against the strict critic with the 7-14 Hz band view (P2).

G3_flowgan_r (experiment_v3, flow_r.FlowGANR): the R1 U-Net as a 4-step Heun student on the 40 s grid, ending in the
record-context v3 view (flow_r.RView), no white sensor term (P3), trained against strict_judge.StrictCritic(band=True)
with the MSE anchor to the frozen 16-step R1 teacher. The teacher is the P1 round's ship seed (DECISION_R.json: the
eligible R1 seed with the lowest validation AUC), taken from that round's output whether or not R1 won P1; its sha256
is frozen in FROZEN_P4.json before training.

Fine-tuning does not touch the judge: the strict judge is retrained from scratch against every source, with the same
kind, seeds, sets and real_other_people null as P1, on validation people for the decision and once on test people.
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
from ml.kaggle_multidomain.experiment_r import ARM as TEACHER_ARM, targets
from ml.kaggle_multidomain.experiment_strict import (app_sources, checkpoint_generator, indistinguishable,
                                                     judge_family, mean_auc, null_control, spread)

ARM = "G3_flowgan_r"
JUDGE = "strict"
TEACHER = "r1_teacher"
REFERENCES = ("physiomix_app", "physioflow_app", TEACHER)
C_LIMIT = .10
KERNEL_HOURS, JUDGE_RESERVE_HOURS = 12., 3.5
RULE = ("P4 round rule, fixed before training; validation people only. G3_flowgan_r seeds 42/123/2026 fine-tune the "
        "P1 ship seed's R1 (sha256 in FROZEN_P4.json) against the strict critic with the 7-14 Hz band view, no sensor "
        "term. Sources judged by the strict judge (judge seeds 0-2 + offset): physiomix_app, physioflow_app, "
        "r1_teacher, the G3 seeds and real_other_people. Validity: the real_other_people null mean AUC lies in "
        "[0.40, 0.60]; otherwise no claim. G3 wins if the round is valid, every seed passes the round-9 gates "
        "(eligible), its mean AUC over seeds is below the lowest of physiomix_app, physioflow_app and r1_teacher by "
        "more than max(0.02, seed SD) and its mean fresh-seed C is at most 0.10. The ship seed is the eligible seed "
        "with the lowest validation AUC. Targets (reported, not part of the win) are P1's. The test people are judged "
        "once, after DECISION_P4.json. indistinguishable = 100(1-|2AUC-1|).")


def rule_sha256():
    return hashlib.sha256(RULE.encode()).hexdigest()


def resolve_teacher(input_root, folder):
    """Copy the P1 ship seed's export (under input_root, the P1 round's output) to folder as the R1 teacher file."""
    from ml.kaggle_multidomain.flow_r import TEACHER_R_FILE
    decisions = sorted(Path(input_root).rglob("DECISION_R.json"))
    if len(decisions) != 1:
        raise ValueError(f"Expected one P1 DECISION_R.json, found {len(decisions)}")
    decision = json.loads(decisions[0].read_text())
    seed = decision["ship_seed"]
    if seed is None:
        raise ValueError("P1 has no eligible seed to fine-tune")
    source = decisions[0].parent/"benchmark"/f"{TEACHER_ARM}_seed{seed}"/"generator_cpu.ts"
    folder = Path(folder)
    folder.mkdir(parents=True)
    shutil.copy2(source, folder/TEACHER_R_FILE)
    sha = hashlib.sha256((folder/TEACHER_R_FILE).read_bytes()).hexdigest()
    shipped = decisions[0].parent/"ship"/TEACHER_R_FILE
    if shipped.exists() and hashlib.sha256(shipped.read_bytes()).hexdigest() != sha:
        raise ValueError("P1 ship/ file is not its ship seed's export")
    return dict(seed=seed, sha256=sha, p1_winner=decision["winner"], p1_rule_sha256=decision["rule_sha256"],
                p1_auc_by_seed=decision["auc_by_seed"], p1_C=decision["C"], source=str(source))


def train_seeds(device, seeds, input_root, output, steps, interval, n, seed_hours, deadline, teacher_root):
    """Seeds in turn on one device, each with its own seed_hours, none past the kernel's deadline."""
    from ml.kaggle_multidomain import experiment_v3
    rows = []
    for seed in seeds:
        stop = min(time.time()+3600*seed_hours, deadline)
        rows += experiment_v3.worker(device, [(ARM, seed)], input_root, output, steps, 32, interval, n, None, 2, stop,
                                     [teacher_root])
    return rows


def train_all(seeds, devices, input_root, output, steps, interval, n, seed_hours, deadline, teacher_root):
    """One worker per GPU (experiment_flow.final_devices): worker i trains seeds i, i+2, ... in turn."""
    args = (input_root, output, steps, interval, n, seed_hours, deadline, teacher_root)
    if devices == ["cpu"]:
        return train_seeds("cpu", seeds, *args)
    rows = []
    with ProcessPoolExecutor(len(devices), mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(train_seeds, d, seeds[i::len(devices)], *args) for i, d in enumerate(devices)]
        for future in as_completed(futures):
            rows.extend(future.result())
            save_json(Path(output)/"training_progress.json", rows)
    if sorted(r["seed"] for r in rows) != sorted(seeds):
        raise RuntimeError("Missing or duplicate training runs")
    return rows


def decide(val, training, seeds):
    names = [f"{ARM}_seed{s}" for s in seeds]
    mine = {r["seed"]: r for r in training}
    auc = {s: mean_auc(val, JUDGE, f"{ARM}_seed{s}") for s in seeds}
    values = list(auc.values())
    references = {n: mean_auc(val, JUDGE, n) for n in REFERENCES}
    best = min(references.values())
    null = null_control(val, JUDGE)
    margin = max(.02, spread(values))
    c = float(np.mean([mine[s]["C_fresh"] for s in seeds]))
    checks = dict(null_valid=null["valid"], eligible=all(mine[s]["eligible"] for s in seeds),
                  auc_gain=best-float(np.mean(values)) > margin, c_ok=c <= C_LIMIT)
    ships = [s for s in seeds if mine[s]["eligible"]]
    return dict(judge=JUDGE, rule_sha256=rule_sha256(), arm=ARM, references=references, best_reference=best,
                auc_by_seed=auc, mean_auc=float(np.mean(values)), margin=margin, C=c, null_control=null,
                checks=checks, winner=ARM if all(checks.values()) else None,
                ship_seed=min(ships, key=lambda s: auc[s]) if ships else None, targets=targets(val, JUDGE, names))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="v3 pack, app model files and the P1 round's output")
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=3000)
    parser.add_argument("--seed-hours", type=float, default=3.75, help="Training time of each seed")
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 2026])
    parser.add_argument("--judge-seeds", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--interval", type=int, default=500)
    parser.add_argument("--eval-samples", type=int, default=256)
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    from ml.kaggle_multidomain.data_gxu import load_input
    from ml.kaggle_multidomain.experiment_v3 import ARMS, PROTOCOL, check_pack, conditions_for
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and len(names) != 2:
        raise RuntimeError(f"Two GPUs required, allocated {names}")
    devices = ["cpu"] if a.allow_cpu else ["cuda:0", "cuda:1"]
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started, kernel_start = time.monotonic(), time.time()
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    teacher = resolve_teacher(a.input_root, output/"teacher")
    save_json(output/"FROZEN_P4.json", dict(rule=RULE, rule_sha256=rule_sha256(), arm=ARM, arm_config=ARMS[ARM],
                                            judge=JUDGE, judge_spec=sj.JUDGES[JUDGE], seeds=a.seeds,
                                            judge_seeds=a.judge_seeds, steps=a.steps, seed_hours=a.seed_hours,
                                            data_sha256=manifest["windows_sha256"], teacher=teacher))
    save_json(output/"configuration.json", dict(args=vars(a), python=platform.python_version(), torch=torch.__version__,
                                                allocated_gpus=names, cpu_count=os.cpu_count()))
    print("TEACHER", json.dumps({k: teacher[k] for k in ("seed", "sha256", "p1_winner")}), flush=True)
    deadline = kernel_start+3600*(KERNEL_HOURS-JUDGE_RESERVE_HOURS)
    (output/"benchmark").mkdir()
    training = train_all(a.seeds, devices, a.input_root, output/"benchmark", a.steps, a.interval, a.eval_samples,
                         a.seed_hours, deadline, str(output/"teacher"))
    save_json(output/"training_execution.json", training)
    print("TRAINING DONE", f"{time.monotonic()-started:.0f}s", flush=True)

    pack = {k: v[pack["split"] != "external"] for k, v in pack.items()}
    keep = np.flatnonzero(np.isin(pack["split"], ["train", "validation"]))
    bank = sj.ConditionsView(conditions_for({k: v[keep] for k, v in pack.items()}, "v2"), keep)
    bundle = next(p.parent for p in Path(a.input_root).rglob("manifest.json") if (p.parent/"physiomix_generator.ts").exists())
    apps = app_sources(bundle, bank, devices[0])
    from ml.kaggle_multidomain.flow_r import TEACHER_R_FILE
    sources = dict(physiomix_app=apps["physiomix_app"], physioflow_app=apps["physioflow_app"])
    sources[TEACHER] = sj.torchscript_generator(output/"teacher"/TEACHER_R_FILE, devices[0], len(bank.domains)+5)
    sources.update({f"{ARM}_seed{s}": checkpoint_generator(output/"benchmark"/f"{ARM}_seed{s}", ARM, bank, devices[0])
                    for s in a.seeds})
    kinds = [JUDGE, "probe"]
    val = judge_family(pack, bank, sources, "validation", sj.DOMAINS, kinds, a.judge_seeds, devices,
                       output/"validation")
    decision = decide(val, training, a.seeds)
    save_json(output/"DECISION_P4.json", decision)
    print("DECISION", json.dumps(dict(winner=decision["winner"], checks=decision["checks"])), flush=True)
    test = judge_family(pack, bank, sources, "test", sj.DOMAINS, kinds, a.judge_seeds, devices, output/"test")
    ship = output/"ship"
    ship.mkdir()
    if decision["winner"]:
        shutil.copy2(output/"benchmark"/f"{ARM}_seed{decision['ship_seed']}"/"generator_cpu.ts",
                     ship/"physioflow_r_gan_generator.ts")
    names = [f"{ARM}_seed{s}" for s in a.seeds]
    summary = dict(judge=JUDGE, teacher=teacher, decision=decision,
                   validation={k: indistinguishable(val, k) for k in kinds},
                   test={k: indistinguishable(test, k) for k in kinds},
                   test_targets=targets(test, JUDGE, names), wall_seconds=time.monotonic()-started)
    save_json(output/"summary.json", summary)
    save_json(output/"COMPLETE.json", dict(status="complete", winner=decision["winner"],
                                           wall_seconds=time.monotonic()-started, deployment="research_only"))
    print("COMPLETE", flush=True)
    return summary


if __name__ == "__main__":
    main()
