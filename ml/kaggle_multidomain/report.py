"""Turn completed, frozen benchmark artifacts into a readable report and figures."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t


def report(root):
    root = Path(root)
    result = json.loads((root/"results.json").read_text())
    selection = json.loads((root/"selection.json").read_text())
    manifest = json.loads((root/"data_manifest.json").read_text())
    rows, winner = result["models"], selection["winner"]
    arms = sorted(set(r["arm"] for r in rows))
    domains = [(split, d) for split in ("test", "external") for d in sorted(rows[0][split])]
    summary = []
    for arm in arms:
        runs = [r for r in rows if r["arm"] == arm]
        for split, domain in domains:
            values = np.asarray([r[split][domain]["total_mmd"] for r in runs])
            std = float(values.std(ddof=1)) if len(values) > 1 else 0.
            summary.append(dict(arm=arm, split=split, domain=domain, seeds=len(values),
                                total_mmd_mean=float(values.mean()), total_mmd_std=std,
                                cpu_median_ms=float(np.mean([r["latency"]["median_ms"] for r in runs])),
                                parameters=runs[0]["generator_parameters"]))
    with (root/"summary.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary[0])); writer.writeheader(); writer.writerows(summary)
    lines = ["# PPG multidomain benchmark", "", f"Selected by validation: **{winner}**.", "",
             "Five independent research arms; the hybrid and diffusion are adaptations, not reproductions of named papers.",
             "Lower total MMD is better. It sums train-calibrated ACF, log-PSD and morphology MMD².",
             "Model/checkpoint choice was frozen before test and PTT evaluation. Selection is restricted to this experiment.", "",
             "## Architecture and data ablations", "", "| Arm | Validation mean | Parameters | CPU median (ms / 30 s clip) | Training hours |", "|---|---:|---:|---:|---:|"]
    for arm in arms:
        runs = [r for r in rows if r["arm"] == arm]
        lines.append(f"| {arm} | {selection['mean_validation'][arm]:.4f} | {runs[0]['generator_parameters']:,} | "
                     f"{np.mean([r['latency']['median_ms'] for r in runs]):.2f} | {sum(r['training_seconds'] for r in runs)/3600:.3f} |")
    lines += ["", "## Domain scores (mean ± SD across training seeds)", "", "| Domain | "+" | ".join(arms)+" |",
              "|---|"+"---:|"*len(arms)]
    for split, domain in domains:
        items = {r["arm"]: r for r in summary if r["split"] == split and r["domain"] == domain}
        lines.append("| "+domain+" | "+" | ".join(f"{items[a]['total_mmd_mean']:.4f} ± {items[a]['total_mmd_std']:.4f}" for a in arms)+" |")
    lines += ["", "## Improvement and regressions", ""]
    deltas = []
    for baseline in ("lsm_bidmc", "lsm_multi", "tcn_multi"):
        if baseline not in arms or baseline == winner:
            continue
        lines += [f"Compared with **{baseline}** (positive percentage means improvement):", "",
                  "| Domain | Improvement | Paired MMD delta: winner − baseline (95% t interval) |", "|---|---:|---:|"]
        for split, domain in domains:
            chosen = {r["seed"]: r[split][domain]["total_mmd"] for r in rows if r["arm"] == winner}
            base = {r["seed"]: r[split][domain]["total_mmd"] for r in rows if r["arm"] == baseline}
            seeds = sorted(set(chosen) & set(base))
            delta = np.array([chosen[s]-base[s] for s in seeds])
            denominator = np.mean([base[s] for s in seeds])
            percent = float(-100*delta.mean()/max(denominator, 1e-12))
            half = float(student_t.ppf(.975, len(delta)-1)*delta.std(ddof=1)/np.sqrt(len(delta))) if len(delta) > 1 else None
            ci = f"[{delta.mean()-half:.4f}, {delta.mean()+half:.4f}]" if half is not None else "unavailable: one seed"
            lines.append(f"| {domain} | {percent:+.1f}% | {delta.mean():+.4f} {ci} |")
            deltas.append(dict(baseline=baseline, domain=domain, improvement_percent=percent,
                               paired_delta=float(delta.mean()), ci95_half=half))
        lines.append("")
    worse = [d for d in deltas if d["baseline"] == "lsm_multi" and d["improvement_percent"] < 0]
    lines += ["Regressions against LSM with the same expanded data: "+(", ".join(d["domain"] for d in worse) if worse else "none in the reported mean scores (uncertainty still matters)."), "",
              "Three seeds provide limited statistical power; these exploratory intervals are not adjusted for multiple comparisons.",
              "Per-domain JSON also contains patient-bootstrap intervals, feature precision/recall, morphology Wasserstein distances and two-sample 1-NN accuracy.", "",
              "## Data and limits", "",
              "Training sampling gives equal weight to each dataset and each patient within a dataset. Test draws have no duplicate windows.",
              "PTT sit/walk/run are a complete source holdout. The MIMIC-derived datasets are related cohorts, not independent hospitals.",
              "No hyperparameter changes are made using these test results; a further improvement round needs a new holdout or nested protocol.", ""]
    lines += ["- "+s for s in manifest.get("limitations", [])]
    lines += ["- CPU timings describe the Kaggle/host processor; no Raspberry Pi or physical DAC validation.",
              "- Equal steps do not imply equal compute or convergence. Diffusion uses 32 DDIM sampling steps.",
              "- Basic morphology metrics are proxies; no clinical equivalence or reliable AF detection is established.",
              "- Runtime/UI/main assets have not been promoted by this experiment.", ""]
    (root/"REPORT.md").write_text("\n".join(lines))
    (root/"improvements.json").write_text(json.dumps(deltas, indent=2, allow_nan=False)+"\n")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 5), layout="constrained")
    for arm in arms:
        histories = [json.loads((root/f"{arm}_seed{r['seed']}"/"history.json").read_text()) for r in rows if r["arm"] == arm]
        steps = [h["step"] for h in histories[0]]
        values = np.array([[h["validation_score"] for h in history] for history in histories])
        line, = ax.plot(steps, values.mean(0), label=arm)
        ax.fill_between(steps, values.min(0), values.max(0), alpha=.12, color=line.get_color())
    ax.set(xlabel="Optimizer step", ylabel="Macro validation total MMD²", title="Checkpoint selection on validation only")
    ax.legend(fontsize=8); fig.savefig(root/"learning_curves.png", dpi=180); plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    for ax, split in zip(axes, ("test", "external")):
        names = [d for s, d in domains if s == split]
        x = np.arange(len(names)); width = .8/len(arms)
        for i, arm in enumerate(arms):
            vals = [next(r for r in summary if r["arm"] == arm and r["split"] == split and r["domain"] == d) for d in names]
            ax.bar(x+(i-(len(arms)-1)/2)*width, [r["total_mmd_mean"] for r in vals], width,
                   yerr=[r["total_mmd_std"] for r in vals], label=arm, capsize=2)
        ax.set_xticks(x, names, rotation=20); ax.set(title=split, ylabel="Total MMD² (lower is better)")
    axes[1].legend(fontsize=7); fig.savefig(root/"domain_benchmark.png", dpi=180); plt.close(fig)
    return root/"REPORT.md"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("run")
    print(report(parser.parse_args().run))
