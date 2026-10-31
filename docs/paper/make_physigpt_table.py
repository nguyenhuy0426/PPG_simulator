"""Write tables/physigpt.tex from evidence/physigpt-stage0-v1/results.json.

results.json is written by docs/physigpt/build_results.py on the branch that holds the PPG-physiGPT runs, from the
Kaggle kernel records in docs/physigpt/evidence/; it is copied here unchanged.

    python3 docs/paper/make_physigpt_table.py
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
RESULTS = json.loads((HERE/"evidence/physigpt-stage0-v1/results.json").read_text())
ROWS = [("Base, longer + sharpness 0.25", "base, longer + sharpness loss 0.25"),
        ("Base, longer + sharpness 8", "base, longer + sharpness loss 8"),
        ("Large", "large, plateau stop + decay 3k")]


def cell(value, digits):
    return "--" if value is None else f"{value:.{digits}f}"


def rel(feat):
    if not feat:
        return "--"
    return f"{feat['mean_similarity']:.3f} ({100*feat['relative_similarity']:.1f}\\%)"


variants = {row["variant"]: row for row in RESULTS["variants"]}
lines = []
for label, key in ROWS:
    row = variants[key]
    strict, feat = row["strict"] or {}, row["fidelity"] or {}
    lines.append(f"{label} & {row['parameters']/1e6:.1f} & {row['valid_flow']:.4f} & {cell(strict.get('mean_auc'), 2)} & "
                 f"{cell(strict.get('mean_d_prime'), 1)} & {rel(feat)} & "
                 f"{cell(feat.get('tree_accuracy'), 2)} \\\\")
ref = variants["large, plateau stop + decay 3k"]["fidelity"]["reference"]
lines.append(f"Real, other subjects & -- & -- & -- & {RESULTS['controls']['real_other_people']:.2f} & "
             f"{ref['mean_similarity']:.3f} & {ref['tree_accuracy']:.2f} \\\\")
(HERE/"tables/physigpt.tex").write_text("\n".join(lines)+"\n")
print("\n".join(lines))
