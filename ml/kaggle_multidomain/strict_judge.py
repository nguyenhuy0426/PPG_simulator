"""Strict judge: a large real-vs-generated discriminator (classifier two-sample test) for 30 s, 40 Hz PPG windows.

The project's C2ST probe (control.Probe: 3 convolutions, width 16, ~11 k parameters, 600-1000 steps on a few hundred
windows) is a weak opponent: a generator it cannot separate may still be easy to tell apart. StrictJudge is a
~3 M-parameter network with three views of a window:
- time: the window and its first/second differences through a residual dilated 1D CNN (mean/max/std pooling);
- spectral: a log-power STFT (3.2 s frames) through a residual CNN over frames;
- acf: the normalised autocorrelation up to 5 s through an MLP.
It trains on many windows (real windows of training people vs generated windows prompted with the same people's
labels, 512 per domain with person-balanced sampling), with random 25.6 s crops on both classes, AdamW, a cosine
schedule and early stopping on held-out people; it is scored on people it never saw.

Every source is judged by the same procedure:
- real_other_people (null control): real windows of other training people. A judge that separates them is reading
  person identity, not generation artefacts; it must stay near AUC 0.5 to be eligible.
- positive controls built from those people's real windows: +1% white noise, phase-randomised surrogates (same
  power spectrum, destroyed pulse shape) and circular band-limiting (round 5's known artefact).
- the app's models (physiomix, physioflow, lsm_gan) and the three-Gaussian shaper.
The judge is chosen by JUDGE_RULE on validation people before anything else reads its numbers. Engineering
evaluation of normalised waveform shape; not clinical validation, not measured on the Pi/DAC/OPT101.
"""
import argparse
import copy
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ml.kaggle_lsm.train_lsm import FS, LENGTH, save_json
from ml.kaggle_multidomain import control
from ml.kaggle_multidomain.physio import view_mask

DOMAINS = ("bidmc", "gxu_finger", "perform_af", "perform_large", "perform_non_af", "wrist")
PEOPLE_SEED = 20261022
# Share of each domain's training people: judge fit (real class), judge early stopping, control train, control eval.
PEOPLE_SHARES = (("fit", .6), ("inner", .1), ("control_train", .15), ("control_eval", .15))
PER_DOMAIN_TRAIN, PER_DOMAIN_INNER, PER_DOMAIN_EVAL = 512, 64, 128
CROP, EVAL_STARTS = 1024, (0, 88, 176)
JUDGES = {"probe": dict(steps=1000, batch=32, lr=1e-3),
          "strict_time": dict(branches=("time",), steps=3000, batch=64, lr=3e-4),
          "strict": dict(branches=("time", "spectral", "acf"), steps=3000, batch=64, lr=3e-4)}
EVAL_EVERY = 250
MODELS = ("physiomix", "physioflow", "lsm_gan", "gaussian_shaper")
CONTROLS = ("real_other_people", "noise_1pct", "phase_randomized", "circular_filter")
HARD = ("physiomix", "physioflow", "lsm_gan", "noise_1pct", "phase_randomized", "circular_filter")
BANDS = {"0.5-1.5 Hz": (.5, 1.5), "1.5-3 Hz": (1.5, 3.), "3-5 Hz": (3., 5.), "5-8 Hz": (5., 8.)}
JUDGE_RULE = ("Strict judge selection, fixed before scoring (validation people only). A judge kind is eligible if its "
              "mean pooled AUC on real_other_people over seeds lies in [0.40, 0.60]. Among eligible kinds the best "
              "has the highest mean pooled AUC over physiomix, physioflow, lsm_gan, noise_1pct, phase_randomized and "
              "circular_filter (seeds averaged); within 0.01 the kind with fewer parameters wins. "
              "indistinguishable = 100(1-|2AUC-1|).")


# ---------------------------------------------------------------- networks
def derivative_channels(x):
    return torch.cat((x-x.mean(-1, keepdim=True), 10*F.pad(torch.diff(x, dim=-1), (1, 0)),
                      20*F.pad(torch.diff(x, n=2, dim=-1), (1, 1))), 1)


class Block(nn.Module):
    """Pre-activation residual block; GroupNorm, so a batch's real/fake mix never enters the normalisation."""
    def __init__(self, cin, cout, dilation=1, stride=1, kernel=5, dropout=.1):
        super().__init__()
        self.body = nn.Sequential(nn.GroupNorm(8, cin), nn.SiLU(),
                                  nn.Conv1d(cin, cout, kernel, stride, kernel//2*dilation, dilation),
                                  nn.GroupNorm(8, cout), nn.SiLU(), nn.Dropout(dropout),
                                  nn.Conv1d(cout, cout, kernel, padding=kernel//2))
        self.skip = nn.Conv1d(cin, cout, 1, stride) if cin != cout or stride > 1 else nn.Identity()

    def forward(self, x):
        return self.skip(x)+self.body(x)


def pooled(h):
    return torch.cat((h.mean(-1), h.amax(-1), h.std(-1)), 1)


class TimeBranch(nn.Module):
    def __init__(self, width=64, dropout=.1):
        super().__init__()
        widths, layers = (width, 2*width, 4*width, 4*width), [nn.Conv1d(3, width, 7, padding=3)]
        previous = width
        for i, w in enumerate(widths):
            layers += [Block(previous, w, 1, 1 if i == 0 else 2, dropout=dropout), Block(w, w, 2, dropout=dropout)]
            previous = w
        self.net, self.size = nn.Sequential(*layers, nn.GroupNorm(8, previous), nn.SiLU()), 3*previous

    def forward(self, x):
        return pooled(self.net(derivative_channels(x)))


class SpectralBranch(nn.Module):
    N_FFT, HOP = 128, 16

    def __init__(self, width=128, dropout=.1):
        super().__init__()
        bins = self.N_FFT//2+1
        self.net = nn.Sequential(nn.Conv1d(bins, width, 3, padding=1), Block(width, width, dropout=dropout),
                                 Block(width, width, 2, dropout=dropout),
                                 nn.GroupNorm(8, width), nn.SiLU())
        self.register_buffer("window", torch.hann_window(self.N_FFT))
        self.size = 2*width

    def forward(self, x):
        x = (x[:, 0]-x[:, 0].mean(-1, keepdim=True)).float()
        power = torch.stft(x, self.N_FFT, self.HOP, window=self.window, return_complex=True).abs().square()
        h = self.net((power+1e-6).log())
        return torch.cat((h.mean(-1), h.amax(-1)), 1)


class AcfBranch(nn.Module):
    LAGS = 5*FS

    def __init__(self):
        super().__init__()
        self.net, self.size = nn.Sequential(nn.Linear(self.LAGS, 128), nn.SiLU(), nn.Linear(128, 64), nn.SiLU()), 64

    def forward(self, x):
        x = (x[:, 0]-x[:, 0].mean(-1, keepdim=True)).float()
        n = x.shape[-1]
        acf = torch.fft.irfft(torch.fft.rfft(x, n=2*n).abs().square(), n=2*n)[:, :self.LAGS+1]
        return self.net(acf[:, 1:]/acf[:, :1].clamp_min(1e-8))


class StrictJudge(nn.Module):
    """One real-vs-generated logit per window (positive = generated)."""
    def __init__(self, branches=("time", "spectral", "acf"), width=64):
        super().__init__()
        make = dict(time=lambda: TimeBranch(width), spectral=SpectralBranch, acf=AcfBranch)
        self.branches = nn.ModuleList([make[b]() for b in branches])
        size = sum(b.size for b in self.branches)
        self.head = nn.Sequential(nn.Dropout(.2), nn.Linear(size, 256), nn.SiLU(), nn.Linear(256, 1))

    def forward(self, x):
        features = []
        for branch in self.branches:
            if isinstance(branch, TimeBranch):
                features.append(branch(x).float())
            else:
                with torch.autocast(x.device.type, enabled=False):
                    features.append(branch(x.float()))
        return self.head(torch.cat(features, 1))[:, 0]


def random_crop(x, length=CROP):
    start = torch.randint(0, x.shape[-1]-length+1, (len(x), 1), device=x.device)
    return x.gather(-1, (start+torch.arange(length, device=x.device))[:, None].expand(-1, x.shape[1], -1))


def sn(module):
    return nn.utils.spectral_norm(module)


class CriticBlock(nn.Module):
    """Residual block of the GAN critic: spectral-normalised convolutions and LeakyReLU with no normalisation layer,
    so the critic's input gradient stays bounded like the round-9 critic's (lazy R1 and the round-3 clip limits were
    calibrated on such critics; the judge's GroupNorm blocks gave ~1e3-1e4x larger R1 terms)."""
    def __init__(self, cin, cout, dilation=1, stride=1, kernel=5):
        super().__init__()
        self.body = nn.Sequential(nn.LeakyReLU(.2), sn(nn.Conv1d(cin, cout, kernel, stride, kernel//2*dilation, dilation)),
                                  nn.LeakyReLU(.2), sn(nn.Conv1d(cout, cout, kernel, padding=kernel//2)))
        self.skip = sn(nn.Conv1d(cin, cout, 1, stride)) if cin != cout or stride > 1 else nn.Identity()

    def forward(self, x):
        return (self.skip(x)+self.body(x))/math.sqrt(2)


class CriticTime(nn.Module):
    """The judge's time view (window, first and second differences; dilated residual CNN; mean/max/std pooling)."""
    def __init__(self, width):
        super().__init__()
        widths, layers = (width, 2*width, 4*width, 4*width), [sn(nn.Conv1d(3, width, 7, padding=3))]
        previous = width
        for i, w in enumerate(widths):
            layers += [CriticBlock(previous, w, 1, 1 if i == 0 else 2), CriticBlock(w, w, 2)]
            previous = w
        self.net, self.size = nn.Sequential(*layers, nn.LeakyReLU(.2)), 3*previous

    def forward(self, x):
        return pooled(self.net(derivative_channels(x)))


class CriticSpectral(nn.Module):
    """The judge's log-STFT view with a floor at 1e-3 of the window's mean frame power (-30 dB): an absolute 1e-6
    floor made the input gradient ~1/power in the stop band."""
    FLOOR = 1e-3

    def __init__(self, width):
        super().__init__()
        bins = SpectralBranch.N_FFT//2+1
        self.net = nn.Sequential(sn(nn.Conv1d(bins, width, 3, padding=1)), CriticBlock(width, width),
                                 CriticBlock(width, width, 2), nn.LeakyReLU(.2))
        self.register_buffer("window", torch.hann_window(SpectralBranch.N_FFT))
        self.size = 2*width

    def forward(self, x):
        x = (x[:, 0]-x[:, 0].mean(-1, keepdim=True)).float()
        power = torch.stft(x, SpectralBranch.N_FFT, SpectralBranch.HOP, window=self.window, return_complex=True).abs().square()
        h = self.net((power+self.FLOOR*power.mean((1, 2), keepdim=True)).log())
        return torch.cat((h.mean(-1), h.amax(-1)), 1)


class CriticAcf(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(sn(nn.Linear(AcfBranch.LAGS, 128)), nn.LeakyReLU(.2), sn(nn.Linear(128, 64)), nn.LeakyReLU(.2))
        self.size = 64

    def forward(self, x):
        x = (x[:, 0]-x[:, 0].mean(-1, keepdim=True)).float()
        n = x.shape[-1]
        acf = torch.fft.irfft(torch.fft.rfft(x, n=2*n).abs().square(), n=2*n)[:, :AcfBranch.LAGS+1]
        return self.net(acf[:, 1:]/acf[:, :1].clamp_min(1e-8))


class StrictCritic(nn.Module):
    """GAN critic with the judge's three views (spectral-normalised, see CriticBlock): one hinge logit per view, plus a
    projection term on the condition (size > 0), plus a minibatch-std feature (minibatch_std) against mode collapse.
    In training mode every window is randomly cropped to 25.6 s, real and generated alike (augmentation of the critic's
    view only)."""
    def __init__(self, size=0, width=32, minibatch_std=False):
        super().__init__()
        self.branches = nn.ModuleList([CriticTime(width), CriticSpectral(2*width), CriticAcf()])
        self.minibatch_std = minibatch_std
        extra = int(minibatch_std)
        self.heads = nn.ModuleList([sn(nn.Linear(b.size+extra, 1)) for b in self.branches])
        self.projections = nn.ModuleList([sn(nn.Linear(size, b.size)) for b in self.branches]) if size else None

    def forward(self, x, condition=None):
        if self.training:
            x = random_crop(x)
        values = []
        for i, branch in enumerate(self.branches):
            f = h = branch(x)
            if self.minibatch_std:
                # Feature spread across groups of 4 windows (the whole batch when it is not a multiple of 4).
                group = 4 if len(f) % 4 == 0 else len(f)
                spread = f.reshape(group, -1, f.shape[1]).std(0, unbiased=False).mean(1).repeat(group)
                h = torch.cat((f, spread[:, None]), 1)
            v = self.heads[i](h)[:, 0]
            if self.projections is not None:
                v = v+(f*self.projections[i](condition)).sum(1)/math.sqrt(f.shape[1])
            values.append(v)
        return torch.stack(values, 1)


def make_judge(kind):
    if kind == "probe":
        return control.Probe(True, 16)
    return StrictJudge(JUDGES[kind]["branches"])


def parameters(kind):
    return sum(p.numel() for p in make_judge(kind).parameters())


# ---------------------------------------------------------------- training
def crops(x, rng):
    starts = torch.as_tensor(rng.integers(0, LENGTH-CROP+1, len(x)), device=x.device)
    index = starts[:, None]+torch.arange(CROP, device=x.device)
    return x.gather(-1, index[:, None].expand(-1, x.shape[1], -1))


@torch.no_grad()
def scores(model, kind, x, device):
    """Logit per window; the strict kinds average three fixed crops."""
    model.eval()
    out = []
    for part in torch.as_tensor(np.asarray(x, np.float32)[:, None]).split(256):
        part = part.to(device)
        if kind == "probe":
            out.append(model(part).float())
        else:
            with torch.autocast(device.type, enabled=device.type == "cuda"):
                out.append(torch.stack([model(part[..., s:s+CROP]).float() for s in EVAL_STARTS]).mean(0))
    return torch.cat(out).cpu().numpy()


def fit(kind, real, fake, inner_real, inner_fake, device, seed):
    """Train one judge; strict kinds keep the state with the best AUC on held-out people (inner set)."""
    spec = JUDGES[kind]
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    device = torch.device(device)
    model = make_judge(kind).to(device)
    real_t = torch.as_tensor(np.asarray(real, np.float32)[:, None], device=device)
    fake_t = torch.as_tensor(np.asarray(fake, np.float32)[:, None], device=device)
    if kind == "probe":
        optimizer = torch.optim.Adam(model.parameters(), lr=spec["lr"])
    else:
        optimizer = torch.optim.AdamW(model.parameters(), lr=spec["lr"], weight_decay=.05)
    scaler = torch.amp.GradScaler(enabled=device.type == "cuda" and kind != "probe")
    steps, batch, warmup = spec["steps"], spec["batch"], 100
    best, best_state, history = -1., None, []
    for step in range(1, steps+1):
        if kind != "probe":
            for group in optimizer.param_groups:
                group["lr"] = spec["lr"]*min(1, step/warmup)*.5*(1+math.cos(math.pi*step/steps))
        model.train()
        x = torch.cat((real_t[rng.integers(len(real_t), size=batch)], fake_t[rng.integers(len(fake_t), size=batch)]))
        target = torch.cat((torch.zeros(batch, device=device), torch.ones(batch, device=device)))
        optimizer.zero_grad(set_to_none=True)
        if kind == "probe":
            F.binary_cross_entropy_with_logits(model(x), target).backward()
            optimizer.step()
            continue
        with torch.autocast(device.type, enabled=device.type == "cuda"):
            logits = model(crops(x, rng))
        scaler.scale(F.binary_cross_entropy_with_logits(logits.float(), target)).backward()
        scaler.unscale_(optimizer)
        nn.utils.clip_grad_norm_(model.parameters(), 5.)
        scaler.step(optimizer)
        scaler.update()
        if step % EVAL_EVERY == 0 or step == steps:
            value = control.auc(scores(model, kind, inner_real, device), scores(model, kind, inner_fake, device))
            history.append(dict(step=step, inner_auc=value))
            if value > best:
                best, best_state = value, copy.deepcopy(model.state_dict())
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, history


def judge_scores(model, kind, real, real_domain, fake, fake_domain, device):
    """Pooled and per-domain AUC, indistinguishable %, balanced accuracy at logit 0."""
    a, b = scores(model, kind, real, device), scores(model, kind, fake, device)
    value = control.auc(a, b)
    per_domain = {}
    for d in DOMAINS:
        ra, fb = a[real_domain == d], b[fake_domain == d]
        if len(ra) and len(fb):
            v = control.auc(ra, fb)
            per_domain[d] = dict(auc=v, indistinguishable=100*(1-abs(2*v-1)), real=int(len(ra)), fake=int(len(fb)))
    return dict(auc=value, indistinguishable=100*(1-abs(2*value-1)),
                balanced_accuracy=100*.5*((a < 0).mean()+(b > 0).mean()), per_domain=per_domain), (a, b)


def band_stop(x, band):
    freq = np.fft.rfftfreq(LENGTH, 1/FS)
    keep = ~((freq >= band[0]) & (freq < band[1]))
    y = np.fft.irfft(np.fft.rfft(np.asarray(x, np.float64), axis=-1)*keep, n=LENGTH, axis=-1)
    return normalise(y)


# ---------------------------------------------------------------- sources
def normalise(y):
    y = np.asarray(y, np.float64)
    return ((y-y.min(-1, keepdims=True))/np.maximum(np.ptp(y, -1, keepdims=True), 1e-9)).astype(np.float32)


def noisy(x, rng, level=.01):
    return normalise(x+level*rng.standard_normal(x.shape))


def phase_randomized(x, rng):
    """Same amplitude spectrum, uniform random phases (DC and Nyquist kept real)."""
    spectrum = np.fft.rfft(np.asarray(x, np.float64), axis=-1)
    phase = np.exp(2j*np.pi*rng.uniform(size=spectrum.shape))
    phase[:, 0] = 1
    phase[:, -1] = 1
    return normalise(np.fft.irfft(np.abs(spectrum)*phase, n=LENGTH, axis=-1))


def circular_filter(x):
    return normalise(np.fft.irfft(np.fft.rfft(np.asarray(x, np.float64), axis=-1)*view_mask("v3"), n=LENGTH, axis=-1))


def people_split(pack, ids, seed=PEOPLE_SEED, domains=DOMAINS):
    """Per domain, the training people shuffled once into PEOPLE_SHARES (every part gets at least one person)."""
    rng = np.random.default_rng(seed)
    parts = {name: [] for name, _ in PEOPLE_SHARES}
    for d in domains:
        people = rng.permutation(np.unique(pack["subject"][ids][pack["domain"][ids] == d]))
        if len(people) < len(PEOPLE_SHARES):
            raise ValueError(f"{d}: {len(people)} training people, need {len(PEOPLE_SHARES)}")
        counts = [max(1, int(round(share*len(people)))) for _, share in PEOPLE_SHARES[1:]]
        cuts = np.cumsum([len(people)-sum(counts)]+counts)
        for (name, _), chunk in zip(PEOPLE_SHARES, np.split(people, cuts[:-1])):
            parts[name] += [str(p) for p in chunk]
    return parts


def sample(pack, ids, per_domain, rng, replace=True, domains=DOMAINS):
    """Equal count per domain, people weighted equally inside a domain."""
    out = []
    for d in domains:
        rows = ids[pack["domain"][ids] == d]
        if not len(rows):
            continue
        _, inverse, counts = np.unique(pack["subject"][rows], return_inverse=True, return_counts=True)
        p = 1/counts[inverse]
        n = per_domain if replace else min(per_domain, len(rows))
        out.append(rng.choice(rows, n, replace=replace, p=p/p.sum()))
    return np.concatenate(out)


def build_sets(pack, conditions, generators, split="validation", seed=0, domains=DOMAINS, controls=CONTROLS,
               eval_prompts="fit"):
    """Arrays for the judge workers: real_{train,inner,eval}, every source's {train,inner,eval} windows with matched
    per-domain counts, and each eval set's domain labels ({name}_eval_domain).
    seed draws the windows and prompts; generator g's set i (train, inner, eval) uses noise seed 1000*g+i+100000*seed
    (seed 0 is the strict-judge kernel's draw). eval_prompts: whose labels prompt the eval fakes, the judge's fit people
    (strict-judge kernel) or control_eval (people the judge never saw, as the null control's eval windows)."""
    rng = np.random.default_rng(seed)
    train = np.flatnonzero((pack["split"] == "train") & np.isin(pack["domain"], domains))
    parts = people_split(pack, train, domains=domains)
    of = {name: train[np.isin(pack["subject"][train], people)] for name, people in parts.items()}
    held = np.flatnonzero((pack["split"] == split) & np.isin(pack["domain"], domains))
    real_ids = dict(train=sample(pack, of["fit"], PER_DOMAIN_TRAIN, rng, domains=domains),
                    inner=sample(pack, of["inner"], PER_DOMAIN_INNER, rng, domains=domains),
                    eval=sample(pack, held, PER_DOMAIN_EVAL, rng, replace=False, domains=domains))
    counts = {k: {d: int((pack["domain"][v] == d).sum()) for d in domains} for k, v in real_ids.items()}
    arrays = {f"real_{k}": pack["signal"][v] for k, v in real_ids.items()}
    arrays["real_eval_domain"] = pack["domain"][real_ids["eval"]]
    # Fakes are prompted with labels of fit/inner people, domain counts equal to the real side of the same set.
    if eval_prompts not in ("fit", "control_eval"):
        raise ValueError(f"Unknown eval_prompts {eval_prompts}")
    prompt_from = dict(train="fit", inner="inner", eval=eval_prompts)
    prompt_ids = {k: sample_counts(pack, of[prompt_from[k]], counts[k], rng) for k in counts}
    # The controls' inner (early-stopping) windows are disjoint from their training windows, as a generator's inner
    # fakes are fresh samples (the strict-judge kernel v1 drew both from all control_train windows: ~93% overlap).
    control_train, control_inner = window_split(pack, of["control_train"], rng)
    pools = dict(train=control_train, inner=control_inner, eval=of["control_eval"])
    control_ids = {k: sample_counts(pack, pools[k], counts[k], rng) for k in counts}
    transform = dict(real_other_people=lambda x: x, noise_1pct=lambda x: noisy(x, rng),
                     phase_randomized=lambda x: phase_randomized(x, rng), circular_filter=circular_filter)
    for name in controls:
        arrays.update({f"{name}_{k}": transform[name](pack["signal"][v]) for k, v in control_ids.items()})
        arrays[f"{name}_eval_domain"] = pack["domain"][control_ids["eval"]]
    for g, (name, generate) in enumerate(generators.items()):
        started = time.monotonic()
        for i, k in enumerate(("train", "inner", "eval")):
            arrays[f"{name}_{k}"] = generate(prompt_ids[k], conditions, 1000*g+i+100000*seed)
        arrays[f"{name}_eval_domain"] = pack["domain"][prompt_ids["eval"]]
        print("generated", name, f"{time.monotonic()-started:.0f}s", flush=True)
    return arrays, dict(people=parts, counts=counts)


def window_split(pack, ids, rng, share=.2):
    """Per domain, a random share of ids' windows (at least one) apart from the rest: (rest, share)."""
    rest, held = [], []
    for d in sorted(set(pack["domain"][ids])):
        rows = rng.permutation(ids[pack["domain"][ids] == d])
        if len(rows) < 2:
            raise ValueError(f"{d}: one control window, cannot hold out inner windows")
        k = max(1, int(round(share*len(rows))))
        held.append(rows[:k])
        rest.append(rows[k:])
    return np.concatenate(rest), np.concatenate(held)


def sample_counts(pack, ids, counts, rng):
    out = []
    for d, n in counts.items():
        if n:
            out.append(sample(pack, ids[pack["domain"][ids] == d], n, rng, domains=(d,)))
    return np.concatenate(out)


def app_generators(bundle, conditions, device):
    """The app's TorchScript files (sha256 from its manifest), prompted with the v2 condition bank of the v3 pack."""
    from ml.kaggle_multidomain.realism import lsm_source
    bundle = Path(bundle)
    manifest = json.loads((bundle/"manifest.json").read_text())
    out = {}
    for slot in ("physiomix", "physioflow"):
        meta, entry = manifest[slot], manifest["models"][f"{slot}_generator"]
        if meta["domains"] != conditions.domains or not np.allclose(meta["center"], conditions.center, rtol=1e-5) \
                or not np.allclose(meta["scale"], conditions.scale, rtol=1e-5):
            raise ValueError(f"{slot}: app condition schema differs from the v3 pack's")
        path = bundle/entry["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"{slot} checksum mismatch")
        out[slot] = torchscript_generator(path, device, len(conditions.domains)+5)
    lsm = lsm_source(bundle/manifest["models"]["lsm_generator"]["file"])
    out["lsm_gan"] = lambda ids, conditions, seed: lsm(ids, seed)
    out["gaussian_shaper"] = gaussian_generator()
    return out


def torchscript_generator(path, device, width):
    """Runs on the GPU when the scripted graph allows it (checked against the CPU on 4 windows), else on the CPU.
    width: condition row length (v2: domain one-hot, two known flags, rate, irregularity, std)."""
    cpu = torch.jit.load(str(path), map_location="cpu").eval()
    model, where = cpu, "cpu"
    if device.startswith("cuda"):
        try:
            gpu = torch.jit.load(str(path), map_location=device).eval()
            z, c = torch.randn(4, LENGTH, generator=torch.Generator().manual_seed(0)), torch.zeros(4, width)
            c[:, 0] = 1
            with torch.inference_mode():
                if torch.allclose(gpu(z.to(device), c.to(device)).cpu(), cpu(z, c), atol=1e-3):
                    model, where = gpu, device
        except RuntimeError as error:
            print("gpu sampling unavailable for", Path(path).name, str(error)[:200], flush=True)
    print("sampling", Path(path).name, "on", where, flush=True)

    def generate(ids, conditions, seed):
        z = torch.randn(len(ids), LENGTH, generator=torch.Generator().manual_seed(seed))
        rows = torch.from_numpy(conditions.for_ids(ids))
        with torch.inference_mode():
            parts = [model(a.to(where), b.to(where)).cpu() for a, b in zip(z.split(64), rows.split(64))]
        return torch.cat(parts)[:, 0].numpy().astype(np.float32)
    return generate


def gaussian_generator():
    def generate(ids, conditions, seed):
        rates = conditions.for_ids(ids)[:, -3]*conditions.scale[0]+conditions.center[0]
        return np.asarray(control.gaussian_reference(rates, view_mask("v3"), seed), np.float32)
    return generate


# ---------------------------------------------------------------- execution
def worker(device, jobs, data_path, output, bands):
    torch.set_num_threads(2)
    if device.startswith("cuda"):
        torch.cuda.set_device(device)
    with np.load(data_path, allow_pickle=False) as source:
        data = {k: source[k] for k in source.files}
    rows = []
    for kind, name, seed in jobs:
        started = time.monotonic()
        model, history = fit(kind, data["real_train"], data[f"{name}_train"], data["real_inner"],
                             data[f"{name}_inner"], device, seed)
        result, _ = judge_scores(model, kind, data["real_eval"], data["real_eval_domain"], data[f"{name}_eval"],
                                 data[f"{name}_eval_domain"], torch.device(device))
        row = dict(judge=kind, source=name, seed=seed, history=history, seconds=time.monotonic()-started, **result)
        if bands and kind != "probe" and seed == 0:
            row["band_stop_auc"] = {b: control.auc(scores(model, kind, band_stop(data["real_eval"], r), torch.device(device)),
                                                   scores(model, kind, band_stop(data[f"{name}_eval"], r), torch.device(device)))
                                    for b, r in BANDS.items()}
        if kind != "probe" and seed == 0:
            torch.save({k: v.half() for k, v in model.state_dict().items()}, Path(output)/f"judge_{kind}_{name}.pt")
        rows.append(row)
        print("JUDGE", kind, name, seed, f"auc {row['auc']:.3f}", f"{row['seconds']:.0f}s", flush=True)
    return rows


def run_jobs(jobs, devices, data_path, output, bands=True):
    if devices == ["cpu"]:
        return worker("cpu", jobs, data_path, output, bands)
    rows = []
    with ProcessPoolExecutor(len(devices), mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(worker, d, jobs[i::len(devices)], data_path, output, bands) for i, d in enumerate(devices)]
        for future in as_completed(futures):
            rows.extend(future.result())
            save_json(Path(output)/"judges_progress.json", rows)
    return rows


def select(rows):
    """JUDGE_RULE on the validation rows."""
    kinds = sorted({r["judge"] for r in rows})
    table = {}
    for kind in kinds:
        mine = [r for r in rows if r["judge"] == kind]
        mean = lambda name: float(np.mean([r["auc"] for r in mine if r["source"] == name]))
        null = mean("real_other_people")
        table[kind] = dict(null_auc=null, eligible=bool(.4 <= null <= .6), hard_mean_auc=float(np.mean([mean(s) for s in HARD])),
                           parameters=parameters(kind), auc={s: mean(s) for s in MODELS+CONTROLS})
    eligible = [k for k in kinds if table[k]["eligible"]]
    if not eligible:
        return dict(rule=JUDGE_RULE, best=None, table=table)
    top = max(table[k]["hard_mean_auc"] for k in eligible)
    best = min((k for k in eligible if table[k]["hard_mean_auc"] >= top-.01), key=lambda k: table[k]["parameters"])
    return dict(rule=JUDGE_RULE, rule_sha256=hashlib.sha256(JUDGE_RULE.encode()).hexdigest(), best=best, table=table)


def summarize(rows):
    out = {}
    for kind in sorted({r["judge"] for r in rows}):
        out[kind] = {}
        for name in MODELS+CONTROLS:
            mine = [r for r in rows if r["judge"] == kind and r["source"] == name]
            if not mine:
                continue
            stat = lambda values: dict(mean=float(np.mean(values)), sd=float(np.std(values, ddof=1)) if len(values) > 1 else 0.)
            out[kind][name] = dict(auc=stat([r["auc"] for r in mine]), indistinguishable=stat([r["indistinguishable"] for r in mine]),
                                   balanced_accuracy=stat([r["balanced_accuracy"] for r in mine]),
                                   per_domain={d: stat([r["per_domain"][d]["indistinguishable"] for r in mine])
                                               for d in DOMAINS if all(d in r["per_domain"] for r in mine)})
    return out


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="Holds the verified v3 pack and the app model files")
    parser.add_argument("--output", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--judges", nargs="+", choices=tuple(JUDGES), default=list(JUDGES))
    parser.add_argument("--split", choices=("validation", "test"), default="validation")
    parser.add_argument("--smoke", action="store_true", help="Tiny CPU run for tests")
    a = parser.parse_args(argv)
    from ml.kaggle_multidomain.data_gxu import load_input
    from ml.kaggle_multidomain.experiment_v3 import PROTOCOL, conditions_for
    if a.smoke:
        global PER_DOMAIN_TRAIN, PER_DOMAIN_INNER, PER_DOMAIN_EVAL, EVAL_EVERY
        PER_DOMAIN_TRAIN, PER_DOMAIN_INNER, PER_DOMAIN_EVAL, EVAL_EVERY = 16, 8, 8, 2
        for spec in JUDGES.values():
            spec.update(steps=4, batch=8)
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    devices = [f"cuda:{i}" for i in range(len(names))] or ["cpu"]
    pack, manifest = load_input(a.input_root, PROTOCOL)
    pack = {k: v[pack["split"] != "external"] for k, v in pack.items()}
    # The app's condition bank was fitted on the train+validation view; train ids of this view map into it.
    keep = np.flatnonzero(np.isin(pack["split"], ["train", "validation"]))
    bank = ConditionsView(conditions_for({k: v[keep] for k, v in pack.items()}, "v2"), keep)
    bundle = next(p.parent for p in Path(a.input_root).rglob("manifest.json") if (p.parent/"physiomix_generator.ts").exists())
    generators = app_generators(bundle, bank, devices[0])
    save_json(output/"FROZEN_JUDGE.json", dict(rule=JUDGE_RULE, rule_sha256=hashlib.sha256(JUDGE_RULE.encode()).hexdigest(),
              judges={k: dict(v, parameters=parameters(k)) for k, v in JUDGES.items()}, seeds=a.seeds, split=a.split,
              data_sha256=manifest["windows_sha256"], allocated_gpus=names))
    arrays, info = build_sets(pack, bank, generators, a.split)
    save_json(output/"sets.json", dict(counts=info["counts"], people={k: len(v) for k, v in info["people"].items()}))
    data_path = Path("/tmp" if not a.smoke else output)/"strict_judge_sets.npz"
    np.savez(data_path, **arrays)
    jobs = [(kind, name, seed) for seed in a.seeds for kind in a.judges for name in MODELS+CONTROLS]
    # Longest jobs first so both GPUs finish together.
    jobs.sort(key=lambda j: j[0] == "probe")
    rows = run_jobs(jobs, devices, data_path, output)
    save_json(output/"judges.json", rows)
    selection = select(rows)
    save_json(output/"SELECTION_JUDGE.json", selection)
    save_json(output/"summary.json", dict(split=a.split, summary=summarize(rows), selection=selection,
                                          wall_seconds=time.monotonic()-started))
    if not a.smoke:
        os.remove(data_path)
    print("BEST JUDGE", selection["best"], flush=True)
    save_json(output/"COMPLETE.json", dict(status="complete", best=selection["best"], wall_seconds=time.monotonic()-started))
    return selection


class ConditionsView:
    """Conditions fitted on the train+validation view, addressed with ids of a larger view through keep."""
    def __init__(self, conditions, keep):
        self.conditions, self.keep = conditions, keep
        self.domains, self.center, self.scale = conditions.domains, conditions.center, conditions.scale

    def for_ids(self, ids):
        return self.conditions.for_ids(self.keep_index(ids))

    def keep_index(self, ids):
        position = np.searchsorted(self.keep, ids)
        if np.any(position >= len(self.keep)) or np.any(self.keep[np.minimum(position, len(self.keep)-1)] != ids):
            raise ValueError("Prompt ids outside the condition view")
        return position


if __name__ == "__main__":
    main()
