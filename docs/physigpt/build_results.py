"""Summarise the PPG-physiGPT Kaggle runs in evidence/ into results.json.

Every number comes from a file in evidence/ (copied from the Kaggle kernel outputs of the same name):
stage_summary.json for the held-out flow loss, generated_judge.json and scores_*.npz for the strict judge,
fidelity.json for the feature tier. V1 passes the feature tier when the generated mean similarity reaches
RELATIVE (95%) of real people against other real people (judge_physigpt.FIDELITY_REL). That relative bar is the
OLD criterion and is kept only for the earlier variants. The current criterion is absolute (see CRITERIA): mean 1-KS
over 22 features >= 0.95, every feature >= 0.90 (or the real-vs-real value if lower), tree accuracy <= 0.60; the
strict judge is no longer a pass criterion. The "benchmark" block compares four models on the same 180 held-out
MIMIC people from evidence/ppg-physigpt-judge-benchmark-generated-v1-fid/ (comparison.json, app_samples.json and the
per-model target.json); "rsr_flowgan" summarises evidence/ppg-rsr-flowgan-v1/. Records written before the relative
field existed get it here from their own two means. d' = (mean fake score - mean real score) / pooled standard deviation,
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


CRITERIA = dict(mean_similarity_22_features_at_least=0.95, feature_floor_at_least=0.90,
                feature_floor_note="or the real-vs-real value of that feature when lower",
                tree_accuracy_at_most=0.60, strict_judge="not a pass criterion; kept as a known limit "
                "(real vs other real people: AUC about 0.5)")
BENCH = "ppg-physigpt-judge-benchmark-generated-v1-fid"
RSR_FLOWGAN = "ppg-rsr-flowgan-v1"
# comparison.json key -> (name on the page, earlier name); V1 large = PPG-physiGPT V1 large
MODELS = {"v1_large": ("V1 large", None), "apft_gan": ("APFT-GAN", None),
          "rsh_gan_app": ("RSH-GAN", "PhysioMix"), "rsr_flow_app": ("RSR-Flow", "PhysioFlow")}


def benchmark(real_tree_accuracy):
    root = EVIDENCE/BENCH
    comp = json.loads((root/"comparison.json").read_text())
    samples = json.loads((root/"app_samples.json").read_text())
    full = comp["sets"]["full"]
    rows = []
    for key, (name, old) in MODELS.items():
        target = json.loads((root/f"generated_{key}"/"target.json").read_text())
        gen, tab = target["generated"], comp["table"][key]
        assert abs(gen["full"]["mean_similarity"]-tab["full"]) < 1e-9 and gen["full"]["features"] == 22
        assert abs(gen["classifier"]["trees"]["accuracy"]-tab["trees_accuracy"]) < 1e-9
        floor = {k: min(v, target["real_other_people"]["similarity"][k]) for k, v in target["floor"].items()}
        below = sorted(k for k, v in floor.items() if gen["similarity"][k] < v)
        passes = (gen["full"]["mean_similarity"] >= CRITERIA["mean_similarity_22_features_at_least"] and not below
                  and gen["classifier"]["trees"]["accuracy"] <= CRITERIA["tree_accuracy_at_most"])
        assert (target["verdict"] == "pass") == passes
        rows.append(dict(model=key, name=name, earlier_name=old, verdict="pass" if passes else "fail",
                         mean_22=round(gen["full"]["mean_similarity"], 4), mean_14=round(gen["fourteen"]["mean_similarity"], 4),
                         mean_beat_8=round(gen["beat"]["mean_similarity"], 4),
                         ci_95_mean_22=[round(v, 4) for v in full["means"][key]["corrected_95"]],
                         lowest=gen["lowest"], lowest_value=round(gen["similarity"][gen["lowest"]], 4),
                         features_below_floor=below, tree_accuracy=round(gen["classifier"]["trees"]["accuracy"], 4),
                         tree_auc=round(gen["classifier"]["trees"]["auc"], 4),
                         vs_real_22=round(full["against_real"][key]["point"], 4),
                         vs_real_22_ci_95=[round(v, 4) for v in full["against_real"][key]["corrected_95"]]))
    ref = json.loads((root/"generated_v1_large"/"target.json").read_text())["real_other_people"]
    pairs = {k: dict(point=round(v["point"], 4), ci_95=[round(x, 4) for x in v["corrected_95"]],
                     share_rounds_above_zero=v["share_rounds_above_zero"]) for k, v in full["differences"].items()}
    return dict(
        note="Same 180 held-out MIMIC people (2,000 windows), same 22 features, same scorer. RSH-GAN and RSR-Flow are the "
             "app models and were given the perform_large condition for the prompts, so this set is unfavourable to "
             "them; it does not show they are worse on their own data. Intervals: 2,000 bootstrap rounds over people, "
             "bias-corrected (comparison.json); differences are paired.",
        criteria=CRITERIA, held_people=comp["held_people"], other_people=comp["other_people"], rounds=comp["rounds"],
        app_domain=samples["domain"], models=rows,
        real_other_people=dict(mean_22=round(ref["full"]["mean_similarity"], 4), mean_14=round(ref["fourteen"]["mean_similarity"], 4),
                               tree_accuracy=real_tree_accuracy, tree_accuracy_source="earlier real-vs-real feature run (ppg-physigpt-judge-decay0-large-v1-fid)", ci_95_mean_22=[round(v, 4) for v in full["means"]["real_other_people"]["corrected_95"]]),
        paired_differences_22=pairs)


def rsr_flowgan():
    root = EVIDENCE/RSR_FLOWGAN
    fid = json.loads((root/"fidelity.json").read_text())["fidelity"]
    judge = json.loads((root/"judge_summary.json").read_text())["summary"]
    out = {}
    for key, source in (("rsr_flow_app", "rsr_flow_app"), ("seed42", "rsr_flowgan_seed42"), ("seed123", "rsr_flowgan_seed123")):
        g = fid[source]["generated"]
        out[key] = dict(source=source, mean_14=round(g["mean_similarity"], 4), tree_accuracy=round(g["classifier"]["trees"]["accuracy"], 4),
                        strict_auc=round(judge[source]["mean_auc"], 5), passes_absolute=g["passes"])
    for seed in ("42", "123"):
        t = json.loads((root/f"seed{seed}"/"train_summary.json").read_text())
        out[f"seed{seed}"].update(steps=t["steps"], hours=round(t["hours"], 2), best_step=t["best"]["step"])
    out["real_other_people"] = dict(mean_14=round(fid["rsr_flow_app"]["real_other_people"]["mean_similarity"], 4),
                                    strict_auc=round(judge["real_other_people"]["mean_auc"], 3))
    out["note"] = ("Multi-domain held-out people (6 domains, 14 features, small samples), not the 180 MIMIC people of "
                   "benchmark; the real-vs-real mean is itself only 0.855 there. Not comparable with benchmark numbers.")
    return out


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
               controls=controls("ppg-physigpt-judge-of-ppg-physigpt-decay0-v1"), variants=rows,
               benchmark=benchmark(next(r for r in rows if r["fidelity"] and r["variant"].startswith("large"))["fidelity"]["reference"]["tree_accuracy"]), rsr_flowgan=rsr_flowgan())
    (HERE/"results.json").write_text(json.dumps(out, indent=1, ensure_ascii=False)+"\n")
    for row in rows:
        s, f = row["strict"], row["fidelity"]
        print(f"{row['variant']:40s} flow {row['valid_flow']:.5f}  "
              f"d' {s['mean_d_prime'] if s else '-':>6}  AUC {s['mean_auc'] if s else '-':>8}  "
              f"fid {f['mean_similarity'] if f else '-'}  rel {f['relative_similarity'] if f else '-'}  "
              f"V1 {f['passes_v1_relative'] if f else '-'}  trees {f['tree_accuracy'] if f else '-'}")
    print("controls d'", out["controls"])
    for m in out["benchmark"]["models"]:
        print(f"{m['name']:10s} {m['verdict']}  22 feat {m['mean_22']}  CI {m['ci_95_mean_22']}  trees {m['tree_accuracy']}  "
              f"below floor {len(m['features_below_floor'])}  lowest {m['lowest']} {m['lowest_value']}")
    print("real", out["benchmark"]["real_other_people"])
    print("rsr_flowgan", {k: v for k, v in out["rsr_flowgan"].items() if k != "note"})


if __name__ == "__main__":
    main()
