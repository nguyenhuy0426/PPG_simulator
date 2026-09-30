"""Audit a completed pilot without selecting or retraining a model.

Usage: python -m ml.evaluate_run ml/runs/kaggle-v1/ppg_run
No hardware I/O. Metrics are descriptive, not clinical pass/fail criteria.
"""
import argparse
import json
import platform
import time
from pathlib import Path

import numpy as np

from ml.kaggle.train_ppg import CONDITION_NAMES, LATENT_DIM, PHASE, condition, measure, write_json


def classification(expected, observed):
    expected, observed = np.asarray(expected, bool), np.asarray(observed, bool)
    tp = int((expected & observed).sum())
    tn = int((~expected & ~observed).sum())
    fp = int((~expected & observed).sum())
    fn = int((expected & ~observed).sum())
    return dict(tp=tp, tn=tn, fp=fp, fn=fn,
                sensitivity=tp/(tp+fn) if tp+fn else None,
                specificity=tn/(tn+fp) if tn+fp else None,
                precision=tp/(tp+fp) if tp+fp else None)


def audit(run):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import torch

    data = np.load(run/"test_samples.npz", allow_pickle=False)
    prepared = np.load(run/"prepared.npz", allow_pickle=False)
    target = data["condition"]
    subjects = prepared["subject"][data["source_indices"]]
    result = dict(condition_names=CONDITION_NAMES, methods={})
    for name in ("gan", "replay", "gaussian", "real"):
        measured = np.stack([condition(y, float(q[0]*200)) for y, q in zip(data[name], target)])
        error = np.abs(measured[:, 1]-target[:, 1])
        per_patient = {str(p): float(error[subjects == p].mean()) for p in np.unique(subjects)}
        result["methods"][name] = dict(notch=classification(target[:, -1], measured[:, -1]),
                                      sp_phase_mae_patient_macro=float(np.mean(list(per_patient.values()))),
                                      sp_phase_mae_by_patient=per_patient)
    torch.set_num_threads(1)
    torch.manual_seed(42)
    model = torch.jit.load(str(run/"generator_cpu.ts"), map_location="cpu").eval()
    c = torch.tensor(target[:1]); z = torch.randn(1, LATENT_DIM)
    timings = []
    with torch.inference_mode():
        for _ in range(20):
            model(z, c)
        for _ in range(200):
            started = time.perf_counter()
            y = model(z, c)
            timings.append((time.perf_counter()-started)*1000)
        batched = model(torch.randn(3, LATENT_DIM), torch.tensor(target[:3]))
    assert y.shape == (1, 256) and batched.shape == (3, 256)
    assert torch.isfinite(y).all() and torch.all(y[:, [0, -1]] == 0)
    result["cpu_benchmark"] = dict(machine=platform.machine(), processor=platform.processor(),
                                   platform=platform.platform(), torch=torch.__version__,
                                   threads=1, batch=1, repeats=200,
                                   median_ms=float(np.median(timings)), p95_ms=float(np.quantile(timings, .95)),
                                   note="This host only; NOT a Raspberry Pi measurement")
    selected = np.concatenate((np.flatnonzero(target[:, -1] == 1)[:4],
                               np.flatnonzero(target[:, -1] == 0)[:4]))
    fig, axes = plt.subplots(len(selected), 3, figsize=(12, max(4, len(selected)*1.8)),
                             sharex=True, sharey=True, squeeze=False)
    for row, i in enumerate(selected):
        for column, name in enumerate(("real", "gan", "replay")):
            ax = axes[row, column]
            y = data[name][i]
            ax.plot(PHASE, y, color="#0072B2")
            m = measure(y)
            for key, color in (("sp_phase", "#D55E00"), ("dn_phase", "#009E73"), ("dp_phase", "#CC79A7")):
                if m[key] is not None:
                    ax.plot(m[key], np.interp(m[key], PHASE, y), "o", color=color, markersize=4)
            ax.set_title(f"{name} | sample {i} | target notch={int(target[i,-1])}", fontsize=9)
            ax.set_ylim(-.05, 1.05)
    fig.tight_layout(); fig.savefig(run/"morphology_review.png", dpi=150); plt.close(fig)
    write_json(run/"audit.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    audit(parser.parse_args().run)
