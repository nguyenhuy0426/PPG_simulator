"""LSM-GAN-S: an architectural revision of the LSM-GAN author topology (unconditional, one dataset), v3 view.

Kept from LSM-GAN (Ding et al., arXiv 2108.05272): parallel 5/21/61-sample convolutions over noise as the generator's
front end and the log-spectral matching loss (all pairs, plus within-window consistency, as in train_lsm's
lsm_repo_corrected). Changed, each a known remedy for a weakness measured in this project (the app's LSM-GAN covers
~2% of real BIDMC morphology and a C2ST probe separates it completely):
- generator: a dilated residual trunk (receptive field ~25 s) modulated by a global style vector (FiLM), so one
  window's beat shape and rhythm stay coherent while the style varies across windows; output band-limited to the
  v3 view on a padded span and cropped (no circular-filter artefact), min-max normalised;
- critic: strict_judge.StrictCritic (the strict judge's time, spectral and autocorrelation views, spectral-normalised;
  ~0.87 M parameters vs the author's sigmoid D) with a minibatch-std feature against mode collapse (the strict judge
  measured the app's LSM-GAN at 10-25% of real between-window spread on every beat feature) and random 25.6 s crops
  of real and generated windows alike;
- objective: hinge loss, lazy R1 on real windows, Adam(0, 0.99), generator EMA, plus models.distribution_loss
  (sorted spectra/ACF across the batch, which rewards diversity).
Checkpoints are chosen on validation MMD (ACF + log-PSD), as lsm_multiset.train_gan does for the author topology.
"""
import json

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ml.kaggle_lsm.lsm_multiset import bandwidths, generate
from ml.kaggle_lsm.train_lsm import LENGTH, prepare_discriminator_for_generator, score, spectral_loss
from ml.kaggle_multidomain.models import Residual, distribution_loss
from ml.kaggle_multidomain.physio import CROP_PAD, ema_model, update_ema, view_mask
from ml.kaggle_multidomain.strict_judge import StrictCritic

STRICT = dict(steps=8000, batch=64, lr=2e-4, every=250, r1=1., r1_every=16, clip=100.)


class LsmStrictGenerator(nn.Module):
    def __init__(self, width=64, pad=CROP_PAD, view="v3", style=16):
        super().__init__()
        self.pad, self.style_size = pad, style
        self.style = nn.Sequential(nn.Linear(style, width), nn.SiLU(), nn.Linear(width, width))
        self.branches = nn.ModuleList([nn.Conv1d(1, c, k, padding=k//2)
                                       for k, c in ((5, width//2), (21, width//4), (61, width//4))])
        self.blocks = nn.ModuleList([Residual(width, d) for d in (1, 2, 4, 8, 16, 32, 64, 128)])
        self.film = nn.ModuleList([nn.Linear(width, 2*width) for _ in self.blocks])
        self.out = nn.Conv1d(width, 1, 5, padding=2)
        self.register_buffer("band_long", torch.tensor(view_mask(view, LENGTH+2*pad)))

    def forward(self, z):
        z = z.reshape(-1, LENGTH)
        style = self.style(z[:, :self.style_size])
        noise = torch.cat((z[:, :self.pad].flip(1), z, z[:, LENGTH-self.pad:].flip(1)), 1)[:, None]
        h = torch.cat([branch(noise) for branch in self.branches], 1)
        for block, film in zip(self.blocks, self.film):
            gain, bias = film(style).chunk(2, 1)
            h = block(h)*(1+.1*gain[:, :, None])+.1*bias[:, :, None]
        y = self.out(h)
        y = torch.fft.irfft(torch.fft.rfft(y, dim=-1)*self.band_long, n=y.shape[-1], dim=-1)[..., self.pad:self.pad+LENGTH]
        return (y-y.amin(-1, keepdim=True))/(y.amax(-1, keepdim=True)-y.amin(-1, keepdim=True)).clamp_min(1e-6)


def train_strict(train, valid, seed, device, recipe=None, log=print):
    """One LSM-GAN-S generator; returns (EMA generator in eval mode on CPU, history, best validation row)."""
    r = dict(STRICT, **(recipe or {}))
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    g, d = LsmStrictGenerator().to(device), StrictCritic(minibatch_std=True).to(device)
    ema = ema_model(g)
    optg = torch.optim.Adam(g.parameters(), lr=r["lr"], betas=(0., .99))
    optd = torch.optim.Adam(d.parameters(), lr=r["lr"], betas=(0., .99))
    x = torch.tensor(np.asarray(train, np.float32)[:, None], device=device)
    widths = bandwidths(train)
    history, best, best_state = [], None, None
    stability = dict(d_clipped=0, g_clipped=0, r1_updates=0)
    for step in range(1, r["steps"]+1):
        real = x[torch.as_tensor(rng.integers(0, len(x), r["batch"]), device=device)]
        fake = g(torch.randn(r["batch"], LENGTH, device=device))
        d.train().requires_grad_(True)
        optd.zero_grad(set_to_none=True)
        regularize = step % r["r1_every"] == 0
        real.requires_grad_(regularize)
        pr = d(real)
        ld = F.relu(1-pr).mean()+F.relu(1+d(fake.detach())).mean()
        if regularize:
            grad = torch.autograd.grad(pr.mean(1).sum(), real, create_graph=True)[0]
            ld = ld+.5*r["r1_every"]*r["r1"]*grad.square().flatten(1).sum(1).mean()
            stability["r1_updates"] += 1
        ld.backward()
        # Lazy R1 multiplies its gradient by the interval; the clip limit scales with it on those steps.
        limit = r["clip"]*(r["r1_every"] if regularize else 1)
        stability["d_clipped"] += int(nn.utils.clip_grad_norm_(d.parameters(), limit, error_if_nonfinite=True) > limit)
        optd.step()
        real = real.detach()
        prepare_discriminator_for_generator(d)
        optg.zero_grad(set_to_none=True)
        matching, consistency = spectral_loss(fake, real, pairing="all_pairs")
        lg = -d(fake).mean()+matching+consistency+.5*distribution_loss(fake, real)
        if not torch.isfinite(lg+ld):
            raise RuntimeError(f"Nonfinite loss at step {step}")
        lg.backward()
        stability["g_clipped"] += int(nn.utils.clip_grad_norm_(g.parameters(), 10., error_if_nonfinite=True) > 10)
        optg.step()
        update_ema(ema, g)
        if step % r["every"] == 0 or step == r["steps"]:
            val = score(generate(ema, len(valid), seed+7, device), valid, widths)
            row = dict(step=step, d_loss=float(ld.detach()), g_loss=float(lg.detach()), validation=val,
                       selection=val["acf_mmd2"]+val["log_psd_mmd2"], **stability)
            history.append(row)
            if best is None or row["selection"] < best["selection"]:
                best, best_state = row, {k: v.detach().cpu().clone() for k, v in ema.state_dict().items()}
    ema.load_state_dict(best_state)
    log(json.dumps(dict(arm="lsm_strict", seed=seed, steps=r["steps"], best_step=best["step"],
                        best_selection=best["selection"], **stability)))
    return ema.cpu().eval(), history, best
