"""PhysioMix round 4: longer training at a lower learning rate, a scale-anchored pulse and beat timing.

Single stage. The rule is written to FROZEN_ROUND4.json before any training, reads validation-derived
fields only (the locked round-3 criterion), and is applied before the GXU finger test is scored. That
test was opened once in round 3, so here it is a re-used holdout, not a sealed one. Workers only ever
receive train+validation.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import time

import torch

from ml.kaggle_lsm.train_lsm import save_json
from ml.kaggle_multidomain.data_gxu import load_input
from ml.kaggle_multidomain.experiment_v3 import (CRITERION_SHA256, PROTOCOL, VIEW, check_pack, config, parallel,
                                                 sealed_subjects)
from ml.kaggle_multidomain.report_v3 import fmt, stat, summarize

# Ordered by number of changes on top of round-3 physiomix_v2 (P4_v2_osc_dc).
ROUND4 = ("L1_v2_lr", "L2_rel_lr", "L3_rel_beat_lr", "L4_rel_beat_dom_lr")
TIE = .01
# Round-3 physiomix_v2 (lr 2e-4 constant, 10000 steps), seeds 42/123/2026, from
# ml/runs/physiomix3-final-result-v1/physiomix3/benchmark/training_execution.json.
ROUND3_V2 = dict(S_arm=[.5786631538990534, .5822552091758637, .6259113024743039],
                 S_real_fresh=[.37724536685135757, .3394293098960376, .38247588889461326])
RULE = f"""PhysioMix round 4 rule (validation only; same locked criterion sha256 {CRITERION_SHA256}).
Arms L1-L4, three seeds each, Adam 1e-4 cosine-decayed to 1e-5, checkpoints every 500 steps from 1000.
Winner: lowest mean S_arm among arms whose every seed passes all round-3 gates; any arm within {TIE} of
that mean with fewer changes (L1 < L2 < L3 < L4) wins instead. Ship to the app only if the winner beats
round-3 physiomix_v2 (mean S_arm {sum(ROUND3_V2['S_arm'])/3:.4f}) by more than the pooled seed SD and its
mean S_real is at most round-3 + 0.05; the shipped seed is the winner's lowest-S_arm seed. Otherwise
round-3 physiomix_v2 stays in the app. The GXU test is scored only after this selection is saved."""
RULE_SHA256 = hashlib.sha256(RULE.encode()).hexdigest()


def select_round4(rows):
    arms = {}
    for arm in ROUND4:
        mine = [r for r in rows if r["arm"] == arm]
        arms[arm] = dict(S_arm=stat([r["S_arm"] for r in mine]), S_real=stat([r["S_real_fresh"] for r in mine]),
                         eligible=bool(mine) and all(r["eligible"] for r in mine), seeds=[r["seed"] for r in mine])
    eligible = [a for a in ROUND4 if arms[a]["eligible"]]
    reference, reference_real = stat(ROUND3_V2["S_arm"]), stat(ROUND3_V2["S_real_fresh"])
    if not eligible:
        return dict(winner=None, ship=False, reason="no eligible arm", arms=arms, rule_sha256=RULE_SHA256)
    best = min(arms[a]["S_arm"]["mean"] for a in eligible)
    winner = next(a for a in eligible if arms[a]["S_arm"]["mean"] <= best+TIE)
    chosen = arms[winner]
    pooled = math.sqrt(((chosen["S_arm"]["sd"] or 0)**2+reference["sd"]**2)/2)
    gap = reference["mean"]-chosen["S_arm"]["mean"]
    non_inferior = chosen["S_real"]["mean"] <= reference_real["mean"]+.05
    seed = min((r for r in rows if r["arm"] == winner), key=lambda r: r["S_arm"])["seed"]
    return dict(winner=winner, ship=bool(gap > pooled and non_inferior), ship_seed=seed, gap_vs_round3=gap,
                pooled_sd=pooled, non_inferior=non_inferior, round3_reference=dict(S_arm=reference, S_real=reference_real),
                arms=arms, rule_sha256=RULE_SHA256, criterion_sha256=CRITERION_SHA256)


def report(output, results, selection):
    from ml.kaggle_multidomain.report_v3 import figures
    references = json.loads((output/"benchmark"/"references.json").read_text())
    summary = summarize(results)
    save_json(output/"summary.json", dict(arms=summary, selection=selection, references=references))
    figures(output, results, summary, references)
    pools = list(next(iter(summary.values()))["pools"])
    lines = ["# PhysioMix round 4: learning rate thấp hơn, train lâu hơn, sửa trôi nhịp và nhịp AF", "",
             f"Chọn bằng validation: **{selection['winner']}**; vượt round-3 v2 và đưa vào app: **{selection['ship']}** "
             f"(chênh S_arm {selection.get('gap_vs_round3', float('nan')):.3f}, SD gộp {selection.get('pooled_sd', float('nan')):.3f}).",
             "", "| Arm | S_arm (↓) | S_real | C (HR) | C2ST đạo hàm | MAE HR ngoài | CV đo ở σ=0.2 | " +
             " | ".join(f"Q {p}" for p in pools)+" | GXU test Q |",
             "|"+"---|"*(8+len(pools))]
    for arm, s in summary.items():
        c = s["control"]
        lines.append(f"| {arm} | {fmt(s['S_arm'])} | {fmt(s['S_real'])} | {fmt(s['C'])} | {fmt(s['c2st_derivative'])} | "
                     f"{fmt(c['mae_ext'], 1)} | {fmt(c['irr_cv_at_sigma_0_2'])} | " +
                     " | ".join(fmt(s["pools"][p]) for p in pools)+f" | {fmt(s['gxu_test_Q'])} |")
    lines += ["", f"Round-3 physiomix_v2: S_arm {fmt(selection['round3_reference']['S_arm'])}, "
              f"S_real {fmt(selection['round3_reference']['S_real'])}.",
              "GXU test đã mở một lần ở round 3: ở đây chỉ báo cáo, không dùng để chọn.",
              "", "![Control](control_and_fresh_test.png)", "![Waveforms](waveforms_gxu.png)"] \
        if selection.get("round3_reference") else []
    (output/"REPORT_ROUND4.md").write_text("\n".join(lines)+"\n")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=20000)
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 2026])
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--interval", type=int, default=500)
    parser.add_argument("--eval-samples", type=int, default=256)
    parser.add_argument("--bootstrap", type=int, default=200)
    parser.add_argument("--workers-per-gpu", type=int, help="Default: 2 when at least 4 CPUs, else 1")
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and (len(names) != 2 or any("T4" not in name for name in names)):
        raise RuntimeError(f"Two T4 GPUs required, allocated {names}")
    per_gpu = a.workers_per_gpu or (2 if (os.cpu_count() or 1) >= 4 else 1)
    devices = ["cpu"] if a.allow_cpu else [f"cuda:{i % 2}" for i in range(2*per_gpu)]
    threads = 1 if per_gpu > 1 else 2
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    seal, sealed_count = sealed_subjects(pack)
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    save_json(output/"FROZEN_ROUND4.json", dict(rule=RULE, rule_sha256=RULE_SHA256, criterion_sha256=CRITERION_SHA256,
              arms={arm: config(arm) for arm in ROUND4}, seeds=a.seeds, steps=a.steps, batch=a.batch,
              round3_physiomix_v2=ROUND3_V2, data_sha256=manifest["windows_sha256"], gxu_test_subject_sha256=seal,
              holdout_rule="GXU test opened once in round 3; scored here after SELECTION_ROUND4.json, report only"))
    save_json(output/"data_manifest.json", manifest)
    save_json(output/"configuration.json", dict(args=vars(a), python=platform.python_version(), torch=torch.__version__,
              allocated_gpus=names, training_workers=len(devices), threads_per_worker=threads, cpu_count=os.cpu_count(),
              data_sha256=manifest["windows_sha256"], view=VIEW, gxu_test_subjects=sealed_count))
    rows = parallel([(arm, seed) for arm in ROUND4 for seed in a.seeds], devices, a.input_root, output/"benchmark",
                    a.steps, a.batch, a.interval, a.eval_samples, None, threads)
    selection = select_round4(rows)
    save_json(output/"SELECTION_ROUND4.json", selection)
    print("SELECTED", selection["winner"], "ship", selection["ship"], flush=True)
    from ml.kaggle_multidomain.evaluate_v3 import evaluate_frozen
    results = evaluate_frozen(rows, pack, output/"benchmark", dict(arms=list(ROUND4), aliases={}), devices[0],
                              a.bootstrap, a.eval_samples)
    report(output, results, selection)
    save_json(output/"COMPLETE.json", dict(status="complete", trained_runs=len(rows), winner=selection["winner"],
              ship=selection["ship"], data_sha256=manifest["windows_sha256"], wall_seconds=time.monotonic()-started,
              deployment="research_only"))
    print("COMPLETE", selection["winner"], flush=True)


if __name__ == "__main__":
    main()
