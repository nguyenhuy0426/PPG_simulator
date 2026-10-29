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
Sizes are chosen for two T4s (fp16): "base" 30.7 M parameters (backbone 25.3 M), "large" 99.9 M (backbone 85.0 M,
GPT-PPG's 85 M class).
"""
from dataclasses import asdict, dataclass
import math

import torch
from torch import nn
import torch.nn.functional as F

DOMAINS = ("mimic3_icu",)  # index = domain id; later domains are appended, never reordered
LAPLACE_LO, LAPLACE_SPAN = .1, .8


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
        cos, sin = rope_tables(cfg.patches, cfg.dim//cfg.heads, cfg.rope_base)
        self.register_buffer("cos", cos, persistent=False)
        self.register_buffer("sin", sin, persistent=False)
        for name, p in self.named_parameters():
            if p.dim() == 2 and not name.startswith("flow."):
                nn.init.normal_(p, std=.02/math.sqrt(2*cfg.layers) if name.endswith(("out.weight", "down.weight"))
                                else .02)

    def hidden(self, patches, domain):
        """patches [B, n<=30, 40] of x in [0, 1] -> h [B, n, dim]; h_i depends on the domain and patches < i only."""
        x = self.embed(2*patches[:, :-1]-1)
        x = torch.cat((self.start(domain)[:, None], x), 1)
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

    def forward(self, signal, domain, aux=.1, repeats=4, generator=None, diff=0.):
        patches = signal.view(len(signal), self.cfg.patches, self.cfg.patch)
        h = self.hidden(patches, domain)
        nll = self.laplace_nll(h, patches).mean()
        flow, sharp = self.flow_loss(h, patches, repeats, generator, diff)
        parts = dict(flow=flow.detach(), laplace_nll=nll.detach())
        if diff:
            parts["sharp"] = sharp.detach()
        return flow+aux*nll+diff*sharp, parts

    @torch.no_grad()
    def sample_patch(self, h, steps, generator=None, clamp=True):
        x = torch.randn(len(h), self.cfg.patch, device=h.device, generator=generator)
        dt = 1/steps
        for i in range(steps):
            t = torch.full((len(h),), i*dt, device=h.device)
            v = self.flow(x.to(h.dtype), t, h).float()
            if i < steps-1:
                v2 = self.flow((x+dt*v).to(h.dtype), t+dt, h).float()
                v = (v+v2)/2
            x = x+dt*v
        x = (x+1)/2
        return x.clamp(0, 1) if clamp else x

    @torch.no_grad()
    def generate(self, n, domain=0, steps=32, seed=0, device="cpu", clamp=True):
        """n windows [n, 1200], each min-max normalised like the training windows. clamp=False leaves the sampled
        patches (also the context fed back) unclipped to [0, 1]; the window min-max then sets the range."""
        generator = torch.Generator(device).manual_seed(seed)
        domain = torch.full((n,), domain, dtype=torch.long, device=device)
        patches = torch.zeros(n, 1, self.cfg.patch, device=device)
        for i in range(self.cfg.patches):
            h = self.hidden(patches, domain)[:, i]
            patches[:, i] = self.sample_patch(h, steps, generator, clamp)
            if i < self.cfg.patches-1:
                patches = torch.cat((patches, torch.zeros_like(patches[:, :1])), 1)
        x = patches.reshape(n, -1)
        lo, hi = x.min(1, keepdim=True).values, x.max(1, keepdim=True).values
        return (x-lo)/(hi-lo).clamp_min(1e-6)


def describe(model):
    return dict(config=asdict(model.cfg), parameters=sum(p.numel() for p in model.parameters()),
                backbone_parameters=sum(p.numel() for n, p in model.named_parameters()
                                        if not n.startswith(("flow.", "laplace."))),
                domains=list(DOMAINS))
