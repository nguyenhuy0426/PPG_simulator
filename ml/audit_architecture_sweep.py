"""Audit downloaded architecture-sweep artifacts without retraining."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
import torch

from ml.kaggle_arch.train_architectures import LATENT_DIM, POINTS, make_networks, measure, save_json


def benchmark(model, inputs, repetitions=100):
    with torch.inference_mode():
        for _ in range(10):
            model(*inputs)
        values = []
        for _ in range(repetitions):
            started = time.perf_counter()
            model(*inputs)
            values.append((time.perf_counter()-started)*1000)
    return dict(median_ms=float(np.median(values)), p95_ms=float(np.quantile(values, .95)))


def audit(root):
    root = Path(root)
    configuration = json.loads((root/"configuration.json").read_text())
    summary = json.loads((root/"summary.json").read_text())
    source = Path("ml/kaggle_arch/train_architectures.py")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source_hash != configuration["code_sha256"]:
        raise ValueError("Downloaded run does not match local training source")
    expected = min(summary["architectures"], key=lambda name:
                   summary["architectures"][name]["validation_selection_median"])
    if expected != summary["winner_selected_by_validation"]:
        raise ValueError("Winner is inconsistent with validation medians")
    torch.set_num_threads(1)
    torch.manual_seed(2026)
    report = dict(host=platform.platform(), architecture=platform.machine(),
                  torch=torch.__version__, threads=1, note="Host CPU, not Raspberry Pi",
                  code_sha256=source_hash, winner=expected, runs={})
    names = tuple(summary["architectures"])
    for name in names:
        for seed in configuration["args"]["seeds"]:
            folder = root/name/f"seed_{seed}"
            checkpoint = torch.load(folder/"best.pt", map_location="cpu", weights_only=True)
            generator, critic = make_networks(name)
            generator.load_state_dict(checkpoint["generator"])
            critic.load_state_dict(checkpoint["discriminator"])
            generator.eval(); critic.eval()
            traced_g = torch.jit.load(str(folder/"generator_cpu.ts"), map_location="cpu").eval()
            traced_d = torch.jit.load(str(folder/"critic_cpu.ts"), map_location="cpu").eval()
            z = torch.randn(3, LATENT_DIM)
            condition = torch.rand(3, 7)
            pulse = torch.rand(3, POINTS)
            with torch.inference_mode():
                torch.testing.assert_close(traced_g(z, condition), generator(z, condition),
                                           atol=1e-6, rtol=1e-5)
                actual_d, actual_aux = traced_d(pulse, condition)
                expected_d, expected_aux = critic(pulse, condition)
                torch.testing.assert_close(actual_d, expected_d, atol=1e-6, rtol=1e-5)
                torch.testing.assert_close(actual_aux, expected_aux, atol=1e-6, rtol=1e-5)
            result = json.loads((folder/"result.json").read_text())
            if result["best_step"] != checkpoint["step"]:
                raise ValueError("Result/checkpoint step mismatch")
            samples = np.load(folder/"samples.npz", allow_pickle=False)
            generated = samples["generated"]
            if (not np.isfinite(generated).all() or generated.min() < 0 or generated.max() > 1.000001
                    or np.abs(generated[:, [0, -1]]).max() != 0):
                raise ValueError("Generated sample integrity check failed")
            key = f"{name}/seed_{seed}"
            report["runs"][key] = dict(
                best_step=checkpoint["step"],
                generator_bytes=(folder/"generator_cpu.ts").stat().st_size,
                critic_bytes=(folder/"critic_cpu.ts").stat().st_size,
                generator=benchmark(traced_g, (z[:1], condition[:1])),
                critic=benchmark(traced_d, (pulse[:1], condition[:1])),
                output_integrity="finite, normalized, zero endpoints",
                parity="pass")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    winner_rows = []
    for seed in configuration["args"]["seeds"]:
        folder = root/expected/f"seed_{seed}"
        result = json.loads((folder/"result.json").read_text())
        winner_rows.append((result["validation"]["selection_score"], seed, folder))
    _, review_seed, review_folder = min(winner_rows)
    samples = np.load(review_folder/"samples.npz", allow_pickle=False)
    conditions = samples["condition"]
    rng = np.random.default_rng(2026)
    positives = rng.choice(np.flatnonzero(conditions[:, -1] > .5), 8, replace=False)
    negatives = rng.choice(np.flatnonzero(conditions[:, -1] <= .5), 8, replace=False)
    fig, axes = plt.subplots(4, 4, figsize=(14, 10), sharex=True, sharey=True)
    for ax, index in zip(axes.flat, np.concatenate((positives, negatives))):
        real, generated = samples["real"][index], samples["generated"][index]
        observed = measure(generated)
        ax.plot(real, color="black", linewidth=1, label="held-out real")
        ax.plot(generated, color="#0072B2", linewidth=1, label="generated")
        ax.axvline(observed["sp_phase"]*(POINTS-1), color="#D55E00", alpha=.5)
        if observed["has_notch"]:
            ax.axvline(observed["dn_phase"]*(POINTS-1), color="#CC79A7", alpha=.5)
            ax.axvline(observed["dp_phase"]*(POINTS-1), color="#009E73", alpha=.5)
        ax.set_title(f"request notch={int(conditions[index, -1])}; observed={int(observed['has_notch'])}")
    axes[0, 0].legend(fontsize=7)
    fig.suptitle(f"{expected}, representative seed {review_seed}; SP/DN/DP markers")
    fig.tight_layout()
    fig.savefig(root/"winner_morphology_review.png", dpi=150)
    plt.close(fig)
    report["review_seed"] = review_seed
    save_json(root/"audit.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    audit(parser.parse_args().root)
