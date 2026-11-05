"""PSF-GAN: a pure GAN (one generator, one set of discriminators, no likelihood model) for 30 s, 40 Hz PPG windows in
the project's v3 view (0.5-8 Hz band, per-window min-max), trained on the MIMIC-III shards of PPG-physiGPT and scored
on the same held-out people. Engineering model of normalised waveform shape; not clinical.

Why the earlier pure GANs (PhysioMix/RSH-GAN, LSM-GAN, PhysioGAN-R P5) stayed at strict-judge AUC ~1 and RSH-GAN at
tree accuracy 0.975 on the 22-feature benchmark, and what this file changes (engineering reading of the repository's
code and reports; P5 never reported a result):
- data: they trained on the multi-domain packs (thousands of windows, a few hundred people), small enough for the
  critic to memorise; ADA and halved critic rates were then needed to keep it from winning. Here: the 2.18 M training
  windows of the physiGPT shards (~30,000 ICU records), resident on the GPUs, so no augmentation is used;
- rhythm: an up-sampling convolution stack has to agree on every beat time across 30 s from a 25-sample seed, which
  shows as wrong beat regularity (acf_peak, ibi_cv, amp_cv, template_corr). Here the generator is source-filter
  (neural source-filter / DDSP style): a phase phi(t) = phi0 + 2 pi integral f(t) dt from a mean rate (the heart-rate
  condition, or a rate from the style when unconditional) and a smooth learnt rate variability; sin/cos of the first
  harmonics of phi enter every fine block, and the network shapes the pulse, its amplitude and baseline around it;
- view: the generator writes a 40 s record; a fixed zero-phase band-pass (|H|^2 of the v3 4th-order Butterworth,
  applied in the frequency domain) and a centre crop give the 30 s window, then min-max as the data. No network has
  to learn the stop band (as P5's RView);
- discriminators: HiFi-GAN's multi-period (sub-critics on samples spaced by prime periods) and multi-scale ones,
  plus a log-STFT critic (the strict judge's spectral view), each with projection on the heart-rate condition;
- losses: least-squares GAN + discriminator feature matching on batch means (Salimans et al. 2016) + the
  feature-distribution term of APFT-GAN v3 (gan.feature_distance, the feature tier's differentiable signal features);
- training: fp16 autocast with one gradient scaler per network, fused AdamW, an EMA generator for selection and
  release, one process per GPU with gradients all-reduced in one flat buffer, every --eval-every steps the 22-feature
  selection score on training records (gan.select_score), early stop by --patience, and a hold-then-decay learning
  rate.
Selection uses training records only; the decision is the target report on held-out people (stage puregan runs it).
"""
import argparse
import json
import copy
import math
from pathlib import Path
import time

import numpy as np
from scipy.signal import butter, sosfreqz
import torch
import torch.distributed as dist
from torch import nn
from torch.nn import functional as F
from torch.nn.utils.parametrizations import weight_norm

from ml.kaggle_lsm.train_lsm import save_json
from ml.kaggle_physigpt.gan import average, feature_distance, mean_over_ranks, save_state, select_score
from ml.kaggle_physigpt.judge_physigpt import all_features
from ml.kaggle_physigpt.mimic_wdb import rate_features
from ml.kaggle_physigpt.model import hr_embedding, window_rate
from ml.kaggle_physigpt.train import Windows, synthetic_shard, warm_cache

FS, WINDOW, RECORD = 40, 1200, 1600
CROP = (RECORD-WINDOW)//2
HARMONICS = 4
CONFIGS = {
    "tiny": dict(latent=32, wdim=64, base=25, channels=(64, 64, 48, 48, 32, 32, 16), d_width=8, mpd=(2, 3), scales=1),
    "base": dict(latent=128, wdim=256, base=25, channels=(384, 384, 256, 256, 192, 128, 64), d_width=32,
                 mpd=(2, 3, 5, 7, 11), scales=3),
}
SELECT_REAL = 2048


def band_mask(n=RECORD, fs=FS):
    """|H|^2 of the v3 band-pass (4th-order Butterworth 0.5-8 Hz, applied forward and back) on the rfft bins of n."""
    sos = butter(4, [.5, 8.], "bandpass", fs=fs, output="sos")
    _, h = sosfreqz(sos, worN=np.fft.rfftfreq(n, 1/fs), fs=fs)
    return torch.tensor(np.abs(h)**2, dtype=torch.float32)


def view(record, mask):
    """Raw records [n, RECORD] -> v3 windows [n, WINDOW] in [0, 1]: zero-phase band-pass, centre crop, min-max."""
    record = record.float()
    x = torch.fft.irfft(torch.fft.rfft(record-record.mean(1, keepdim=True), dim=1)*mask, n=record.shape[1], dim=1)
    x = x[:, CROP:CROP+WINDOW]
    lo, hi = x.amin(1, keepdim=True), x.amax(1, keepdim=True)
    return (x-lo)/(hi-lo).clamp_min(1e-6)


# ---------------------------------------------------------------- generator
class GenBlock(nn.Module):
    """x2 linear up-sampling, a residual pair of convolutions with a FiLM of the style, per-sample noise and the
    harmonic excitation at this resolution. The second convolution starts at zero (the block starts as its skip)."""

    def __init__(self, cin, cout, wdim):
        super().__init__()
        self.conv1, self.conv2 = nn.Conv1d(cin, cout, 5, padding=2), nn.Conv1d(cout, cout, 5, padding=2)
        nn.init.zeros_(self.conv2.weight), nn.init.zeros_(self.conv2.bias)
        self.film = nn.Linear(wdim, 2*cout)
        nn.init.zeros_(self.film.weight), nn.init.zeros_(self.film.bias)
        self.source = nn.Conv1d(2*HARMONICS, cout, 1)
        self.noise = nn.Parameter(torch.zeros(cout))
        self.skip = nn.Conv1d(cin, cout, 1) if cin != cout else nn.Identity()

    def forward(self, x, w, excitation, noise):
        x = F.interpolate(x, scale_factor=2, mode="linear", align_corners=False)
        h = self.conv1(F.leaky_relu(x, .2))+self.source(F.adaptive_avg_pool1d(excitation, x.shape[-1]))
        scale, shift = self.film(w).chunk(2, 1)
        h = h*(1+scale[:, :, None])+shift[:, :, None]+self.noise[None, :, None]*noise
        return self.skip(x)+self.conv2(F.leaky_relu(h, .2))


class SourceFilterGenerator(nn.Module):
    """(z [n, latent], hr [n] bpm or None) -> raw 40 s records [n, RECORD]; windows(...) applies the v3 view."""

    def __init__(self, latent, wdim, base, channels, hr_cond, **_):
        super().__init__()
        self.latent, self.base, self.hr_cond = latent, base, hr_cond
        if base*2**(len(channels)-1) != RECORD:
            raise ValueError("base * 2**(blocks) must be the record length")
        cond = 64 if hr_cond else 0
        layers, width = [], latent+cond
        for _ in range(4):
            layers += [nn.Linear(width, wdim), nn.LeakyReLU(.2)]
            width = wdim
        self.mapping = nn.Sequential(*layers)
        self.stem = nn.Linear(wdim, channels[0]*base)
        self.blocks = nn.ModuleList(GenBlock(a, b, wdim) for a, b in zip(channels[:-1], channels[1:]))
        self.out = nn.Conv1d(channels[-1], 1, 7, padding=3)
        # rhythm: the unconditional mean rate (35-180 bpm), 8 cosine/sine pairs of rate variability over the record
        # (zero at start: a constant rate), and the start phase
        self.rate = nn.Linear(wdim, 1)
        self.variability = nn.Linear(wdim, 16)
        nn.init.zeros_(self.variability.weight), nn.init.zeros_(self.variability.bias)
        self.phase = nn.Linear(wdim, 2)
        t = torch.arange(RECORD, dtype=torch.float32)/FS
        k = torch.arange(1, 9, dtype=torch.float32)
        basis = torch.cat((torch.cos(math.pi*k[:, None]*t/t[-1]), torch.sin(math.pi*k[:, None]*t/t[-1])))
        self.register_buffer("basis", basis, persistent=False)
        self.register_buffer("mask", band_mask(), persistent=False)

    def style(self, z, hr):
        if self.hr_cond:
            if hr is None:
                raise ValueError("this generator is heart-rate conditioned: pass hr (bpm)")
            z = torch.cat((z, hr_embedding(hr).to(z.dtype)), 1)
        return self.mapping(z)

    def excitation(self, w, hr):
        """sin/cos of the first HARMONICS harmonics of the pulse phase [n, 2*HARMONICS, RECORD] and the mean rate (bpm)."""
        if hr is None:
            bpm = 35.+145.*torch.sigmoid(self.rate(w).float()[:, 0])
        else:
            bpm = hr.float()
        mod = .3*torch.tanh(self.variability(w).float()@self.basis)          # log-rate modulation, within +-30 %
        f = bpm[:, None]/60.*torch.exp(mod)
        start = torch.atan2(*self.phase(w).float().unbind(1))
        phi = start[:, None]+2*math.pi*torch.cumsum(f, 1)/FS
        k = torch.arange(1, HARMONICS+1, device=w.device, dtype=torch.float32)[None, :, None]
        return torch.cat((torch.sin(k*phi[:, None]), torch.cos(k*phi[:, None])), 1), bpm

    def forward(self, z, hr=None, generator=None):
        w = self.style(z, hr)
        source, _ = self.excitation(w, hr)
        source = source.to(w.dtype)
        x = self.stem(w).view(len(z), -1, self.base)
        for block in self.blocks:
            noise = torch.randn(len(z), 1, x.shape[-1]*2, device=z.device, generator=generator, dtype=x.dtype)
            x = block(x, w, source, noise)
        return self.out(F.leaky_relu(x, .2))[:, 0]

    def windows(self, z, hr=None, generator=None):
        return view(self(z, hr, generator), self.mask)

    @torch.no_grad()
    def generate(self, n, steps=None, seed=0, device="cpu", hr=None, batch=512):
        """n v3 windows [n, WINDOW] (the signature of PhysiGPT.generate, so gan.select_score can score it)."""
        g = torch.Generator(device).manual_seed(seed)
        if hr is not None:
            hr = torch.as_tensor(hr, dtype=torch.float32, device=device).expand(n).contiguous()
        parts = []
        for i in range(0, n, batch):
            m = min(batch, n-i)
            z = torch.randn(m, self.latent, device=device, generator=g)
            parts.append(self.windows(z, None if hr is None else hr[i:i+m], g).float())
        return torch.cat(parts)


# ---------------------------------------------------------------- discriminators
class Projected(nn.Module):
    """Shared head: logits map from the last feature map plus the projection <embed(hr), pooled features>."""

    def __init__(self, channels, conv, hr_cond):
        super().__init__()
        self.final = conv
        self.embed = nn.Linear(64, channels) if hr_cond else None

    def forward(self, h, hr):
        # fp32: an LSGAN logit past ~256 overflows fp16 when squared (the v1 PSF-GAN run died of it at step ~4300)
        with torch.autocast(h.device.type, enabled=False):
            h = h.float()
            logits = self.final(h).flatten(1)
            if self.embed is not None:
                pooled = h.flatten(2).mean(-1)
                logits = logits+(self.embed(hr_embedding(hr))*pooled).sum(1, keepdim=True)
        return logits


class PeriodD(nn.Module):
    """HiFi-GAN sub-critic: the window folded into [T/p, p] and 2-D convolutions along the T/p axis."""

    def __init__(self, period, width, hr_cond):
        super().__init__()
        self.period = period
        c = (width, 4*width, 8*width, 8*width)
        self.convs = nn.ModuleList([weight_norm(nn.Conv2d(1, c[0], (5, 1), (3, 1), (2, 0))),
                                    weight_norm(nn.Conv2d(c[0], c[1], (5, 1), (3, 1), (2, 0))),
                                    weight_norm(nn.Conv2d(c[1], c[2], (5, 1), (3, 1), (2, 0))),
                                    weight_norm(nn.Conv2d(c[2], c[3], (5, 1), 1, (2, 0)))])
        self.head = Projected(c[3], weight_norm(nn.Conv2d(c[3], 1, (3, 1), 1, (1, 0))), hr_cond)

    def forward(self, x, hr):
        b, t = x.shape
        if t % self.period:
            x = F.pad(x, (0, self.period-t % self.period), mode="reflect")
        h = x.view(b, 1, -1, self.period)
        feats = []
        for conv in self.convs:
            h = F.leaky_relu(conv(h), .1)
            feats.append(h)
        return self.head(h, hr), feats


class ScaleD(nn.Module):
    """HiFi-GAN multi-scale sub-critic: strided grouped 1-D convolutions on the window (or a pooled copy)."""

    def __init__(self, width, hr_cond):
        super().__init__()
        c = (width, 2*width, 4*width, 8*width, 8*width)
        self.convs = nn.ModuleList([weight_norm(nn.Conv1d(1, c[0], 15, 1, 7)),
                                    weight_norm(nn.Conv1d(c[0], c[1], 41, 2, 20, groups=4)),
                                    weight_norm(nn.Conv1d(c[1], c[2], 41, 2, 20, groups=16)),
                                    weight_norm(nn.Conv1d(c[2], c[3], 41, 4, 20, groups=16)),
                                    weight_norm(nn.Conv1d(c[3], c[4], 5, 1, 2))])
        self.head = Projected(c[4], weight_norm(nn.Conv1d(c[4], 1, 3, 1, 1)), hr_cond)

    def forward(self, x, hr):
        h, feats = x[:, None], []
        for conv in self.convs:
            h = F.leaky_relu(conv(h), .1)
            feats.append(h)
        return self.head(h, hr), feats


class SpectralD(nn.Module):
    """Critic on the log-magnitude STFT (128-sample Hann frames, hop 8), the strict judge's spectral view."""

    def __init__(self, width, hr_cond):
        super().__init__()
        c = (width, 2*width, 4*width)
        self.register_buffer("window", torch.hann_window(128), persistent=False)
        self.convs = nn.ModuleList([weight_norm(nn.Conv2d(1, c[0], (3, 9), (1, 1), (1, 4))),
                                    weight_norm(nn.Conv2d(c[0], c[1], (3, 9), (2, 2), (1, 4))),
                                    weight_norm(nn.Conv2d(c[1], c[2], (3, 9), (2, 2), (1, 4))),
                                    weight_norm(nn.Conv2d(c[2], c[2], (3, 3), 1, (1, 1)))])
        self.head = Projected(c[2], weight_norm(nn.Conv2d(c[2], 1, (3, 3), 1, (1, 1))), hr_cond)

    def forward(self, x, hr):
        spec = torch.stft(x.float()-.5, 128, 8, window=self.window, return_complex=True).abs()
        h, feats = torch.log(spec+1e-4)[:, None].to(x.dtype), []
        for conv in self.convs:
            h = F.leaky_relu(conv(h), .1)
            feats.append(h)
        return self.head(h, hr), feats


class Discriminators(nn.Module):
    def __init__(self, d_width, mpd, scales, hr_cond, **_):
        super().__init__()
        self.subs = nn.ModuleList([PeriodD(p, d_width, hr_cond) for p in mpd]
                                  + [ScaleD(d_width, hr_cond) for _ in range(scales)]
                                  + [SpectralD(d_width, hr_cond)])
        self.pools = [0]*len(mpd)+[2**i for i in range(scales)]+[0]

    def forward(self, x, hr):
        """[n, WINDOW] -> list of (logits [n, ...], feature maps) per sub-critic."""
        out = []
        for sub, pool in zip(self.subs, self.pools):
            y = F.avg_pool1d(x[:, None], pool, pool)[:, 0] if pool > 1 else x
            out.append(sub(y, hr))
        return out


def d_loss(real_out, fake_out):
    """Least-squares GAN critic loss summed over the sub-critics (in fp32)."""
    return sum((r.float()-1).square().mean()+f.float().square().mean() for (r, _), (f, _) in zip(real_out, fake_out))


def g_terms(real_out, fake_out):
    """Least-squares generator loss and feature matching of batch means of every critic feature map."""
    adv = sum((f.float()-1).square().mean() for f, _ in fake_out)
    fm = sum((rf.detach().float().mean(0)-ff.float().mean(0)).abs().mean() for (_, r), (_, f) in zip(real_out, fake_out)
             for rf, ff in zip(r, f))/len(fake_out)
    return adv, fm


# ---------------------------------------------------------------- data
class DeviceWindows:
    """This rank's share of the training windows (rows rank::world) resident on its device as uint16, drawn per step
    on the device: no host loader, no page faults. Falls back to host memory if the device lacks room."""

    def __init__(self, data, rank, world, device, reserve_gb):
        rows = data.train[rank::world]
        need = len(rows)*WINDOW*2
        on_device = device.type == "cuda" and (torch.cuda.mem_get_info(device)[0]-need)/2**30 > reserve_gb
        host = np.empty((len(rows), WINDOW), np.uint16)
        for i in range(0, len(rows), 65536):
            host[i:i+65536] = data.rows(rows[i:i+65536])
        # int16 holds the uint16 bits; the sign is undone in draw()
        store = torch.from_numpy(host.view(np.int16))
        self.store = store.to(device) if on_device else store.pin_memory() if device.type == "cuda" else store
        self.device, self.on_device, self.n = device, on_device, len(rows)
        self.gb = need/2**30
        self.host_gen = None if on_device else torch.Generator().manual_seed(rank)

    def draw(self, n, generator):
        g = generator if self.on_device else self.host_gen
        index = torch.randint(self.n, (n,), device=self.store.device, generator=g)
        x = self.store[index].to(self.device, non_blocking=True).to(torch.int32) & 0xFFFF
        return x.float()/65535


# ---------------------------------------------------------------- training
def hold_decay(progress, peak, decay_frac, floor=.1):
    """Learning rate at progress in [0, 1] (the larger of the step share and the time share of the budget): the peak,
    then linear to floor*peak over the last decay_frac, so the decay happens inside the kernel's time."""
    start = 1-decay_frac
    return peak if progress < start else peak*(1-(1-floor)*min(1., (progress-start)/max(1e-9, decay_frac)))


def logit_max(outs):
    """Largest |logit| over the sub-critics (a tensor; read it only when logging)."""
    return torch.stack([o.detach().float().abs().amax() for o, _ in outs]).amax()


def to_cpu(state):
    """A copy of a (nested) state dict with every tensor on the host."""
    if torch.is_tensor(state):
        return state.detach().cpu().clone()
    if isinstance(state, dict):
        return {k: to_cpu(v) for k, v in state.items()}
    if isinstance(state, (list, tuple)):
        return type(state)(to_cpu(v) for v in state)
    return copy.deepcopy(state)


def snapshot(**modules):
    """Host copies of the state dicts of modules, optimisers and scalers: the state a non-finite run rolls back to."""
    return {k: to_cpu(m.state_dict()) for k, m in modules.items()}


def worker(rank, world, args):
    cuda = torch.cuda.is_available() and not args.cpu
    if world > 1:
        dist.init_process_group("nccl" if cuda else "gloo", init_method=f"tcp://127.0.0.1:{args.port}", rank=rank,
                                world_size=world)
    device = torch.device(f"cuda:{rank}" if cuda else "cpu")
    if cuda:
        torch.cuda.set_device(device)
        torch.backends.cudnn.benchmark = True
        torch.backends.cuda.matmul.allow_tf32 = True
    torch.set_num_threads(max(1, args.threads//world))
    begin, output = time.time(), Path(args.output)
    cfg = CONFIGS[args.config]
    torch.manual_seed(args.seed)   # identical initial weights on every rank
    G = SourceFilterGenerator(hr_cond=args.hr_cond, **cfg).to(device)
    D = Discriminators(hr_cond=args.hr_cond, **cfg).to(device)
    ema = SourceFilterGenerator(hr_cond=args.hr_cond, **cfg).to(device).eval().requires_grad_(False)
    ema.load_state_dict(G.state_dict())
    fused = dict(fused=True) if cuda else {}
    g_opt = torch.optim.AdamW(G.parameters(), lr=args.lr, betas=(.8, .99), weight_decay=0., **fused)
    d_opt = torch.optim.AdamW(D.parameters(), lr=args.d_lr, betas=(.8, .99), weight_decay=0., **fused)
    g_scaler, d_scaler = torch.amp.GradScaler("cuda", enabled=cuda), torch.amp.GradScaler("cuda", enabled=cuda)
    data = Windows(args.data)
    selection = np.sort(np.random.default_rng(20261105).choice(data.train, min(SELECT_REAL, len(data.train)),
                                                                replace=False))
    sel = data.rows(selection).astype(np.float32)/65535
    real_features = all_features(sel)
    hr_bank = rate_features(sel)[1].astype(np.float32) if args.hr_cond else None
    del sel
    step, best, stale, stop_reason = 0, dict(step=None, mean_similarity=-math.inf), 0, "steps"
    # non-finite guard: GradScaler skips a step with inf/NaN gradients and halves its scale, so a loss that stays
    # non-finite drives the scale to 0 and the run never recovers (v1: from step ~4300 on). After --nan-patience bad
    # steps in a row the run returns to the last good snapshot with the lr scaled by .5; --max-rollbacks ends it.
    lr_factor, rollbacks, bad_run, bad_total = 1., 0, 0, 0
    if args.resume:
        state = torch.load(args.resume, map_location=device, weights_only=False)
        G.load_state_dict(state["G"]), D.load_state_dict(state["D"]), ema.load_state_dict(state["ema"])
        g_opt.load_state_dict(state["g_opt"]), d_opt.load_state_dict(state["d_opt"])
        g_scaler.load_state_dict(state["g_scaler"]), d_scaler.load_state_dict(state["d_scaler"])
        step, best, stale = state["step"], state["best"], state["stale"]
        lr_factor, rollbacks = state.get("lr_factor", 1.), state.get("rollbacks", 0)
        del state
    if rank == 0:
        output.mkdir(parents=True, exist_ok=True)
        print(f"warm cache: {warm_cache(data)/2**30:.2f} GB", flush=True)
    if world > 1:
        dist.barrier()
    loaded = time.time()
    windows = DeviceWindows(data, rank, world, device, args.reserve_gb)
    if rank == 0:
        save_json(output/"run_config.json", dict(
            vars(args), world=world, config=cfg, g_parameters=sum(p.numel() for p in G.parameters()),
            d_parameters=sum(p.numel() for p in D.parameters()), train_windows=int(len(data.train)),
            windows_per_rank=windows.n, data_on_device=windows.on_device, data_gb_per_rank=round(windows.gb, 2),
            load_seconds=round(time.time()-loaded, 1), shards=data.shards, start_step=step))
    g_params, d_params = list(G.parameters()), list(D.parameters())
    log = (output/"metrics.jsonl").open("a") if rank == 0 else None
    gen = torch.Generator(device).manual_seed(args.seed*1_000_003+rank)
    last_save, tick, step_seconds = time.time(), None, None
    nets = dict(G=G, D=D, ema=ema, g_opt=g_opt, d_opt=d_opt, g_scaler=g_scaler, d_scaler=d_scaler)
    good = snapshot(**nets)

    def checkpoint_select(at):
        nonlocal best, stale
        if rank == 0:
            record = dict(step=at, select=select_score(ema, real_features, None, device, hr_bank),
                          hours=round((time.time()-begin)/3600, 4))
            if record["select"]["mean_similarity"] > best["mean_similarity"]:
                best, stale = dict(step=at, mean_similarity=record["select"]["mean_similarity"]), 0
                torch.save(dict(kind="pure_gan", config=args.config, hr_cond=args.hr_cond, generator=ema.state_dict(),
                                hr_bank=hr_bank, step=at, select=record["select"]), output/"gan_release.pt")
            elif at > 0:
                stale += 1
            record.update(best=best, stale=stale)
            log.write(json.dumps(record)+"\n")
            log.flush()
            print(json.dumps(record), flush=True)
        if world > 1:
            dist.barrier()

    if step == 0:
        checkpoint_select(0)
    while step < args.steps:
        logging = step % args.log_every == 0
        budget = max(1., args.hours*3600-args.reserve_minutes*60)
        progress = torch.tensor(max(step/args.steps, (time.time()-begin)/budget), device=device)
        if world > 1:
            dist.broadcast(progress, 0)   # rank 0's clock: the same rate on every rank
        progress = float(progress)
        lr_g = lr_factor*hold_decay(progress, args.lr, args.decay_frac)
        for group in g_opt.param_groups:
            group["lr"] = lr_g
        for group in d_opt.param_groups:
            group["lr"] = lr_factor*hold_decay(progress, args.d_lr, args.decay_frac)
        real = windows.draw(args.batch, gen)
        hr_real = window_rate(real) if args.hr_cond else None
        hr_fake = hr_real[torch.randperm(args.batch, device=device, generator=gen)] if args.hr_cond else None
        z = torch.randn(args.batch, G.latent, device=device, generator=gen)

        # critics
        D.requires_grad_(True)
        with torch.autocast("cuda", torch.float16, enabled=cuda):
            fake = G.windows(z, hr_fake, gen)
            d_real_out, d_fake_out = D(real, hr_real), D(fake.detach(), hr_fake)
            loss_d = d_loss(d_real_out, d_fake_out)
        d_max = torch.maximum(logit_max(d_real_out), logit_max(d_fake_out))
        del d_real_out, d_fake_out
        d_opt.zero_grad(set_to_none=True)
        d_scaler.scale(loss_d).backward()
        average(d_params, world)
        d_scaler.unscale_(d_opt)
        d_grad = torch.nn.utils.clip_grad_norm_(d_params, args.clip)
        d_scaler.step(d_opt)
        d_scaler.update()

        # generator
        D.requires_grad_(False)
        with torch.autocast("cuda", torch.float16, enabled=cuda):
            with torch.no_grad():
                real_out = D(real, hr_real)
            adv, fm = g_terms(real_out, D(fake, hr_fake))
        feat = feature_distance(fake.float(), real) if args.feature_weight else adv.new_zeros(())
        loss_g = adv+args.fm_weight*fm+args.feature_weight*feat
        g_opt.zero_grad(set_to_none=True)
        g_scaler.scale(loss_g).backward()
        average(g_params, world)
        g_scaler.unscale_(g_opt)
        g_grad = torch.nn.utils.clip_grad_norm_(g_params, args.clip)
        g_scaler.step(g_opt)
        g_scaler.update()
        # a loss or an (unscaled) gradient norm that is not finite; one now and then is the scaler finding its level
        bad = (~torch.isfinite(loss_d.detach()+loss_g.detach()+d_grad+g_grad)).float()
        if world > 1:
            dist.all_reduce(bad, op=dist.ReduceOp.MAX)
        if bad.item():
            bad_run, bad_total = bad_run+1, bad_total+1
        else:
            bad_run = 0
        if bad_run >= args.nan_patience:
            rollbacks += 1
            if rollbacks > args.max_rollbacks:
                stop_reason = "nonfinite"
            else:
                for k, m in nets.items():
                    m.load_state_dict(good[k])
                lr_factor *= .5
                bad_run = 0
            if rank == 0:
                print(json.dumps(dict(step=step+1, rollback=rollbacks, lr_factor=lr_factor, stop_reason=stop_reason,
                                      d_logit_max=float(d_max))), flush=True)
            if stop_reason != "steps":
                break
            step += 1
            continue
        with torch.no_grad():
            decay = min(args.ema, (1+step)/(10+step))
            for e, p in zip(ema.parameters(), G.parameters()):
                e.lerp_(p, 1-decay)
        step += 1
        if step == 20:
            if cuda:
                torch.cuda.synchronize(device)
            tick = time.time()
        elif step == 120 and tick:
            if cuda:
                torch.cuda.synchronize(device)
            step_seconds = (time.time()-tick)/100
        stop = torch.tensor(float(time.time()-begin > args.hours*3600-args.reserve_minutes*60), device=device)
        if world > 1:
            dist.broadcast(stop, 0)
        stop = bool(stop.item())
        if rank == 0 and (logging or stop):
            record = dict(step=step, loss_d=float(loss_d.detach()), adv=float(adv.detach()), fm=float(fm.detach()),
                          feat=float(feat.detach()), d_grad=float(d_grad), g_grad=float(g_grad), lr=lr_g, g_scale=float(g_scaler.get_scale()),
                          d_scale=float(d_scaler.get_scale()), d_logit_max=float(d_max), bad_steps=bad_total,
                          rollbacks=rollbacks, lr_factor=lr_factor, hours=round((time.time()-begin)/3600, 4),
                          step_seconds=step_seconds, windows_per_second=None if not step_seconds else
                          round(args.batch*world/step_seconds),
                          max_memory_gb=torch.cuda.max_memory_allocated(device)/2**30 if cuda else None)
            if args.hr_cond:
                record["hr_mae"] = float((window_rate(fake.detach().float())-hr_fake).abs().mean())
            log.write(json.dumps(record)+"\n")
            log.flush()
            print(json.dumps(record), flush=True)
        if step % args.eval_every == 0 or step == args.steps or stop:
            checkpoint_select(step)
            if bad_run == 0:
                good = snapshot(**nets)
            exhausted = torch.tensor(float(args.patience > 0 and stale >= args.patience), device=device)
            if world > 1:
                dist.broadcast(exhausted, 0)
            if exhausted.item() and step < args.steps:
                stop_reason = "patience"
        if stop:
            stop_reason = "hours"
        if rank == 0 and (time.time()-last_save > args.save_minutes*60 or step == args.steps or stop_reason != "steps"):
            save_state(output/"last.pt", G=G.state_dict(), D=D.state_dict(), ema=ema.state_dict(),
                       g_opt=g_opt.state_dict(), d_opt=d_opt.state_dict(), g_scaler=g_scaler.state_dict(),
                       d_scaler=d_scaler.state_dict(), step=step, best=best, stale=stale, config=args.config,
                       lr_factor=lr_factor, rollbacks=rollbacks)
            last_save = time.time()
        if stop_reason != "steps":
            break
    if rank == 0:
        save_json(output/"gan_summary.json", dict(
            steps=step, planned=args.steps, hours=(time.time()-begin)/3600, stop_reason=stop_reason, best=best,
            stale_evals=stale, patience=args.patience, bad_steps=bad_total, rollbacks=rollbacks, lr_factor=lr_factor, step_seconds=step_seconds, hr_cond=args.hr_cond,
            windows_per_second=None if not step_seconds else round(args.batch*world/step_seconds),
            max_memory_gb=torch.cuda.max_memory_allocated(device)/2**30 if cuda else None,
            note="selection on training records only; the decision is the target report on held-out people"))
        log.close()
    if world > 1:
        dist.barrier()
        dist.destroy_process_group()


def load_release(path, device="cpu"):
    state = torch.load(path, map_location=device, weights_only=False)
    model = SourceFilterGenerator(hr_cond=state["hr_cond"], **CONFIGS[state["config"]]).to(device).eval()
    model.load_state_dict(state["generator"])
    return model, state


def generate_release(path, n, seed, device):
    """n windows of a release; a conditional one asks for rates drawn from its real-rate bank."""
    model, state = load_release(path, device)
    hr = np.random.default_rng(seed).choice(np.asarray(state["hr_bank"]), n) if state["hr_cond"] else None
    return model.generate(n, seed=seed, device=device, hr=hr).cpu().numpy()


def smoke(root, steps=6):
    """A few steps of the tiny config on synthetic windows through the device path before the kernel spends hours."""
    root = Path(root)
    if not (root/"shard"/"manifest.json").exists():
        synthetic_shard(root/"shard")
    main(["--data", str(root/"shard"), "--output", str(root/"run"), "--config", "tiny", "--steps", str(steps),
          "--batch", "8", "--eval-every", "3", "--log-every", "1", "--port", "29525", "--hr-cond"])
    return json.loads((root/"run"/"gan_summary.json").read_text())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", nargs="+", required=True, help="roots holding the shards (manifest.json)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="base", choices=sorted(CONFIGS))
    parser.add_argument("--resume", default=None, help="last.pt of this run after a stop")
    parser.add_argument("--hr-cond", action="store_true", help="condition generator and critics on the heart rate")
    parser.add_argument("--steps", type=int, default=200_000, help="planned steps (the lr decay is placed on these)")
    parser.add_argument("--batch", type=int, default=128, help="windows per device per step")
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--d-lr", type=float, default=2e-4)
    parser.add_argument("--decay-frac", type=float, default=.2, help="share of the planned steps with a falling lr")
    parser.add_argument("--fm-weight", type=float, default=2., help="critic feature matching (batch means)")
    parser.add_argument("--feature-weight", type=float, default=1., help="feature-distribution term (0: off)")
    parser.add_argument("--ema", type=float, default=.999)
    parser.add_argument("--clip", type=float, default=10.)
    parser.add_argument("--hours", type=float, default=11.)
    parser.add_argument("--reserve-minutes", type=float, default=10.)
    parser.add_argument("--reserve-gb", type=float, default=6., help="device memory kept free when loading the data")
    parser.add_argument("--save-minutes", type=float, default=30.)
    parser.add_argument("--log-every", type=int, default=200)
    parser.add_argument("--eval-every", type=int, default=2000)
    parser.add_argument("--patience", type=int, default=10,
                        help="stop after this many evaluations in a row without a new best (0: no early stop)")
    parser.add_argument("--nan-patience", type=int, default=20,
                        help="non-finite steps in a row before the run returns to its last good snapshot")
    parser.add_argument("--max-rollbacks", type=int, default=3, help="rollbacks before the run ends (stop: nonfinite)")
    parser.add_argument("--threads", type=int, default=4, help="CPU threads shared by the ranks")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--port", type=int, default=29531)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--cpu-world", type=int, default=1)
    args = parser.parse_args(argv)
    world = args.cpu_world if args.cpu or not torch.cuda.is_available() else torch.cuda.device_count()
    if world > 1:
        torch.multiprocessing.spawn(worker, args=(world, args), nprocs=world, join=True)
    else:
        worker(0, 1, args)


if __name__ == "__main__":
    main()
