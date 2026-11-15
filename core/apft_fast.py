"""Faster CPU sampling for APFT-GAN (PhysiGPT large, hr_cond): same model, same weights.

1. Flow-head precompute. In PhysiGPT.integrate each Heun stage calls the flow head with the token state h and the flow
   time t; everything that depends only on (h, t) -- cond(h), the time MLP and every adaptive-LN modulation, ~60 % of
   the head's multiply-adds -- is the same for the two stages that share t and for every patch at a given t. Per patch
   it is computed once for the `steps` distinct times as one batched matrix product instead of 2*steps-1 single-row
   products. The ODE itself is unchanged.
2. Loading without the random initialisation: the network is built on the meta device and the checkpoint tensors are
   assigned in place (load_state_dict assign=True). On the Pi 4 mmap=True was slower (11.6 s vs 6.4-6.9 s).
3. Dynamic int8 (torch.ao.quantization.quantize_dynamic on nn.Linear, qnnpack on ARM): 21.7 s per window on the Pi 4
   but it shifts the generated distribution (mean feature 1 - KS against fp32 0.82-0.86 where fp32 against itself
   with another seed is 0.91; amp_cv 0.69), so the app does not use it. torch.ao.quantization is deprecated in
   favour of torchao in newer PyTorch; the Pi runs 2.5.1.

Measured on the Pi 4 (PyTorch 2.5.1, one thread, GUI running): fp32 as shipped 94.8 s per 30 s window, with 1.
45.7 s and bit-identical output, int8 + 1. 21.7 s (scripts/apft_speed_bench.py, scripts/apft_quant_quality.py).
"""
from dataclasses import replace
import types

import torch
from torch import nn
import torch.nn.functional as F

from core.apft_network import CONFIGS, PhysiGPT, rope_tables, time_embedding


def flow_tables(model, h, steps):
    """Per distinct flow time i/steps: (shift, scale, gate) per block and the final (shift, scale), each [n, steps, w]."""
    flow = model.flow
    w = flow.inp.out_features
    t = torch.arange(steps, device=h.device, dtype=torch.float32)/steps
    c = F.silu(flow.cond(h)[:, None]+flow.time(time_embedding(t, w).to(h.dtype))[None])     # [n, steps, w]
    blocks = [block["mod"](c).chunk(3, -1) for block in flow.blocks]
    return blocks, flow.final_mod(c).chunk(2, -1)


def head_at(model, xt, k, tables):
    flow = model.flow
    blocks, (fshift, fscale) = tables
    x = flow.inp(xt)
    for block, (shift, scale, gate) in zip(flow.blocks, blocks):
        x = x+gate[:, k]*block["mlp"](block["norm"](x)*(1+scale[:, k])+shift[:, k])
    return flow.outp(flow.final_norm(x)*(1+fscale[:, k])+fshift[:, k])


def integrate_fast(self, x, h, steps, flow=None):
    if flow is not None:
        return PhysiGPT.integrate(self, x, h, steps, flow)
    tables = flow_tables(self, h, steps)
    dt = 1/steps
    for i in range(steps):
        v = head_at(self, x.to(h.dtype), i, tables).float()
        if i < steps-1:
            v2 = head_at(self, (x+dt*v).to(h.dtype), i+1, tables).float()
            v = (v+v2)/2
        x = x+dt*v
    return x


def fast(model):
    model.integrate = types.MethodType(integrate_fast, model)
    return model


def load(path, mmap=False):
    state = torch.load(path, map_location="cpu", weights_only=True, mmap=mmap)
    with torch.device("meta"):
        model = PhysiGPT(replace(CONFIGS[state["config"]], hr_cond=bool(state.get("hr_cond", False))))
    model.load_state_dict(state["model"], assign=True)
    cos, sin = rope_tables(model.cfg.patches, model.cfg.dim//model.cfg.heads, model.cfg.rope_base)
    model.cos, model.sin = cos, sin            # non-persistent buffers are not in the checkpoint
    return model.eval()


def quantize(model):
    """Dynamic int8 on every nn.Linear except the patch embedding: sample_patches reads embed.weight.dtype for its
    key/value cache (a quantised Linear has a weight() method instead), and the 40 -> dim embedding is 0.03 % of
    the multiply-adds."""
    if "qnnpack" in torch.backends.quantized.supported_engines and torch.backends.cpu.get_cpu_capability() in (
            "DEFAULT", "NO AVX"):
        torch.backends.quantized.engine = "qnnpack"     # ARM (the Pi 4): onednn has no int8 GEMM path there
    names = {name for name, m in model.named_modules() if isinstance(m, nn.Linear) and name != "embed"}
    return torch.ao.quantization.quantize_dynamic(model, names, dtype=torch.qint8)
