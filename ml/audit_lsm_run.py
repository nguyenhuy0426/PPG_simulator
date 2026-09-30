"""Audit exported LSM G/D artifacts; does not retrain or select checkpoints."""
import argparse
import json
import platform
import time
from pathlib import Path

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import LENGTH, VARIANTS, make_networks, save_json


def auc(real_scores, fake_scores):
    differences = real_scores[:, None]-fake_scores[None, :]
    return float((differences > 0).mean()+.5*(differences == 0).mean())


def audit(root):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    torch.set_num_threads(1)
    torch.manual_seed(2026)
    results = dict(host=platform.platform(), architecture=platform.machine(),
                   torch=torch.__version__, threads=1, note="Host CPU, not Pi", arms={})
    fig, axes = plt.subplots(3, 2, figsize=(12, 10))
    for row, name in enumerate(VARIANTS):
        folder = root/name
        checkpoint = torch.load(folder/"best.pt", map_location="cpu", weights_only=True)
        g, d = make_networks()
        g.load_state_dict(checkpoint["generator"])
        d.load_state_dict(checkpoint["discriminator"])
        arm = dict(best_step=checkpoint["step"])
        for label, eager, shape in (("generator", g, (3, LENGTH)),
                                    ("discriminator", d, (3, 1, LENGTH))):
            model = torch.jit.load(str(folder/f"{label}_cpu.ts"), map_location="cpu").eval()
            eager.eval(); x = torch.randn(*shape)
            with torch.inference_mode():
                y = model(x)
                torch.testing.assert_close(y, eager(x), atol=1e-6, rtol=1e-5)
                assert torch.isfinite(y).all()
                one = x[:1]
                for _ in range(10):
                    model(one)
                timings = []
                for _ in range(100):
                    start = time.perf_counter(); model(one)
                    timings.append((time.perf_counter()-start)*1000)
            arm[label] = dict(batch3_shape=list(y.shape), median_ms=float(np.median(timings)),
                              p95_ms=float(np.quantile(timings, .95)),
                              bytes=(folder/f"{label}_cpu.ts").stat().st_size)
        samples = np.load(folder/"samples.npz", allow_pickle=False)
        # Offline example only: same learned shape in both channels, nominal
        # A=110, B=25, SpO2=98, equal 1.5 V pedestals, AC_IR=45 mV.
        pulse_strip = samples["generated"][0].astype(np.float64)
        assert np.isfinite(pulse_strip).all() and pulse_strip.min() >= 0 and pulse_strip.max() <= 1
        ir, red = 1.5+.045*pulse_strip, 1.5+.0216*pulse_strip
        np.savetxt(folder/"example_ir_red_40hz.csv",
                   np.column_stack((np.arange(LENGTH)/40, ir, red)), delimiter=",",
                   header="time_s,ir_v,red_v", comments="")
        arm["offline_ir_red_example"] = dict(fs_hz=40, seconds=30, rows=LENGTH,
                                            same_shape_both_channels=True,
                                            ac_red_over_ac_ir=float(np.ptp(red)/np.ptp(ir)))
        real, fake = samples["d_real"].mean(1), samples["d_fake"].mean(1)
        arm["d_real_vs_fake_auc"] = auc(real, fake)
        arm["d_balanced_accuracy_at_half"] = float(.5*((real >= .5).mean()+(fake < .5).mean()))
        # Diagnostic only; train-mode outputs depend on batch composition and
        # are not held-out performance metrics. Never save these mutated buffers.
        probe_real = torch.tensor(samples["real"][:32, None])
        probe_fake = torch.tensor(samples["generated"][:32, None])
        with torch.inference_mode():
            d.eval()
            arm["bn_probe_eval_real_fake"] = [float(d(probe_real).mean()), float(d(probe_fake).mean())]
            d.train()
            arm["bn_probe_train_real_fake"] = [float(d(probe_real).mean()), float(d(probe_fake).mean())]
        axes[row, 0].hist(real, bins=20, alpha=.6, label="held-out real")
        axes[row, 0].hist(fake, bins=20, alpha=.6, label="own generated")
        axes[row, 0].set_title(name+" | D scores (not clinical quality)")
        axes[row, 0].legend(fontsize=8)
        history = json.loads((folder/"history.json").read_text())
        axes[row, 1].plot([h["step"] for h in history], [h["selection_score"] for h in history])
        axes[row, 1].axvline(checkpoint["step"], linestyle="--", color="gray")
        axes[row, 1].set_title("Validation ACF-MMD2 + log-PSD-MMD2")
        axes[row, 1].set_xlabel("Generator steps")
        results["arms"][name] = arm
    fig.tight_layout(); fig.savefig(root/"discriminator_audit.png", dpi=140); plt.close(fig)
    save_json(root/"audit.json", results)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    audit(parser.parse_args().root)
