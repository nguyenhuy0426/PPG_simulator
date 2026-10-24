"""Spectral-finish round: the app's generators with the spectral_finish low-pass, judged by the strict judge.

No training. scripts/leak_features.py found the generators' windows carry 12-20 Hz power the real windows do not;
this round measures how much of the strict judge's AUC that residue explains. PhysioMix slot only (six domains): the
LSM slot's null control is invalid on BIDMC (the judge separates its people), so an LSM comparison would not be
interpretable. Judged on validation people with three judge seeds, RULE and the decision saved before the test
people are judged once (experiment_strict.SET_SEEDS / JUDGE_SEED_OFFSETS).
Engineering evaluation of normalised 30 s PPG shape; not clinical validation, not measured on the Pi/DAC/OPT101.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import time

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import save_json
from ml.kaggle_multidomain import strict_judge as sj
from ml.kaggle_multidomain.experiment_strict import app_sources, indistinguishable, judge_family, mean_auc, \
    null_control, spread
from ml.kaggle_multidomain.spectral_finish import low_passed

JUDGE = "strict"
# Per round: name -> (base source, low-pass start Hz, stop Hz). Round 1 found 10-12 Hz best on PhysioFlow (validation
# strict AUC 0.954, 11-12.5 Hz 0.992) and no gain on PhysioMix; round 2 sweeps lower and steeper bands on PhysioFlow,
# 10-12 Hz kept as the anchor.
ROUNDS = {"v1": {"physioflow_lp10": ("physioflow_app", 10., 12.), "physioflow_lp11": ("physioflow_app", 11., 12.5),
                 "physiomix_lp11": ("physiomix_app", 11., 12.5), "physiomix_lp12": ("physiomix_app", 12., 14.)},
          "v2": {"physioflow_lp10": ("physioflow_app", 10., 12.), "physioflow_lp9": ("physioflow_app", 9., 11.),
                 "physioflow_lp9_5": ("physioflow_app", 9.5, 11.), "physioflow_lp10_s": ("physioflow_app", 10., 11.)}}
CANDIDATES = ROUNDS["v1"]
REFERENCES = ("physiomix_app", "physioflow_app")
RULE = ("Spectral-finish round rule, fixed before scoring (validation people only). A candidate is an app generator "
        "followed by spectral_finish.low_pass(start, stop). It wins if its mean strict-judge AUC over judge seeds "
        "0-2 (+offset) is below the PhysioMix app model's by more than max(0.02, its judge-seed SD) and the "
        "real_other_people null control lies in [0.40, 0.60]. Among winners the lowest mean AUC is chosen. Each "
        "candidate is also compared with its own unfinished base (finish_gain = base AUC - candidate AUC), reported, "
        "not a gate. The test people are judged once, after DECISION_FINISH.json, for every source. "
        "indistinguishable = 100(1-|2AUC-1|).")


def rule_sha256():
    return hashlib.sha256(RULE.encode()).hexdigest()


def sources(apps, candidates):
    out = {name: apps[name] for name in REFERENCES}
    out.update({name: low_passed(apps[base], start, stop) for name, (base, start, stop) in candidates.items()})
    return out


def decide(rows, candidates):
    app = mean_auc(rows, JUDGE, "physiomix_app")
    null = null_control(rows, JUDGE)
    arms = {}
    for name, (base, start, stop) in candidates.items():
        values = [r["auc"] for r in rows if r["judge"] == JUDGE and r["source"] == name]
        mean = float(np.mean(values))
        margin = max(.02, spread(values))
        arms[name] = dict(base=base, band=[start, stop], mean_auc=mean, margin=margin, auc_gain=app-mean > margin,
                          finish_gain=mean_auc(rows, JUDGE, base)-mean)
    winners = [n for n, v in arms.items() if v["auc_gain"] and null["valid"]]
    return dict(judge=JUDGE, rule_sha256=rule_sha256(), app_auc=app, null_control=null, candidates=arms,
                references={n: mean_auc(rows, JUDGE, n) for n in REFERENCES},
                winner=min(winners, key=lambda n: arms[n]["mean_auc"]) if winners else None)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="v3 pack and the app model files (manifest.json)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--round", choices=sorted(ROUNDS), default="v1")
    parser.add_argument("--judge-seeds", nargs="+", type=int, default=[0, 1, 2])
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
    started = time.monotonic()
    candidates = ROUNDS[a.round]
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    save_json(output/"FROZEN_FINISH.json", dict(rule=RULE, rule_sha256=rule_sha256(), round=a.round, candidates=candidates,
                                                references=REFERENCES, judge=JUDGE, judge_spec=sj.JUDGES[JUDGE],
                                                judge_seeds=a.judge_seeds, data_sha256=manifest["windows_sha256"]))
    save_json(output/"configuration.json", dict(args=vars(a), python=platform.python_version(), torch=torch.__version__,
                                                allocated_gpus=names, cpu_count=os.cpu_count()))
    pack = {k: v[pack["split"] != "external"] for k, v in pack.items()}
    keep = np.flatnonzero(np.isin(pack["split"], ["train", "validation"]))
    bank = sj.ConditionsView(conditions_for({k: v[keep] for k, v in pack.items()}, "v2"), keep)
    bundle = next(p.parent for p in Path(a.input_root).rglob("manifest.json")
                  if (p.parent/"physiomix_generator.ts").exists())
    gens = sources(app_sources(bundle, bank, devices[0]), candidates)
    kinds = [JUDGE, "probe"]
    val = judge_family(pack, bank, gens, "validation", sj.DOMAINS, kinds, a.judge_seeds, devices,
                       output/"validation"/"physiomix")
    decision = dict(decide(val, candidates), round=a.round)
    save_json(output/"DECISION_FINISH.json", decision)
    print("DECISION", decision["winner"], flush=True)
    test = judge_family(pack, bank, gens, "test", sj.DOMAINS, kinds, a.judge_seeds, devices,
                        output/"test"/"physiomix")
    summary = dict(judge=JUDGE, decision=decision, validation={k: indistinguishable(val, k) for k in kinds},
                   test={k: indistinguishable(test, k) for k in kinds}, wall_seconds=time.monotonic()-started)
    save_json(output/"summary.json", summary)
    save_json(output/"COMPLETE.json", dict(status="complete", winner=decision["winner"],
                                           wall_seconds=time.monotonic()-started, deployment="research_only"))
    print("COMPLETE", json.dumps(summary["validation"][JUDGE]), flush=True)
    return summary


if __name__ == "__main__":
    main()
