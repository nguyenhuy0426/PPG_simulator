"""Private, bounded BIDMC conditional WGAN-GP research pilot; no hardware I/O.

Source: https://physionet.org/content/bidmc/1.0.0/ (ODC Attribution 1.0).
Pimentel et al., IEEE TBME 2017, DOI:10.1109/TBME.2016.2613126.
GP: Gulrajani et al. 2017, https://arxiv.org/abs/1704.00028.
Landmarks below are engineering pseudo-labels, NOT clinical annotations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.io import loadmat
from scipy.signal import butter, find_peaks, sosfiltfilt
from scipy.spatial.distance import cdist
from scipy.stats import wasserstein_distance

POINTS = 256
LATENT_DIM = 32
CONDITION_NAMES = ["hr_div_200", "sp_phase", "dn_phase", "dp_phase",
                   "dn_over_sp", "dp_over_sp", "has_notch"]
MAT_SHA256 = "91865c2fffff70868875545f897542003d376a53262c7c0ead5b6e9109e884db"
DATA_URL = "https://physionet.org/files/bidmc/1.0.0/bidmc_data.mat"
PHASE = np.linspace(0, 1, POINTS)


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n")


def measure(pulse):
    """SP = global maximum; DN = valley preceding first prominent later peak.

    A 2% SP prominence and 3% cycle separation suppress small ripples. A
    monophasic pulse is valid: no visible DN/DP is represented by None.
    These fixed thresholds are not population reference intervals.
    """
    y = np.asarray(pulse, dtype=float)
    if y.ndim != 1 or len(y) < 16 or not np.isfinite(y).all() or np.ptp(y) < 1e-8:
        raise ValueError("Pulse must be finite, one-dimensional and non-flat")
    y = (y - y.min()) / np.ptp(y)
    sp = int(y.argmax())
    n = len(y) - 1
    result = dict(sp_phase=sp/n, dn_phase=None, dp_phase=None,
                  dn_level=None, dp_level=None, has_notch=False)
    peaks, _ = find_peaks(y, prominence=.02, distance=max(1, round(.03*n)))
    for dp in peaks:
        if not sp + .06*n < dp < .90*n:
            continue
        dn = sp + int(np.argmin(y[sp:dp+1]))
        if sp < dn < dp and y[dp] - y[dn] >= .02:
            result.update(dn_phase=dn/n, dp_phase=int(dp)/n,
                          dn_level=float(y[dn]), dp_level=float(y[dp]), has_notch=True)
            break
    return result


def condition(pulse, hr):
    m = measure(pulse)
    return np.array([hr/200, m["sp_phase"], m["dn_phase"] or 0,
                     m["dp_phase"] or 0, m["dn_level"] or 0,
                     m["dp_level"] or 0, float(m["has_notch"])], dtype=np.float32)


def split_subjects(ids, seed=42):
    ids = np.unique(ids)
    if len(ids) < 7:
        raise ValueError("At least seven subjects required for three held-out groups")
    ids = np.random.default_rng(seed).permutation(ids).tolist()
    a, b = int(.70*len(ids)), int(.85*len(ids))
    return dict(train=ids[:a], validation=ids[a:b], test=ids[b:])


def render_ir_red(pulse, fs=100, hr=75, seconds=4, dc_ir=1.5, dc_red=1.5,
                  ac_ir=.045, spo2=98, polarity=1, coeff_a=110, coeff_b=25,
                  fullscale=3.28):
    """Phase template -> timestamps and volts; DC is the simulator pedestal.

    Not a learned optical model. R=(A-SpO2)/B, AC_red=R*AC_ir*DC_red/DC_ir.
    The two traces share their shape. Reject rails instead of hiding clipping.
    """
    values = [fs, hr, seconds, dc_ir, dc_red, ac_ir, spo2, polarity,
              coeff_a, coeff_b, fullscale]
    if (not np.isfinite(values).all() or min(fs, hr, seconds, dc_ir, dc_red,
                                           coeff_b, fullscale) <= 0
            or ac_ir < 0 or polarity not in (-1, 1) or not 0 <= spo2 <= 100
            or fs <= 2*hr/60):
        raise ValueError("Invalid sampling, amplitude or calibration parameters")
    y = np.asarray(pulse, dtype=float)
    measure(y)
    if y.min() < -1e-6 or y.max() > 1.00001 or abs(y[0]-y[-1]) > 1e-5:
        raise ValueError("Expected normalized, continuous periodic template")
    ac_red = max(0., (coeff_a-spo2)/coeff_b)*ac_ir*dc_red/dc_ir
    for dc, ac in ((dc_ir, ac_ir), (dc_red, ac_red)):
        if min(dc, dc+polarity*ac) < 0 or max(dc, dc+polarity*ac) > fullscale:
            raise ValueError("Requested waveform exceeds DAC rails")
    t = np.arange(round(seconds*fs), dtype=float)/fs
    wave = np.interp((t*hr/60) % 1., np.linspace(0, 1, len(y)), y)
    return t, dc_ir+polarity*ac_ir*wave, dc_red+polarity*ac_red*wave


def gaussian_baseline():
    """Current project's DEFAULT preset, not fitted to held-out targets."""
    y = np.exp(-.5*((PHASE-.15)/.055)**2) + .4*np.exp(-.5*((PHASE-.40)/.10)**2)
    y *= 1-.25*np.exp(-.5*((PHASE-.30)/.02)**2)
    edge = np.minimum(1, np.minimum(PHASE, 1-PHASE)/.05)
    y *= edge**2*(3-2*edge)
    return (y/y.max()).astype(np.float32)


def prepare(data_path, output, seed):
    import neurokit2 as nk
    if hashlib.sha256(Path(data_path).read_bytes()).hexdigest() != MAT_SHA256:
        raise ValueError("BIDMC MAT checksum mismatch; incomplete or wrong download")
    records = loadmat(data_path, simplify_cells=True)["data"]
    pulses, conditions, subjects, record_ids, starts = [], [], [], [], []
    record_report = []
    for index, record in enumerate(records, 1):
        subject = str(record["fix"]["id"])
        if not re.fullmatch(r"s\d+", subject):
            raise ValueError(f"Unrecognized patient identifier {subject!r}")
        fs = float(record["ppg"]["fs"])
        raw = np.asarray(record["ppg"]["v"], dtype=float).ravel()
        if not np.isfinite(raw).all():
            raise ValueError(f"Nonfinite source record {index}")
        detection = nk.ppg_clean(raw, sampling_rate=fs, method="elgendi")
        _, info = nk.ppg_peaks(detection, sampling_rate=fs, method="elgendi")
        peaks = info["PPG_Peaks"]
        # Detection bandpass is NOT the signal used for morphology labels.
        smooth = sosfiltfilt(butter(4, 12, fs=fs, output="sos"), raw)
        feet = []
        for previous, peak in zip(peaks[:-1], peaks[1:]):
            lo = previous + max(1, int(.25*(peak-previous)))
            feet.append(lo + int(np.argmin(smooth[lo:peak])))
        rejected = Counter()
        accepted = 0
        for left, right in zip(feet[:-1], feet[1:]):
            hr = 60*fs/(right-left) if right > left else 0
            if not 40 <= hr <= 180:  # engineering pilot inclusion, not normal HR
                rejected["duration"] += 1
                continue
            segment = smooth[left:right+1].copy()
            segment -= np.linspace(segment[0], segment[-1], len(segment))
            amplitude = segment.max()
            if amplitude < 1e-8 or segment.min() < -.05*amplitude:
                rejected["baseline_or_flat"] += 1
                continue
            segment = np.maximum(segment/amplitude, 0)
            y = PchipInterpolator(np.linspace(0, 1, len(segment)), segment)(PHASE)
            y[[0, -1]] = 0
            y = (y/y.max()).astype(np.float32)
            c = condition(y, hr)
            if not .05 <= c[1] <= .55:
                rejected["sp_position"] += 1
                continue
            # Reject large extra peaks; absent DN alone is never a rejection.
            if len(find_peaks(y, prominence=.15, distance=8)[0]) > 3:
                rejected["extra_peaks"] += 1
                continue
            pulses.append(y); conditions.append(c); subjects.append(subject)
            record_ids.append(index); starts.append(left)
            accepted += 1
        record_report.append(dict(record=index, subject=subject, fs_hz=fs,
                                  accepted=accepted, rejected=dict(rejected)))
        print(f"PREP record={index:02d} patient={subject} beats={accepted}", flush=True)
    x, c, ids = np.asarray(pulses), np.asarray(conditions), np.asarray(subjects)
    split = split_subjects([r["fix"]["id"] for r in records], seed)
    masks = {key: np.isin(ids, group) for key, group in split.items()}
    if any(mask.sum() < 32 for mask in masks.values()):
        raise ValueError("Insufficient accepted beats in a patient split")
    np.savez_compressed(output/"prepared.npz", pulse=x, condition=c, subject=ids,
                        record=np.asarray(record_ids), start_sample=np.asarray(starts),
                        **masks)
    manifest = dict(source=DATA_URL, sha256=MAT_SHA256, license="ODC-By-1.0",
                    attribution="Pimentel et al. BIDMC PPG and Respiration Dataset 1.0.0",
                    seed=seed, subjects=split, records=record_report,
                    counts={k: int(v.sum()) for k, v in masks.items()},
                    points=POINTS, condition_names=CONDITION_NAMES,
                    train_condition_min=c[masks["train"]].min(0).tolist(),
                    train_condition_max=c[masks["train"]].max(0).tolist(),
                    train_notch_fraction=float(c[masks["train"], -1].mean()),
                    detector="v1: SP global max; later peak prominence .02; DN local minimum",
                    preprocessing="Elgendi peaks; 12Hz lowpass morphology; foot baseline; PCHIP",
                    limitations=["No manual notch ground truth", "No paired optical IR/Red",
                                 "Critical-care cohort, not healthy reference ranges"])
    write_json(output/"manifest.json", manifest)
    return x, c, masks, manifest


def make_networks():
    import torch
    from torch import nn

    class Generator(nn.Module):
        def __init__(self):
            super().__init__()
            self.fc = nn.Sequential(nn.Linear(LATENT_DIM+7, 256), nn.LeakyReLU(.2),
                                    nn.Linear(256, 32*32), nn.LeakyReLU(.2))
            self.conv = nn.Sequential(
                nn.Upsample(scale_factor=2, mode="linear", align_corners=False),
                nn.Conv1d(32, 32, 7, padding=3), nn.LeakyReLU(.2),
                nn.Upsample(scale_factor=2, mode="linear", align_corners=False),
                nn.Conv1d(32, 16, 7, padding=3), nn.LeakyReLU(.2),
                nn.Upsample(scale_factor=2, mode="linear", align_corners=False),
                nn.Conv1d(16, 1, 7, padding=3), nn.Sigmoid())
            edge = torch.clamp(torch.minimum(torch.linspace(0, 1, POINTS),
                                             torch.linspace(1, 0, POINTS))/.03, max=1)
            self.register_buffer("edge", edge**2*(3-2*edge))

        def forward(self, z, c):
            x = self.fc(torch.cat((z, c), dim=1)).reshape(-1, 32, 32)
            y = self.conv(x).squeeze(1)*self.edge
            return y/y.amax(dim=1, keepdim=True).clamp_min(1e-6)

    class Critic(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv = nn.Sequential(nn.Conv1d(8, 16, 7, 2, 3), nn.LeakyReLU(.2),
                                      nn.Conv1d(16, 32, 7, 2, 3), nn.LeakyReLU(.2),
                                      nn.Conv1d(32, 32, 7, 2, 3), nn.LeakyReLU(.2))
            self.out = nn.Linear(32*32, 1)

        def forward(self, x, c):
            joined = torch.cat((x.unsqueeze(1), c.unsqueeze(2).expand(-1, -1, POINTS)), 1)
            return self.out(self.conv(joined).flatten(1)).squeeze(1)

    return Generator(), Critic()


def gradient_penalty(critic, real, fake, c):
    import torch
    alpha = torch.rand(len(real), 1, device=real.device)
    mixed = (alpha*real + (1-alpha)*fake).requires_grad_(True)
    score = critic(mixed, c)
    grad = torch.autograd.grad(score.sum(), mixed, create_graph=True)[0]
    return ((grad.norm(2, dim=1)-1)**2).mean()


def landmark_loss(y, c):
    """Weak differentiable condition constraints, no paired waveform regression."""
    import torch
    phase = torch.linspace(0, 1, POINTS, device=y.device)
    soft_sp = (torch.softmax(40*y, dim=1)*phase).sum(1)
    idx = (c[:, 1:4]*255).round().long().clamp(1, 254)
    levels = y.gather(1, idx)
    slopes = (y[:, 2:]-y[:, :-2]).gather(1, idx-1)
    present = c[:, -1]
    return ((soft_sp-c[:, 1])**2).mean() + ((levels[:, 0]-1)**2).mean() + (
        present*((levels[:, 1]-c[:, 4])**2+(levels[:, 2]-c[:, 5])**2
                 + 10*(slopes[:, 1:]**2).sum(1))).mean()


def metrics(samples, requested, reference, train_bank):
    observed = np.stack([condition(y, float(c[0]*200)) for y, c in zip(samples, requested)])
    both = (requested[:, -1] == 1) & (observed[:, -1] == 1)
    feature_mae = {"sp_phase": float(np.abs(observed[:, 1]-requested[:, 1]).mean())}
    for i, name in enumerate(CONDITION_NAMES[2:6], 2):
        feature_mae[name] = float(np.abs(observed[both, i]-requested[both, i]).mean()) if both.any() else None
    ref = np.stack([condition(y, float(c[0]*200)) for y, c in zip(reference, requested)])
    nn_dist = np.sqrt(cdist(samples, train_bank, metric="sqeuclidean").min(1)/POINTS)
    return dict(condition_mae=feature_mae, notch_flag_accuracy=float(
        (observed[:, -1] == requested[:, -1]).mean()),
        notch_fraction=float(observed[:, -1].mean()), matched_notch_count=int(both.sum()),
        sp_distribution_wasserstein=float(wasserstein_distance(observed[:, 1], ref[:, 1])),
        mean_pointwise_std=float(samples.std(0).mean()),
        nearest_train_rmse_median=float(np.median(nn_dist)),
        nearest_train_rmse_min=float(nn_dist.min()),
        mean_abs_second_difference=float(np.abs(np.diff(samples, n=2, axis=1)).mean()))


def train(x, c, masks, manifest, output, args):
    import torch
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    torch.set_num_threads(2)
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if args.require_gpu and device.type != "cuda":
        raise RuntimeError("Kaggle pilot requires GPU; refusing silent CPU fallback")
    g, d = make_networks()
    g, d = g.to(device), d.to(device)
    opt_g = torch.optim.Adam(g.parameters(), lr=1e-4, betas=(0., .9))
    opt_d = torch.optim.Adam(d.parameters(), lr=1e-4, betas=(0., .9))
    tx, tc = torch.tensor(x[masks["train"]], device=device), torch.tensor(c[masks["train"]], device=device)
    vi = rng.choice(np.flatnonzero(masks["validation"]), min(256, masks["validation"].sum()), replace=False)
    vc = torch.tensor(c[vi], device=device)
    vz = torch.randn(len(vi), LATENT_DIM, device=device)
    history, best = [], float("inf")
    start = time.monotonic()
    print(f"TRAIN device={device} steps={args.steps} subjects={manifest['counts']}", flush=True)
    for step in range(1, args.steps+1):
        for _ in range(args.ncritic):
            idx = torch.randint(len(tx), (args.batch,), device=device)
            real, cond = tx[idx], tc[idx]
            with torch.no_grad():
                fake = g(torch.randn(args.batch, LATENT_DIM, device=device), cond)
            opt_d.zero_grad(set_to_none=True)
            gp = gradient_penalty(d, real, fake, cond)
            loss_d = d(fake, cond).mean()-d(real, cond).mean()+10*gp
            loss_d.backward(); opt_d.step()
        for p in d.parameters():
            p.requires_grad_(False)
        opt_g.zero_grad(set_to_none=True)
        fake = g(torch.randn(args.batch, LATENT_DIM, device=device), cond)
        morphology_loss = landmark_loss(fake, cond)
        loss_g = -d(fake, cond).mean()+10*morphology_loss
        loss_g.backward(); opt_g.step()
        for p in d.parameters():
            p.requires_grad_(True)
        if step == 1 or step % 100 == 0 or step == args.steps:
            g.eval()
            with torch.no_grad():
                vy = g(vz, vc).cpu().numpy()
            measured = np.stack([condition(y, float(q[0]*200)) for y, q in zip(vy, c[vi])])
            # Validation only: missing landmarks penalized through zero encoding and flag.
            val = float(np.abs(measured[:, 1:]-c[vi, 1:]).mean())
            row = dict(step=step, critic=float(loss_d.detach()), generator=float(loss_g.detach()),
                       gp=float(gp.detach()), landmark=float(morphology_loss.detach()),
                       validation_condition_l1=val, elapsed_seconds=time.monotonic()-start)
            history.append(row); print(json.dumps(row), flush=True)
            if val < best:
                best = val
                torch.save(dict(generator=g.state_dict(), step=step, validation=val,
                                args=vars(args), condition_names=CONDITION_NAMES), output/"generator_best.pt")
            write_json(output/"history.json", history)
            g.train()
    checkpoint = torch.load(output/"generator_best.pt", map_location=device, weights_only=False)
    g.load_state_dict(checkpoint["generator"]); g.eval()
    ti = rng.choice(np.flatnonzero(masks["test"]), min(512, masks["test"].sum()), replace=False)
    target, reference = c[ti], x[ti]
    with torch.no_grad():
        generated = g(torch.randn(len(ti), LATENT_DIM, device=device),
                      torch.tensor(target, device=device)).cpu().numpy()
        fixed_c = torch.tensor(np.repeat(target[:1], 64, 0), device=device)
        variations = g(torch.randn(64, LATENT_DIM, device=device), fixed_c).cpu().numpy()
    # Replay searches ONLY training data using the same requested conditions.
    bank = x[masks["train"]]
    nearest = cdist(target, c[masks["train"]]).argmin(1)
    replay = bank[nearest]
    gaussian = np.repeat(gaussian_baseline()[None], len(target), 0)
    # Bound memory for distance reporting; the subset seed is reproducible.
    distance_bank = bank[rng.choice(len(bank), min(2048, len(bank)), replace=False)]
    result = {name: metrics(y, target, reference, distance_bank) for name, y in
              (("gan", generated), ("gaussian_default_not_fitted", gaussian),
               ("real_replay_train_only", replay), ("real_heldout_reference", reference))}
    result["run"] = dict(best_step=checkpoint["step"], steps=args.steps,
                         elapsed_seconds=time.monotonic()-start, device=str(device),
                         gpu=torch.cuda.get_device_name(0) if device.type == "cuda" else None,
                         python=platform.python_version(), torch=torch.__version__, numpy=np.__version__,
                         generator_parameters=sum(p.numel() for p in g.parameters()),
                         fixed_condition_diversity=float(variations.std(0).mean()),
                         evaluated_test_beats=len(ti), seed=args.seed,
                         status="research_pilot_not_approved_for_hardware",
                         code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    write_json(output/"metrics.json", result)
    np.savez_compressed(output/"test_samples.npz", gan=generated, real=reference, replay=replay,
                        gaussian=gaussian, condition=target, source_indices=ti, variations=variations)
    g = g.cpu()
    example = (torch.randn(1, LATENT_DIM), torch.tensor(target[:1]))
    artifact = torch.jit.trace(g, example)
    artifact.save(str(output/"generator_cpu.ts"))
    with torch.no_grad():
        torch.testing.assert_close(artifact(*example), g(*example))
    for fs in (100, 1000):
        traces = render_ir_red(generated[0], fs=fs, hr=float(target[0, 0]*200))
        np.savetxt(output/f"ir_red_{fs}hz.csv", np.column_stack(traces), delimiter=",",
                   header="time_s,ir_v,red_v", comments="")
    fig, axes = plt.subplots(3, 4, figsize=(14, 8), sharex=True, sharey=True)
    for i, ax in enumerate(axes.flat):
        ax.plot(PHASE, reference[i], label="Held-out real", color="black")
        ax.plot(PHASE, generated[i], label="GAN", color="#0072B2")
        ax.plot(PHASE, replay[i], label="Train replay", color="#009E73", alpha=.6)
        ax.plot(PHASE, gaussian[i], label="Gaussian default", color="#D55E00", alpha=.6)
        ax.set_title(f"HR={target[i,0]*200:.1f}; notch={int(target[i,-1])}")
        ax.set_xlabel("Cycle phase")
    axes[0, 0].legend(fontsize=7)
    fig.tight_layout(); fig.savefig(output/"comparison.png", dpi=150); plt.close(fig)
    print("COMPLETE " + json.dumps(result["run"]), flush=True)


def main():
    kaggle = Path("/kaggle/working").is_dir()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="/tmp/bidmc_data.mat" if kaggle else "dataset/bidmc/bidmc_data.mat")
    parser.add_argument("--output", default="/kaggle/working/ppg_run" if kaggle else "ml/runs/local")
    parser.add_argument("--steps", type=int, default=1500)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--ncritic", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--require-gpu", action="store_true", default=kaggle)
    args = parser.parse_args()
    if min(args.steps, args.batch, args.ncritic) <= 0:
        parser.error("steps, batch and ncritic must be positive")
    try:
        import neurokit2  # noqa: F401
    except ImportError:
        if not kaggle:
            raise
        subprocess.run([sys.executable, "-m", "pip", "install", "neurokit2==0.2.13"], check=True)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if (output/"metrics.json").exists():
        raise FileExistsError("Use a new output directory to preserve the previous run")
    data = Path(args.data)
    if not data.exists():
        subprocess.run(["curl", "-fSL", "--retry", "2", "--max-time", "900", "-o", str(data), DATA_URL], check=True)
    x, c, masks, manifest = prepare(data, output, args.seed)
    if not args.prepare_only:
        train(x, c, masks, manifest, output, args)


if __name__ == "__main__":
    main()
