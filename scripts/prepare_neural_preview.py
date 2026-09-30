#!/usr/bin/env python3
"""Create a small portable inference bundle from the audited Kaggle runs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def prepare(cwgan, lsm, output, architecture):
    config = json.loads((lsm / "configuration.json").read_text())
    if config["implementation_revision"] != "v2: consistent D train-mode during G update":
        raise ValueError("Require audited LSM v2, not the BatchNorm-mismatched v1")
    generator = cwgan / "generator_cpu.ts"
    if hashlib.sha256(generator.read_bytes()).hexdigest() != config["prior_generator_sha256"]:
        raise ValueError("cWGAN generator is not the frozen comparator")
    data = np.load(cwgan / "prepared.npz", allow_pickle=False)
    train = data["condition"][data["train"]]
    # Actual training exemplar, closest HR to 75 bpm. Do not take test labels.
    condition = train[np.argmin(abs(train[:, 0] * 200 - 75))]
    presets = {}
    for flag, label in ((0, "No notch"), (1, "With notch")):
        subset = train[train[:, -1] == flag]
        presets[label] = subset[np.argmin(abs(subset[:, 0] * 200 - 75))].tolist()
    summary = json.loads((architecture / "summary.json").read_text())
    if summary["winner_selected_by_validation"] != "tcn_film_projection":
        raise ValueError("Expected validation-selected TCN winner")
    candidates = list((architecture / "tcn_film_projection").glob("seed_*/result.json"))
    winner = min(candidates, key=lambda p: json.loads(p.read_text())["validation"]["selection_score"]).parent
    sources = {"cwgan_generator": generator,
               "lsm_generator": lsm / "lsm_repo_corrected" / "generator_cpu.ts",
               "lsm_discriminator": lsm / "lsm_repo_corrected" / "discriminator_cpu.ts",
               "tcn_generator": winner / "generator_cpu.ts", "tcn_critic": winner / "critic_cpu.ts"}
    output.mkdir(parents=True, exist_ok=True)
    models = {}
    for key, source in sources.items():
        target = output / (key + ".ts")
        shutil.copy2(source, target)
        models[key] = dict(file=target.name, sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    manifest = dict(models=models, cwgan_condition=condition.tolist(),
                    condition_presets=presets, tcn_selected_run=winner.name,
                    condition_source="Training exemplar nearest 75 bpm; HR is adjustable in preview",
                    lsm_variant="lsm_repo_corrected", lsm_revision=config["implementation_revision"],
                    lsm_source_sha256=config["code_sha256"],
                    note="Research preview only. No cWGAN critic artifact exists for pilot v1.")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Prepared five CPU models and manifest in {output}; Gaussian remains built in")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwgan", type=Path, default=ROOT / "ml/runs/kaggle-v1/ppg_run")
    parser.add_argument("--lsm", type=Path, default=ROOT / "ml/runs/lsm-kaggle-v2/lsm_comparison")
    parser.add_argument("--output", type=Path, default=ROOT / "assets/neural")
    parser.add_argument("--architecture", type=Path, default=ROOT / "ml/runs/architecture-kaggle-v1/architecture_sweep")
    args = parser.parse_args()
    prepare(args.cwgan, args.lsm, args.output, args.architecture)
