"""Seed-aggregated summary, honest comparison rule and figures for the PhysioMix v2 round."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from ml.kaggle_lsm.train_lsm import FS, save_json
from ml.kaggle_multidomain.control import GRID


def stat(values):
    values = np.asarray([v for v in values if v is not None and np.isfinite(v)], float)
    if not len(values):
        return None
    return dict(mean=float(values.mean()), sd=float(values.std(ddof=1)) if len(values) > 1 else None, n=int(len(values)))


def summarize(results):
    summary = {}
    for arm in sorted({r["arm"] for r in results}):
        rows = sorted([r for r in results if r["arm"] == arm], key=lambda r: r["seed"])
        gxu = [r["gxu_fresh_test"] for r in rows]
        entry = dict(seeds=[r["seed"] for r in rows], hr_control=rows[0]["hr_control"],
                     gxu_test_Q=stat([g["Q"] for g in gxu]), gxu_test_mmd=stat([g["total_mmd"] for g in gxu]),
                     gxu_test_precision=stat([g["precision"] for g in gxu]), gxu_test_recall=stat([g["recall"] for g in gxu]),
                     gxu_test_1nn=stat([g["one_nn"] for g in gxu]),
                     gxu_test_states={s: stat([g["states"].get(s, {}).get("Q") for g in gxu])
                                      for s in sorted({k for g in gxu for k in g.get("states", {})})},
                     latency_ms=stat([(r.get("latency") or {}).get("median_ms") for r in rows]),
                     generator_parameters=rows[0].get("generator_parameters"))
        if not rows[0]["unconditional"]:
            entry.update(S_arm=stat([r["S_arm"] for r in rows]), S_real=stat([r["S_real_fresh"] for r in rows]),
                         C=stat([r["C_fresh"] for r in rows]),
                         c2st_derivative=stat([r["c2st_derivative_auc"] for r in rows]),
                         c2st_raw=stat([r.get("c2st_raw_auc") for r in rows]),
                         eligible=[r["eligible"] for r in rows],
                         control={k: stat([r["control"][k] for r in rows])
                                  for k in ("mae_in", "mae_ext", "spearman", "auc_irr", "lock_rate", "irr_cv_at_sigma_0_2")},
                         pools={p: stat([r["prompted_validation"]["pools"][p]["Q"] for r in rows])
                                for p in rows[0]["prompted_validation"]["pools"]})
        summary[arm] = entry
    return summary


def compare(summary, new="physiomix_v2", old="physiomix_no_div"):
    a, b = summary.get(new, {}).get("S_arm"), summary.get(old, {}).get("S_arm")
    if not a or not b or a["sd"] is None or b["sd"] is None:
        return dict(verdict="not_available")
    gap = b["mean"]-a["mean"]
    pooled = float(np.sqrt((a["sd"]**2+b["sd"]**2)/2))
    non_inferior = summary[new]["S_real"]["mean"] <= summary[old]["S_real"]["mean"]+.05
    verdict = ("v2_better" if gap > pooled and non_inferior else
               "v1_better" if -gap > pooled else "not_distinguishable")
    return dict(verdict=verdict, S_arm_gap=gap, pooled_sd=pooled, non_inferior=non_inferior)


def figures(output, results, summary, references):
    conditional = [a for a in summary if summary[a].get("S_arm")]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    for arm in conditional:
        row = next(r for r in results if r["arm"] == arm)
        medians = np.nanmedian(np.array([[np.nan if m is None else m for m in d["median_hr"]]
                                         for d in row["control"]["per_domain"].values()], float), 0)
        axes[0].plot(GRID, medians, marker="o", label=arm)
    axes[0].plot(GRID, GRID, "k--", lw=1, label="ideal")
    axes[0].set_xlabel("requested HR (bpm)")
    axes[0].set_ylabel("measured span rate (bpm)")
    axes[0].set_title("HR control, sinus prompts (median over domains)", fontsize=9)
    axes[0].legend(fontsize=7)
    names = list(summary)
    values = [summary[a]["gxu_test_Q"]["mean"] for a in names]
    errors = [summary[a]["gxu_test_Q"]["sd"] or 0 for a in names]
    axes[1].bar(range(len(names)), values, yerr=errors, color="#4c78a8")
    axes[1].axhline(references["gxu_train_replay_on_fresh_test"]["Q"], color="k", ls="--", lw=1, label="train replay")
    axes[1].axhline(references["gaussian_shaper"]["gxu_fresh_test"]["Q"], color="#e45756", ls=":", lw=1.5,
                    label="Gaussian shaper (app)")
    axes[1].set_xticks(range(len(names)), names, rotation=25, ha="right", fontsize=8)
    axes[1].set_ylabel("Q on sealed GXU finger test (lower better)")
    axes[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(output/"control_and_fresh_test.png", dpi=150)
    plt.close(fig)
    shown = [a for a in names if (output/"benchmark"/f"{a}_seed42"/"gxu_samples.npz").exists()]
    fig, axes = plt.subplots(len(shown)+1, 1, figsize=(10, 1.6*(len(shown)+1)), sharex=True)
    axes = np.atleast_1d(axes)
    from ml.kaggle_multidomain.data_gxu import load_input
    t = np.arange(400)/FS
    for ax, arm in zip(axes[1:], shown):
        y = np.load(output/"benchmark"/f"{arm}_seed42"/"gxu_samples.npz")["generated"][0]
        ax.plot(t, y[:400], lw=1)
        ax.set_title(arm, fontsize=8)
    pack, _ = load_input(json.loads((output/"configuration.json").read_text())["args"]["input_root"], "ppg_physiomix_v3")
    real = pack["signal"][(pack["domain"] == "gxu_finger") & (pack["split"] == "test")][0]
    axes[0].plot(t, real[:400], color="k", lw=1)
    axes[0].set_title("Real GXU finger (sealed test)", fontsize=8)
    axes[-1].set_xlabel("seconds")
    fig.tight_layout()
    fig.savefig(output/"waveforms_gxu.png", dpi=150)
    plt.close(fig)


def fmt(s, digits=3):
    if not s:
        return "—"
    return f"{s['mean']:.{digits}f}" + (f" ± {s['sd']:.{digits}f}" if s.get("sd") is not None else "")


def report(output, results, frozen):
    output = Path(output)
    references = json.loads((output/"benchmark"/"references.json").read_text())
    summary = summarize(results)
    verdict = compare(summary)
    save_json(output/"summary.json", dict(arms=summary, comparison=verdict, references=references,
                                          winner_alias=frozen["aliases"]["physiomix_v2"]))
    figures(output, results, summary, references)
    lines = ["# PhysioMix v2 (view v3 + GXU): kết quả benchmark", "",
             f"Biến thể v2 chọn từ pilot (chỉ validation): `{frozen['aliases']['physiomix_v2']}`. "
             f"So sánh với v1 (physiomix_no_div train lại trên cùng dữ liệu): **{verdict['verdict']}**.", "",
             "| Arm | S_arm (↓) | S_real | C (HR) | C2ST đạo hàm | GXU test Q (↓) | GXU recall | MAE HR 60–140 | MAE HR ngoài | ms CPU |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for arm, s in summary.items():
        c = s.get("control", {})
        lines.append(f"| {arm} | {fmt(s.get('S_arm'))} | {fmt(s.get('S_real'))} | {fmt(s.get('C'))} | "
                     f"{fmt(s.get('c2st_derivative'))} | {fmt(s['gxu_test_Q'])} | {fmt(s['gxu_test_recall'])} | "
                     f"{fmt(c.get('mae_in'), 1)} | {fmt(c.get('mae_ext'), 1)} | {fmt(s['latency_ms'], 1)} |")
    g = references["gaussian_shaper"]["gxu_fresh_test"]
    lines += ["", f"Tham chiếu GXU test: train replay Q {references['gxu_train_replay_on_fresh_test']['Q']:.3f}; "
              f"Gaussian shaper của app Q {g['Q']:.3f}. Sàn C2ST real-vs-real {references['c2st_real_vs_real_floor']:.3f}.",
              "", "GXU test (22 người khỏe, chưa từng dùng để chọn) là holdout mới duy nhất; mọi split cũ chỉ thăm dò.",
              "Điểm số là độ giống phân bố của PPG đã lọc và độ chính xác điều khiển nhịp tự nhất quán;",
              "không phải độ chính xác thông số sinh lý, SpO2 hay kiểm chứng lâm sàng. Chưa đo trên Pi/DAC.",
              "", "![Control](control_and_fresh_test.png)", "![Waveforms](waveforms_gxu.png)"]
    (output/"REPORT_VI.md").write_text("\n".join(lines)+"\n")
    return summary
