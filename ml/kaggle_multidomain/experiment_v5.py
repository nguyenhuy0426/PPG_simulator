"""PhysioMix rounds 5-6: the round-4 winner with a cropped (non-circular) output window.

A derivative C2ST probe separated unseen real GXU windows from circularly band-limited copies of other
people's real windows (AUC 0.98) about as well as from round-3 v2 (0.975), while the unmodified real
windows scored 0.53: most of the detectability came from the circular output filter, not the learned
waveform. One arm, three seeds. The rule names the incumbent (round-4 winner if round 4 shipped, else
round-3 v2) with its per-seed scores and is frozen before training; the GXU test is scored after.
Round 6 (variant crop_r1) repeats it with the critic clip on lazy-R1 steps scaled by the 16-step interval:
in round 5 every R1 step was clipped (median norm ~100 vs limit 10), failing the d_clipped gate on all seeds.
"""
VARIANTS = {"crop": "a {pad}-sample cropped output",
            "crop_r1": "a {pad}-sample cropped output and the critic clip on lazy-R1 steps scaled x16 (10 -> 160)",
            "crop_r1w": "a {pad}-sample cropped output, the x16 R1-step clip and the R1 weight lowered to 0.1, about "
                        "the effective strength of round 5's always-clipped R1 (norm 10 of ~100)"}
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
from ml.kaggle_multidomain.experiment_v4 import ROUND3_V2
from ml.kaggle_multidomain.report_v3 import fmt, stat, summarize


def scores(execution, arm):
    rows = sorted((r for r in json.loads(execution.read_text())["runs"] if r["arm"] == arm), key=lambda r: r["seed"])
    return dict(arm=arm, S_arm=[r["S_arm"] for r in rows], S_real_fresh=[r["S_real_fresh"] for r in rows],
                seeds=[r["seed"] for r in rows])


def round4_reference(root, incumbent_root=None):
    """Round-4 winner (the base arm) and the incumbent: the latest shipped arm, read from each round's own
    outputs. incumbent_root holds a later shipped round (DECISION_ROUND5.json with its benchmark)."""
    path = next(Path(root).rglob("SELECTION_ROUND4.json"))
    selection = json.loads(path.read_text())
    winner = selection["winner"]
    if winner is None:
        raise ValueError("Round 4 selected no eligible arm")
    base = scores(path.parent/"benchmark"/"training_execution.json", winner)
    incumbent = dict(base, name=winner) if selection["ship"] else dict(ROUND3_V2, name="round3_physiomix_v2")
    if incumbent_root is not None:
        path = next(Path(incumbent_root).rglob("DECISION_ROUND5.json"))
        decision = json.loads(path.read_text())
        if decision["ship"]:
            incumbent = dict(scores(path.parent/"benchmark"/"training_execution.json", decision["arm"]),
                             name=decision["arm"])
    return base, incumbent


def rule_text(base, incumbent, variant="crop"):
    mean = sum(incumbent["S_arm"])/len(incumbent["S_arm"])
    arm = f"{base['arm']}_{variant}"
    change = VARIANTS[variant].format(pad=config(arm)["pad"])
    return (f"PhysioMix {variant} rule (validation only; locked criterion sha256 {CRITERION_SHA256}).\n"
            f"Arm {arm} = round-4 winner {base['arm']} with {change}, same seeds, steps and learning-rate schedule "
            "as round 4; every round-3 gate unchanged.\n"
            f"Incumbent: {incumbent['name']}, S_arm {incumbent['S_arm']}, S_real {incumbent['S_real_fresh']} "
            f"(mean S_arm {mean:.4f}).\n"
            "Ship the crop arm only if every seed passes the round-3 gates, its mean S_arm beats the incumbent by more "
            "than the pooled seed SD and its mean S_real is at most the incumbent's + 0.05; the shipped seed is its "
            "lowest-S_arm seed. Otherwise the incumbent stays. The GXU test is scored only after this decision is saved.")


def decide(rows, arm, incumbent):
    mine = [r for r in rows if r["arm"] == arm]
    s_arm, s_real = stat([r["S_arm"] for r in mine]), stat([r["S_real_fresh"] for r in mine])
    ref, ref_real = stat(incumbent["S_arm"]), stat(incumbent["S_real_fresh"])
    eligible = bool(mine) and all(r["eligible"] for r in mine)
    pooled = math.sqrt(((s_arm["sd"] or 0)**2+(ref["sd"] or 0)**2)/2)
    gap = ref["mean"]-s_arm["mean"]
    non_inferior = s_real["mean"] <= ref_real["mean"]+.05
    return dict(arm=arm, incumbent=incumbent["name"], ship=bool(eligible and gap > pooled and non_inferior),
                ship_seed=min(mine, key=lambda r: r["S_arm"])["seed"], eligible=eligible, gap=gap, pooled_sd=pooled,
                non_inferior=non_inferior, S_arm=s_arm, S_real=s_real, incumbent_S_arm=ref, incumbent_S_real=ref_real)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--round4-root", required=True, help="Directory holding round-4 outputs")
    parser.add_argument("--incumbent-root", help="Directory holding a later round whose shipped arm is the incumbent")
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=20000)
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 2026])
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--interval", type=int, default=500)
    parser.add_argument("--eval-samples", type=int, default=256)
    parser.add_argument("--bootstrap", type=int, default=200)
    parser.add_argument("--variant", choices=tuple(VARIANTS), default="crop")
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and (len(names) != 2 or any("T4" not in name for name in names)):
        raise RuntimeError(f"Two T4 GPUs required, allocated {names}")
    base, incumbent = round4_reference(a.round4_root, a.incumbent_root)
    arm = f"{base['arm']}_{a.variant}"
    devices = ["cpu"] if a.allow_cpu else [f"cuda:{i % 2}" for i in range(len(a.seeds))]
    threads = 1 if len(devices) > 2 else 2
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    seal, sealed_count = sealed_subjects(pack)
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    rule = rule_text(base, incumbent, a.variant)
    save_json(output/"FROZEN_ROUND5.json", dict(rule=rule, rule_sha256=hashlib.sha256(rule.encode()).hexdigest(),
              arm=arm, config=config(arm), base=base, incumbent=incumbent, seeds=a.seeds, steps=a.steps,
              data_sha256=manifest["windows_sha256"], gxu_test_subject_sha256=seal))
    save_json(output/"configuration.json", dict(args=vars(a), python=platform.python_version(), torch=torch.__version__,
              allocated_gpus=names, training_workers=len(devices), threads_per_worker=threads, cpu_count=os.cpu_count(),
              data_sha256=manifest["windows_sha256"], view=VIEW, gxu_test_subjects=sealed_count))
    rows = parallel([(arm, seed) for seed in a.seeds], devices, a.input_root, output/"benchmark", a.steps, a.batch,
                    a.interval, a.eval_samples, None, threads)
    decision = decide(rows, arm, incumbent)
    save_json(output/"DECISION_ROUND5.json", decision)
    print("DECISION", arm, "ship", decision["ship"], flush=True)
    from ml.kaggle_multidomain.evaluate_v3 import evaluate_frozen
    from ml.kaggle_multidomain.report_v3 import figures
    results = evaluate_frozen(rows, pack, output/"benchmark", dict(arms=[arm], aliases={}), devices[0], a.bootstrap,
                              a.eval_samples)
    references = json.loads((output/"benchmark"/"references.json").read_text())
    summary = summarize(results)
    save_json(output/"summary.json", dict(arms=summary, decision=decision, references=references))
    figures(output, results, summary, references)
    s = summary[arm]
    (output/"REPORT_ROUND5.md").write_text("\n".join([
        f"# PhysioMix round 5: {arm}", "",
        f"Đưa vào app: **{decision['ship']}** so với {incumbent['name']} (S_arm {fmt(decision['incumbent_S_arm'])}); "
        f"chênh {decision['gap']:.3f}, SD gộp {decision['pooled_sd']:.3f}.", "",
        f"S_arm {fmt(s['S_arm'])}, S_real {fmt(s['S_real'])}, C {fmt(s['C'])}, C2ST đạo hàm {fmt(s['c2st_derivative'])}, "
        f"C2ST raw {fmt(s['c2st_raw'])}, GXU test Q {fmt(s['gxu_test_Q'])} (test đã mở ở round 3; chỉ báo cáo).", "",
        "![Control](control_and_fresh_test.png)", "![Waveforms](waveforms_gxu.png)"])+"\n")
    save_json(output/"COMPLETE.json", dict(status="complete", arm=arm, ship=decision["ship"],
              data_sha256=manifest["windows_sha256"], wall_seconds=time.monotonic()-started, deployment="research_only"))
    print("COMPLETE", arm, flush=True)


if __name__ == "__main__":
    main()
