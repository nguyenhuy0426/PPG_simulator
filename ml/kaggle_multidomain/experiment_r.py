"""PhysioFlow-R round (P1): PhysioFlow trained on the resample-only domain, ending in the v3 band-pass applied once.

Diagnosis this round tests (validation people, CPU re-measurement 2026-10-25): PhysioFlow is separated by the strict
judge through its spectral view alone (spectral branch AUC 1.00, time 0.65, acf 0.55): its 12-16 / 16-20 Hz STFT
power is 2.9e-6 / 2.5e-6 against real 1.9e-9 / 1.0e-10 (univariate AUC 1.00 on both bands), white error a velocity
network trained on v3 windows does not push down to the view's -95 dB stop band. Post-hoc band-limiting of its output
filters twice (8-12 Hz falls below real: AUC 0.09 / 0.00 on P8-10 / P10-12). R1_flowr trains the same recipe as the
app's PhysioFlow (experiment_v3 F6, 16 Heun steps) on the R pack (data_r: the v3 windows' records before the
band-pass, 40 s context) and ends in flow_r.RView: sosfiltfilt over the window plus the context its record had, as
the real windows were made, then the middle 30 s min-max. The band-pass runs once, on real and generated alike.

r_pipeline (pipeline null control): the real R windows of the prompted people through the same RView. If the judge
separates them from the pack's v3 windows, the view is not the real one and no claim is made.
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
from ml.kaggle_multidomain.experiment_strict import (app_sources, checkpoint_generator, indistinguishable,
                                                     judge_family, mean_auc, null_control, spread)

ARM = "R1_flowr"
JUDGE = "strict"
INCUMBENT = "physioflow_app"
C_LIMIT = .10
TARGET_POOLED, TARGET_LARGE, TARGET_SMALL = .75, .75, .60
VALID_RANGE = (.40, .60)
KERNEL_HOURS, JUDGE_RESERVE_HOURS = 12., 3.
LARGE_DOMAINS = ("perform_large", "gxu_finger")
SMALL_DOMAINS = ("bidmc", "perform_af", "perform_non_af", "wrist")
RULE = ("PhysioFlow-R round rule (P1), fixed before training; validation people only. Sources judged by the strict "
        "judge (judge seeds 0-2 + offset): the app's PhysioFlow (incumbent), R1_flowr seeds 42/123/2026, r_pipeline "
        "(real R windows of the prompted people through flow_r.RView) and real_other_people. Validity: the "
        "real_other_people null and the r_pipeline mean AUC both lie in [0.40, 0.60]; otherwise no claim. Null gate: "
        "before training the same judge and seeds judge r_pipeline and real_other_people on the validation people "
        "(NULL_R.json); if either mean AUC is outside [0.40, 0.60] the round stops there and makes no claim. R1 wins if "
        "the round is valid, every seed passes the round-9 gates (eligible), its mean AUC over seeds is below the "
        "incumbent's by more than max(0.02, seed SD) and its mean fresh-seed C is at most 0.10. The ship seed is the "
        "eligible seed with the lowest validation AUC. Targets (reported, not part of the win): pooled AUC <= 0.75; "
        "perform_large and gxu_finger AUC <= 0.75; bidmc, perform_af, perform_non_af and wrist AUC <= 0.60, checked "
        "only for a domain whose own real_other_people null lies in [0.40, 0.60] (else 'not verifiable'). The test "
        "people are judged once, after DECISION_R.json. indistinguishable = 100(1-|2AUC-1|).")


def rule_sha256():
    return hashlib.sha256(RULE.encode()).hexdigest()


def null_gate(rows):
    """NULL_R.json: the pre-training check that the view and the null control are valid before any GPU training."""
    auc = {name: mean_auc(rows, JUDGE, name) for name in ("r_pipeline", "real_other_people")}
    per_domain = {name: domain_means(rows, JUDGE, name) for name in auc}
    valid = {name: bool(VALID_RANGE[0] <= v <= VALID_RANGE[1]) for name, v in auc.items()}
    return dict(rule_sha256=rule_sha256(), judge=JUDGE, range=VALID_RANGE, auc=auc, per_domain=per_domain, valid=valid,
                passed=all(valid.values()))


def train_one(device, seed, input_root, output, steps, interval, n, deadline):
    from ml.kaggle_multidomain import experiment_v3
    return experiment_v3.worker(device, [(ARM, seed)], input_root, output, steps, 32, interval, n, None, 2, deadline)[0]


def train_all(seeds, devices, input_root, output, steps, interval, n, deadline):
    if devices == ["cpu"]:
        return [train_one("cpu", s, input_root, output, steps, interval, n, deadline) for s in seeds]
    rows = []
    with ProcessPoolExecutor(len(seeds), mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(train_one, devices[i % len(devices)], s, input_root, output, steps, interval, n,
                               deadline) for i, s in enumerate(seeds)]
        for future in as_completed(futures):
            rows.append(future.result())
            save_json(Path(output)/"training_progress.json", rows)
    return rows


def domain_means(rows, judge, name):
    by = {}
    for r in rows:
        if r["judge"] == judge and r["source"] == name:
            for d, v in r["per_domain"].items():
                by.setdefault(d, []).append(v["auc"])
    return {d: float(np.mean(v)) for d, v in by.items()}


def targets(rows, judge, names):
    """The rule's reported targets for the mean of names (the arm's seeds)."""
    null = domain_means(rows, judge, "real_other_people")
    per = [domain_means(rows, judge, n) for n in names]
    auc = {d: float(np.mean([p[d] for p in per])) for d in per[0]}
    pooled = float(np.mean([mean_auc(rows, judge, n) for n in names]))
    out = dict(pooled=dict(auc=pooled, target=TARGET_POOLED, met=pooled <= TARGET_POOLED))
    for d, v in auc.items():
        limit = TARGET_LARGE if d in LARGE_DOMAINS else TARGET_SMALL
        verifiable = d in LARGE_DOMAINS or .40 <= null.get(d, -1) <= .60
        out[d] = dict(auc=v, target=limit, null=null.get(d), met=(v <= limit) if verifiable else "not verifiable")
    return out


def decide(val, training, seeds):
    names = [f"{ARM}_seed{s}" for s in seeds]
    mine = {r["seed"]: r for r in training}
    auc = {s: mean_auc(val, JUDGE, f"{ARM}_seed{s}") for s in seeds}
    values = list(auc.values())
    incumbent = mean_auc(val, JUDGE, INCUMBENT)
    pipeline = mean_auc(val, JUDGE, "r_pipeline")
    null = null_control(val, JUDGE)
    margin = max(.02, spread(values))
    c = float(np.mean([mine[s]["C_fresh"] for s in seeds]))
    checks = dict(null_valid=null["valid"], pipeline_valid=.40 <= pipeline <= .60,
                  eligible=all(mine[s]["eligible"] for s in seeds), auc_gain=incumbent-float(np.mean(values)) > margin,
                  c_ok=c <= C_LIMIT)
    ships = [s for s in seeds if mine[s]["eligible"]]
    return dict(judge=JUDGE, rule_sha256=rule_sha256(), arm=ARM, incumbent_auc=incumbent, auc_by_seed=auc,
                mean_auc=float(np.mean(values)), margin=margin, C=c, null_control=null, r_pipeline_auc=pipeline,
                checks=checks, winner=ARM if all(checks.values()) else None,
                ship_seed=min(ships, key=lambda s: auc[s]) if ships else None,
                targets=targets(val, JUDGE, names))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="v3 pack, R pack and the app model files")
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=8000)
    parser.add_argument("--hours", type=float, default=6., help="Training deadline after the null gate")
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 2026])
    parser.add_argument("--judge-seeds", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--interval", type=int, default=500)
    parser.add_argument("--eval-samples", type=int, default=256)
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    from ml.kaggle_multidomain.data_gxu import load_input
    from ml.kaggle_multidomain.data_r import load_r
    from ml.kaggle_multidomain.experiment_v3 import PROTOCOL, TEACHER_ROOTS, check_pack, conditions_for
    from ml.kaggle_multidomain.flow_r import r_pipeline_source
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and len(names) != 2:
        raise RuntimeError(f"Two GPUs required, allocated {names}")
    devices = ["cpu"] if a.allow_cpu else ["cuda:0", "cuda:1"]
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started, kernel_start = time.monotonic(), time.time()
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    r, r_manifest = load_r(a.input_root, manifest)
    save_json(output/"FROZEN_R.json", dict(rule=RULE, rule_sha256=rule_sha256(), arm=ARM, judge=JUDGE,
                                           judge_spec=sj.JUDGES[JUDGE], seeds=a.seeds, judge_seeds=a.judge_seeds,
                                           steps=a.steps, hours=a.hours, data_sha256=manifest["windows_sha256"],
                                           r_sha256=r_manifest["windows_sha256"]))
    save_json(output/"configuration.json", dict(args=vars(a), python=platform.python_version(), torch=torch.__version__,
                                                allocated_gpus=names, cpu_count=os.cpu_count()))
    pack = {k: v[pack["split"] != "external"] for k, v in pack.items()}
    keep = np.flatnonzero(np.isin(pack["split"], ["train", "validation"]))
    bank = sj.ConditionsView(conditions_for({k: v[keep] for k, v in pack.items()}, "v2"), keep)
    gate = null_gate(judge_family(pack, bank, {"r_pipeline": r_pipeline_source(r, pack)}, "validation", sj.DOMAINS,
                                  [JUDGE], a.judge_seeds, devices, output/"null_check"))
    save_json(output/"NULL_R.json", gate)
    print("NULL GATE", json.dumps(dict(auc=gate["auc"], passed=gate["passed"])), f"{time.monotonic()-started:.0f}s",
          flush=True)
    if not gate["passed"]:
        save_json(output/"COMPLETE.json", dict(status="stopped_at_null_gate", winner=None, null_gate=gate,
                                               wall_seconds=time.monotonic()-started, deployment="research_only"))
        print("COMPLETE", flush=True)
        return dict(judge=JUDGE, null_gate=gate, decision=None)
    # Training gets its hours after the gate, but must leave the judges their reserve inside the kernel's limit.
    deadline = min(time.time()+3600*a.hours, kernel_start+3600*(KERNEL_HOURS-JUDGE_RESERVE_HOURS))
    (output/"benchmark").mkdir()
    training = train_all(a.seeds, devices, a.input_root, output/"benchmark", a.steps, a.interval, a.eval_samples,
                         deadline)
    save_json(output/"training_execution.json", training)
    print("TRAINING DONE", f"{time.monotonic()-started:.0f}s", flush=True)

    TEACHER_ROOTS[:] = [a.input_root]
    bundle = next(p.parent for p in Path(a.input_root).rglob("manifest.json") if (p.parent/"physiomix_generator.ts").exists())
    apps = app_sources(bundle, bank, devices[0])
    sources = {INCUMBENT: apps[INCUMBENT], "r_pipeline": r_pipeline_source(r, pack)}
    sources.update({f"{ARM}_seed{s}": checkpoint_generator(output/"benchmark"/f"{ARM}_seed{s}", ARM, bank, devices[0])
                    for s in a.seeds})
    kinds = [JUDGE, "probe"]
    val = judge_family(pack, bank, sources, "validation", sj.DOMAINS, kinds, a.judge_seeds, devices,
                       output/"validation")
    decision = decide(val, training, a.seeds)
    save_json(output/"DECISION_R.json", decision)
    print("DECISION", json.dumps(dict(winner=decision["winner"], checks=decision["checks"])), flush=True)
    test = judge_family(pack, bank, sources, "test", sj.DOMAINS, kinds, a.judge_seeds, devices, output/"test")
    ship = output/"ship"
    ship.mkdir()
    if decision["winner"]:
        shutil.copy2(output/"benchmark"/f"{ARM}_seed{decision['ship_seed']}"/"generator_cpu.ts",
                     ship/"physioflow_r_generator.ts")
    names = [f"{ARM}_seed{s}" for s in a.seeds]
    summary = dict(judge=JUDGE, null_gate=gate, decision=decision,
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
