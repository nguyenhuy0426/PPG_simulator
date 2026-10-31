"""Summarise the PPG-physiGPT Kaggle runs in evidence/ into results.json.

Every number comes from a file in evidence/ (copied from the Kaggle kernel outputs of the same name):
stage_summary.json for the held-out flow loss, generated_judge.json and scores_*.npz for the strict judge,
fidelity.json for the feature tier. V1 passes the feature tier when the generated mean similarity reaches
RELATIVE (95%) of real people against other real people (judge_physigpt.FIDELITY_REL); the absolute criterion
(0.95 and tree accuracy <= 0.60) is the V2 target. Records written before the relative field existed get it here
from their own two means. d' = (mean fake score - mean real score) / pooled standard deviation,
computed per judge seed from the raw scores and averaged; it is reported because the AUC is saturated at 1.0.

    python3 docs/physigpt/build_results.py
"""
import json
import pathlib

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
EVIDENCE = HERE/"evidence"
RELATIVE = .95   # judge_physigpt.FIDELITY_REL, repeated so this script runs without the ML dependencies

# variant -> (training kernel, strict-judge kernel, feature-tier kernel); None where that run was not made
VARIANTS = {
    "base, plateau stop (no decay)": ("ppg-physigpt-stage0-v1", "ppg-physigpt-judge0-v1", None),
    "base, decay 3k": ("ppg-physigpt-decay0-v1", "ppg-physigpt-judge-of-ppg-physigpt-decay0-v1", None),
    "base, decay 3k, unclamped sampling": ("ppg-physigpt-decay0-v1", "ppg-physigpt-judge-decay0-v1-noclamp", None),
    "base, decay 3k, 128 ODE steps": ("ppg-physigpt-decay0-v1", "ppg-physigpt-judge-decay0-v1-g128", None),
    "base, hold 7k + decay 3k (longer)": ("ppg-physigpt-decay0-longer-v1", "ppg-physigpt-judge-decay0-longer-v1", None),
    "base, longer + sharpness loss 0.25": ("ppg-physigpt-decay0-sharp-v1", "ppg-physigpt-judge-decay0-sharp-v1", None),
    "base, longer + sharpness loss 8": ("ppg-physigpt-decay0-sharp8-v1", None, "ppg-physigpt-judge-decay0-sharp8-v1-fid"),
    "large, plateau stop + decay 3k": ("ppg-physigpt-decay0-large-v1", "ppg-physigpt-judge-decay0-large-v1",
                                       "ppg-physigpt-judge-decay0-large-v1-fid"),
}


def d_prime(path):
    scores = np.load(path, allow_pickle=False)
    real, fake = scores["real"].astype(np.float64), scores["fake"].astype(np.float64)
    return float((fake.mean()-real.mean())/np.sqrt((fake.var()+real.var())/2))


def strict(kernel):
    record = json.loads((EVIDENCE/kernel/"generated_judge.json").read_text())
    seeds = [run["seed"] for run in record["result"]["runs"]]
    d = [d_prime(EVIDENCE/kernel/f"scores_generated_seed{s}.npz") for s in seeds]
    return dict(kernel=kernel, seeds=seeds, gen_steps=record["info"].get("gen_steps", 32),
                clamp=record["info"].get("clamp", True), mean_auc=round(record["result"]["mean_auc"], 6),
                d_prime=[round(v, 2) for v in d], mean_d_prime=round(float(np.mean(d)), 2))


def controls(kernel):
    found = {}
    for path in sorted((EVIDENCE/kernel).glob("scores_*_seed0.npz")):
        name = path.name[len("scores_"):-len("_seed0.npz")]
        if name != "generated":
            found[name] = round(d_prime(path), 2)
    return found


def fidelity(kernel):
    record = json.loads((EVIDENCE/kernel/"fidelity.json").read_text())
    gen, ref = record["generated"], record["real_other_people"]
    return dict(kernel=kernel, mean_similarity=round(gen["mean_similarity"], 4),
                share_at_least_95=round(gen["share_at_least_95"], 4),
                tree_accuracy=round(gen["classifier"]["trees"]["accuracy"], 4),
                tree_auc=round(gen["classifier"]["trees"]["auc"], 4),
                relative_similarity=round(gen["mean_similarity"]/ref["mean_similarity"], 4),
                passes_v1_relative=bool(gen["mean_similarity"]/ref["mean_similarity"] >= RELATIVE),
                passes_v2_absolute=gen["passes"],
                similarity=gen["similarity"], reference=dict(mean_similarity=round(ref["mean_similarity"], 4),
                share_at_least_95=round(ref["share_at_least_95"], 4),
                tree_accuracy=round(ref["classifier"]["trees"]["accuracy"], 4), similarity=ref["similarity"]),
                criteria=dict(record["criteria"], relative_mean_similarity_at_least=RELATIVE))


def main():
    rows = []
    for name, (train, judge, feat) in VARIANTS.items():
        summary = json.loads((EVIDENCE/train/"stage_summary.json").read_text())
        config = json.loads((EVIDENCE/train/"run_config.json").read_text())
        rows.append(dict(variant=name, config=config["config"], parameters=config["model"]["parameters"],
                         train_kernel=train, steps=summary["steps"], hours=round(summary["hours"], 2),
                         valid_flow=round(summary["final"]["valid_flow"], 5),
                         strict=strict(judge) if judge else None, fidelity=fidelity(feat) if feat else None))
    out = dict(note="Engineering evaluation of normalised 30 s, 40 Hz PPG shape; not clinical validation. valid_flow "
                    "is on held-out records that also chose best.pt; the strict judge and the feature tier use "
                    "separate held-out people.",
               controls=controls("ppg-physigpt-judge-of-ppg-physigpt-decay0-v1"), variants=rows)
    (HERE/"results.json").write_text(json.dumps(out, indent=1, ensure_ascii=False)+"\n")
    for row in rows:
        s, f = row["strict"], row["fidelity"]
        print(f"{row['variant']:40s} flow {row['valid_flow']:.5f}  "
              f"d' {s['mean_d_prime'] if s else '-':>6}  AUC {s['mean_auc'] if s else '-':>8}  "
              f"fid {f['mean_similarity'] if f else '-'}  rel {f['relative_similarity'] if f else '-'}  "
              f"V1 {f['passes_v1_relative'] if f else '-'}  trees {f['tree_accuracy'] if f else '-'}")
    print("controls d'", out["controls"])


if __name__ == "__main__":
    main()
