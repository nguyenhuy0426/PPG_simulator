"""LSM-GAN independent research reimplementation and controlled ablation.

Paper: https://arxiv.org/abs/2108.05272v2 (Ding et al.). Architecture reference:
https://github.com/chengding0713/Log-Spectral-matching-GAN
commit d2d01feab0cec7c129bae0b63c56277adc4f48cc.
Paper/code differ: least squares vs BCE; aligned vs all-pairs matching.
We expose both, with stable per-sample log-spectrum normalization. This is
NOT byte-for-byte author code nor a reproduction of AF classification results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path

import numpy as np
import torch
from scipy.io import loadmat
from scipy.signal import firwin, filtfilt, resample_poly, welch
from scipy.spatial.distance import cdist, pdist
from scipy.stats import wasserstein_distance
from torch import nn

FS, LENGTH = 40, 1200
MAT_HASH = "91865c2fffff70868875545f897542003d376a53262c7c0ead5b6e9109e884db"
DATA_URL = "https://physionet.org/files/bidmc/1.0.0/bidmc_data.mat"
VARIANTS = {"lsm_paper": ("mse", "aligned", 1., 1.),
            "lsm_repo_corrected": ("bce", "all_pairs", 1., 1.),
            "dcgan1200_no_spectral": ("bce", "all_pairs", 0., 0.)}


def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False)+"\n")


def make_networks():
    """Same topology for all new arms; no upsampling in the generator."""
    class Generator(nn.Module):
        def __init__(self):
            super().__init__()
            self.branches = nn.ModuleList([
                nn.Sequential(nn.Conv1d(1, width, kernel, padding=kernel//2, bias=False),
                              nn.BatchNorm1d(width), nn.ReLU())
                for width, kernel in ((80, 5), (40, 21), (20, 61))])
            self.merge = nn.Sequential(nn.Conv1d(140, 50, 15, padding=7, bias=False),
                                       nn.BatchNorm1d(50), nn.ReLU(),
                                       nn.Conv1d(50, 50, 4, padding=1, bias=False), nn.Tanh(),
                                       nn.Conv1d(50, 1, 2, padding=1, bias=False), nn.Tanh())

        def forward(self, z):
            z = z.reshape(-1, 1, LENGTH)
            y = self.merge(torch.cat([branch(z) for branch in self.branches], 1))
            lo, hi = y.amin(2, keepdim=True), y.amax(2, keepdim=True)
            return (y-lo)/(hi-lo).clamp_min(1e-6)

    class Discriminator(nn.Module):
        def __init__(self):
            super().__init__()
            layers = []
            previous = 1
            for width in (64, 128, 256, 512):
                layers.append(nn.Conv1d(previous, width, 4, stride=2, padding=1, bias=False))
                if previous != 1:
                    layers.append(nn.BatchNorm1d(width))
                layers.append(nn.LeakyReLU(.2))
                previous = width
            layers.append(nn.Conv1d(512, 1, 4, bias=False))
            self.encoder = nn.Sequential(*layers)
            # Keep the reference's two sigmoid outputs; both share real/fake targets.
            # These are NOT the AF/non-AF classes.
            self.head = nn.Sequential(nn.Linear(72, 2), nn.Sigmoid())

        def forward(self, x):
            return self.head(self.encoder(x).flatten(1))

    def initialize(module):
        if isinstance(module, nn.Conv1d):
            nn.init.normal_(module.weight, 0, .02)
        elif isinstance(module, nn.BatchNorm1d):
            nn.init.normal_(module.weight, 1, .02)
            nn.init.zeros_(module.bias)

    g, d = Generator(), Discriminator()
    g.apply(initialize); d.apply(initialize)
    return g, d


def log_spectra(x, window=400, overlap=200):
    """Hann-windowed log power, scaled along frequency PER sample/block.

    Corrects the reference's batch-mixing view and log(0) instability; torch.fft
    replaces removed torch.rfft. No detrending, matching the reference loss.
    """
    if window <= 1 or not 0 <= overlap < window or x.shape[-1] < window:
        raise ValueError("Invalid spectral block configuration")
    x = x.reshape(x.shape[0], -1).clamp_min(1e-6)
    blocks = x.unfold(-1, window, window-overlap)
    taper = 2*torch.hann_window(window, device=x.device, dtype=x.dtype)
    power = torch.fft.rfft(blocks*taper, dim=-1).abs().square()
    logs = power.clamp_min(1e-6).log()
    lo, hi = logs.amin(-1, keepdim=True), logs.amax(-1, keepdim=True)
    return (logs-lo)/(hi-lo).clamp_min(1e-6)


def spectral_loss(fake, real, pairing="aligned", aggregation="mean"):
    if pairing not in ("aligned", "all_pairs") or aggregation not in ("mean", "max"):
        raise ValueError("Unknown spectral pairing or aggregation")
    f, r = log_spectra(fake), log_spectra(real)
    if f.shape != r.shape:
        raise ValueError("Real and generated block shapes must match")
    if pairing == "aligned":
        match = (f-r).square().mean((0, 2))
    else:
        match = (f[:, :, None]-r[:, None, :]).square().mean((0, 3))
    i, j = torch.triu_indices(f.shape[1], f.shape[1], offset=1, device=f.device)
    consistency = (f[:, i]-f[:, j]).square().mean((0, 2))
    reduce = torch.mean if aggregation == "mean" else torch.max
    return reduce(match), reduce(consistency)


def normalize(x):
    x = np.asarray(x, dtype=np.float64)
    span = np.ptp(x, axis=-1, keepdims=True)
    if not np.isfinite(x).all() or np.any(span < 1e-8):
        raise ValueError("Nonfinite/flat signal")
    return ((x-x.min(axis=-1, keepdims=True))/span).astype(np.float32)


def bandpass(x):
    # Explicit engineering FIR design: paper does not supply tap count/phase.
    taps = firwin(161, [.9, 5.], pass_zero=False, fs=FS)
    return filtfilt(taps, [1.], x, axis=-1)


def prepare(data_path, prior, output):
    if hashlib.sha256(data_path.read_bytes()).hexdigest() != MAT_HASH:
        raise ValueError("Source MAT checksum failed")
    source_manifest = json.loads((prior/"manifest.json").read_text())
    groups = source_manifest["subjects"]
    sets = [set(v) for v in groups.values()]
    if any(sets[i] & sets[j] for i in range(3) for j in range(i+1, 3)):
        raise ValueError("Prior patient groups overlap")
    windows, subjects, records, starts = [], [], [], []
    for record_id, rec in enumerate(loadmat(data_path, simplify_cells=True)["data"], 1):
        subject = str(rec["fix"]["id"])
        if subject not in set.union(*sets):
            raise ValueError("Unknown patient in frozen split")
        if float(rec["ppg"]["fs"]) != 125:
            raise ValueError("Expected BIDMC native 125 Hz")
        wave = bandpass(resample_poly(np.asarray(rec["ppg"]["v"]).ravel(), 8, 25))
        for left in range(0, len(wave)-LENGTH+1, LENGTH):
            windows.append(normalize(wave[left:left+LENGTH]))
            subjects.append(subject); records.append(record_id); starts.append(left)
    x = np.stack(windows); subjects = np.asarray(subjects)
    masks = {k: np.isin(subjects, v) for k, v in groups.items()}
    manifest = dict(source=DATA_URL, sha256=MAT_HASH, subjects=groups,
                    counts={k: int(v.sum()) for k, v in masks.items()}, fs_hz=FS,
                    native_fs_hz=125, length=LENGTH, seconds=30,
                    preprocessing="resample_poly 8/25; 161-tap 0.9-5Hz zero-phase FIR; per-window minmax",
                    limitations=["BIDMC mixed critical-care rhythms; no AF labels used",
                                 "Not the author's AF/Non-AF datasets",
                                 "Prior test patients already inspected: exploratory comparison"],
                    attribution="BIDMC 1.0.0; Pimentel et al.; ODC-By-1.0")
    np.savez_compressed(output/"windows.npz", signal=x, subject=subjects,
                        record=np.asarray(records), start_sample=np.asarray(starts), **masks)
    save_json(output/"manifest.json", manifest)
    return x, masks, manifest


def features(x):
    """Biased normalized ACF at 25ms..5s; normalized log-Welch power."""
    x = np.asarray(x).reshape(-1, LENGTH).astype(np.float64)
    centered = x-x.mean(-1, keepdims=True)
    fft = np.fft.rfft(centered, n=2*LENGTH, axis=-1)
    acf = np.fft.irfft(np.abs(fft)**2, n=2*LENGTH, axis=-1)[:, :201]
    acf /= np.maximum(acf[:, :1], 1e-12)
    _, psd = welch(x, fs=FS, nperseg=400, noverlap=200, axis=-1)
    psd /= np.maximum(psd.sum(-1, keepdims=True), 1e-12)
    return acf[:, 1:], np.log10(psd[:, 1:]+1e-8)


def mmd2(a, b, bandwidth):
    """Biased RBF MMD squared; bandwidth fixed from training features only."""
    return float(np.exp(-cdist(a, a, "sqeuclidean")/(2*bandwidth)).mean()
                 + np.exp(-cdist(b, b, "sqeuclidean")/(2*bandwidth)).mean()
                 - 2*np.exp(-cdist(a, b, "sqeuclidean")/(2*bandwidth)).mean())


def describe(x):
    f, p = welch(x, fs=FS, nperseg=400, noverlap=200, axis=-1)
    band = (f >= .5) & (f <= 3.)
    bpm = 60*f[band][p[:, band].argmax(1)]
    high = p[:, f > 5].sum(1)/np.maximum(p.sum(1), 1e-12)
    return dict(dominant_bpm_median=float(np.median(bpm)),
                dominant_bpm_p05_p95=np.quantile(bpm, [.05, .95]).tolist(),
                above_5hz_power_fraction_mean=float(high.mean()),
                mean_abs_second_difference=float(np.abs(np.diff(x, n=2)).mean()),
                mean_pointwise_std=float(x.std(0).mean()))


def score(samples, reference, bandwidths):
    a, b = features(samples), features(reference)
    return {"acf_mmd2": mmd2(a[0], b[0], bandwidths[0]),
            "log_psd_mmd2": mmd2(a[1], b[1], bandwidths[1]),
            "mean_log_psd_rmse": float(np.sqrt(np.mean((a[1].mean(0)-b[1].mean(0))**2))),
            **describe(samples)}


def prepare_discriminator_for_generator(discriminator):
    """Freeze weights, NOT BatchNorm mode; G and D must see the same mapping.

    Switching D to eval only for G optimizes against running statistics while
    D learns using batch statistics. Keep training mode as in the reference.
    Evaluation/export still uses eval on both networks.
    """
    discriminator.train()
    for parameter in discriminator.parameters():
        parameter.requires_grad_(False)


def train_one(name, x, masks, output, args, bandwidths):
    loss_kind, pairing, w_match, w_self = VARIANTS[name]
    # Reset all random streams for each arm: same initial weights/minibatches/noise.
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    g, d = make_networks(); g.to(device); d.to(device)
    optg = torch.optim.Adam(g.parameters(), lr=5e-4, betas=(.5, .999))
    optd = torch.optim.Adam(d.parameters(), lr=5e-4, betas=(.5, .999))
    criterion = nn.MSELoss() if loss_kind == "mse" else nn.BCELoss()
    train_x = torch.tensor(x[masks["train"], None], device=device)
    val_real = x[masks["validation"]]
    val_z = torch.tensor(rng.standard_normal((len(val_real), LENGTH)).astype(np.float32), device=device)
    run = output/name; run.mkdir()
    best, history, started = float("inf"), [], time.monotonic()
    for step in range(1, args.steps+1):
        g.train(); d.train()
        idx = torch.randint(len(train_x), (args.batch,), device=device)
        real = train_x[idx]
        fake = g(torch.randn(args.batch, LENGTH, device=device))
        optd.zero_grad(set_to_none=True)
        pred_real, pred_fake = d(real), d(fake.detach())
        ld = criterion(pred_real, torch.ones_like(pred_real))+criterion(pred_fake, torch.zeros_like(pred_fake))
        ld.backward(); optd.step()
        prepare_discriminator_for_generator(d)
        optg.zero_grad(set_to_none=True)
        pred = d(fake)
        adv = criterion(pred, torch.ones_like(pred))
        if w_match or w_self:
            matching, consistency = spectral_loss(fake, real, pairing=pairing)
        else:
            matching = consistency = torch.zeros((), device=device)
        lg = adv+w_match*matching+w_self*consistency
        lg.backward(); optg.step()
        for p in d.parameters():
            p.requires_grad_(True)
        if not torch.isfinite(ld+lg):
            raise RuntimeError(f"Nonfinite loss in {name} step {step}")
        if step == 1 or step % 100 == 0 or step == args.steps:
            g.eval(); d.eval()
            with torch.no_grad():
                generated = torch.cat([g(z) for z in val_z.split(32)]).cpu().numpy()[:, 0]
            val = score(generated, val_real, bandwidths)
            total = val["acf_mmd2"]+val["log_psd_mmd2"]
            row = dict(step=step, d_loss=float(ld.detach()), g_loss=float(lg.detach()),
                       adversarial=float(adv.detach()), matching=float(matching.detach()),
                       consistency=float(consistency.detach()), validation=val,
                       selection_score=total, seconds=time.monotonic()-started)
            history.append(row); print(name, json.dumps(row), flush=True)
            if total < best:
                best = total
                torch.save(dict(generator=g.state_dict(), discriminator=d.state_dict(),
                                step=step, variant=name, validation=val), run/"best.pt")
            save_json(run/"history.json", history)
    # Save BOTH trained networks plus optimizer/RNG states, not just a generator.
    torch.save(dict(generator=g.state_dict(), discriminator=d.state_dict(),
                    optimizer_g=optg.state_dict(), optimizer_d=optd.state_dict(), step=args.steps,
                    torch_rng=torch.get_rng_state(), numpy_rng=rng.bit_generator.state,
                    cuda_rng=torch.cuda.get_rng_state_all() if device.type == "cuda" else [],
                    args=vars(args), variant=name), run/"last_training_state.pt")
    checkpoint = torch.load(run/"best.pt", map_location=device, weights_only=False)
    g.load_state_dict(checkpoint["generator"]); d.load_state_dict(checkpoint["discriminator"])
    g.eval(); d.eval()
    test_real = x[masks["test"]]
    test_noise = np.random.default_rng(args.seed+1000).standard_normal((len(test_real), LENGTH)).astype(np.float32)
    with torch.no_grad():
        generated = torch.cat([g(z.to(device)) for z in torch.tensor(test_noise).split(32)]).cpu().numpy()[:, 0]
        dr = torch.cat([d(z.to(device)) for z in torch.tensor(test_real[:, None]).split(32)]).cpu().numpy()
        df = torch.cat([d(z.to(device)) for z in torch.tensor(generated[:, None]).split(32)]).cpu().numpy()
    result = score(generated, test_real, bandwidths)
    result.update(best_step=checkpoint["step"], steps=args.steps, seconds=time.monotonic()-started,
                  d_real_mean=float(dr.mean()), d_fake_mean=float(df.mean()),
                  generator_parameters=sum(p.numel() for p in g.parameters()),
                  discriminator_parameters=sum(p.numel() for p in d.parameters()),
                  status="research_only_not_for_DAC")
    g.cpu(); d.cpu()
    with torch.no_grad():
        for label, model, example in (("generator", g, torch.randn(1, LENGTH)),
                                      ("discriminator", d, torch.rand(1, 1, LENGTH))):
            traced = torch.jit.trace(model, example)
            torch.testing.assert_close(traced(example), model(example))
            traced.save(str(run/f"{label}_cpu.ts"))
    np.savez_compressed(run/"samples.npz", generated=generated, real=test_real,
                        d_real=dr, d_fake=df)
    save_json(run/"metrics.json", result)
    return generated, result


def render_pulses(pulses, conditions):
    # Comparator-only adapter: constant HR, repeated single pulse, then SAME
    # 0.9-5Hz view as the strip data. Not a learned HRV/AF generator.
    t = np.arange(LENGTH)/FS
    rows = [np.interp((t*float(c[0]*200)/60) % 1, np.linspace(0, 1, len(p)), p)
            for p, c in zip(pulses, conditions)]
    return normalize(bandpass(np.asarray(rows)))


def baselines(prior, n, seed):
    data = np.load(prior/"prepared.npz", allow_pickle=False)
    rng = np.random.default_rng(seed+2026)
    ids = rng.choice(np.flatnonzero(data["train"]), n, replace=True)
    c = data["condition"][ids]
    g = torch.jit.load(str(prior/"generator_cpu.ts"), map_location="cpu").eval()
    torch.manual_seed(seed+2026)
    with torch.no_grad():
        pulse = g(torch.randn(n, 32), torch.tensor(c)).numpy()
    return {"cwgan_v1_periodic_adapter": render_pulses(pulse, c),
            "real_train_pulse_periodic_adapter": render_pulses(data["pulse"][ids], c)}


def main():
    kaggle = Path("/kaggle/working").is_dir()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=1500)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data", default="/tmp/bidmc_data.mat" if kaggle else "dataset/bidmc/bidmc_data.mat")
    parser.add_argument("--prior", default=None)
    parser.add_argument("--output", default="/kaggle/working/lsm_comparison" if kaggle else "ml/runs/lsm-local")
    parser.add_argument("--variants", nargs="+", choices=list(VARIANTS), default=list(VARIANTS))
    args = parser.parse_args()
    if min(args.steps, args.batch) <= 0 or args.batch < 2:
        parser.error("Positive steps and batch >=2 required")
    torch.set_num_threads(2)
    if kaggle and not torch.cuda.is_available():
        raise RuntimeError("GPU required; refusing silent CPU fallback")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    if args.prior:
        prior = Path(args.prior)
    elif kaggle:
        candidates = list(Path("/kaggle/input").rglob("generator_cpu.ts"))
        if len(candidates) != 1:
            raise RuntimeError(f"Expected exactly one mounted pilot artifact, found {len(candidates)}")
        prior = candidates[0].parent
    else:
        prior = Path("ml/runs/kaggle-v1/ppg_run")
    expected = "0894f5aa8b2b37d117c188170c2c460c49f3fd0ec1aaa22aa226a46b103ff60b"
    if json.loads((prior/"metrics.json").read_text())["run"]["code_sha256"] != expected:
        raise ValueError("Mounted cWGAN pilot is not the frozen v1 implementation")
    data_path = Path(args.data)
    if not data_path.exists():
        subprocess.run(["curl", "-fsSL", "--retry", "2", "--max-time", "900", "-o", str(data_path), DATA_URL], check=True)
    x, masks, manifest = prepare(data_path, prior, output)
    train_features = features(x[masks["train"]])
    bandwidths = [max(float(np.median(pdist(f, "sqeuclidean"))), 1e-6) for f in train_features]
    configuration = dict(args=vars(args), bandwidths=bandwidths, counts=manifest["counts"],
                         implementation_revision="v2: consistent D train-mode during G update",
                         variants=VARIANTS, window=400, overlap=200, aggregation="mean",
                         selection="validation ACF MMD2 + log-PSD MMD2; bandwidth train-only",
                         seed=args.seed, python=platform.python_version(), torch=torch.__version__,
                         gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                         code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                         prior_generator_sha256=hashlib.sha256((prior/"generator_cpu.ts").read_bytes()).hexdigest())
    save_json(output/"configuration.json", configuration)
    print("CONFIG "+json.dumps(configuration), flush=True)
    samples, results = {}, {}
    for name in args.variants:
        samples[name], results[name] = train_one(name, x, masks, output, args, bandwidths)
    test_real = x[masks["test"]]
    samples.update(baselines(prior, len(test_real), args.seed))
    rng = np.random.default_rng(args.seed+100)
    samples["real_train_window_replay"] = x[rng.choice(np.flatnonzero(masks["train"]), len(test_real), replace=True)]
    for name, values in samples.items():
        if name not in results:
            results[name] = score(values, test_real, bandwidths)
    results["heldout_real_reference"] = score(test_real, test_real, bandwidths)
    save_json(output/"comparison.json", results)
    np.savez_compressed(output/"comparison_samples.npz", real=test_real, **samples)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(len(samples)+1, 2, figsize=(15, 2.4*(len(samples)+1)))
    for row, (name, values) in enumerate({"heldout_real": test_real, **samples}.items()):
        axes[row, 0].plot(np.arange(400)/FS, values[0, :400], lw=1)
        axes[row, 0].set_title(name+" — first sample (not paired)", fontsize=9)
        axes[row, 0].set_xlabel("Time (s), first 10s of 30s")
        f, p = welch(values, fs=FS, nperseg=400, noverlap=200, axis=-1)
        axes[row, 1].semilogy(f, p.mean(0)+1e-10)
        axes[row, 1].set_xlim(0, 10); axes[row, 1].set_xlabel("Frequency (Hz)")
        axes[row, 1].set_title("Mean Welch PSD", fontsize=9)
    fig.tight_layout(); fig.savefig(output/"comparison.png", dpi=140); plt.close(fig)
    print("COMPLETE "+json.dumps(results), flush=True)


if __name__ == "__main__":
    main()
