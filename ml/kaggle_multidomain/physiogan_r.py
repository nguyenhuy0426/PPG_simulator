"""PhysioGAN-R (P5): a GAN trained from scratch on the R pack's records, ending in the record-context v3 view.

What differs from the GANs before it (PhysioMix: hinge loss on v3 windows with heart-rate conditions; LSM-GAN: the
author topology; G3: a 4-step flow student pulled to a frozen teacher):
- the generator writes the 40 s record before the band-pass (as flow_r.RView expects it) in one pass, and RView applies
  the v3 band-pass once, as the real windows had it: no network has to reach the -95 dB stop band by itself;
- the loss is the relativistic pairing GAN loss with zero-centred gradient penalties on real (R1) and generated (R2)
  windows (Huang et al. 2024, "The GAN is dead; long live the GAN!"), which keeps the critic from separating a mode
  it has dropped without the hinge's flat regions;
- the critic is strict_judge.StrictCritic with the judge's views (time, log-STFT, ACF) and the 7-14 Hz band view, a
  minibatch-std feature against mode collapse, conditioned by projection on domain and record context only;
- the critic is kept in balance with the generator (P5 v2, after the user's request): it learns at half the
  generator's rate, and adaptive augmentation (ADA, Karras et al. 2020) of everything it sees (gain/offset, time
  stretch, instance noise, each with probability p) raises p while the critic wins too easily: p moves to keep
  r_t = E[sign(D(real) - D(generated))] at ADA_TARGET (0: the critic cannot rank the pair; 1: it always can);
- conditions are the domain and the record context (left/right seconds of record around the window); no heart rate,
  SpO2 or irregularity, so C is not measured;
- checkpoints are chosen by a selection C2ST: a fresh strict-judge network trained on training people (fit share) and
  scored on other training people (control_eval share). The round's decision judge uses the validation people, which
  training and selection never see.
Engineering evaluation of normalised 30 s PPG shape; not clinical validation, not measured on the Pi/DAC/OPT101.
"""
import json
import math
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ml.kaggle_lsm.train_lsm import LENGTH, save_json
from ml.kaggle_multidomain import strict_judge as sj
from ml.kaggle_multidomain.data_r import CONTEXT, R_LENGTH

ARM = "G4_physiogan_r"
BASE = 25                                   # R_LENGTH / 2**6
CONFIG = dict(latent=128, wdim=256, channels=(384, 384, 256, 256, 192, 128, 64))
CRITIC = dict(width=48, minibatch_std=True, band=True)
TRAIN = dict(lr=2e-4, d_lr=1e-4, betas=(0., .99), batch=32, gamma=1., lazy=4, ema=.999, max_steps=10**6,
             warmup_ema=2000, select_every_s=1200., clip=10., log_every=200)
ADA_TARGET, ADA_IMAGES, ADA_MAX = .6, 100_000, .8     # p can cross 0..1 in ADA_IMAGES critic windows
# The selection judge: the strict kind's network and recipe at a third of its steps, on training people only.
SELECT = dict(branches=("time", "spectral", "acf"), steps=1000, batch=64, lr=3e-4)
SELECT_SIZES, SELECT_SEED = dict(fit=256, inner=64, eval=128), 31337
CHUNK = 256


def condition_rows(onehot, context):
    """Model and critic condition: domain one-hot and the context (left, right) as a fraction of CONTEXT."""
    return np.c_[onehot, np.asarray(context, np.float32)/CONTEXT].astype(np.float32)


# ---------------------------------------------------------------- generator
class GenBlock(nn.Module):
    """x2 linear upsampling, then a residual pair of convolutions with a FiLM of the style w and per-sample noise.
    The second convolution starts at zero, so each block starts as its upsampled skip path."""
    def __init__(self, cin, cout, wdim):
        super().__init__()
        self.conv1, self.conv2 = nn.Conv1d(cin, cout, 5, padding=2), nn.Conv1d(cout, cout, 5, padding=2)
        nn.init.zeros_(self.conv2.weight)
        nn.init.zeros_(self.conv2.bias)
        self.film = nn.Linear(wdim, 2*cout)
        nn.init.zeros_(self.film.weight)
        nn.init.zeros_(self.film.bias)
        self.noise = nn.Parameter(torch.zeros(cout))
        self.skip = nn.Conv1d(cin, cout, 1) if cin != cout else nn.Identity()

    def forward(self, x, w, noise):
        x = F.interpolate(x, scale_factor=2, mode="linear", align_corners=False)
        h = self.conv1(F.leaky_relu(x, .2))
        scale, shift = self.film(w).chunk(2, 1)
        h = h*(1+scale[:, :, None])+shift[:, :, None]+self.noise[None, :, None]*noise
        return self.skip(x)+self.conv2(F.leaky_relu(h, .2))


class PhysioGANR(nn.Module):
    """generator(z (n, latent), condition (n, D+2), context (n, 2)) -> (n, 1, LENGTH) v3 windows in [0, 1]."""
    def __init__(self, domains, latent=128, wdim=256, channels=(384, 384, 256, 256, 192, 128, 64)):
        super().__init__()
        if len(channels) != 7:
            raise ValueError("Six x2 stages from BASE to R_LENGTH need seven widths")
        self.latent, self.domains = int(latent), int(domains)
        self.mapping = nn.Sequential(nn.Linear(latent+domains+2, wdim), nn.LeakyReLU(.2), nn.Linear(wdim, wdim),
                                     nn.LeakyReLU(.2), nn.Linear(wdim, wdim), nn.LeakyReLU(.2), nn.Linear(wdim, wdim))
        self.base = nn.Linear(wdim, channels[0]*BASE)
        self.blocks = nn.ModuleList(GenBlock(a, b, wdim) for a, b in zip(channels[:-1], channels[1:]))
        self.out = nn.Conv1d(channels[-1], 1, 5, padding=2)
        from ml.kaggle_multidomain.flow_r import RView
        self.view = RView()

    def record(self, z, condition, generator=None):
        """(n, R_LENGTH) record in the R domain (any scale and offset: the view is linear and ends in min-max)."""
        w = self.mapping(torch.cat((z, condition), 1))
        x = self.base(w).view(len(z), -1, BASE)
        for block in self.blocks:
            noise = torch.randn(len(z), 1, 2*x.shape[-1], device=z.device, generator=generator)
            x = block(x, w, noise)
        return self.out(F.leaky_relu(x, .2))[:, 0]

    def forward(self, z, condition, context, generator=None):
        return self.view(self.record(z, condition, generator)[:, None], context)


def draw_context(domain_index, contexts, cdf, generator):
    """(n, 2) context types, each from its domain's training distribution (flow_r.context_table)."""
    u = torch.rand(len(domain_index), generator=generator, device=cdf.device)
    k = (cdf[domain_index] < u[:, None]).sum(1).clamp(max=contexts.shape[0]-1)
    return contexts[k]


@torch.no_grad()
def windows(model, onehot, contexts, cdf, seed, device, context=None):
    """(n, LENGTH) generated v3 windows for domain one-hot rows; context per row given, or drawn per domain."""
    device = torch.device(device)
    model = model.to(device).eval()
    generator = torch.Generator(device).manual_seed(int(seed))
    onehot = torch.as_tensor(np.asarray(onehot, np.float32), device=device)
    if context is None:
        context = draw_context(onehot.argmax(1), contexts.to(device), cdf.to(device), generator)
    context = torch.as_tensor(np.asarray(context.cpu() if torch.is_tensor(context) else context), dtype=torch.long,
                              device=device)
    out = []
    for part, ctx in zip(onehot.split(CHUNK), context.split(CHUNK)):
        z = torch.randn(len(part), model.latent, device=device, generator=generator)
        condition = torch.cat((part, ctx.float()/CONTEXT), 1)
        out.append(model(z, condition, ctx, generator)[:, 0].cpu())
    return torch.cat(out).numpy().astype(np.float32)


def load(run_dir, device="cpu"):
    state = torch.load(Path(run_dir)/"best.pt", map_location="cpu", weights_only=True)
    model = PhysioGANR(state["domains"], **state["config"])
    model.load_state_dict(state["generator"])
    return model.to(device).eval(), state


def generator(run_dir, device):
    """Judge source: generate(ids, conditions, seed) prompted by the domain of each id's condition row only."""
    model, state = load(run_dir, device)

    def generate(ids, conditions, seed):
        onehot = np.asarray(conditions.for_ids(ids), np.float32)[:, :state["domains"]]
        return windows(model, onehot, state["contexts"], state["cdf"], seed, device)
    return generate


# ---------------------------------------------------------------- critic balance (ADA)
def stretch(x, factor):
    """Time stretch of (n, 1, L) windows about their centre by factor (n, 1, 1), edge samples held: linear
    interpolation written with gather, so the critic's R1/R2 penalties can differentiate it twice (grid_sample's
    backward has no derivative)."""
    length = x.shape[-1]
    centre = (length-1)/2
    position = ((torch.arange(length, device=x.device, dtype=x.dtype)[None, None]-centre)*factor+centre).clamp(0, length-1)
    left = position.floor().long().clamp(max=length-2)
    w = position-left
    return x.gather(-1, left)*(1-w)+x.gather(-1, left+1)*w


class Augment(nn.Module):
    """Differentiable augmentation of (n, 1, L) windows, each part applied to a window with probability p: gain and
    offset, a time stretch of +-10% about the centre (stretch), white instance noise (SD 0.02).
    All three leave the critic a way to tell the classes apart only through what real and generated windows differ in
    (they are applied alike to both), and are invertible in distribution for p < 1 (non-leaking, ADA)."""
    def __init__(self):
        super().__init__()
        self.register_buffer("p", torch.zeros(()))

    def forward(self, x):
        p = float(self.p)
        if p <= 0:
            return x
        n, _, length = x.shape
        pick = lambda: (torch.rand(n, 1, 1, device=x.device) < p).to(x.dtype)
        m = pick()
        gain, offset = torch.exp(.2*torch.randn(n, 1, 1, device=x.device)), .1*torch.randn(n, 1, 1, device=x.device)
        x = m*(x*gain+offset)+(1-m)*x
        m = pick()
        x = stretch(x, torch.exp(.1*(2*torch.rand(n, 1, 1, device=x.device)-1))*m+(1-m))
        m = pick()
        return x+m*.02*torch.randn_like(x)

    @torch.no_grad()
    def adjust(self, rt, images):
        """p += sign(r_t - target) * images / ADA_IMAGES, within [0, ADA_MAX]."""
        self.p.add_(float(np.sign(rt-ADA_TARGET))*images/ADA_IMAGES).clamp_(0, ADA_MAX)


class Balanced(nn.Module):
    """The critic behind its augmentation: what training and the penalties call."""
    def __init__(self, critic):
        super().__init__()
        self.critic, self.augment = critic, Augment()

    def forward(self, x, condition):
        return self.critic(self.augment(x), condition)


# ---------------------------------------------------------------- loss
def critic_terms(d, real, fake, c):
    """Per-view logits of paired real and generated windows (n, views)."""
    return d(real, c), d(fake, c)


def penalty(d, x, c):
    """Zero-centred gradient penalty: mean over windows of |grad_x sum of the views' logits|^2."""
    x = x.detach().requires_grad_(True)
    grad, = torch.autograd.grad(d(x, c).sum(), x, create_graph=True)
    return grad.square().sum((1, 2)).mean()


def d_loss(real_logits, fake_logits):
    """Relativistic pairing loss of the critic, every view its own critic: softplus(-(D(real) - D(fake)))."""
    return F.softplus(fake_logits-real_logits).mean()


def g_loss(real_logits, fake_logits):
    return F.softplus(real_logits-fake_logits).mean()


# ---------------------------------------------------------------- selection C2ST (training people only)
def selection_sets(pack, train_ids, rng):
    """Rows of the selection judge: fit people (judge training), inner (its early stopping), control_eval (scoring);
    each also prompts the generated side of its set (same domains and record contexts)."""
    parts = sj.people_split(pack, train_ids)
    of = {name: train_ids[np.isin(pack["subject"][train_ids], people)] for name, people in parts.items()}
    take = dict(fit="fit", inner="inner", eval="control_eval")
    return {k: sj.sample(pack, of[take[k]], SELECT_SIZES[k], rng) for k in take}


def selection_auc(model, sets, signal, condition, context, device, seed):
    """AUC of a fresh selection judge (generated positive) on control_eval people: lower is closer to real."""
    kind = "p5_select"
    sj.JUDGES[kind] = dict(SELECT)
    fakes = {k: windows(model, condition[rows][:, :model.domains], None, None, seed+i, device, context[rows])
             for i, (k, rows) in enumerate(sets.items())}
    judge, _ = sj.fit(kind, signal[sets["fit"]], fakes["fit"], signal[sets["inner"]], fakes["inner"], device, seed)
    device = torch.device(device)
    from ml.kaggle_multidomain import control
    return control.auc(sj.scores(judge, kind, signal[sets["eval"]], device), sj.scores(judge, kind, fakes["eval"], device))


# ---------------------------------------------------------------- training
def finite(loss, stability, step):
    if torch.isfinite(loss):
        return True
    stability["nonfinite_losses"] += 1
    if stability["nonfinite_losses"] > max(10, .01*step):
        raise RuntimeError(f"Nonfinite objective: {ARM}/{step}")
    return False


def update(model, optimizer, clip, stability, name):
    norm = nn.utils.clip_grad_norm_(model.parameters(), clip)
    stability[f"max_{name}_grad_norm"] = max(stability[f"max_{name}_grad_norm"], float(norm))
    stability[f"{name}_clipped"] += int(norm > clip)
    optimizer.step()


def train(seed, input_root, output, device, deadline, config=None, spec=None):
    """Train one PhysioGAN-R seed on the train people; keep the EMA generator with the lowest selection AUC.
    deadline: epoch seconds; the step running at it is the last, followed by a final selection."""
    from ml.kaggle_multidomain import flow_r
    from ml.kaggle_multidomain.data import balanced_pool
    from ml.kaggle_multidomain.data_gxu import load_input
    from ml.kaggle_multidomain.experiment_v3 import PROTOCOL
    from ml.kaggle_multidomain.physio import ema_model, update_ema
    config, spec = dict(CONFIG, **(config or {})), dict(TRAIN, **(spec or {}))
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    device = torch.device(device)
    cuda = device.type == "cuda"
    if cuda:
        torch.cuda.set_device(device)
        torch.cuda.reset_peak_memory_stats(device)
    pack, _ = load_input(input_root, PROTOCOL)
    pack = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    domains = sorted({str(d) for d in pack["domain"][pack["split"] == "train"]})
    train_ids, weights = balanced_pool(pack, "train")
    _, context_all = flow_r.training_rows(pack, train_ids, [input_root])
    context = np.zeros((len(pack["signal"]), 2), np.int64)
    context[train_ids] = context_all
    contexts, cdf = flow_r.context_table(context_all, pack["domain"][train_ids], domains)
    onehot = np.eye(len(domains), dtype=np.float32)[[domains.index(str(d)) for d in pack["domain"]]]
    condition = condition_rows(onehot, context)
    sets = selection_sets(pack, train_ids, np.random.default_rng(SELECT_SEED))
    real_all = torch.tensor(pack["signal"][:, None], device=device)
    cond_all, ctx_all = torch.tensor(condition, device=device), torch.tensor(context, device=device)
    g = PhysioGANR(len(domains), **config).to(device)
    d = Balanced(sj.StrictCritic(len(domains)+2, **CRITIC)).to(device)
    ema = ema_model(g)
    optg = torch.optim.Adam(g.parameters(), lr=spec["lr"], betas=spec["betas"])
    optd = torch.optim.Adam(d.parameters(), lr=spec["d_lr"], betas=spec["betas"])
    run_dir = Path(output)/f"{ARM}_seed{seed}"
    run_dir.mkdir(parents=True)
    best, best_step, history = float("inf"), 0, []
    stability = dict(nonfinite_losses=0, d_clipped=0, g_clipped=0, max_d_grad_norm=0., max_g_grad_norm=0.)
    balance, signs = [], []
    start = last_select = time.monotonic()
    batch = spec["batch"]

    def select(step):
        nonlocal best, best_step
        value = selection_auc(ema, sets, pack["signal"], condition, context, device, SELECT_SEED+seed)
        row = dict(step=step, selection_auc=value, seconds=time.monotonic()-start)
        history.append(row)
        if value < best:
            best, best_step = value, step
            torch.save(dict(generator=ema.state_dict(), config=config, domains=len(domains), domain_names=domains,
                            contexts=contexts, cdf=cdf, step=step, selection_auc=value, seed=seed), run_dir/"best.pt")
        save_json(run_dir/"history.json", history)
        print(ARM, seed, json.dumps(row), flush=True)

    step = 0
    for step in range(1, spec["max_steps"]+1):
        g.train()
        d.train()
        rows = torch.as_tensor(train_ids[rng.choice(len(train_ids), batch, p=weights)], device=device)
        real, c, ctx = real_all[rows], cond_all[rows], ctx_all[rows]
        z = torch.randn(batch, g.latent, device=device)
        # Critic: relativistic pairing loss, lazy R1 (real) and R2 (generated) penalties every `lazy` steps.
        fake = g(z, c, ctx)
        rl, fl = critic_terms(d, real, fake.detach(), c)
        loss_d = d_loss(rl, fl)
        if step % spec["lazy"] == 0:
            loss_d = loss_d+.5*spec["gamma"]*spec["lazy"]*(penalty(d, real, c)+penalty(d, fake, c))
        if not finite(loss_d, stability, step):
            continue
        optd.zero_grad(set_to_none=True)
        loss_d.backward()
        update(d, optd, spec["clip"], stability, "d")
        signs.append(float(torch.sign(rl-fl).detach().mean()))
        if step % spec["lazy"] == 0:
            d.augment.adjust(float(np.mean(signs[-spec["lazy"]:])), spec["lazy"]*batch)
        # Generator: the same pairing with the roles swapped, against the updated critic (its weights frozen here).
        d.requires_grad_(False)
        rl_g, fl_g = critic_terms(d, real, fake, c)
        loss_g = g_loss(rl_g, fl_g)
        d.requires_grad_(True)
        if not finite(loss_g, stability, step):
            continue
        optg.zero_grad(set_to_none=True)
        loss_g.backward()
        update(g, optg, spec["clip"], stability, "g")
        update_ema(ema, g, min(spec["ema"], step/spec["warmup_ema"]))
        if step % spec["log_every"] == 0:
            # Balance trace: r_t over the interval, ADA p, both losses and the per-view real-minus-generated margin.
            balance.append(dict(step=step, rt=float(np.mean(signs)), p=float(d.augment.p), loss_d=float(loss_d.detach()),
                                loss_g=float(loss_g.detach()), margin=(rl-fl).detach().mean(0).tolist()))
            signs.clear()
            save_json(run_dir/"balance.json", balance)
        late = time.time() > deadline
        if time.monotonic()-last_select > spec["select_every_s"] or late:
            select(step)
            last_select = time.monotonic()
        if late:
            stability["stopped_at_step"] = step
            break
    if not (run_dir/"best.pt").exists():
        select(step)
    result = dict(arm=ARM, seed=seed, best_step=best_step, selection_auc=best, config=config, critic=CRITIC,
                  train=spec, select=SELECT, steps=step, ada=dict(target=ADA_TARGET, images=ADA_IMAGES, max=ADA_MAX,
                                                                 final_p=float(d.augment.p)),
                  final_balance=balance[-1] if balance else None,
                  generator_parameters=sum(p.numel() for p in g.parameters()),
                  critic_parameters=sum(p.numel() for p in d.critic.parameters()), training_seconds=time.monotonic()-start,
                  training_device=str(device), worker_pid=os.getpid(), stability=stability,
                  peak_cuda_bytes=torch.cuda.max_memory_allocated(device) if cuda else 0)
    save_json(run_dir/"training_result.json", result)
    return result


# ---------------------------------------------------------------- copy gate
def rms_nearest(a, b, exclude=None, batch=512):
    """For each row of a, the RMS distance to its nearest row of b (pairs where exclude[i, j] is True skipped)."""
    a, b = torch.as_tensor(a, dtype=torch.float32), torch.as_tensor(b, dtype=torch.float32)
    out = []
    for i, part in enumerate(a.split(batch)):
        d = torch.cdist(part, b)/math.sqrt(a.shape[1])
        if exclude is not None:
            d = d.masked_fill(torch.as_tensor(exclude[i*batch:i*batch+len(part)]), float("inf"))
        out.append(d.min(1).values)
    return torch.cat(out).numpy()


def copy_rate(fake, fake_domain, train, train_domain, train_record, quantile=.01):
    """Share of fake windows closer (RMS, v3 view) to a training window of their domain than the quantile of the
    training windows' distance to their nearest training window of another record (per domain)."""
    rates, copies, total = {}, 0, 0
    for dom in sorted(set(fake_domain)):
        t = train_domain == dom
        rows, records = train[t], train_record[t]
        own = rms_nearest(rows, rows, records[:, None] == records[None])
        threshold = float(np.quantile(own[np.isfinite(own)], quantile))
        near = rms_nearest(fake[fake_domain == dom], rows)
        rates[dom] = dict(rate=float((near < threshold).mean()), threshold=threshold, median=float(np.median(near)),
                          train_median=float(np.median(own[np.isfinite(own)])), n=int(len(near)))
        copies += int((near < threshold).sum())
        total += len(near)
    return dict(rate=copies/total, per_domain=rates)
