"""Shared metrics fitted on training only; subject-balanced evaluation and bootstrap."""
import time

import numpy as np
from scipy.signal import find_peaks, peak_widths, welch
from scipy.spatial.distance import cdist, pdist
from scipy.stats import wasserstein_distance
import torch

from ml.kaggle_lsm.train_lsm import FS, LENGTH, features, mmd2
from ml.kaggle_multidomain.data import balanced_indices, balanced_pool
from ml.kaggle_multidomain.models import generate

MORPH_NAMES = ("peak_rate_bpm", "ibi_cv", "median_width_seconds", "median_rise_seconds",
               "signal_std", "skew", "mean_abs_slope", "mean_abs_curvature", "above_5hz_fraction")


def morphology(x):
    result = []
    for row in x:
        peaks, _ = find_peaks(row, distance=round(.3*FS), prominence=.15)
        ibi = np.diff(peaks)/FS
        if len(peaks):
            widths = peak_widths(row, peaks, rel_height=.5)[0]/FS
            rise = [(p-(max(0, p-round(.7*FS))+np.argmin(row[max(0, p-round(.7*FS)):p+1])))/FS for p in peaks]
        else:
            widths, rise = [0.], [0.]
        std = max(float(np.std(row)), 1e-8)
        f, power = welch(row, fs=FS, nperseg=400, noverlap=200)
        result.append([len(peaks)*2, np.std(ibi)/max(np.mean(ibi), 1e-8) if len(ibi) else 0.,
                       np.median(widths), np.median(rise), std, np.mean(((row-row.mean())/std)**3),
                       np.abs(np.diff(row)).mean(), np.abs(np.diff(row, n=2)).mean(),
                       power[f > 5].sum()/max(power.sum(), 1e-12)])
    return np.asarray(result)


class Evaluator:
    def __init__(self, pack, n=128):
        self.pack, self.n = pack, n
        rng = np.random.default_rng(8102)
        ids = balanced_indices(pack, "train", rng, 512)
        train = pack["signal"][ids]
        self.center = np.median(morphology(train), axis=0)
        self.scale = np.maximum(np.std(morphology(train), axis=0), 1e-4)
        blocks = self.blocks(train)
        self.bandwidths = [max(float(np.median(pdist(b, "sqeuclidean"))), 1e-6) for b in blocks]
        self.train_blocks = blocks
        self.train_waveforms = train
        self.indices = {}
        self.reference = {}
        for split in ("validation", "test", "external"):
            for domain in sorted(set(pack["domain"][pack["split"] == split])):
                pool, weights = balanced_pool(pack, split, [domain])
                idx = np.random.default_rng(9001).choice(pool, min(n, len(pool)), replace=False, p=weights)
                if len(idx) < 2:
                    raise ValueError(f"Too few evaluation windows: {split}/{domain}")
                self.indices[split, domain] = idx
                self.reference[split, domain] = self.blocks(pack["signal"][idx])

    def blocks(self, x):
        return (*features(x), (morphology(x)-self.center)/self.scale)

    def validation(self, generated):
        blocks = self.blocks(generated)
        per_domain = {domain: [mmd2(a[:len(b)], b, bw) for a, b, bw in zip(blocks, ref, self.bandwidths)]
                      for (split, domain), ref in self.reference.items() if split == "validation"}
        if not per_domain:
            raise ValueError("No validation domains")
        return float(np.mean([sum(v) for v in per_domain.values()])), per_domain

    def evaluate(self, generated, split, bootstrap=50):
        all_blocks = self.blocks(generated)
        results = {}
        for (s, domain), real in self.reference.items():
            if s != split:
                continue
            blocks = tuple(b[:len(real[0])] for b in all_blocks)
            values = [mmd2(a, b, bw) for a, b, bw in zip(blocks, real, self.bandwidths)]
            subject = self.pack["subject"][self.indices[s, domain]]
            unique = np.unique(subject)
            rng = np.random.default_rng(1803)
            totals = []
            for _ in range(bootstrap):
                # Resample patients, then all their selected windows; fake resampled independently.
                ids = np.concatenate([np.flatnonzero(subject == p) for p in rng.choice(unique, len(unique))])
                fi = rng.integers(len(blocks[0]), size=len(blocks[0]))
                totals.append(sum(mmd2(a[fi], b[ids], bw) for a, b, bw in zip(blocks, real, self.bandwidths)))
            a, b = blocks[2], real[2]
            rr, ff, rf = cdist(b, b), cdist(a, a), cdist(b, a)
            np.fill_diagonal(rr, np.inf); np.fill_diagonal(ff, np.inf)
            k = min(5, len(a)-1, len(b)-1)
            radius_r = np.partition(rr, k-1, axis=1)[:, k-1]
            radius_f = np.partition(ff, k-1, axis=1)[:, k-1]
            all_features = np.concatenate((b, a))
            dist = cdist(all_features, all_features)
            np.fill_diagonal(dist, np.inf)
            labels = np.r_[np.zeros(len(b)), np.ones(len(a))]
            metrics = dict(zip(("acf_mmd2", "log_psd_mmd2", "morphology_mmd2"), values))
            metrics.update(total_mmd=float(sum(values)),
                           patient_bootstrap_total_ci95=np.quantile(totals, [.025, .975]).tolist() if totals else None,
                           sampled_patients=len(unique), sampled_windows=len(b),
                           feature_precision=float((rf <= radius_r[:, None]).any(0).mean()),
                           feature_recall=float((rf <= radius_f[None, :]).any(1).mean()),
                           two_sample_1nn_accuracy=float((labels[dist.argmin(1)] == labels).mean()),
                           morphology_wasserstein_standardized={name: float(wasserstein_distance(a[:, i], b[:, i]))
                                                               for i, name in enumerate(MORPH_NAMES)})
            results[domain] = metrics
        return results

    def diagnostics(self, generated):
        x = self.blocks(generated)[2]
        reference = self.train_blocks[2]
        nn_feature = cdist(x, reference).min(1)
        nn_wave = cdist(generated, self.train_waveforms)/np.sqrt(LENGTH)
        return dict(finite=bool(np.isfinite(generated).all()),
                    flat_fraction=float((np.ptp(generated, axis=1) < 1e-6).mean()),
                    morphology_pairwise_distance_median=float(np.median(pdist(x))),
                    train_morphology_pairwise_distance_median=float(np.median(pdist(reference))),
                    nearest_train_feature_distance_median=float(np.median(nn_feature)),
                    nearest_train_waveform_rmse_p05=float(np.quantile(nn_wave.min(1), .05)),
                    memorization_reference="512 subject/domain-balanced training draws; screening, not a privacy guarantee")


@torch.no_grad()
def sample(model, seed, device, n=128, diffusion=False):
    generator = torch.Generator(device=device).manual_seed(seed)
    z = torch.randn(n, LENGTH, device=device, generator=generator)
    return torch.cat([generate(model, part, diffusion) for part in z.split(16)]).cpu().numpy()[:, 0]


@torch.no_grad()
def cpu_latency(model, diffusion=False):
    model = model.cpu().eval()
    torch.set_num_threads(1)
    z = torch.randn(1, LENGTH)
    for _ in range(3):
        generate(model, z, diffusion)
    times = []
    for _ in range(20):
        start = time.perf_counter()
        generate(model, z, diffusion)
        times.append((time.perf_counter()-start)*1000)
    return dict(cpu_threads=1, median_ms=float(np.median(times)), p95_ms=float(np.quantile(times, .95)),
                realtime_factor=float(np.median(times)/30000), hardware_scope="Kaggle/host CPU; Raspberry Pi not measured")
