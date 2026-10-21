"""Red head (round 13 candidate): the red channel as R x (infrared + a learned residual) on top of an unchanged
infrared generator.

Round 12's diagnosis (docs/physioflow2/REPORT_VI.md): on the v3 view the real red window is the infrared window up
to a small residual (3-6 % of the infrared SD, mostly in the cardiac band), and the two-channel C2ST is set by the
infrared (infrared alone: AUC 0.856; model pair 0.877; infrared copy 0.874). A probe on the residual alone separates
round 12's residual from the real one (AUC 1.0): too much < 0.5 Hz drift, too little 4-8 Hz power while running,
too small while walking. So the head generates only the residual, conditioned on the infrared window, the dataset
and R, and the red window is rebuilt so that ptp(red) = R exactly:

    y = (red / a - ir_c) / (RESIDUAL_SCALE * sd(ir_c)),   a = <red, ir_c> / <ir_c, ir_c>,  ir_c = ir - mean(ir)
    red = R * (s - mean(s)) / ptp(s),                     s = ir_c + RESIDUAL_SCALE * sd(ir_c) * y

The infrared generator (PhysioMix R9 or PhysioFlow F6) is not touched, so every infrared criterion is unchanged.
R is an optical ratio of the recording devices, not an SpO2 label.
"""
import math

import numpy as np
from scipy.signal import welch
import torch
from torch import nn

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain.flow import UNet1D, flow_times, log_psd

HEAD_DOMAINS = ("gxu_finger", "ptt_run", "ptt_sit", "ptt_walk")
HEAD_SLOTS = 8                      # reserved dataset positions, so a new red dataset does not change the input size
RESIDUAL_SCALE = .05                # y has roughly unit SD at the real residual size
BANDS = ((0., .5), (.5, 4.), (4., 8.), (8., 20.))
CHANNELS = (16, 32, 64, 96, 96)


def residual_target(ir, red):
    """ir (n, L) infrared view, red (n, L) red window with ptp R -> (y (n, L), a (n,), valid (n,)).
    valid is False where red is not positively related to the infrared (a <= 0) or the infrared is flat."""
    ir_c = ir-ir.mean(-1, keepdims=True)
    energy = np.sum(ir_c*ir_c, -1)
    sd = ir_c.std(-1)
    valid = (energy > 1e-12) & (sd > 1e-6)
    a = np.where(valid, np.sum((red-red.mean(-1, keepdims=True))*ir_c, -1)/np.maximum(energy, 1e-12), 0.)
    valid &= a > 1e-6
    y = np.where(valid[:, None], ((red-red.mean(-1, keepdims=True))/np.where(valid, a, 1.)[:, None]-ir_c)
                 / (RESIDUAL_SCALE*np.maximum(sd, 1e-6)[:, None]), 0.)
    return y.astype(np.float32), a.astype(np.float32), valid


def compose(ir, y, ratio):
    """Red window (n, L) from infrared (n, L), residual y (n, L) and R (n,); works on numpy arrays and tensors."""
    if isinstance(ir, np.ndarray):
        mean, sd = (lambda x: x.mean(-1, keepdims=True)), (lambda x: x.std(-1, keepdims=True))
        span = lambda x: np.ptp(x, -1, keepdims=True)
    else:
        mean, sd = (lambda x: x.mean(-1, keepdim=True)), (lambda x: x.std(-1, unbiased=False, keepdim=True))
        span = lambda x: x.amax(-1, keepdim=True)-x.amin(-1, keepdim=True)
    ir_c = ir-mean(ir)
    s = ir_c+RESIDUAL_SCALE*sd(ir_c)*y
    s = s-mean(s)
    return ratio[:, None]*s/(span(s)+1e-9)


def ir_features(ir):
    """(n, L) tensor -> (n, 3, L): standardised infrared, its scaled first difference and a ones channel, in the
    three scaffold positions of UNet1D."""
    x = (ir-ir.mean(-1, keepdim=True))/ir.std(-1, keepdim=True).clamp_min(1e-6)
    d = 10*torch.nn.functional.pad(torch.diff(x, dim=-1), (1, 0))
    return torch.stack((x, d, torch.ones_like(x)), 1)


class HeadConditions:
    """[dataset slot one-hot (HEAD_SLOTS), R standardised]. R is standardised with the training windows."""
    def __init__(self, domains, ratios):
        domains = sorted(set(domains))
        if len(domains) > HEAD_SLOTS:
            raise ValueError("More red datasets than reserved slots")
        self.domains = domains
        ratios = np.asarray(ratios, np.float64)
        self.r_center, self.r_scale = float(np.median(ratios)), float(max(np.std(ratios), .02))

    @property
    def size(self):
        return HEAD_SLOTS+1

    def rows(self, domains, ratios):
        out = np.zeros((len(domains), self.size), np.float32)
        for i, (d, r) in enumerate(zip(domains, ratios)):
            if d not in self.domains:
                raise ValueError(f"Red head has no slot for {d}")
            out[i, self.domains.index(d)] = 1
            out[i, HEAD_SLOTS] = (r-self.r_center)/self.r_scale
        return out

    def metadata(self):
        return dict(domains=self.domains, slots=HEAD_SLOTS, r_center=self.r_center, r_scale=self.r_scale,
                    residual_scale=RESIDUAL_SCALE)


def head_loss(net, y, ir, condition, deriv=1., spectral=.1, amplitude=.1):
    """Rectified flow on the residual y (n, L) given the infrared (n, L); first-difference, full-band log-PSD and
    log-SD terms on the x0 estimate, weighted towards low noise."""
    x0 = y[:, None]
    n = len(x0)
    t = flow_times(n, x0.device, "uniform")
    noise = torch.randn_like(x0)
    xt = (1-t[:, None, None])*x0+t[:, None, None]*noise
    ones = torch.ones(n, device=x0.device)
    v = net(xt, t, ir_features(ir), condition, ones)
    loss = (v-(noise-x0)).square().mean()
    estimate = xt-t[:, None, None]*v
    weight = (1-t)**2
    if deriv:
        loss = loss+deriv*(weight*(10*(torch.diff(estimate, dim=-1)-torch.diff(x0, dim=-1))).square().mean((1, 2))).mean()
    if spectral:
        loss = loss+spectral*(weight*(log_psd(estimate)-log_psd(x0)).square().mean(-1)).mean()
    if amplitude:
        log_sd = lambda x: torch.log(x.std(-1).clamp_min(1e-4))[:, 0]
        loss = loss+amplitude*(weight*(log_sd(estimate)-log_sd(x0)).square()).mean()
    return loss


class RedHead(nn.Module):
    """head(z, ir, condition, ratio) -> red (n, L) with ptp R. Fixed-step Heun from t=1 to 0."""
    def __init__(self, cond_size=HEAD_SLOTS+1, sample_steps=8, channels=CHANNELS):
        super().__init__()
        self.net = UNet1D(cond_size, channels)
        self.sample_steps = int(sample_steps)

    def residual(self, z, ir, condition):
        features = ir_features(ir)
        x = z[:, None]
        ones = torch.ones(len(z), device=z.device)
        steps = self.sample_steps
        for i in range(steps):
            t, t_next = 1-i/steps, 1-(i+1)/steps
            v = self.net(x, ones*t, features, condition, ones)
            proposal = x+(t_next-t)*v
            x = x+(t_next-t)*.5*(v+self.net(proposal, ones*t_next, features, condition, ones)) if i < steps-1 \
                else proposal
        return x[:, 0]

    def forward(self, z, ir, condition, ratio):
        return compose(ir, self.residual(z, ir, condition), ratio)


class ColouredResidual:
    """Non-neural baseline: per dataset, Gaussian residual with the median training amplitude spectrum of y and
    random phases (no locking to the infrared beats)."""
    def __init__(self, y, domains):
        self.spectrum = {}
        for d in sorted(set(domains)):
            rows = y[np.asarray(domains) == d]
            self.spectrum[d] = np.median(np.abs(np.fft.rfft(rows-rows.mean(-1, keepdims=True), axis=-1)), 0)

    def sample(self, domains, rng):
        out = np.zeros((len(domains), LENGTH), np.float32)
        for i, d in enumerate(domains):
            amplitude = self.spectrum[d]
            phase = np.exp(2j*math.pi*rng.random(len(amplitude)))
            phase[0] = 0
            out[i] = np.fft.irfft(amplitude*phase, n=LENGTH)
        return out


def band_powers(y):
    """(n, len(BANDS)) Welch power of y in each band (absolute, so the residual size counts)."""
    f, p = welch(y, FS, nperseg=256, axis=-1)
    return np.stack([p[:, (f >= lo) & (f < hi)].sum(-1) for lo, hi in BANDS], 1)


def residual_score(y_gen, y_real, domains_gen, domains_real):
    """Per dataset: |log10| ratio of the median residual SD, plus the mean over BANDS of the |log10| ratio of the
    median band power; the score is the mean over datasets (0 = the real medians)."""
    domains_gen, domains_real = np.asarray(domains_gen), np.asarray(domains_real)
    out = {}
    for d in sorted(set(domains_real)):
        g, r = y_gen[domains_gen == d], y_real[domains_real == d]
        if not len(g):
            continue
        sd = abs(math.log10(max(np.median(g.std(-1)), 1e-6)/max(np.median(r.std(-1)), 1e-6)))
        bands = np.abs(np.log10(np.maximum(np.median(band_powers(g), 0), 1e-12)/np.maximum(np.median(band_powers(r), 0), 1e-12)))
        out[d] = dict(sd=float(sd), bands=bands.tolist(), score=float((sd+bands.mean())/2))
    return float(np.mean([v["score"] for v in out.values()])), out
