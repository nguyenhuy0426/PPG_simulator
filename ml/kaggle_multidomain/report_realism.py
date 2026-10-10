"""Vietnamese tables and figures for realism.py results (per-dataset realism, state following)."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

NAMES = dict(gxu_finger="GXU ngón tay (khỏe)", perform_large="MIMIC PERform Large (ICU)", bidmc="BIDMC (ICU)",
             perform_af="MIMIC PERform AF", perform_non_af="MIMIC PERform không AF", wrist="Cổ tay khi vận động")
STATES = dict(bidmc="BIDMC", perform_af="AF", perform_non_af="không AF", perform_large="PERform Large",
              gxu_rest="GXU nghỉ", gxu_post_exercise="GXU sau gắng sức", wrist_exercise="Cổ tay vận động")


def pct(value):
    return "—" if value is None else f"{100*value:.0f}%"


def realism_table(result, sources):
    lines = ["| Tập dữ liệu (người chưa dùng để train) | Nguồn | Độ giống (fidelity) | Độ phủ (coverage) | "
             "Không phân biệt được (C2ST) |", "|---|---|---|---|---|"]
    for domain, entry in result["realism"].items():
        for i, name in enumerate(["real_other_people", *sources]):
            v = entry[name]
            label = f"{NAMES[domain]} · {entry['people']} người" if i == 0 else ""
            source = "Dữ liệu thật của người khác" if name == "real_other_people" else name
            lines.append(f"| {label} | {source} | {pct(v['fidelity'])} | {pct(v['coverage'])} | "
                         f"{pct(v['indistinguishable'])} (AUC {v['c2st_auc']:.2f}) |")
    return lines


def state_table(result, sources):
    c = result["condition_following"]
    lines = ["| Trạng thái yêu cầu | Dữ liệu thật: nhận đúng | " + " | ".join(f"{s}: nhận đúng · P(vận động)" for s in sources)+" |",
             "|---|---|"+"---|"*len(sources)]
    for state in c["states"]:
        row = [STATES[state], f"{pct(c['real_unseen']['accuracy'][state])} · {c['real_unseen']['motion_probability'][state]:.2f}"]
        row += [f"{pct(c[s]['accuracy'][state])} · {c[s]['motion_probability'][state]:.2f}" for s in sources]
        lines.append("| "+" | ".join(row)+" |")
    lines.append("| **Trung bình (đoán mò = 14%)** | " + pct(c["real_unseen"]["balanced_accuracy"]) + " | " +
                 " | ".join(pct(c[s]["balanced_accuracy"]) for s in sources)+" |")
    lines.append("| **Cùng nhiễu, đổi lệnh: tỉ lệ theo lệnh** | — | " +
                 " | ".join(pct(c[s]["swap_following"]) for s in sources)+" |")
    return lines


def physiology_table(result, sources):
    c = result["condition_following"]["physiology"]
    lines = ["| Trạng thái | Nguồn | HR trung vị | CV khoảng nhịp | Đo được nhịp | Độ tuần hoàn (ACF) |",
             "|---|---|---|---|---|---|"]
    for state in result["condition_following"]["states"]:
        for i, name in enumerate(["real_unseen", *sources]):
            v = c[name][state]
            hr = "—" if v["hr_median"] is None else f"{v['hr_median']:.0f}"
            cv = "—" if v["ibi_cv_median"] is None else f"{v['ibi_cv_median']:.3f}"
            lines.append(f"| {STATES[state] if i == 0 else ''} | {'Thật (người chưa dùng)' if name == 'real_unseen' else name} | "
                         f"{hr} | {cv} | {pct(v['rate_measurable'])} | {v['periodicity_median']:.2f} |")
    return lines


def figure(result, sources, path):
    domains = list(result["realism"])
    names = ["real_other_people", *sources]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), sharey=True)
    for ax, key, title in zip(axes, ("fidelity", "coverage", "indistinguishable"),
                              ("Độ giống (fidelity)", "Độ phủ (coverage)", "Không phân biệt được (C2ST)")):
        width = .8/len(names)
        for i, name in enumerate(names):
            ax.bar(np.arange(len(domains))+i*width, [100*result["realism"][d][name][key] for d in domains], width,
                   label="thật · người khác" if name == "real_other_people" else name)
        ax.set_xticks(np.arange(len(domains))+.4-width/2, [NAMES[d].split(" (")[0] for d in domains], rotation=30,
                      ha="right", fontsize=8)
        ax.set_title(title, fontsize=10)
    axes[0].set_ylabel("%")
    axes[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    a = parser.parse_args(argv)
    result = json.loads(Path(a.input).read_text())
    sources = result["sources"]
    out = Path(a.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    figure(result, sources, out/"realism_by_dataset.png")
    lines = ["## Giống thật đến đâu, trên từng tập dữ liệu", "", *realism_table(result, sources), "",
             "## Có làm theo lệnh trạng thái không", "", *state_table(result, sources), "",
             "## Thống kê sinh lý theo trạng thái", "", *physiology_table(result, sources), "",
             "![Realism](realism_by_dataset.png)"]
    (out/"REALISM_VI.md").write_text("\n".join(lines)+"\n")


if __name__ == "__main__":
    main()
