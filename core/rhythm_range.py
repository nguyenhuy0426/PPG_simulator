"""Beat sequences for a heart-rate range (for example 70-75 bpm) for the conditioned PPG generators.

The generators build their beat sequence from interval noise u_k that they read from fixed positions of the noise
vector z (PhysioMix: z[32:192]; PhysioFlow: the last 160 samples, reversed), with IBI_k = exp(sigma u_k - sigma^2/2)/f.
For a range command this module draws u from the dataset's R1c rhythm model (assets/neural/rhythm_r1c.json: an
AR process on standardised log intervals, re-centred over the beats inside the 30 s window, selected by
RULE_RHYTHM_2 on held-out windows) and writes it into z. The mean rate is (lo + hi)/2; sigma is chosen so that the
5th-95th percentiles of the instantaneous rate span the range. Without the asset or for a dataset it does not
cover, u is independent normal (the generators' own behaviour).

Engineering model of rate variability from PPG peak intervals; not a clinical HRV model and not an arrhythmia model.
"""
import json
import math
from pathlib import Path

import numpy as np

ASSET = Path(__file__).resolve().parents[1]/"assets"/"neural"/"rhythm_r1c.json"
BEATS, DURATION, Z95, SIGMA_RANGE = 160, 30., 1.6448536269514722, (.005, .35)
POSITIONS = {"physiomix": "front", "physioflow": "back"}


def load_models(path=ASSET):
    try:
        return json.loads(Path(path).read_text())["domains"]
    except (OSError, ValueError, KeyError):
        return {}


def range_sigma(lo, hi):
    if not (math.isfinite(lo) and math.isfinite(hi)) or lo <= 0 or hi < lo:
        raise ValueError("Heart-rate range must satisfy 0 < low <= high")
    return float(np.clip(math.log(hi/lo)/(2*Z95), *SIGMA_RANGE))


def _ar(coef, innovation_sd, n, rng, burn=200):
    coef = np.asarray(coef, float)
    p = len(coef)
    x = np.zeros(n+burn+p)
    e = rng.standard_normal(len(x))*innovation_sd
    for t in range(p, len(x)):
        x[t] = coef@x[t-p:t][::-1]+e[t]
    x = x[-n:]
    return (x-x.mean())/max(x.std(), 1e-9)


def interval_noise(domain, lo, hi, rng, models=None):
    """(u (BEATS,), sigma, mean_bpm, model name) for a range command."""
    sigma, mean = range_sigma(lo, hi), (lo+hi)/2
    models = load_models() if models is None else models
    spec = models.get(domain)
    if spec is None:
        return rng.standard_normal(BEATS), sigma, mean, "independent"
    u = _ar(spec["coef"], spec["innovation_sd"], BEATS, rng)
    f = mean/60
    for _ in range(2):
        ibi = np.exp(sigma*u-.5*sigma**2)/f
        k = int(np.searchsorted(np.cumsum(ibi), DURATION+1/f))+1
        u = u.copy()
        u[:k] -= u[:k].mean()
    return u, sigma, mean, "R1c"


def encode(z, u, slot):
    """Copy of z (length >= 192) with the interval noise u at the positions the slot's generator reads."""
    z = np.array(z, dtype=np.float32, copy=True)
    u = np.asarray(u, np.float32)[:BEATS]
    if POSITIONS.get(slot) == "front":
        z[32:32+len(u)] = u
    elif POSITIONS.get(slot) == "back":
        z[len(z)-len(u):] = u[::-1]
    else:
        raise ValueError(f"Unknown generator slot: {slot}")
    return z
