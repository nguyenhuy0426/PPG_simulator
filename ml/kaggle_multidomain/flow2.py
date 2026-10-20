"""PhysioFlow-2 (round 11): a paired infrared/red rectified-flow generator on the constructed rhythm scaffold.

Same rhythm scaffold, flow-time distribution, first-difference and stop-band losses as PhysioFlow-SB (F10), with
four changes:
- two output channels: infrared in the v3 view and red relative to it (data_dual), so ptp(red)/ptp(infrared) is the
  ratio of ratios R; datasets without red train the infrared channel alone (masked red loss);
- the condition carries R (with a known flag) before the v2 fields, so the last five entries keep their v2 meaning;
- the dataset code has DOMAIN_SLOTS reserved positions, so a new dataset takes a free slot without changing the
  input size (fine-tuning or retraining with the same architecture);
- two velocity backbones: the PhysioFlow U-Net with two input/output channels, and a one-dimensional diffusion
  transformer (DiT-1D: patches of 8 samples, adaLN-zero conditioning, a zero-initialised convolutional refinement).

The generator keeps the app contract generator(z, condition) with z of shape (n, 1200): the red channel's starting
noise is a fixed permutation of z, and the rhythm noise is read from the far end of z as before. Output (n, 2, 1200):
infrared min-max normalised to [0, 1], red zero-mean on the same scale (its ptp is the generated R).
"""
import math

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain.flow import (BEATS, HZ_RANGE, SPECTRAL_T, UNet1D, constructed_phase, flow_times, log_psd,
                                        scaffold, stop_band_weight)
from ml.kaggle_multidomain.labels import IRR_MAX
from ml.kaggle_multidomain.physio import Conditions

DOMAIN_SLOTS = 16
RATE_KNOWN, R_KNOWN, R_VALUE = -5, -7, -6
PERMUTATION_SEED = 20261021


class DualConditions(Conditions):
    """v2 conditions with DOMAIN_SLOTS dataset positions and the ratio of ratios.

    Layout [slot one-hot (DOMAIN_SLOTS), R_known, R (standardised), rate_known, irregularity_known, rate, irregularity,
    std]. Slots follow the sorted training domains; unused slots stay zero. R is standardised with the training
    windows that have red; windows without red get R_known = 0 and the median training R."""
    def __init__(self, pack):
        super().__init__(pack, "v2")
        if len(self.domains) > DOMAIN_SLOTS:
            raise ValueError("More training domains than reserved slots")
        domain_of = pack["domain"][self.ids]
        onehot = np.zeros((len(self.ids), DOMAIN_SLOTS), np.float32)
        onehot[np.arange(len(self.ids)), [self.domains.index(d) for d in domain_of]] = 1
        known = pack["red_known"][self.ids].astype(bool)
        ratio = pack["ratio_r"][self.ids].astype(np.float64)
        if not known.any():
            raise ValueError("No training window with red")
        self.r_center, self.r_scale = float(np.median(ratio[known])), float(max(np.std(ratio[known]), .02))
        self.r_default = {d: float(np.median(ratio[known & (domain_of == d)])) for d in self.domains
                          if (known & (domain_of == d)).any()}
        r_std = np.where(known, (ratio-self.r_center)/self.r_scale, 0.).astype(np.float32)
        tail = self.bank[:, -5:]
        self.bank = np.c_[onehot, known.astype(np.float32), r_std, tail].astype(np.float32)
        self.red_known = known

    def prompt(self, domain, bpm, sigma, n, ratio=None):
        """App command: chosen domain, rate and irregularity, domain-median std; R if given or the domain median."""
        row = np.zeros(self.bank.shape[1], np.float32)
        row[self.domains.index(domain)] = 1
        if ratio is None:
            ratio = self.r_default.get(domain)
        if ratio is not None:
            row[DOMAIN_SLOTS], row[DOMAIN_SLOTS+1] = 1, (ratio-self.r_center)/self.r_scale
        row[-5:-3] = 1
        raw = np.array([bpm, sigma, self.defaults[domain][1]], dtype=np.float32)
        row[-3:] = (raw-self.center)/self.scale
        return np.repeat(row[None], n, 0)

    def metadata(self):
        result = super().metadata()
        result.update(size=int(self.bank.shape[1]), domain_slots=DOMAIN_SLOTS,
                      layout=[f"slot {i}" for i in range(DOMAIN_SLOTS)]+["R_known", "R", "rate_known",
                                                                        "irregularity_known", "rate", "irregularity",
                                                                        "PPG_signal_std"],
                      r_center=self.r_center, r_scale=self.r_scale, r_default=self.r_default)
        return result


class UNet2(UNet1D):
    """The PhysioFlow U-Net with (infrared, red) in and out next to the three scaffold channels."""
    def __init__(self, cond_size, channels=(32, 64, 128, 160, 160)):
        super().__init__(cond_size, channels)
        self.inp = nn.Conv1d(5, channels[0], 7, padding=3)
        self.out = nn.Conv1d(self.out.in_channels, 2, 3, padding=1)
        nn.init.zeros_(self.out.weight)
        nn.init.zeros_(self.out.bias)


class DiTBlock(nn.Module):
    def __init__(self, width, heads, emb):
        super().__init__()
        self.norm1 = nn.LayerNorm(width, elementwise_affine=False, eps=1e-6)
        self.attn = nn.MultiheadAttention(width, heads, batch_first=True)
        self.norm2 = nn.LayerNorm(width, elementwise_affine=False, eps=1e-6)
        self.mlp = nn.Sequential(nn.Linear(width, 4*width), nn.GELU(approximate="tanh"), nn.Linear(4*width, width))
        self.ada = nn.Linear(emb, 6*width)
        nn.init.zeros_(self.ada.weight)
        nn.init.zeros_(self.ada.bias)

    def forward(self, x, emb):
        shift1, scale1, gate1, shift2, scale2, gate2 = self.ada(F.silu(emb))[:, None].chunk(6, -1)
        h = self.norm1(x)*(1+scale1)+shift1
        x = x+gate1*self.attn(h, h, h, need_weights=False)[0]
        h = self.norm2(x)*(1+scale2)+shift2
        return x+gate2*self.mlp(h)


class DiT1D(nn.Module):
    """Diffusion transformer over 150 patches of 8 samples (0.2 s): the 30 s window is one sequence, so every patch
    attends to every beat. Conditioning by adaLN-zero from flow-time and condition embeddings; a zero-initialised
    two-layer convolution on the unpatchified output smooths patch boundaries and adds sub-patch texture."""
    def __init__(self, cond_size, width=256, depth=8, heads=8, patch=8, emb=256):
        super().__init__()
        self.patch, self.tokens = patch, LENGTH//patch
        self.register_buffer("freqs", torch.exp(-math.log(1e4)*torch.arange(64, dtype=torch.float32)/64))
        self.time_mlp = nn.Sequential(nn.Linear(128, emb), nn.SiLU(), nn.Linear(emb, emb))
        self.cond_mlp = nn.Sequential(nn.Linear(cond_size+1, emb), nn.SiLU(), nn.Linear(emb, emb))
        self.embed = nn.Conv1d(5, width, patch, stride=patch)
        self.position = nn.Parameter(torch.zeros(1, self.tokens, width))
        nn.init.normal_(self.position, std=.02)
        self.blocks = nn.ModuleList([DiTBlock(width, heads, emb) for _ in range(depth)])
        self.final_norm = nn.LayerNorm(width, elementwise_affine=False, eps=1e-6)
        self.final_ada = nn.Linear(emb, 2*width)
        self.final = nn.Linear(width, 2*patch)
        for layer in (self.final_ada, self.final):
            nn.init.zeros_(layer.weight)
            nn.init.zeros_(layer.bias)
        self.refine = nn.Sequential(nn.Conv1d(7, 32, 7, padding=3), nn.SiLU(), nn.Conv1d(32, 2, 7, padding=3))
        nn.init.zeros_(self.refine[2].weight)
        nn.init.zeros_(self.refine[2].bias)

    def forward(self, x, t, scaffold3, condition, cond_flag):
        angle = t[:, None]*1000*self.freqs[None]
        emb = self.time_mlp(torch.cat((angle.sin(), angle.cos()), 1))
        emb = emb+self.cond_mlp(torch.cat((condition*cond_flag[:, None], cond_flag[:, None]), 1))
        inp = torch.cat((x, scaffold3), 1)
        h = self.embed(inp).transpose(1, 2)+self.position
        for block in self.blocks:
            h = block(h, emb)
        shift, scale = self.final_ada(F.silu(emb))[:, None].chunk(2, -1)
        h = self.final(self.final_norm(h)*(1+scale)+shift)                    # (n, tokens, 2*patch)
        v = h.reshape(-1, self.tokens, 2, self.patch).permute(0, 2, 1, 3).reshape(-1, 2, LENGTH)
        return v+self.refine(torch.cat((v, inp), 1))


def joint_standardize(ir, red, red_known):
    """Both channels on the infrared scale: zero-mean, unit-SD infrared; red divided by the same SD (zero if unknown)."""
    mean, sd = ir.mean(-1, keepdim=True), ir.std(-1, keepdim=True).clamp_min(1e-6)
    return (ir-mean)/sd, red*red_known[:, None, None].to(red.dtype)/sd


def dual_flow_loss(net, ir, red, red_known, phase, present, condition, cond_drop=.1, scaffold_drop=.15, deriv=1.,
                   spectral=.1, t_dist="uniform"):
    """Rectified flow on (infrared, red) with F10's terms on each channel; red terms only where red is known.
    ir, red: (n, 1, L). The per-channel means are taken over the batch rows that carry the channel."""
    x0_ir, x0_red = joint_standardize(ir, red, red_known)
    x0 = torch.cat((x0_ir, x0_red), 1)
    n = len(x0)
    t = flow_times(n, x0.device, t_dist)
    noise = torch.randn_like(x0)
    xt = (1-t[:, None, None])*x0+t[:, None, None]*noise
    keep = (torch.rand(n, device=x0.device) >= cond_drop).to(x0.dtype)
    present = present & (torch.rand(n, device=x0.device) >= scaffold_drop)
    v = net(xt, t, scaffold(phase, present), condition, keep)
    mask = torch.stack((torch.ones_like(red_known, dtype=x0.dtype), red_known.to(x0.dtype)), 1)     # (n, 2)
    rows = mask.sum(0).clamp_min(1)

    def per_channel(value):                                  # value (n, 2): mean over rows carrying the channel
        return ((value*mask).sum(0)/rows).sum()
    loss = per_channel((v-(noise-x0)).square().mean(-1))
    estimate = xt-t[:, None, None]*v
    if deriv:
        weight = (1-t)[:, None]**2
        error = (10*(torch.diff(estimate, dim=-1)-torch.diff(x0, dim=-1))).square().mean(-1)
        loss = loss+deriv*per_channel(weight*error)
    if spectral:
        weight = (1-t/SPECTRAL_T).clamp_min(0)[:, None]
        bins = stop_band_weight().to(x0.device)
        error = torch.stack([((log_psd(estimate[:, c:c+1])-log_psd(x0[:, c:c+1])).square()*bins).sum(-1)/bins.sum()
                             for c in range(2)], 1)
        loss = loss+spectral*per_channel(weight*error)
    return loss


def dual_phase(z, condition, center, scale, time):
    raw = condition[:, -3:]*scale+center
    hz = (raw[:, 0]/60).clamp(*HZ_RANGE)
    return constructed_phase(z, hz, raw[:, 1].clamp(0, IRR_MAX), time)


def normalise_pair(x):
    """(n, 2, L) -> infrared min-max to [0, 1]; red minus its mean, divided by the infrared range."""
    ir, red = x[:, :1], x[:, 1:]
    lo, hi = ir.amin(-1, keepdim=True), ir.amax(-1, keepdim=True)
    span = (hi-lo).clamp_min(1e-6)
    return torch.cat(((ir-lo)/span, (red-red.mean(-1, keepdim=True))/span), 1)


class DualFlowGenerator(nn.Module):
    """generator(z, condition) -> (n, 2, LENGTH). Fixed-step Heun from t=1 to 0, no guidance, flag-gated scaffold."""
    def __init__(self, size, center, scale, backbone="unet", sample_steps=16):
        super().__init__()
        self.net = UNet2(size) if backbone == "unet" else DiT1D(size)
        self.backbone, self.sample_steps = backbone, int(sample_steps)
        self.register_buffer("center", torch.tensor(center, dtype=torch.float32))
        self.register_buffer("scale", torch.tensor(scale, dtype=torch.float32))
        self.register_buffer("time", torch.arange(LENGTH, dtype=torch.float32)/FS)
        permutation = np.random.default_rng(PERMUTATION_SEED).permutation(LENGTH)
        self.register_buffer("permutation", torch.tensor(permutation, dtype=torch.long))

    def scaffold_of(self, z, condition):
        phase = dual_phase(z, condition, self.center, self.scale, self.time)
        return scaffold(phase, condition[:, RATE_KNOWN] > .5)

    def start(self, z):
        return torch.stack((z, z[:, self.permutation]), 1)

    def forward(self, z, condition):
        s = self.scaffold_of(z, condition)
        x = self.start(z)
        steps = self.sample_steps
        ones = torch.ones(len(z), device=z.device)
        for i in range(steps):
            t, t_next = 1-i/steps, 1-(i+1)/steps
            v = self.net(x, ones*t, s, condition, ones)
            proposal = x+(t_next-t)*v
            if i < steps-1:
                x = x+(t_next-t)*.5*(v+self.net(proposal, ones*t_next, s, condition, ones))
            else:
                x = proposal
        return normalise_pair(x)

    def export(self, z, condition):
        net = self.net.eval()
        n = len(z)
        example = (self.start(z), torch.full((n,), .5), self.scaffold_of(z, condition), condition, torch.ones(n))
        return torch.jit.script(DualSampler(torch.jit.trace(net, example, check_trace=False), self.center, self.scale,
                                            self.time, self.permutation, self.sample_steps))


class DualSampler(nn.Module):
    """Scriptable twin of DualFlowGenerator.forward around a traced velocity network."""
    def __init__(self, net, center, scale, time, permutation, sample_steps: int):
        super().__init__()
        self.net = net
        for name, value in (("center", center), ("scale", scale), ("time", time), ("permutation", permutation)):
            self.register_buffer(name, value.clone())
        self.sample_steps = sample_steps
        self.hz_lo, self.hz_hi, self.irr_max, self.beats = HZ_RANGE[0], HZ_RANGE[1], IRR_MAX, BEATS
        self.rate_known = RATE_KNOWN

    def forward(self, z, condition):
        raw = condition[:, -3:]*self.scale+self.center
        hz = (raw[:, 0]/60).clamp(self.hz_lo, self.hz_hi)
        sigma = raw[:, 1].clamp(0., self.irr_max)
        u = z.flip(1)
        ibi = torch.exp(sigma[:, None]*u[:, :self.beats]-.5*sigma[:, None]**2)/hz[:, None]
        first = -ibi[:, :1]*torch.sigmoid(u[:, self.beats:self.beats+1])
        peaks = first+torch.cumsum(ibi, 1)-ibi
        index = ((peaks[:, :, None] <= self.time[None, None]).sum(1)-1).clamp(0, self.beats-1)
        phase = index.to(z.dtype)+(self.time[None]-peaks.gather(1, index))/ibi.gather(1, index)
        flag = (condition[:, self.rate_known] > .5).to(z.dtype)[:, None]
        angle = 2*math.pi*phase
        s = torch.stack((angle.sin()*flag, angle.cos()*flag, flag.expand_as(phase)), 1)
        x = torch.stack((z, z[:, self.permutation]), 1)
        ones = torch.ones(z.shape[0], device=z.device)
        steps = self.sample_steps
        for i in range(steps):
            t, t_next = 1.-i/steps, 1.-(i+1)/steps
            v = self.net(x, ones*t, s, condition, ones)
            proposal = x+(t_next-t)*v
            if i < steps-1:
                x = x+(t_next-t)*.5*(v+self.net(proposal, ones*t_next, s, condition, ones))
            else:
                x = proposal
        ir, red = x[:, :1], x[:, 1:]
        lo, hi = ir.amin(-1, keepdim=True), ir.amax(-1, keepdim=True)
        span = (hi-lo).clamp_min(1e-6)
        return torch.cat(((ir-lo)/span, (red-red.mean(-1, keepdim=True))/span), 1)


class InfraredView(nn.Module):
    """The infrared channel only, (n, 1, L), so every single-channel evaluation applies unchanged."""
    def __init__(self, generator):
        super().__init__()
        self.generator = generator

    def forward(self, z, condition):
        return self.generator(z, condition)[:, :1]
