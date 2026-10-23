"""Simulator-facing checks: HR controllability grid, derivative C2ST probe, Gaussian reference.

All inputs come from train/validation for selection. The rate estimator is independent of
the generator and is cross-checked against ACF so it does not grade its own construction.
"""
import math

import numpy as np
from scipy.stats import rankdata, spearmanr
import torch
from torch import nn
from torch.nn import functional as F

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain.labels import acf_hr, beat_stats

GRID = np.arange(40., 181., 10.)
INSIDE = (GRID >= 60) & (GRID <= 140)
SINUS, IRREGULAR = .02, .20
NAN_ERROR = 20.


def auc(negative, positive):
    """Mann-Whitney AUC that positive scores exceed negative ones."""
    negative, positive = np.asarray(negative, float), np.asarray(positive, float)
    negative, positive = negative[np.isfinite(negative)], positive[np.isfinite(positive)]
    if not len(negative) or not len(positive):
        return float("nan")
    ranks = rankdata(np.r_[negative, positive])
    return float((ranks[len(negative):].sum()-len(positive)*(len(positive)+1)/2)/(len(negative)*len(positive)))


@torch.no_grad()
def controllability(sample_fn, conditions, n=8, seed=4242):
    """sample_fn(z, condition) -> (n, LENGTH) numpy. Returns rate/irregularity control metrics and C."""
    errors_in, errors_out, rhos, locks, missing, acf_gap = [], [], [], [], [], []
    rmssd_sinus, rmssd_irregular, irr_measured, per_domain = [], [], [], {}
    for domain in conditions.domains:
        medians = []
        for g in GRID:
            z = torch.randn(n, LENGTH, generator=torch.Generator().manual_seed(seed+int(g)))
            y = sample_fn(z, conditions.prompt(domain, g, SINUS, n))
            stats = beat_stats(y)
            hr = stats[:, 0]
            error = np.where(np.isfinite(hr), np.abs(hr-g), NAN_ERROR)
            (errors_in if INSIDE[GRID == g][0] else errors_out).extend(error)
            missing.extend(~np.isfinite(hr))
            ratio = hr/g
            locks.extend(np.isfinite(ratio) & ((np.abs(ratio-.5) < .07) | (np.abs(ratio-2) < .25)))
            acf = acf_hr(y)
            acf_gap.extend(np.abs(acf-hr)[np.isfinite(acf) & np.isfinite(hr)])
            medians.append(np.nanmedian(hr) if np.isfinite(hr).any() else np.nan)
            if INSIDE[GRID == g][0]:
                rmssd_sinus.extend(stats[:, 2])
                irregular = beat_stats(sample_fn(z, conditions.prompt(domain, g, IRREGULAR, n)))
                rmssd_irregular.extend(irregular[:, 2])
                irr_measured.extend(irregular[:, 1])
        medians = np.asarray(medians)
        ok = np.isfinite(medians)
        rho = float(spearmanr(GRID[ok], medians[ok]).statistic) if ok.sum() >= 3 else 0.
        rhos.append(rho if math.isfinite(rho) else 0.)
        per_domain[domain] = dict(median_hr=[None if not math.isfinite(m) else float(m) for m in medians], spearman=rhos[-1])
    mae_in, mae_out = float(np.mean(errors_in)), float(np.mean(errors_out))
    rho_s, auc_irr = float(np.mean(rhos)), auc(rmssd_sinus, rmssd_irregular)
    auc_term = 0. if math.isnan(auc_irr) else auc_irr
    score = .5*min(mae_in/10, 2)+.25*min(mae_out/10, 2)+.25*(1-rho_s)+.25*(1-auc_term)
    return dict(C=float(score), mae_in=mae_in, mae_ext=mae_out, spearman=rho_s, lock_rate=float(np.mean(locks)),
                nan_rate=float(np.mean(missing)), auc_irr=auc_irr,
                irr_cv_at_sigma_0_2=float(np.nanmedian(irr_measured)) if np.isfinite(irr_measured).any() else None,
                acf_vs_beat_median_abs_bpm=float(np.median(acf_gap)) if acf_gap else None,
                grid_bpm=GRID.tolist(), per_domain=per_domain,
                estimator="relative-prominence beat span rate; NaN counts as 20 bpm error")


class Probe(nn.Module):
    def __init__(self, derivative=True, width=16):
        super().__init__()
        self.derivative = derivative
        channels = 3 if derivative else 1
        self.net = nn.Sequential(nn.Conv1d(channels, width, 7, 2, 3), nn.LeakyReLU(.2),
                                 nn.Conv1d(width, 2*width, 7, 2, 3), nn.LeakyReLU(.2),
                                 nn.Conv1d(2*width, 2*width, 7, 2, 3), nn.LeakyReLU(.2))
        self.head = nn.Linear(2*width, 1)

    def forward(self, x):
        if self.derivative:
            x = torch.cat((x, 10*F.pad(torch.diff(x, dim=-1), (1, 0)), 20*F.pad(torch.diff(x, n=2, dim=-1), (1, 1))), 1)
        return self.head(self.net(x).mean(-1))[:, 0]


def c2st_auc(real_train, fake_train, real_valid, fake_valid, device, derivative=True, width=16, steps=1000, seed=0):
    """Classifier two-sample test: AUC 0.5 means the probe cannot tell real from generated."""
    torch.manual_seed(seed)
    probe = Probe(derivative, width).to(device)
    optimizer = torch.optim.Adam(probe.parameters(), lr=1e-3)
    rng = np.random.default_rng(seed)
    tensor = lambda a: torch.tensor(np.asarray(a, dtype=np.float32)[:, None], device=device)
    real_train, fake_train = tensor(real_train), tensor(fake_train)
    for _ in range(steps):
        r = real_train[rng.integers(len(real_train), size=32)]
        f = fake_train[rng.integers(len(fake_train), size=32)]
        logits = probe(torch.cat((r, f)))
        target = torch.cat((torch.zeros(32, device=device), torch.ones(32, device=device)))
        optimizer.zero_grad(set_to_none=True)
        F.binary_cross_entropy_with_logits(logits, target).backward()
        optimizer.step()
    probe.eval()
    with torch.no_grad():
        real_score = torch.cat([probe(p) for p in tensor(real_valid).split(256)]).cpu().numpy()
        fake_score = torch.cat([probe(p) for p in tensor(fake_valid).split(256)]).cpu().numpy()
    return auc(real_score, fake_score)


def gaussian_reference(rates, view_mask, seed=0):
    """The app's deterministic three-Gaussian shaper at the prompt rates, in the same data view."""
    from models.waveform import PulseShaper, WAVE_PPG
    shaper = PulseShaper()
    rng = np.random.default_rng(seed)
    t = np.arange(LENGTH)/FS
    out = []
    for rate in rates:
        offset = rng.uniform()
        y = np.array([shaper.sample(WAVE_PPG, (offset+s*rate/60) % 1) for s in t])
        y = np.fft.irfft(np.fft.rfft(y-y.mean())*view_mask, n=LENGTH)
        out.append((y-y.min())/max(np.ptp(y), 1e-9))
    return np.asarray(out, dtype=np.float32)
