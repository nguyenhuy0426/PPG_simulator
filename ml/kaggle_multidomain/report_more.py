"""Research report separating fresh holdouts from previously inspected sources."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import welch
from scipy.stats import t

from ml.kaggle_lsm.train_lsm import FS, save_json
from ml.kaggle_multidomain.data_more import load_input


def report(output, results, winner):
    output = Path(output)
    arms = sorted({r["arm"] for r in results})
    domains = sorted({domain for r in results for split in ("test", "external") for domain in r[split]})
    summary, improvements = {}, {}
    for arm in arms:
        rows = sorted([r for r in results if r["arm"] == arm], key=lambda r: r["seed"])
        summary[arm] = dict(validation=float(np.mean([r["validation_score"] for r in rows])),
                            cpu_median_ms=float(np.mean([r["latency"]["median_ms"] for r in rows])),
                            generator_parameters=rows[0]["generator_parameters"],
                            diversity_ratio=[r["diagnostics"]["morphology_pairwise_distance_median"]/
                                             max(r["diagnostics"]["train_morphology_pairwise_distance_median"], 1e-8) for r in rows],
                            domains={})
        improvements[arm] = {}
        for domain in domains:
            split = "test" if domain in rows[0]["test"] else "external"
            values = np.asarray([r[split][domain]["total_mmd"] for r in rows])
            summary[arm]["domains"][domain] = dict(mean_mmd=float(values.mean()), sd_mmd=float(values.std(ddof=1)) if len(values)>1 else None,
                  feature_precision=float(np.mean([r[split][domain]["feature_precision"] for r in rows])),
                  feature_recall=float(np.mean([r[split][domain]["feature_recall"] for r in rows])),
                  two_sample_1nn_accuracy=float(np.mean([r[split][domain]["two_sample_1nn_accuracy"] for r in rows])))
            improvements[arm][domain] = {}
            for baseline in ("lsm_multi", "hybrid_multi", "diffusion_multi"):
                old = sorted([r for r in results if r["arm"] == baseline], key=lambda r: r["seed"])
                reference = np.asarray([r[split][domain]["total_mmd"] for r in old])
                delta = values-reference
                half = float(t.ppf(.975, len(delta)-1)*delta.std(ddof=1)/np.sqrt(len(delta))) if len(delta)>1 else None
                improvements[arm][domain][baseline] = dict(improvement_percent=float(100*(reference.mean()-values.mean())/reference.mean()),
                     paired_delta=float(delta.mean()), paired_delta_ci95=[float(delta.mean()-half), float(delta.mean()+half)] if half is not None else None)
    save_json(output/"summary.json", summary)
    save_json(output/"improvements.json", improvements)
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(domains)); width=.8/len(arms)
    for i, arm in enumerate(arms):
        ax.bar(x-.4+width/2+i*width, [summary[arm]["domains"][d]["mean_mmd"] for d in domains], width, label=arm)
    ax.set_xticks(x, domains, rotation=30, ha="right")
    ax.set_ylabel("ACF + log-PSD + morphology MMD² (lower better)")
    ax.set_title("Fresh holdouts: Wrist test / CapnoBase; remaining domains exploratory")
    ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(output/"domain_benchmark.png", dpi=160); plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    for arm in arms:
        r = next(row for row in results if row["arm"] == arm and row["seed"] == min(row["seed"] for row in results))
        history = json.loads((output/"benchmark"/f"{arm}_seed{r['seed']}"/"history.json").read_text())
        axes[0].plot([h["step"] for h in history], [h["validation_score"] for h in history], label=arm)
        if "diversity_ratio" in history[0]:
            axes[1].plot([h["step"] for h in history], [h["diversity_ratio"] for h in history], label=arm)
            axes[2].plot([h["step"] for h in history], [h["critic_margin"] for h in history], label=arm)
    for ax, title in zip(axes, ("Common validation quality/diversity score", "Custom-model diversity / train", "Custom critic real − fake margin")):
        ax.set_title(title, fontsize=9); ax.set_xlabel("optimizer updates"); ax.legend(fontsize=6)
    fig.tight_layout(); fig.savefig(output/"learning_and_stability.png", dpi=160); plt.close(fig)
    manifest = json.loads((output/"data_manifest.json").read_text())
    input_root = json.loads((output/"configuration.json").read_text())["args"]["input_root"]
    pack, _ = load_input(input_root)
    real = pack["signal"][np.flatnonzero((pack["domain"] == "capnobase") & (pack["split"] == "external"))[:128]]
    plotted = [("Fresh CapnoBase", real)]
    for arm in arms:
        r = next(row for row in results if row["arm"] == arm)
        samples = np.load(output/"benchmark"/f"{arm}_seed{r['seed']}"/"samples.npz")["generated"]
        plotted.append((arm, samples))
    fig, axes = plt.subplots(len(plotted), 2, figsize=(11, 2*len(plotted)))
    for (label, waves), pair in zip(plotted, axes):
        pair[0].plot(np.arange(200)/FS, waves[0, :200]); pair[0].set_title(label, fontsize=9)
        f, p = welch(waves, fs=FS, nperseg=400, noverlap=200, axis=-1)
        pair[1].semilogy(f, np.median(p, axis=0)+1e-10); pair[1].set_xlim(0, 10)
    fig.tight_layout(); fig.savefig(output/"waveforms_and_spectra.png", dpi=160); plt.close(fig)
    args = json.loads((output/"configuration.json").read_text())["args"]
    lines = ["# PhysioMix: vòng cải thiện PPG", "", f"Mô hình chọn **chỉ từ validation**: `{winner}`.", "",
             f"{len(arms)} cấu hình × {len(args['seeds'])} seeds, {args['steps']} steps; 4 pilot × {args['pilot_steps']} steps. Cùng batch/steps, không cùng FLOPs.",
             "Score chọn: macro MMD + 0.25 |log(đa dạng/train)| + 0.5 (1 − macro recall). Nhỏ hơn tốt hơn.",
             "CapnoBase và Wrist test là holdout mới; các miền cũ/PTT đã xem nên chỉ thăm dò.", "",
             "| Cấu hình | Validation | Đa dạng/train trung bình | CPU ms/đoạn | Tham số G |", "|---|---:|---:|---:|---:|"]
    for arm in arms:
        s=summary[arm]
        lines.append(f"| {arm} | {s['validation']:.4f} | {np.mean(s['diversity_ratio']):.3f} | {s['cpu_median_ms']:.2f} | {s['generator_parameters']} |")
    lines += ["", "| Miền | Winner MMD | Recall | 1-NN | So hybrid cũ train lại: giảm MMD % |", "|---|---:|---:|---:|---:|"]
    for domain in domains:
        m=summary[winner]["domains"][domain]
        change=improvements[winner][domain]["hybrid_multi"]["improvement_percent"]
        lines.append(f"| {domain} | {m['mean_mmd']:.4f} | {m['feature_recall']:.3f} | {m['two_sample_1nn_accuracy']:.3f} | {change:+.1f} |")
    lines += ["", "Giảm MMD không phải tăng accuracy. Giá trị âm trong cải thiện là suy giảm.",
              "Đa dạng tăng quá cao có thể là nhiễu; xem precision/recall, 1-NN và phổ cùng nhau.",
              "R1, EMA, gradient clipping và conditioning được ghi nhận thực thi; chưa đủ để tuyên bố GAN luôn ổn định.",
              "conditioning_probe kiểm tra nhịp ước lượng bằng cùng thuật toán PPG, không chứng minh điều khiển HR lâm sàng.",
              "Nearest-neighbor là screening sao chép với 512 training draws; không bảo đảm riêng tư hoặc không ghi nhớ.",
              "3 seeds; Wrist test 2 người; non-AF test 1 người; CapnoBase tính theo case. CI không chứng minh population-wide superiority.",
              "Không học SpO2/AC/DC hoặc IR/RED; chưa đo Pi/DAC. Không gọi tốt nhất tuyệt đối.", "",
              "![Benchmark](domain_benchmark.png)", "![Learning](learning_and_stability.png)", "![Waveforms](waveforms_and_spectra.png)",
              "", "Nguồn và số lượng/nhãn chính xác: `data_manifest.json`. Cấu hình pilot và frozen protocol đi kèm."]
    (output/"REPORT_VI.md").write_text("\n".join(lines)+"\n")
