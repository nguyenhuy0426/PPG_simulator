"""PhysioFlow-R output view (P1): a 40 s window in the resample-only domain -> the v3 view of its middle 30 s.

The real v3 windows are the record's sosfiltfilt band-pass (Butterworth order 4, 0.5-8 Hz, scipy's default odd
extension) cut to 30 s. Where the record ends within 5 s of a window (all PERform Large windows: 32 s records; the
first and last window of every other record) the band-pass ran up to the record edge, and the window's first or last
2 s carry that edge transient: a reflection-padded FFT filter of the 40 s context differs there by up to 0.2-0.46 of
the window's range (measured on the R pack). So the view is applied as the real data had it: SosFiltFilt (scipy's
sosfiltfilt computed exactly with FFTs) over the window plus the context the record had, (left, right) samples, then
the window is cut and min-max normalised. The band-pass is applied once.

The r_pipeline source sends real R windows through this view, with their own context, so the strict judge can test
the view itself against the pack's v3 windows (a null control for the pipeline).
"""
import hashlib
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt
import torch
from torch import nn

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain.data_r import CONTEXT, R_LENGTH
from ml.kaggle_multidomain.flow import FlowGenerator
from ml.kaggle_multidomain.view import VIEWS


def v3_sos():
    spec = VIEWS["v3"]
    return butter(spec["order"], [spec["low"], spec["high"]], "bandpass", fs=FS, output="sos")


class SosFiltFilt(nn.Module):
    """scipy.signal.sosfiltfilt(sos, x) (padtype odd, default padlen) for variable-length rows, exactly, with FFTs.

    sosfiltfilt filters the odd extension forward from the steady state of its first sample, then backward from the
    steady state of the forward output's last sample. For a filter with zero DC gain (a band-pass) the response from
    the steady state of a constant c equals the zero-state response to (input - c), and a zero-state causal IIR on a
    finite row is the causal convolution with its impulse response truncated to the row: an FFT of twice the length.
    Rows of different lengths sit left-aligned in one tensor; `length` gives each row's samples."""
    def __init__(self, sos, max_length):
        super().__init__()
        sos = np.asarray(sos, np.float64)
        if abs(np.prod([s[:3].sum()/s[3:].sum() for s in sos])) > 1e-9:
            raise ValueError("SosFiltFilt needs zero DC gain")
        self.pad = 3*(2*len(sos)+1-min(int((sos[:, 2] == 0).sum()), int((sos[:, 5] == 0).sum())))
        self.size = int(max_length)+2*self.pad
        self.nfft = 2*self.size
        impulse = np.zeros(self.size)
        impulse[0] = 1
        self.register_buffer("h", torch.tensor(sosfilt(sos, impulse), dtype=torch.float32))

    def causal(self, v):
        h = torch.fft.rfft(self.h.to(v.dtype), n=self.nfft)
        return torch.fft.irfft(torch.fft.rfft(v, n=self.nfft)*h, n=self.nfft)[..., :self.size]

    def forward(self, x, length):
        """x (n, L >= max(length)) left-aligned rows, length (n,) -> (n, L) filtered rows (zero past each length)."""
        n, width, p = x.shape[0], x.shape[1], self.pad
        k = torch.arange(self.size, device=x.device)[None]
        m = (length+2*p)[:, None]                                            # extended length of each row
        valid = k < m
        # Odd extension: 2x[0]-x[p..1], x, 2x[-1]-x[-2..-p-1], built by gathering from x.
        src = (k-p).clamp(0)
        left = k < p
        right = (k >= p+length[:, None]) & valid
        last = (length-1)[:, None]
        index = torch.where(left, p-k, torch.where(right, 2*last-(k-p), src)).clamp(0, width-1)
        values = x.gather(1, index.expand(n, -1))
        first, end = x[:, :1], x.gather(1, last)
        ext = torch.where(left, 2*first-values, torch.where(right, 2*end-values, values))*valid
        u = self.causal((ext-ext[:, :1])*valid)
        back = (m-1-k).clamp(0)                                                # reversal within each row
        w = u.gather(1, back)*valid
        w = (w-w[:, :1])*valid
        t = self.causal(w).gather(1, back)*valid
        out = t[:, p:p+width]
        return out*(torch.arange(width, device=x.device)[None] < length[:, None])


class RView(nn.Module):
    """(n, 1, R_LENGTH) resample-only windows and (n, 2) real context (left, right) -> (n, 1, LENGTH) v3 windows in
    [0, 1]: sosfiltfilt over x[CONTEXT-left : CONTEXT+LENGTH+right], the window cut and min-max normalised."""
    def __init__(self):
        super().__init__()
        self.filt = SosFiltFilt(v3_sos(), R_LENGTH)
        self.context, self.r_length, self.length = CONTEXT, R_LENGTH, LENGTH

    def forward(self, x, context):
        x = x[:, 0]
        left, right = context[:, 0].long(), context[:, 1].long()
        n = x.shape[0]
        k = torch.arange(self.r_length, device=x.device)[None]
        start = (self.context-left)[:, None]
        seg = x.gather(1, (start+k).clamp(max=self.r_length-1).expand(n, -1))
        y = self.filt(seg, self.length+left+right)
        y = y.gather(1, left[:, None]+torch.arange(self.length, device=x.device)[None])
        lo, hi = y.amin(-1, keepdim=True), y.amax(-1, keepdim=True)
        return ((y-lo)/(hi-lo).clamp_min(1e-6))[:, None]


def r_pipeline_source(r, pack):
    """Judge source: the real R windows of the prompted rows of pack through RView with their own context (rows
    matched on record and start, data_r.rows_for)."""
    from ml.kaggle_multidomain.data_r import rows_for
    view = RView().double()

    def generate(ids, conditions, seed):
        rows = rows_for(r, pack, ids)
        with torch.no_grad():
            x = view(torch.tensor(r["signal"][rows][:, None], dtype=torch.float64), torch.tensor(r["context"][rows]))
        return x[:, 0].numpy().astype(np.float32)
    return generate


# ---------------------------------------------------------------- PhysioFlow-R generator
SCALE_CAP = 3.                 # target SD at most this many v3-band SDs (GXU baseline drift: raw/v3 SD up to 32)
CHOICE_SAMPLES = 400           # z samples whose mean draws the window's context type
EXTEND_SEED = 20261025


def r_targets(signal, context):
    """Flow targets of R windows: mean removed, divided by max(v3-band SD, SD/SCALE_CAP) over the window's own
    context, so the pulse band is O(1) and a drifting baseline stays within SCALE_CAP."""
    x = torch.tensor(signal, dtype=torch.float64)
    view = RView().double()
    left, right = torch.tensor(context[:, 0]).long(), torch.tensor(context[:, 1]).long()
    k = torch.arange(R_LENGTH)[None]
    seg = x.gather(1, (CONTEXT-left[:, None]+k).clamp(max=R_LENGTH-1))
    band = view.filt(seg, LENGTH+left+right)
    used = k < (LENGTH+left+right)[:, None]
    band_sd = ((band.square()*used).sum(1)/used.sum(1)).sqrt()
    x = x-x.mean(1, keepdim=True)
    scale = torch.maximum(band_sd, x.std(1)/SCALE_CAP).clamp_min(1e-12)
    return (x/scale[:, None]).float().numpy()


def context_table(context, domain, domains):
    """(contexts (K, 2) int64, cdf (D, K) float32): each domain's empirical distribution of (left, right) context
    over the given (training) windows."""
    pairs = sorted({(int(a), int(b)) for a, b in context})
    counts = np.zeros((len(domains), len(pairs)))
    at = {p: i for i, p in enumerate(pairs)}
    for (a, b), d in zip(context, domain):
        counts[domains.index(str(d)), at[int(a), int(b)]] += 1
    if (counts.sum(1) == 0).any():
        raise ValueError("A domain has no training windows")
    cdf = np.cumsum(counts/counts.sum(1, keepdims=True), 1)
    cdf[:, -1] = 1.
    return torch.tensor(pairs, dtype=torch.long), torch.tensor(cdf, dtype=torch.float32)


class ContextChoice(nn.Module):
    """Deterministic z -> (40 s noise, context type): the window's noise z (n, LENGTH) is extended by 2*CONTEXT of its
    own samples in a fixed order (the app contract keeps z at LENGTH), and the context type is drawn from the prompt
    domain's training distribution with u = Phi(sqrt(m) mean(z[:, :m]))."""
    def __init__(self, contexts, cdf, domains: int):
        super().__init__()
        order = torch.randperm(LENGTH, generator=torch.Generator().manual_seed(EXTEND_SEED))[:2*CONTEXT]
        self.register_buffer("order", order)
        self.register_buffer("contexts", contexts.clone())
        self.register_buffer("cdf", cdf.clone())
        self.domains, self.width, self.m = int(domains), CONTEXT, CHOICE_SAMPLES

    def _load_from_state_dict(self, state_dict, prefix, *args, **kwargs):
        # The table's size comes with the checkpoint (build() makes a placeholder).
        for name in ("contexts", "cdf"):
            if prefix+name in state_dict:
                setattr(self, name, torch.empty_like(state_dict[prefix+name]))
        super()._load_from_state_dict(state_dict, prefix, *args, **kwargs)

    @torch.jit.unused
    def set_table(self, contexts, cdf):
        self.contexts, self.cdf = contexts.to(self.order.device), cdf.to(self.order.device)

    def extend(self, z):
        return torch.cat((z[:, self.order[:self.width]], z, z[:, self.order[self.width:]]), 1)

    def context(self, z, condition):
        u = .5*(1+torch.erf(z[:, :self.m].mean(1)*(self.m**.5)/(2**.5)))
        cdf = self.cdf[condition[:, :self.domains].argmax(1)]
        k = (cdf < u[:, None]).sum(1).clamp(max=self.contexts.shape[0]-1)
        return self.contexts[k]


class FlowGeneratorR(nn.Module):
    """PhysioFlow-R: generator(z (n, LENGTH), condition) -> (n, 1, LENGTH) in [0, 1].

    flow: FlowGenerator on the 40 s grid (its rhythm scaffold spans the context), integrated from the extended noise;
    its min-max output is passed to RView with the drawn context type (RView(minmax(x)) = RView(x): the view is
    linear with zero DC gain and ends in min-max). `net` is the velocity U-Net (train_flow's optimiser and loss)."""
    def __init__(self, size, center, scale, domains, contexts=None, cdf=None, sample_steps=16, guidance=1.,
                 width=1., flag_scaffold=True):
        super().__init__()
        self.flow = FlowGenerator(size, center, scale, sample_steps, guidance, width, flag_scaffold)
        self.flow.time = torch.arange(R_LENGTH, dtype=torch.float32)/FS
        if contexts is None:
            contexts, cdf = torch.full((1, 2), CONTEXT, dtype=torch.long), torch.ones(domains, 1)
        self.choice = ContextChoice(contexts, cdf, domains)
        self.view = RView()

    @property
    def net(self):
        return self.flow.net

    def forward(self, z, condition):
        return self.view(self.flow(self.choice.extend(z), condition), self.choice.context(z, condition))

    def export(self, z, condition):
        return torch.jit.script(FlowSamplerR(self.flow.export(self.choice.extend(z), condition), self.choice,
                                             self.view))


class FlowSamplerR(nn.Module):
    """Scriptable twin of FlowGeneratorR.forward around FlowGenerator.export()."""
    def __init__(self, sampler, choice, view):
        super().__init__()
        self.sampler, self.choice, self.view = sampler, choice, view

    def forward(self, z, condition):
        return self.view(self.sampler(self.choice.extend(z), condition), self.choice.context(z, condition))


def training_rows(pack, ids, roots):
    """(R signal, R context) for pack rows ids from the verified R pack under roots (built from the v3 pack there)."""
    from ml.kaggle_multidomain.data_gxu import load_input
    from ml.kaggle_multidomain.data_r import BASE_PROTOCOL, load_r, rows_for
    for root in roots:
        _, base = load_input(root, BASE_PROTOCOL)
        r, _ = load_r(root, base)
        rows = rows_for(r, pack, ids)
        return r["signal"][rows], r["context"][rows]
    raise FileNotFoundError("No input root for the R pack")


# ---------------------------------------------------------------- R1 teacher file (P1 ship seed)
TEACHER_R_FILE = "physioflow_r_generator.ts"


def teacher_state_r(roots):
    """The R1 U-Net weights and context table from the first physioflow_r_generator.ts under roots (the P1 round's
    ship/ folder; its sha256 is checked against that round's DECISION_R.json ship seed export)."""
    for root in roots:
        for path in sorted(Path(root).rglob(TEACHER_R_FILE)):
            scripted = torch.jit.load(str(path), map_location="cpu")
            return dict(net=scripted.sampler.net.state_dict(), contexts=scripted.choice.contexts.clone(),
                        cdf=scripted.choice.cdf.clone(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    raise FileNotFoundError(f"No {TEACHER_R_FILE} under {list(roots)}")
