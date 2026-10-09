"""PhysioMix: periodic prior + conditioned multiscale GAN; conditional clean-sample diffusion."""
import copy
import math

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain.benchmark import morphology
from ml.kaggle_multidomain.data import balanced_indices
from ml.kaggle_multidomain.models import Denoiser, Residual, ScaleCritic, alpha_schedule


class Conditions:
    """Only training signals fit scales and supply all unconditional sampling prompts."""
    def __init__(self, pack):
        self.pack = pack
        self.domains = sorted(set(pack["domain"][pack["split"] == "train"]))
        ids = np.flatnonzero(pack["split"] == "train")
        self.raw = morphology(pack["signal"][ids])[:, [0, 1, 4]].astype(np.float32)
        self.ids = ids
        self.center = self.raw.mean(0)
        self.scale = np.maximum(self.raw.std(0), np.array([5, .02, .01], dtype=np.float32))
        onehot = np.eye(len(self.domains), dtype=np.float32)[
            [self.domains.index(d) for d in pack["domain"][ids]]]
        self.bank = np.c_[onehot, (self.raw-self.center)/self.scale].astype(np.float32)
        self.lookup = {int(index): i for i, index in enumerate(ids)}

    def for_ids(self, ids):
        try:
            return self.bank[[self.lookup[int(index)] for index in ids]]
        except KeyError as error:
            raise ValueError("Condition bank is training-only") from error

    def draw(self, seed, n):
        ids = balanced_indices(self.pack, "train", np.random.default_rng(seed), n)
        return self.for_ids(ids)

    def metadata(self):
        return dict(domains=self.domains, size=self.bank.shape[1], center=self.center.tolist(),
                    scale=self.scale.tolist(), features=["PPG_peak_rate_bpm", "PPG_ibi_cv", "PPG_signal_std"],
                    label_type="PPG-derived proxies; not ECG ground truth, SpO2, or clinical diagnoses",
                    sampling="domain/patient-balanced training-only condition bank; never test prompts",
                    training_ranges=np.c_[self.raw.min(0), self.raw.max(0)].tolist())


def bandlimit(x):
    """Match the shared filtered target view; it does not reproduce raw motion/optical DC."""
    freq = torch.fft.rfftfreq(LENGTH, 1/FS, device=x.device)
    mask = (freq >= .9) & (freq <= 5)
    y = torch.fft.irfft(torch.fft.rfft(x, dim=-1)*mask, n=LENGTH, dim=-1)
    return (y-y.amin(-1, keepdim=True))/(y.amax(-1, keepdim=True)-y.amin(-1, keepdim=True)).clamp_min(1e-6)


def descriptors(x):
    """Differentiable joint waveform descriptors: random phase alone does not count as diversity."""
    x = x[:, 0]
    centered = x-x.mean(-1, keepdim=True)
    std = centered.square().mean(-1).add(1e-6).sqrt()
    power = torch.fft.rfft(centered).abs().square()
    power = power/(power.sum(-1, keepdim=True)+1e-8)
    freq = torch.fft.rfftfreq(LENGTH, 1/FS, device=x.device)
    acf = torch.fft.irfft(torch.fft.rfft(centered, n=2*LENGTH).abs().square(), n=2*LENGTH)
    acf = acf[:, 1:201:8]/acf[:, :1].clamp_min(1e-6)
    moments = torch.stack((std, (centered/std[:, None]).pow(3).mean(-1),
                           (centered/std[:, None]).pow(4).mean(-1)/10,
                           torch.diff(x).abs().mean(-1)*10,
                           torch.diff(x, n=2).abs().mean(-1)*20), 1)
    bands = torch.stack([power[:, (freq >= lo) & (freq < hi)].sum(-1)
                         for lo, hi in ((.9, 1.5), (1.5, 2.2), (2.2, 3), (3, 4), (4, 5.01), (5.01, 20.01))], 1)
    return torch.cat((moments, bands, acf), 1)


def joint_loss(fake, real):
    """Joint MMD plus covariance matching prevents a mean-only distribution objective."""
    a, b = descriptors(fake), descriptors(real)
    center, scale = b.mean(0).detach(), b.std(0, unbiased=False).detach().clamp_min(.05)
    a, b = (a-center)/scale, (b-center)/scale
    distance = torch.cdist(b, b).square().detach()
    bandwidth = distance[~torch.eye(len(b), dtype=torch.bool, device=b.device)].median().clamp_min(1)
    aa, bb, ab = torch.cdist(a, a).square(), distance, torch.cdist(a, b).square()
    mmd = sum(((-aa/(bandwidth*w)).exp().mean()+(-bb/(bandwidth*w)).exp().mean()
               -2*(-ab/(bandwidth*w)).exp().mean()) for w in (.5, 1, 2))/3
    covariance = lambda v: (v-v.mean(0)).T@(v-v.mean(0))/max(1, len(v)-1)
    return mmd+.05*F.smooth_l1_loss(covariance(a), covariance(b))


class PhysioMix(nn.Module):
    def __init__(self, size, center, scale):
        super().__init__()
        self.register_buffer("center", torch.tensor(center, dtype=torch.float32))
        self.register_buffer("scale", torch.tensor(scale, dtype=torch.float32))
        self.style = nn.Sequential(nn.Linear(8+size, 48), nn.SiLU(), nn.Linear(48, 48))
        self.branches = nn.ModuleList([nn.Conv1d(5, 16, k, padding=k//2) for k in (5, 21, 61)])
        self.blocks = nn.ModuleList([Residual(48, d) for d in (1, 2, 4, 8, 16, 32, 64, 128)])
        self.film = nn.ModuleList([nn.Linear(48, 96) for _ in self.blocks])
        self.out = nn.Conv1d(48, 1, 5, padding=2)
        nn.init.normal_(self.out.weight, std=.01)
        nn.init.zeros_(self.out.bias)

    def forward(self, z, condition):
        raw = condition[:, -3:]*self.scale+self.center
        hz = (raw[:, 0]/60).clamp(.9, 3.3)
        time = torch.arange(LENGTH, device=z.device, dtype=z.dtype)/FS
        slow = F.interpolate(z[:, None, :32], size=LENGTH, mode="linear", align_corners=False)[:, 0]
        phase = 2*math.pi*hz[:, None]*time+z[:, :1]*math.pi+raw[:, 1:2].clamp(0, .6)*slow
        carrier = torch.stack([phase.sin(), phase.cos(), (2*phase).sin(), (3*phase).sin()], 1)
        style = self.style(torch.cat((z[:, :8], condition), 1))
        h = torch.cat([branch(torch.cat((z[:, None], carrier), 1)) for branch in self.branches], 1)
        for block, film in zip(self.blocks, self.film):
            gain, bias = film(style).chunk(2, 1)
            h = block(h)*(1+.1*gain[:, :, None])+.1*bias[:, :, None]
        return bandlimit(carrier[:, :1]+.3*carrier[:, 2:3]+self.out(h))


class ConditionedCritic(nn.Module):
    def __init__(self, size):
        super().__init__()
        self.scales = nn.ModuleList([ScaleCritic() for _ in range(3)])
        self.projections = nn.ModuleList([nn.utils.spectral_norm(nn.Linear(size, 128)) for _ in range(3)])

    def forward(self, x, condition):
        values = []
        for net, projection in zip(self.scales, self.projections):
            h = net.net[:-1](x)
            values.append(net.net[-1](h).mean((1, 2))+
                          (h.mean(-1)*projection(condition)).sum(1)/math.sqrt(128))
            x = F.avg_pool1d(x, 4, stride=2, padding=1)
        return torch.stack(values, 1)


class CleanDenoiser(Denoiser):
    def __init__(self, size):
        super().__init__()
        self.down[0][0] = nn.Conv1d(3+size, 16, 5, padding=2)

    def forward(self, x, t, condition):
        phase = t[:, None, None].to(x.dtype)*math.pi/100
        h = torch.cat((x, phase.sin().expand_as(x), phase.cos().expand_as(x),
                       condition[:, :, None].expand(-1, -1, LENGTH)), 1)
        skips = []
        for i, block in enumerate(self.down):
            h = block(h)
            skips.append(h)
            if i < 3:
                h = F.avg_pool1d(h, 2)
        for block, skip in zip(self.up, reversed(skips[:-1])):
            h = block(torch.cat((F.interpolate(h, size=skip.shape[-1], mode="linear", align_corners=False), skip), 1))
        return self.out(h).tanh()


def clean_diffusion_loss(model, real, condition, regularized=True):
    t = torch.randint(100, (len(real),), device=real.device)
    a = alpha_schedule(real.device)[t, None, None]
    target = 2*real-1
    noisy = a.sqrt()*target+(1-a).sqrt()*torch.randn_like(real)
    cond = condition*(torch.rand(len(real), 1, device=real.device) > .1)
    clean = model(noisy, t, cond)
    # Min-SNR weighting for clean prediction caps the dominance of near-clean timesteps.
    weight = (a/(1-a)).clamp(max=5)
    loss = ((clean-target).square()*weight).mean()
    if regularized:
        early = t < 60
        if early.sum() >= 2:
            loss = loss+.1*joint_loss(bandlimit(clean[early]), real[early])
    return loss


@torch.no_grad()
def draw(model, z, condition, diffusion=False, guidance=1., sample_steps=32):
    if not diffusion:
        return model(z, condition)
    x = z[:, None]
    a = alpha_schedule(x.device)
    steps = torch.linspace(99, 0, sample_steps, device=x.device).long()
    for i, t in enumerate(steps):
        clean = model(x, t.expand(len(x)), condition)
        if guidance != 1:
            unconditioned = model(x, t.expand(len(x)), torch.zeros_like(condition))
            clean = (unconditioned+guidance*(clean-unconditioned)).clamp(-1, 1)
        eps = (x-a[t].sqrt()*clean)/(1-a[t]).sqrt().clamp_min(1e-6)
        x = (a[steps[i+1]].sqrt()*clean+(1-a[steps[i+1]]).sqrt()*eps
             if i+1 < len(steps) else clean)
    return bandlimit(x)


def ema_model(model):
    result = copy.deepcopy(model).eval()
    result.requires_grad_(False)
    return result


@torch.no_grad()
def update_ema(ema, model, decay=.995):
    for dst, src in zip(ema.parameters(), model.parameters()):
        dst.lerp_(src, 1-decay)
    for dst, src in zip(ema.buffers(), model.buffers()):
        dst.copy_(src)
