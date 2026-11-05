"""PPG-physiGPT: a decoder-only patch transformer for 30 s, 40 Hz PPG, after GPT-PPG (Chen et al. 2025).

Kept from GPT-PPG: 30 non-overlapping 1 s patches (40 samples) per window, a linear patch embedding, a learnable
start vector in place of the first input (the model reads patches 1..29 and predicts 1..30), pre-norm RMSNorm,
rotary position embedding, causal attention, and its logit-Laplace signal head (mu, b per sample, after mapping the
per-window min-max value x to 0.1 + 0.8 x).

Changed, and why:
- the start vector is a per-domain embedding (MIMIC-III ICU first; the project's finger/wrist domains are added at
  fine-tuning), so one backbone serves several sensor domains;
- SwiGLU feed-forward (GPT-PPG does not name its backbone activation);
- a flow-matching patch head (as the diffusion head of Li et al. 2024, autoregression without vector quantisation):
  the logit-Laplace head treats the 40 samples of a patch as independent given the context, so sampling from it
  adds white noise inside every patch, which the strict judge's STFT view sees. The flow head models the patch
  jointly: a residual MLP with adaptive layer norm on the token's hidden state and the flow time predicts the
  velocity of a straight path from Gaussian noise to the patch. Sampling is autoregressive over the 30 patches with
  a Heun ODE per patch. The logit-Laplace head stays as an auxiliary loss and gives GPT-PPG's likelihood.
- optional heart-rate condition (Config.hr_cond, off in every released checkpoint): a Fourier embedding of the
  window's rate in bpm, through a zero-initialised MLP, added to every input token, so a model built with it starts
  exactly as the checkpoint it is loaded from (load_init) and learns the condition at fine-tuning. The rate label of a
  real window is window_rate, the autocorrelation rate of the feature tier's rate_bpm (30-200 bpm).
Sizes are chosen for two T4s (fp16): "base" 30.7 M parameters (backbone 25.3 M), "large" 99.9 M (backbone 85.0 M,
GPT-PPG's 85 M class).
"""
from dataclasses import asdict, dataclass, replace
import math

import torch
from torch import nn
import torch.nn.functional as F

DOMAINS = ("mimic3_icu",)  # index = domain id; later domains are appended, never reordered
LAPLACE_LO, LAPLACE_SPAN = .1, .8
HR_FEATURES = 32                       # Fourier pairs of the rate embedding
RATE_LAGS = (12, 80)                   # 40 Hz lags 0.3-2.0 s, as mimic_wdb.RATE_LAGS (30-200 bpm)


def window_rate(x, fs=40):
    """Autocorrelation rate (bpm) of windows x [n, L], as mimic_wdb.rate_features (the feature tier's rate_bpm)."""
    x = x.float()
    centered = x-x.mean(1, keepdim=True)
    spectrum = torch.fft.rfft(centered, 2*x.shape[1], dim=1)
    acf = torch.fft.irfft(spectrum.abs().square(), dim=1)[:, :x.shape[1]]
    lo, hi = RATE_LAGS
    lag = lo+acf[:, lo:hi].argmax(1)
    return 60.*fs/lag.float()


def hr_embedding(bpm):
    """[n] bpm -> [n, 2*HR_FEATURES] Fourier features of log(bpm/30), which spans 0..~2 over 30-200 bpm."""
    u = torch.log(bpm.float().clamp(20., 250.)/30.)
    freq = torch.exp(torch.linspace(0., math.log(64.), HR_FEATURES, device=bpm.device))
    return torch.cat(((u[:, None]*freq).sin(), (u[:, None]*freq).cos()), -1)


@dataclass(frozen=True)
class Config:
    patch: int = 40
    patches: int = 30
    dim: int = 512
    layers: int = 8
    heads: int = 8
    ffn: int = 1376
    domain_slots: int = 8
    head_width: int = 512
    head_blocks: int = 3
    rope_base: float = 10000.
    hr_cond: bool = False


CONFIGS = {"tiny": Config(dim=64, layers=2, heads=4, ffn=176, head_width=64, head_blocks=1),
           "base": Config(),
           "large": Config(dim=768, layers=12, heads=12, ffn=2048, head_width=768, head_blocks=4)}


class RMSNorm(nn.Module):
    def __init__(self, dim, eps=1e-6):
        super().__init__()
        self.weight, self.eps = nn.Parameter(torch.ones(dim)), eps

    def forward(self, x):
        x32 = x.float()
        return (x32*torch.rsqrt(x32.square().mean(-1, keepdim=True)+self.eps)).type_as(x)*self.weight


def rope_tables(length, head_dim, base):
    inv = 1/base**(torch.arange(0, head_dim, 2).float()/head_dim)
    angle = torch.outer(torch.arange(length).float(), inv)
    return angle.cos(), angle.sin()


def rotate(x, cos, sin):
    a, b = x[..., ::2], x[..., 1::2]
    return torch.stack((a*cos-b*sin, a*sin+b*cos), -1).flatten(-2)


class Block(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.heads = cfg.heads
        self.norm1, self.norm2 = RMSNorm(cfg.dim), RMSNorm(cfg.dim)
        self.qkv = nn.Linear(cfg.dim, 3*cfg.dim, bias=False)
        self.out = nn.Linear(cfg.dim, cfg.dim, bias=False)
        self.gate_up = nn.Linear(cfg.dim, 2*cfg.ffn, bias=False)
        self.down = nn.Linear(cfg.ffn, cfg.dim, bias=False)

    def forward(self, x, cos, sin):
        b, t, d = x.shape
        q, k, v = self.qkv(self.norm1(x)).view(b, t, 3, self.heads, d//self.heads).permute(2, 0, 3, 1, 4)
        q, k = rotate(q, cos[:t], sin[:t]).type_as(v), rotate(k, cos[:t], sin[:t]).type_as(v)
        x = x+self.out(F.scaled_dot_product_attention(q, k, v, is_causal=True).transpose(1, 2).reshape(b, t, d))
        gate, up = self.gate_up(self.norm2(x)).chunk(2, -1)
        return x+self.down(F.silu(gate)*up)


def time_embedding(t, dim):
    half = dim//2
    freq = torch.exp(-math.log(10000.)*torch.arange(half, device=t.device).float()/half)
    angle = t.float()[:, None]*1000*freq[None]
    return torch.cat((angle.cos(), angle.sin()), -1)


class FlowHead(nn.Module):
    """Velocity v(x_t, t | h) of the straight noise-to-patch path; adaptive-LN residual MLP, zero-initialised out."""

    def __init__(self, cfg):
        super().__init__()
        w = cfg.head_width
        self.inp = nn.Linear(cfg.patch, w)
        self.cond = nn.Linear(cfg.dim, w)
        self.time = nn.Sequential(nn.Linear(w, w), nn.SiLU(), nn.Linear(w, w))
        self.blocks = nn.ModuleList(nn.ModuleDict(dict(
            norm=nn.LayerNorm(w, elementwise_affine=False), mod=nn.Linear(w, 3*w),
            mlp=nn.Sequential(nn.Linear(w, w), nn.SiLU(), nn.Linear(w, w)))) for _ in range(cfg.head_blocks))
        self.final_norm = nn.LayerNorm(w, elementwise_affine=False)
        self.final_mod = nn.Linear(w, 2*w)
        self.outp = nn.Linear(w, cfg.patch)
        for block in self.blocks:
            nn.init.zeros_(block["mod"].weight), nn.init.zeros_(block["mod"].bias)
        nn.init.zeros_(self.final_mod.weight), nn.init.zeros_(self.final_mod.bias)
        nn.init.zeros_(self.outp.weight), nn.init.zeros_(self.outp.bias)

    def forward(self, xt, t, h):
        c = F.silu(self.cond(h)+self.time(time_embedding(t, self.inp.out_features)))
        x = self.inp(xt)
        for block in self.blocks:
            shift, scale, gate = block["mod"](c).chunk(3, -1)
            x = x+gate*block["mlp"](block["norm"](x)*(1+scale)+shift)
        shift, scale = self.final_mod(c).chunk(2, -1)
        return self.outp(self.final_norm(x)*(1+scale)+shift)


class PhysiGPT(nn.Module):
    def __init__(self, cfg=Config()):
        super().__init__()
        if cfg.dim % cfg.heads or (cfg.dim//cfg.heads) % 2:
            raise ValueError("dim must split into heads of even size")
        self.cfg = cfg
        self.start = nn.Embedding(cfg.domain_slots, cfg.dim)
        self.embed = nn.Linear(cfg.patch, cfg.dim)
        self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.layers))
        self.norm = RMSNorm(cfg.dim)
        self.laplace = nn.Linear(cfg.dim, 2*cfg.patch)
        self.flow = FlowHead(cfg)
        if cfg.hr_cond:
            self.hr = nn.Sequential(nn.Linear(2*HR_FEATURES, cfg.dim), nn.SiLU(), nn.Linear(cfg.dim, cfg.dim))
        cos, sin = rope_tables(cfg.patches, cfg.dim//cfg.heads, cfg.rope_base)
        self.register_buffer("cos", cos, persistent=False)
        self.register_buffer("sin", sin, persistent=False)
        for name, p in self.named_parameters():
            if p.dim() == 2 and not name.startswith("flow."):
                nn.init.normal_(p, std=.02/math.sqrt(2*cfg.layers) if name.endswith(("out.weight", "down.weight"))
                                else .02)
        if cfg.hr_cond:   # zero output: a loaded unconditional model is unchanged until fine-tuning moves it
            nn.init.zeros_(self.hr[2].weight), nn.init.zeros_(self.hr[2].bias)

    def hidden(self, patches, domain, hr=None):
        """patches [B, n<=30, 40] of x in [0, 1] -> h [B, n, dim]; h_i depends on the domain, the rate hr [B] (bpm,
        hr_cond models only) and patches < i only."""
        x = self.embed(2*patches[:, :-1]-1)
        x = torch.cat((self.start(domain)[:, None], x), 1)
        if self.cfg.hr_cond:
            if hr is None:
                raise ValueError("this model is heart-rate conditioned: pass hr (bpm)")
            x = x+self.hr(hr_embedding(hr).to(x.dtype))[:, None]
        for block in self.blocks:
            x = block(x, self.cos, self.sin)
        return self.norm(x)

    def laplace_nll(self, h, patches):
        """Per-sample logit-Laplace negative log density of x (in nats, including the 0.1 + 0.8 x Jacobian)."""
        mu, log_b = self.laplace(h).float().chunk(2, -1)
        log_b = log_b.clamp(-7, 5)
        y = LAPLACE_LO+LAPLACE_SPAN*patches.float()
        u = torch.log(y)-torch.log1p(-y)
        return ((u-mu).abs()*torch.exp(-log_b)+log_b+math.log(2)+torch.log(y)+torch.log1p(-y)
                - math.log(LAPLACE_SPAN))

    def flow_loss(self, h, patches, repeats=4, generator=None, diff=0.):
        b, n, p = patches.shape
        h = h.reshape(b*n, -1).repeat(repeats, 1)
        x1 = (2*patches.reshape(b*n, p)-1).repeat(repeats, 1)
        x0 = torch.randn(x1.shape, device=x1.device, generator=generator)
        # logit-normal flow time (Esser et al. 2024) weights the middle of the path where the patch shape is decided
        t = torch.sigmoid(torch.randn(len(x1), device=x1.device, generator=generator))
        xt = (1-t[:, None])*x0+t[:, None]*x1
        v = self.flow(xt.to(h.dtype), t, h)
        error = v.float()-(x1-x0).float()
        flow = error.square().mean()
        if not diff:
            return flow, flow.new_zeros(())
        # The velocity error is white, so it under-weights the sharp detail the judge reads. The error of the
        # one-step estimate x1_hat = xt + (1-t) v, differenced once and twice inside the patch, weights it back.
        err = (1-t[:, None])*error
        return flow, (torch.diff(err, 1, -1).square().mean()+torch.diff(err, 2, -1).square().mean())

    def forward(self, signal, domain, aux=.1, repeats=4, generator=None, diff=0., hr=None):
        patches = signal.view(len(signal), self.cfg.patches, self.cfg.patch)
        h = self.hidden(patches, domain, hr)
        nll = self.laplace_nll(h, patches).mean()
        flow, sharp = self.flow_loss(h, patches, repeats, generator, diff)
        parts = dict(flow=flow.detach(), laplace_nll=nll.detach())
        if diff:
            parts["sharp"] = sharp.detach()
        return flow+aux*nll+diff*sharp, parts

    def integrate(self, x, h, steps, flow=None):
        """Heun ODE of the flow head from the start noise x [n, 40] to a patch in [-1, 1] (unclipped). flow replaces
        self.flow (a gradient-checkpointed call in adversarial fine-tuning); without no_grad, it is differentiable."""
        flow = flow or self.flow
        dt = 1/steps
        for i in range(steps):
            t = torch.full((len(h),), i*dt, device=h.device)
            v = flow(x.to(h.dtype), t, h).float()
            if i < steps-1:
                v2 = flow((x+dt*v).to(h.dtype), t+dt, h).float()
                v = (v+v2)/2
            x = x+dt*v
        return x

    @torch.no_grad()
    def sample_patch(self, h, steps, generator=None, clamp=True):
        x = (self.integrate(torch.randn(len(h), self.cfg.patch, device=h.device, generator=generator), h, steps)+1)/2
        return x.clamp(0, 1) if clamp else x

    @torch.no_grad()
    def generate(self, n, domain=0, steps=32, seed=0, device="cpu", clamp=True, hr=None):
        """n windows [n, 1200], each min-max normalised like the training windows. clamp=False leaves the sampled
        patches (also the context fed back) unclipped to [0, 1]; the window min-max then sets the range. hr: the
        rate (bpm) per window, [n] or a number, for hr_cond models."""
        generator = torch.Generator(device).manual_seed(seed)
        domain = torch.full((n,), domain, dtype=torch.long, device=device)
        if hr is not None:
            hr = torch.as_tensor(hr, dtype=torch.float32, device=device).expand(n).contiguous()
        patches = torch.zeros(n, 1, self.cfg.patch, device=device)
        for i in range(self.cfg.patches):
            h = self.hidden(patches, domain, hr)[:, i]
            patches[:, i] = self.sample_patch(h, steps, generator, clamp)
            if i < self.cfg.patches-1:
                patches = torch.cat((patches, torch.zeros_like(patches[:, :1])), 1)
        x = patches.reshape(n, -1)
        lo, hi = x.min(1, keepdim=True).values, x.max(1, keepdim=True).values
        return (x-lo)/(hi-lo).clamp_min(1e-6)


def build(state):
    """The model of a saved state dict (config name, hr_cond flag) with its weights."""
    model = PhysiGPT(replace(CONFIGS[state["config"]], hr_cond=bool(state.get("hr_cond", False))))
    model.load_state_dict(state["model"])
    return model


def load_init(model, state):
    """Weights of state into model; only an added rate embedding (hr.*) may be missing, nothing may be unexpected."""
    missing, unexpected = model.load_state_dict(state["model"], strict=False)
    if unexpected or any(not k.startswith("hr.") for k in missing):
        raise ValueError(f"--init does not fit this model: missing {missing}, unexpected {unexpected}")
    return [k for k in missing]


def describe(model):
    return dict(config=asdict(model.cfg), parameters=sum(p.numel() for p in model.parameters()),
                backbone_parameters=sum(p.numel() for n, p in model.named_parameters()
                                        if not n.startswith(("flow.", "laplace."))),
                domains=list(DOMAINS))
