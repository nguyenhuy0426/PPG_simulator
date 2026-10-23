"""PhysioMix: periodic prior + conditioned multiscale GAN; conditional clean-sample diffusion."""
import copy
import math

from collections import Counter

import numpy as np
from scipy.signal import butter, sosfreqz
import torch
from torch import nn
from torch.nn import functional as F

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain.benchmark import morphology
from ml.kaggle_multidomain.data import balanced_indices
from ml.kaggle_multidomain.labels import IRR_MAX, robust_labels
from ml.kaggle_multidomain.models import Denoiser, Residual, ScaleCritic, alpha_schedule
from ml.kaggle_multidomain.view import VIEWS

# Carrier range per data view: v1's 0.9 Hz FIR edge cannot represent slower fundamentals.
HZ_RANGE = {"v1": (.9, 3.3), "v3": (.6, 3.3)}
FLOORS = np.array([5, .02, .01], dtype=np.float32)
# A domain needs this many known labels per field; below it labelling is treated as broken.
# Motion-dominated wrist exercise legitimately masks most windows (ECG disagrees with PPG periodicity).
MIN_KNOWN_WINDOWS, MIN_KNOWN_FRACTION = 5, .05
# Fraction of a mean beat (upstroke and systolic peak) whose absolute duration is kept when an IBI
# deviates from the mean; only the remainder, diastole, stretches or compresses.
SYSTOLE = .35
# Samples generated on each side of the window before band-limiting, then cropped. Real windows are cut
# from records filtered as a whole, so their ends do not meet; a circularly band-limited window does,
# and that alone lets a probe separate real windows from their own circularly filtered copies.
CROP_PAD = 6*FS
# Motion oscillator band (Hz): arm swing, step and pedal cadences. Real wrist-exercise windows have a
# concentrated spectrum (median spectral entropy 0.72, ACF peak 0.52) that beat-to-beat irregularity
# alone cannot produce (round 7: 0.82, 0.24). The starting amplitude logit leaves other domains near unchanged.
MOTION_HZ, MOTION_HARMONICS, MOTION_MAX, MOTION_INIT = (.5, 3.5), 3, 1.5, -3.
# Strict round, quiet arm: the trunk's noise channel is a 9-sample moving average (first null 4.4 Hz, gain 3 keeps unit
# variance), because the strict judge read the free residual's white-noise texture (zeroing the residual of the shipped
# model alone moved its AUC from 0.9995 to 0.948); measurement noise is instead an explicit white term before the
# data-view filter, level SENSOR_MAX*sigmoid(.) per condition (initial ~0.02 of a +-1 pulse).
QUIET_KERNEL, SENSOR_MAX, SENSOR_INIT = 9, .1, -1.4


def view_mask(view, n=LENGTH):
    """Zero-phase magnitude |H|^2 of the data view on the rFFT grid of an n-sample signal."""
    freq = np.fft.rfftfreq(n, 1/FS)
    if view == "v1":
        return ((freq >= .9) & (freq <= 5)).astype(np.float32)
    spec = VIEWS[view]
    sos = butter(spec["order"], [spec["low"], spec["high"]], "bandpass", fs=FS, output="sos")
    return (np.abs(sosfreqz(sos, worN=freq, fs=FS)[1])**2).astype(np.float32)


class Conditions:
    """Only training signals fit scales and supply all unconditional sampling prompts.

    v1: [domain one-hot, peak-count rate, proxy IBI CV, std] (frozen PhysioMix v1 layout).
    v2: [domain one-hot, rate known, irregularity known, rate, irregularity, std] with robust
    consensus/ECG-gated labels; unknown values are imputed from the same domain's known pool.
    """
    def __init__(self, pack, version="v1"):
        if version not in ("v1", "v2"):
            raise ValueError("Unknown condition version")
        self.pack, self.version = pack, version
        self.domains = sorted(set(pack["domain"][pack["split"] == "train"]))
        ids = np.flatnonzero(pack["split"] == "train")
        self.ids = ids
        domain_of = pack["domain"][ids]
        onehot = np.eye(len(self.domains), dtype=np.float32)[[self.domains.index(d) for d in domain_of]]
        if version == "v1":
            self.raw = morphology(pack["signal"][ids])[:, [0, 1, 4]].astype(np.float32)
            self.known = np.ones((len(ids), 2), dtype=np.float32)
            self.center = self.raw.mean(0)
            self.scale = np.maximum(self.raw.std(0), FLOORS)
            self.bank = np.c_[onehot, (self.raw-self.center)/self.scale].astype(np.float32)
        else:
            self._fit_v2(pack, ids, domain_of, onehot)
        self.lookup = {int(index): i for i, index in enumerate(ids)}
        self.defaults = {d: [float(np.median(self.raw[(domain_of == d) & (self.known[:, 1] > 0), 1]
                                             if ((domain_of == d) & (self.known[:, 1] > 0)).any() else self.raw[domain_of == d, 1])),
                             float(np.median(self.raw[domain_of == d, 2]))] for d in self.domains}

    def _fit_v2(self, pack, ids, domain_of, onehot):
        signal = pack["signal"][ids]
        ecg = pack["reference_hr_bpm"][ids] if "reference_hr_bpm" in pack else None
        rate, irr, source = robust_labels(signal, ecg)
        ppg_only, _, _ = robust_labels(signal) if ecg is not None else (rate, None, None)
        known = np.c_[np.isfinite(rate), np.isfinite(irr)].astype(np.float32)
        raw = np.c_[rate, irr, signal.std(1)].astype(np.float64)
        rng = np.random.default_rng(20261010)
        self.coverage, self.label_source, self.label_error = {}, {}, {}
        for d in self.domains:
            rows = domain_of == d
            self.coverage[d] = dict(rate=float(known[rows, 0].mean()), irregularity=float(known[rows, 1].mean()))
            self.label_source[d] = dict(Counter(source[rows]))
            counts = known[rows].sum(0)
            if np.any(counts < max(MIN_KNOWN_WINDOWS, MIN_KNOWN_FRACTION*rows.sum())):
                raise ValueError(f"Condition label coverage too low in {d}: {self.coverage[d]}")
            self.coverage[d]["low"] = bool(min(self.coverage[d]["rate"], self.coverage[d]["irregularity"]) < .2)
            for k in (0, 1):
                missing = rows & (known[:, k] == 0)
                raw[missing, k] = rng.choice(raw[rows & (known[:, k] > 0), k], missing.sum())
            if ecg is not None and np.isfinite(ecg[rows]).any():
                both = rows & np.isfinite(ecg) & np.isfinite(ppg_only)
                self.label_error[d] = dict(windows=int(both.sum()), median_abs_bpm=float(np.median(np.abs(ppg_only[both]-ecg[both])))
                                           if both.any() else None)
        self.raw = raw.astype(np.float32)
        self.known = known
        self.center = np.array([raw[known[:, 0] > 0, 0].mean(), raw[known[:, 1] > 0, 1].mean(), raw[:, 2].mean()],
                               dtype=np.float32)
        self.scale = np.maximum(np.array([raw[known[:, 0] > 0, 0].std(), raw[known[:, 1] > 0, 1].std(),
                                          raw[:, 2].std()], dtype=np.float32), FLOORS)
        self.bank = np.c_[onehot, known, (self.raw-self.center)/self.scale].astype(np.float32)

    def prompt(self, domain, bpm, sigma, n):
        """Clean command for the simulator: chosen domain, rate and irregularity, domain-median std."""
        row = np.zeros(self.bank.shape[1], dtype=np.float32)
        row[self.domains.index(domain)] = 1
        if self.version == "v2":
            row[len(self.domains):len(self.domains)+2] = 1
        raw = np.array([bpm, sigma, self.defaults[domain][1]], dtype=np.float32)
        row[-3:] = (raw-self.center)/self.scale
        return np.repeat(row[None], n, 0)

    def for_ids(self, ids):
        try:
            return self.bank[[self.lookup[int(index)] for index in ids]]
        except KeyError as error:
            raise ValueError("Condition bank is training-only") from error

    def draw(self, seed, n):
        ids = balanced_indices(self.pack, "train", np.random.default_rng(seed), n)
        return self.for_ids(ids)

    def metadata(self):
        result = dict(domains=self.domains, size=self.bank.shape[1], center=self.center.tolist(),
                      scale=self.scale.tolist(), version=self.version,
                      features=["PPG_peak_rate_bpm", "PPG_ibi_cv", "PPG_signal_std"],
                      label_type="PPG-derived proxies; not ECG ground truth, SpO2, or clinical diagnoses",
                      sampling="domain/patient-balanced training-only condition bank; never test prompts",
                      training_ranges=np.c_[self.raw.min(0), self.raw.max(0)].tolist(),
                      domain_defaults=self.defaults, domain_defaults_features=["irregularity", "PPG_signal_std"])
        if self.version == "v2":
            result.update(layout=["domain one-hot"]*len(self.domains)+["rate_known", "irregularity_known",
                                                                        "rate", "irregularity", "PPG_signal_std"],
                          features=["consensus_or_ecg_rate_bpm", "robust_ibi_cv", "PPG_signal_std"],
                          label_type="Consensus PPG rate (ECG-gated where available), robust IBI CV clipped to "
                                     f"{IRR_MAX}; engineering labels, not clinical measurements",
                          coverage=self.coverage, label_source=self.label_source, ppg_vs_ecg_label_error=self.label_error)
        return result


_MASKS = {}


def bandlimit(x, view="v1", mask=None):
    """Match the shared filtered target view; it does not reproduce raw motion/optical DC."""
    if mask is None and view == "v1":
        freq = torch.fft.rfftfreq(LENGTH, 1/FS, device=x.device)
        mask = (freq >= .9) & (freq <= 5)
    elif mask is None:
        key = (view, str(x.device), x.dtype)
        if key not in _MASKS:
            _MASKS[key] = torch.tensor(view_mask(view), device=x.device, dtype=x.dtype)
        mask = _MASKS[key]
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
    def __init__(self, size, center, scale, view="v1"):
        super().__init__()
        self.view, self.hz_range = view, HZ_RANGE[view]
        if view != "v1":
            # v1 checkpoints carry no mask buffer; only newer views store theirs.
            self.register_buffer("band", torch.tensor(view_mask(view)))
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
        hz = (raw[:, 0]/60).clamp(*self.hz_range)
        time = torch.arange(LENGTH, device=z.device, dtype=z.dtype)/FS
        slow = F.interpolate(z[:, None, :32], size=LENGTH, mode="linear", align_corners=False)[:, 0]
        phase = 2*math.pi*hz[:, None]*time+z[:, :1]*math.pi+raw[:, 1:2].clamp(0, .6)*slow
        carrier = torch.stack([phase.sin(), phase.cos(), (2*phase).sin(), (3*phase).sin()], 1)
        style = self.style(torch.cat((z[:, :8], condition), 1))
        h = torch.cat([branch(torch.cat((z[:, None], carrier), 1)) for branch in self.branches], 1)
        for block, film in zip(self.blocks, self.film):
            gain, bias = film(style).chunk(2, 1)
            h = block(h)*(1+.1*gain[:, :, None])+.1*bias[:, :, None]
        return bandlimit(carrier[:, :1]+.3*carrier[:, 2:3]+self.out(h), self.view, getattr(self, "band", None))


class PhysioMixH(PhysioMix):
    """Constructed beat sequence plus a harmonic pulse head; the trunk only shapes each beat.

    Phase advances one cycle per beat; IBIs are log-normal with sigma from the irregularity
    command (AF-like, not a validated AF model). Six harmonic amplitudes/phases and a baseline
    are predicted at 1 s knots, and the free residual is bounded so it cannot override the rate.
    """
    def __init__(self, size, center, scale, view="v3", harmonics=6, beats=160):
        super().__init__(size, center, scale, view)
        self.k, self.beats = harmonics, beats
        self.head = nn.Conv1d(48, 2*harmonics+1, 1)
        nn.init.zeros_(self.head.weight)
        with torch.no_grad():
            amplitude = torch.tensor([1., .35, .12, .05, .02, .01])[:harmonics]
            self.head.bias[:harmonics] = torch.log(torch.expm1(amplitude))
            self.head.bias[harmonics:2*harmonics] = torch.tensor([0., -1.2, -2.2, -3., -3.5, -4.])[:harmonics]
            self.head.bias[-1] = 0
        self.register_buffer("orders", torch.arange(1, harmonics+1, dtype=torch.float32)[None, :, None])
        self.register_buffer("time", torch.arange(LENGTH, dtype=torch.float32)/FS)

    def phase(self, z, hz, sigma):
        ibi = torch.exp(sigma[:, None]*z[:, 32:32+self.beats]-.5*sigma[:, None]**2)/hz[:, None]
        onset = torch.cumsum(ibi, 1)-ibi-ibi[:, :1]*torch.sigmoid(z[:, :1])
        index = ((onset[:, :, None] <= self.time[None, None]).sum(1)-1).clamp(0, self.beats-1)
        return 2*math.pi*(index.to(z.dtype)+(self.time[None]-onset.gather(1, index))/ibi.gather(1, index))

    def forward(self, z, condition):
        raw = condition[:, -3:]*self.scale+self.center
        hz = (raw[:, 0]/60).clamp(*self.hz_range)
        phi = self.phase(z, hz, raw[:, 1].clamp(0, .3))
        carrier = torch.stack([phi.sin(), phi.cos(), (2*phi).sin(), (3*phi).sin()], 1)
        style = self.style(torch.cat((z[:, :8], condition), 1))
        h = torch.cat([branch(torch.cat((z[:, None], carrier), 1)) for branch in self.branches], 1)
        for block, film in zip(self.blocks, self.film):
            gain, bias = film(style).chunk(2, 1)
            h = block(h)*(1+.1*gain[:, :, None])+.1*bias[:, :, None]
        knots = F.interpolate(self.head(F.avg_pool1d(h, FS)), size=LENGTH, mode="linear", align_corners=False)
        amplitude, theta = F.softplus(knots[:, :self.k]), knots[:, self.k:2*self.k]
        y = ((amplitude*torch.sin(self.orders*phi[:, None]+theta)).sum(1, keepdim=True)+knots[:, -1:]
             +.15*torch.tanh(self.out(h)))
        return bandlimit(y, self.view, self.band)


class PhysioMixR(PhysioMixH):
    """PhysioMixH with a scale-anchored pulse and optional physiological beat timing.

    Output min-max normalisation leaves the absolute harmonic amplitude free; in PhysioMixH it shrank
    late in training until the bounded free residual dominated and the measured rate drifted. Here the
    head sets only the pulse shape (harmonic amplitudes normalised to sum 1) plus a slow gain bounded
    to [e^-.5, e^.5], so the 0.15 residual stays a minor part of every beat.
    beat=True: diastole alone absorbs IBI deviations, so each pulse peak keeps a fixed delay after its
    onset (pure phase warping made peak intervals a moving average of IBIs and under-reported
    irregularity); each pulse scales by (preceding IBI / mean IBI)^beta with beta in [0, 1] learned per
    condition (filling-time dependence of pulse amplitude; not a validated AF model); and the IBI
    sigma may reach the label clip IRR_MAX.
    motion=True: an additive periodic motion component whose cadence, harmonic shape and amplitude
    (0..MOTION_MAX of the pulse) are set per condition and noise; it models wrist motion artifact as a
    waveform, not as a measured accelerometer signal.
    """
    def __init__(self, size, center, scale, view="v3", harmonics=6, beats=160, beat=False, pad=0, motion=False,
                 quiet=False, sensor=False):
        super().__init__(size, center, scale, view, harmonics, beats)
        self.beat, self.pad, self.with_motion, self.quiet, self.with_sensor = beat, pad, motion, quiet, sensor
        if sensor:
            self.sensor = nn.Linear(48, 1)
            nn.init.zeros_(self.sensor.weight)
            nn.init.constant_(self.sensor.bias, SENSOR_INIT)
            # The measurement noise reuses z in a fixed shuffled order, so the app's (z, condition) interface holds; the
            # padding takes other shuffled z entries (a mirrored pad repeats each edge sample's neighbours and raised the
            # filtered noise variance ~1.8x at the window's first and last samples).
            g = torch.Generator().manual_seed(0)
            window, padding = torch.randperm(LENGTH, generator=g), torch.randperm(LENGTH, generator=g)[:2*pad]
            self.register_buffer("sensor_order", torch.cat((padding[:pad], window, padding[pad:])))
        if pad:
            # Generate pad extra samples on both sides, band-limit the long signal, keep the middle window.
            self.register_buffer("time", (torch.arange(LENGTH+2*pad, dtype=torch.float32)-pad)/FS)
            self.register_buffer("band_long", torch.tensor(view_mask(view, LENGTH+2*pad)))
        head = nn.Conv1d(48, 2*harmonics+2, 1)
        nn.init.zeros_(head.weight)
        with torch.no_grad():
            head.bias.zero_()
            head.bias[:2*harmonics+1] = self.head.bias
        self.head = head
        if beat:
            self.coupling = nn.Linear(48, 1)
            nn.init.zeros_(self.coupling.weight)
            nn.init.constant_(self.coupling.bias, -2.)
        if motion:
            # [cadence logit, amplitude logit, harmonic amplitude logits, harmonic phases]
            self.motion = nn.Linear(48, 2+2*MOTION_HARMONICS)
            nn.init.zeros_(self.motion.weight)
            with torch.no_grad():
                self.motion.bias.zero_()
                self.motion.bias[1] = MOTION_INIT
                self.motion.bias[2:2+MOTION_HARMONICS] = torch.log(torch.expm1(torch.tensor([1., .5, .25])))
            self.register_buffer("motion_orders", torch.arange(1, MOTION_HARMONICS+1, dtype=torch.float32)[None, :, None])

    def beats_of(self, z, hz, sigma):
        """Per output sample: beat index and within-beat phase fraction; plus the beat IBIs (s)."""
        ibi = torch.exp(sigma[:, None]*z[:, 32:32+self.beats]-.5*sigma[:, None]**2)/hz[:, None]
        onset = torch.cumsum(ibi, 1)-ibi-ibi[:, :1]*torch.sigmoid(z[:, :1])-self.pad/FS
        index = ((onset[:, :, None] <= self.time[None, None]).sum(1)-1).clamp(0, self.beats-1)
        tau, length = self.time[None]-onset.gather(1, index), ibi.gather(1, index)
        if not self.beat:
            return index, tau/length, ibi
        mean = 1/hz[:, None]
        systole = torch.minimum(SYSTOLE*mean, .9*length)
        late = (systole+(mean-systole)*(tau-systole)/(length-systole))/mean
        return index, torch.where(tau <= systole, tau/mean, late), ibi

    def motion_component(self, style, z):
        """(n, 1, samples) periodic motion term on this model's time grid; cadence fixed within a window."""
        m = self.motion(style)
        hz = MOTION_HZ[0]+(MOTION_HZ[1]-MOTION_HZ[0])*torch.sigmoid(m[:, :1])
        phi = 2*math.pi*hz*self.time[None]+math.pi*z[:, 1:2]
        shape = F.softplus(m[:, 2:2+MOTION_HARMONICS])
        shape = shape/shape.sum(1, keepdim=True)
        wave = (shape[:, :, None]*torch.sin(self.motion_orders*phi[:, None]
                                             +m[:, 2+MOTION_HARMONICS:, None])).sum(1, keepdim=True)
        return MOTION_MAX*torch.sigmoid(m[:, 1:2])[:, :, None]*wave

    def forward(self, z, condition):
        raw = condition[:, -3:]*self.scale+self.center
        hz = (raw[:, 0]/60).clamp(*self.hz_range)
        index, fraction, ibi = self.beats_of(z, hz, raw[:, 1].clamp(0, IRR_MAX if self.beat else .3))
        phi = 2*math.pi*(index.to(z.dtype)+fraction)
        carrier = torch.stack([phi.sin(), phi.cos(), (2*phi).sin(), (3*phi).sin()], 1)
        style = self.style(torch.cat((z[:, :8], condition), 1))
        # The trunk's noise channel is reflected into the padding; the IBIs and style use z as before.
        noise = torch.cat((z[:, :self.pad].flip(1), z, z[:, LENGTH-self.pad:].flip(1)), 1) if self.pad else z
        if self.quiet:
            noise = 3*F.avg_pool1d(noise[:, None], QUIET_KERNEL, 1, QUIET_KERNEL//2, count_include_pad=False)[:, 0]
        h = torch.cat([branch(torch.cat((noise[:, None], carrier), 1)) for branch in self.branches], 1)
        for block, film in zip(self.blocks, self.film):
            gain, bias = film(style).chunk(2, 1)
            h = block(h)*(1+.1*gain[:, :, None])+.1*bias[:, :, None]
        knots = F.interpolate(self.head(F.avg_pool1d(h, FS)), size=h.shape[-1], mode="linear", align_corners=False)
        amplitude = F.softplus(knots[:, :self.k])
        shape = amplitude/amplitude.sum(1, keepdim=True).clamp_min(1e-6)
        pulse = (shape*torch.sin(self.orders*phi[:, None]+knots[:, self.k:2*self.k])).sum(1, keepdim=True)
        gain = torch.exp(.5*torch.tanh(knots[:, -1:]))
        if self.beat:
            beta = torch.sigmoid(self.coupling(style))
            per_beat = torch.exp(beta*torch.log(torch.cat((ibi[:, :1], ibi[:, :-1]), 1)*hz[:, None]))
            current, before = per_beat.gather(1, index), per_beat.gather(1, (index-1).clamp_min(0))
            # The new beat's gain ramps in over its upstroke instead of stepping at the onset.
            gain = gain*(before+(current-before)*(fraction/.2).clamp(0, 1))[:, None]
        y = gain*pulse+knots[:, 2*self.k:2*self.k+1]+.15*torch.tanh(self.out(h))
        if self.with_motion:
            y = y+self.motion_component(style, z)
        if self.with_sensor:
            y = y+SENSOR_MAX*torch.sigmoid(self.sensor(style))[:, :, None]*z[:, None, self.sensor_order]
        if not self.pad:
            return bandlimit(y, self.view, self.band)
        y = torch.fft.irfft(torch.fft.rfft(y, dim=-1)*self.band_long, n=y.shape[-1], dim=-1)[..., self.pad:self.pad+LENGTH]
        return (y-y.amin(-1, keepdim=True))/(y.amax(-1, keepdim=True)-y.amin(-1, keepdim=True)).clamp_min(1e-6)


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


class DerivCritic(ConditionedCritic):
    """Each scale also sees first/second differences, where the v1 critic was blind."""
    def __init__(self, size):
        super().__init__(size)
        for net in self.scales:
            net.net[0] = nn.utils.spectral_norm(nn.Conv1d(3, 16, 7, stride=2, padding=3))

    @staticmethod
    def channels(x):
        return torch.cat((x, 10*F.pad(torch.diff(x, dim=-1), (1, 0)),
                          20*F.pad(torch.diff(x, n=2, dim=-1), (1, 1))), 1)

    def forward(self, x, condition):
        values = []
        for net, projection in zip(self.scales, self.projections):
            h = net.net[:-1](self.channels(x))
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


def clean_diffusion_loss(model, real, condition, regularized=True, view="v1"):
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
            loss = loss+.1*joint_loss(bandlimit(clean[early], view), real[early])
    return loss


@torch.no_grad()
def draw(model, z, condition, diffusion=False, guidance=1., sample_steps=32, view="v1"):
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
    return bandlimit(x, view)


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
