"""Render actual validation outputs; no retraining, relabeling or sample search."""
import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=Path("ml/runs/round2-independent-validation-final"))
    parser.add_argument("--output", type=Path, default=Path("docs/round2"))
    args = parser.parse_args()
    data = np.load(args.run / "samples.npz", allow_pickle=False)
    report = json.loads((args.run / "metrics.json").read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "metrics.json").write_text(json.dumps(report, indent=2)+"\n")
    names = list(report["results"])
    labels = ["Gaussian", "cWGAN pilot", "TCN-FiLM"]
    colors = ["#E69F00", "#0072B2", "#009E73"]
    styles = [":", "--", "-."]
    fields = ["phase_acf_rmse", "phase_log_psd_rmse", "above_5hz_power_fraction",
              "real_above_5hz_power_fraction", "roughness", "real_roughness",
              "requested_notch_recall", "requested_no_notch_specificity"]
    with (args.output / "comparison.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["model", *fields])
        writer.writeheader()
        for name in names:
            writer.writerow(dict(model=name, **{k: report["results"][name][k] for k in fields}))
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42})
    fig, axes = plt.subplots(2, 3, figsize=(12, 7.4))
    phase = np.linspace(0, 1, 256)
    for ax, notch, letter in zip(axes[0, :2], (False, True), ("A", "B")):
        index = int(np.flatnonzero((data["condition"][:, -1] > .5) == notch)[0])
        ax.plot(phase, data["reference"][index], color="black", label="Real", lw=1.7)
        for name, label, color, style in zip(names, labels, colors, styles):
            ax.plot(phase, data[name][index], color=color, ls=style, label=label, lw=1.5)
        ax.set(title=f"{letter}  First {'notch' if notch else 'no-notch'} request · ID {data['indices'][index]}",
               xlabel="Cycle phase", ylabel="Normalized amplitude", ylim=(-.04, 1.08))
    axes[0, 0].legend(fontsize=8, frameon=False)
    ax = axes[0, 2]
    for name, label, color, style in zip(["reference"]+names, ["Real"]+labels,
                                         ["black"]+colors, ["-"]+styles):
        x = data[name]-data[name].mean(1, keepdims=True)
        psd = abs(np.fft.rfft(x*np.hanning(256), axis=1))**2
        psd /= psd.sum(1, keepdims=True)
        ax.plot(np.arange(129)[1:], np.log10(psd+1e-8).mean(0)[1:], color=color, ls=style, label=label)
    ax.set(title="C  Mean log normalized spectrum", xlabel="Harmonic (cycles / pulse)", ylabel="log10 power fraction", xlim=(1,128))
    ax.set_xscale("log")
    for ax, field, title, scale in zip(axes[1], fields[:3],
            ("D  ACF discrepancy", "E  Log-spectrum discrepancy", "F  Power above 5 Hz"), (1,1,100)):
        values = [report["results"][n][field]*scale for n in names]
        ax.bar(labels, values, color=colors, width=.6, alpha=.65)
        for i, name in enumerate(names):
            subjects = report["results"][name]["by_subject"]
            ys = [v[field]*scale for v in subjects.values()]
            ax.scatter(i+np.linspace(-.14,.14,len(ys)), ys, s=13, color="black", zorder=3)
            ax.text(i, values[i], f"{values[i]:.4f}", ha="center", va="bottom", fontsize=8)
        if field == "above_5hz_power_fraction":
            target = report["results"][names[0]]["real_above_5hz_power_fraction"]*100
            ax.axhline(target, color="black", ls="--", label=f"Real: {target:.3f}%")
            ax.legend(fontsize=8, frameon=False)
        ax.set(title=title, ylabel="Power (%)" if scale==100 else "RMSE", ylim=(0,None))
        ax.tick_params(axis="x", labelsize=8)
    fig.suptitle("Exploratory pulse comparison · 256 validation pulses / 7 subjects", fontsize=13)
    fig.text(.5, .015, "Fixed seed 2809; old automatic condition labels. D–F: pooled bars, individual-subject dots (not confidence intervals).\n"
             "Gaussian uses a fixed preset. LSM strip metrics are a separate experiment. No independent-test claim.",
             ha="center", fontsize=8)
    fig.tight_layout(rect=(0,.065,1,.96))
    fig.savefig(args.output / "comparison.png", dpi=300)
    fig.savefig(args.output / "comparison.pdf")
    plt.close(fig)
    print(args.output)


if __name__ == "__main__":
    main()
