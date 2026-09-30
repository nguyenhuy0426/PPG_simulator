"""Recheck downloaded artifacts and render the prespecified comparison metrics."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from scipy.signal import welch

from ml.kaggle_lsm.train_lsm import VARIANTS, features, score
from ml.kaggle.train_ppg import make_networks


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root, previous, cwgan, source, output):
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads((root / "configuration.json").read_text())
    assert config["implementation_revision"] == "v2: consistent D train-mode during G update"
    assert sha(source) == config["code_sha256"]
    assert sha(cwgan / "generator_cpu.ts") == config["prior_generator_sha256"]
    files = ["configuration.json", "comparison.json", "manifest.json", "windows.npz", "comparison_samples.npz"]
    for name in VARIANTS:
        files += [f"{name}/{file}" for file in ("best.pt", "last_training_state.pt", "generator_cpu.ts",
                                               "discriminator_cpu.ts", "metrics.json", "history.json", "samples.npz")]
    hashes = {file: sha(root / file) for file in files}
    assert all(value == sha(previous / file) for file, value in hashes.items())
    metrics = json.loads((root / "comparison.json").read_text())
    samples = np.load(root / "comparison_samples.npz", allow_pickle=False)
    for name in samples.files:
        if name == "real":
            continue
        actual = score(samples[name], samples["real"], config["bandwidths"])
        for key, value in actual.items():
            np.testing.assert_allclose(value, metrics[name][key], rtol=1e-6, atol=1e-9)
    torch.set_num_threads(1)
    checkpoints = {}
    for name in VARIANTS:
        state = torch.load(root / name / "last_training_state.pt", map_location="cpu", weights_only=True)
        assert state["step"] == 1500 and state["variant"] == name
        for key in ("generator", "discriminator"):
            assert state[key] and all(torch.isfinite(t).all() for t in state[key].values())
        for key in ("optimizer_g", "optimizer_d"):
            assert state[key]["state"]
            for param in state[key]["state"].values():
                assert all(torch.isfinite(v).all() for v in param.values() if torch.is_tensor(v))
        checkpoints[name] = dict(step=state["step"], finite_g_d_and_optimizers=True)
    checkpoint = torch.load(cwgan / "generator_best.pt", map_location="cpu", weights_only=True)
    g, _ = make_networks()
    g.load_state_dict(checkpoint["generator"])
    g.eval()
    traced = torch.jit.load(str(cwgan / "generator_cpu.ts"), map_location="cpu").eval()
    condition = np.load(cwgan / "prepared.npz", allow_pickle=False)["condition"][:3]
    z, c = torch.randn(3, 32), torch.tensor(condition)
    with torch.inference_mode():
        torch.testing.assert_close(g(z, c), traced(z, c), atol=1e-6, rtol=1e-5)
    csv_checks = {}
    csvs = [(root / name / "example_ir_red_40hz.csv", 40) for name in VARIANTS]
    csvs += [(cwgan / f"ir_red_{fs}hz.csv", fs) for fs in (100, 1000)]
    for path, fs in csvs:
        data = np.loadtxt(path, delimiter=",", skiprows=1)
        assert data.shape[1] == 3 and np.isfinite(data).all()
        np.testing.assert_allclose(np.diff(data[:, 0]), 1 / fs, rtol=0, atol=1e-12)
        assert data[0, 0] == 0 and data[:, 1:].min() >= 0 and data[:, 1:].max() <= 3.28
        ratio = np.ptp(data[:, 2]) / np.ptp(data[:, 1])
        np.testing.assert_allclose(data[:, 2] - 1.5, .48 * (data[:, 1] - 1.5), atol=1e-12)
        csv_checks[str(path)] = dict(rows=len(data), fs_hz=fs, duration_s=len(data)/fs,
                                     ac_ratio=float(ratio), min_v=float(data[:, 1:].min()),
                                     max_v=float(data[:, 1:].max()))
    result = dict(source_sha256=config["code_sha256"], artifacts_equal_previous=hashes,
                  metrics_recomputed=True, last_checkpoints=checkpoints, csv_checks=csv_checks,
                  cwgan_export_matches_best=True, cwgan_critic="Not saved in pilot v1; cannot recover",
                  note="No retraining or test-based checkpoint selection; exploratory only")
    (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    render(samples, metrics, output)
    print(f"PASS: {len(hashes)} artifact hashes, recomputed metrics, G/D optimizer states, "
          f"cWGAN export, {len(csv_checks)} native CSVs; report figures in {output}")


def render(samples, metrics, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = {"lsm_paper": "LSM paper", "lsm_repo_corrected": "LSM BCE",
             "dcgan1200_no_spectral": "BCE, no spectral", "cwgan_v1_periodic_adapter": "cWGAN + adapter",
             "real_train_window_replay": "Train strip replay", "heldout_real_reference": "Held-out real"}
    colors = ["#CC79A7", "#0072B2", "#D55E00", "#009E73", "#999999", "#000000"]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), layout="constrained")
    for (key, label), color in zip(names.items(), colors):
        x = samples["real" if key == "heldout_real_reference" else key]
        acf, _ = features(x)
        f, p = welch(x, fs=40, nperseg=400, noverlap=200, axis=-1)
        axes[0, 0].plot(np.arange(1, 201)/40, acf.mean(0), label=label, color=color)
        axes[0, 1].semilogy(f[1:], p.mean(0)[1:] + 1e-12, color=color)
    axes[0, 0].set(xlabel="Lag (s)", ylabel="Mean normalized ACF", title="Temporal structure")
    axes[0, 0].legend(fontsize=8)
    axes[0, 1].set(xlabel="Frequency (Hz)", ylabel="Mean PSD", title="Spectrum", xlim=(0, 10))
    for ax, metric, title in ((axes[1, 0], "mean_log_psd_rmse", "Mean log-spectrum RMSE (lower is better)"),
                               (axes[1, 1], "above_5hz_power_fraction_mean", "Power above 5 Hz (%)")):
        vals = [metrics[name][metric] * (100 if "fraction" in metric else 1) for name in names]
        ax.barh(list(names.values()), vals, color=colors)
        ax.invert_yaxis()
        ax.set_title(title)
        ax.set_xlim(0, max(vals) * 1.3)
        for i, value in enumerate(vals):
            ax.text(value + max(vals) * .015, i, f"{value:.5f}", va="center", fontsize=8)
    fig.suptitle("Exploratory BIDMC comparison · 112 test strips · one seed\n"
                 "cWGAN comparator includes periodic rendering + bandpass; tasks are not equivalent", fontsize=12)
    fig.savefig(output / "comparison_summary.png", dpi=160)
    fig.savefig(output / "comparison_summary.pdf")
    plt.close(fig)
    header = "model,acf_mmd2,log_psd_mmd2,mean_log_psd_rmse,above_5hz_percent\n"
    rows = [f"{key},{v['acf_mmd2']:.8f},{v['log_psd_mmd2']:.8f},{v['mean_log_psd_rmse']:.8f},"
            f"{100*v['above_5hz_power_fraction_mean']:.8f}" for key, v in metrics.items()]
    (output / "comparison_table.csv").write_text(header + "\n".join(rows) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("ml/runs/lsm-v2-verification/download/lsm_comparison"))
    parser.add_argument("--previous", type=Path, default=Path("ml/runs/lsm-kaggle-v2/lsm_comparison"))
    parser.add_argument("--cwgan", type=Path, default=Path("ml/runs/kaggle-v1/ppg_run"))
    parser.add_argument("--source", type=Path, default=Path("ml/runs/lsm-v2-verification/source/ppg-lsm-gan-bidmc-comparison.py"))
    parser.add_argument("--output", type=Path, default=Path("docs/neural-comparison"))
    args = parser.parse_args()
    verify(args.root, args.previous, args.cwgan, args.source, args.output)
