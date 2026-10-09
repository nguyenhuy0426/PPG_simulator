"""Small independent PPG models; inspired by TCN/WaveGAN and DDPM, not paper replicas."""
import math

import torch
from torch import nn
from torch.nn import functional as F

from ml.kaggle_lsm.train_lsm import LENGTH, make_networks


class Residual(nn.Module):
    def __init__(self, width, dilation):
        super().__init__()
        self.block = nn.Sequential(
            nn.GroupNorm(4, width), nn.SiLU(),
            nn.Conv1d(width, width, 5, padding=2*dilation, dilation=dilation),
            nn.GroupNorm(4, width), nn.SiLU(), nn.Conv1d(width, width, 1))

    def forward(self, x):
        return (x+self.block(x))/math.sqrt(2)


class TCNGenerator(nn.Module):
    def __init__(self):
        super().__init__()
        self.branches = nn.ModuleList([nn.Conv1d(1, 16, k, padding=k//2) for k in (5, 21, 61)])
        self.blocks = nn.Sequential(*[Residual(48, d) for d in (1, 2, 4, 8, 16, 32, 64, 128)])
        self.out = nn.Conv1d(48, 1, 5, padding=2)

    def forward(self, z):
        z = z.reshape(-1, 1, LENGTH)
        y = self.out(self.blocks(torch.cat([b(z) for b in self.branches], 1))).sigmoid()
        return (y-y.amin(-1, keepdim=True))/(y.amax(-1, keepdim=True)-y.amin(-1, keepdim=True)).clamp_min(1e-6)


class ScaleCritic(nn.Module):
    def __init__(self):
        super().__init__()
        layers = []
        prev = 1
        for width in (16, 32, 64, 128):
            layers += [nn.utils.spectral_norm(nn.Conv1d(prev, width, 7, stride=2, padding=3)), nn.LeakyReLU(.2)]
            prev = width
        layers += [nn.utils.spectral_norm(nn.Conv1d(128, 1, 3, padding=1))]
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x).mean((1, 2))


class MultiScaleCritic(nn.Module):
    def __init__(self):
        super().__init__()
        self.scales = nn.ModuleList([ScaleCritic() for _ in range(3)])

    def forward(self, x):
        scores = []
        for net in self.scales:
            scores.append(net(x))
            x = F.avg_pool1d(x, 4, stride=2, padding=1)
        return torch.stack(scores, 1)


def distribution_loss(fake, real):
    """Unpaired spectral/ACF distributions: no pointwise matching of unrelated patients."""
    loss = fake.new_zeros(())
    for size in (160, 400, 800):
        def spectrum(x):
            x = x[:, 0]-x[:, 0].mean(-1, keepdim=True)
            blocks = x.unfold(-1, size, size//2)
            p = torch.fft.rfft(blocks*torch.hann_window(size, device=x.device), dim=-1).abs().square().mean(1)
            p = p/(p.sum(-1, keepdim=True)+1e-8)
            return (p[:, 1:]+1e-6).log()
        a, b = spectrum(fake), spectrum(real)
        # Sorted marginal spectra retain batch diversity instead of only matching the mean.
        loss = loss+F.smooth_l1_loss(a.sort(0).values, b.sort(0).values)/3
    def acf(x):
        x = x[:, 0]-x[:, 0].mean(-1, keepdim=True)
        p = torch.fft.rfft(x, n=2*LENGTH).abs().square()
        a = torch.fft.irfft(p, n=2*LENGTH)[:, :201]
        return a[:, 1:]/a[:, :1].clamp_min(1e-8)
    a, b = acf(fake), acf(real)
    return loss+F.mse_loss(a.sort(0).values, b.sort(0).values)


class Denoiser(nn.Module):
    """Four-resolution 1D U-Net with diffusion-time channels; epsilon prediction."""
    def __init__(self):
        super().__init__()
        self.down = nn.ModuleList()
        previous = 3
        for width in (16, 32, 64, 64):
            self.down.append(nn.Sequential(nn.Conv1d(previous, width, 5, padding=2),
                                            nn.GroupNorm(4, width), nn.SiLU(), Residual(width, 1)))
            previous = width
        self.up = nn.ModuleList([nn.Sequential(nn.Conv1d(a, b, 5, padding=2), Residual(b, 1))
                                 for a, b in ((128, 64), (96, 32), (48, 16))])
        self.out = nn.Conv1d(16, 1, 3, padding=1)

    def forward(self, x, t):
        phase = t[:, None, None].to(x.dtype)*math.pi/100
        h = torch.cat((x, phase.sin().expand_as(x), phase.cos().expand_as(x)), 1)
        skips = []
        for i, block in enumerate(self.down):
            h = block(h)
            skips.append(h)
            if i < 3:
                h = F.avg_pool1d(h, 2)
        for block, skip in zip(self.up, reversed(skips[:-1])):
            h = block(torch.cat((F.interpolate(h, size=skip.shape[-1], mode="linear", align_corners=False), skip), 1))
        return self.out(h)


def alpha_schedule(device):
    t = torch.arange(101, device=device)/100
    a = torch.cos((t+.008)/1.008*math.pi/2).square()
    beta = (1-a[1:]/a[:-1]).clamp(0, .999)
    return torch.cumprod(1-beta, 0)


def diffusion_loss(model, real):
    a = alpha_schedule(real.device)
    t = torch.randint(100, (len(real),), device=real.device)
    alpha = a[t, None, None]
    x = real*2-1
    noise = torch.randn_like(x)
    pred = model(alpha.sqrt()*x+(1-alpha).sqrt()*noise, t)
    return F.mse_loss(pred, noise)


@torch.no_grad()
def generate(model, z, diffusion=False, sample_steps=32):
    if not diffusion:
        return model(z)
    x = z.reshape(-1, 1, LENGTH)
    a = alpha_schedule(x.device)
    steps = torch.linspace(99, 0, sample_steps, device=x.device).long()
    for i, t in enumerate(steps):
        eps = model(x, t.expand(len(x)))
        clean = ((x-(1-a[t]).sqrt()*eps)/a[t].sqrt()).clamp(-1, 1)
        if i+1 < len(steps):
            prev = a[steps[i+1]]
            x = prev.sqrt()*clean+(1-prev).sqrt()*eps
        else:
            x = clean
    y = (x+1)/2
    return (y-y.amin(-1, keepdim=True))/(y.amax(-1, keepdim=True)-y.amin(-1, keepdim=True)).clamp_min(1e-6)


def networks(arm):
    if arm.startswith("lsm"):
        return make_networks()
    if arm == "diffusion_multi":
        return Denoiser(), None
    if arm in ("tcn_multi", "hybrid_multi"):
        return TCNGenerator(), MultiScaleCritic()
    raise ValueError(f"Unknown arm: {arm}")
