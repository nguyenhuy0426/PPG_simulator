"""Rhythm from a heart-rate range: inter-beat intervals for a command such as "70-75 bpm" instead of one rate.

A person's rate drifts within a range during a recording, and successive intervals are correlated. Two rhythm models
turn a command (dataset, rate range [lo, hi]) into a beat sequence:

- R0, log-normal independent (the current scaffold): mean rate (lo + hi)/2, log-scale SD chosen so that the 5th-95th
  percentiles of the instantaneous rate span [lo, hi]: sigma = ln(hi/lo)/(2 * 1.645), clipped to [0.005, 0.35].
- R1, autoregressive: log(IBI/mean IBI) follows the dataset's AR(p) process (p <= 4 chosen by AIC, least squares on
  the PPG peak intervals of training windows), scaled to the same stationary SD and centred so that E[IBI] = 1/f.

RULE_RHYTHM is fixed in code before the comparison is run (validation windows only). The generated intervals reach
the deployed generators without retraining: both read the interval noise u_k from fixed positions of z
(PhysioMix: z[32:192]; PhysioFlow: the last 160 samples of z, reversed), with IBI_k = exp(sigma u_k - sigma^2/2)/f, so
u_k = (ln(IBI_k f) + sigma^2/2)/sigma encodes any sequence. Engineering model of rate variability, not a clinical
HRV model and not an arrhythmia model.
"""
import math

import numpy as np

from ml.kaggle_lsm.train_lsm import FS

Z95 = 1.6448536269514722
SIGMA_RANGE = (.005, .35)
BEATS = 160
P_MAX = 4
RULE_RHYTHM = (
    "Rhythm rule, fixed before the comparison. Real windows: validation split of the six original datasets and the "
    "three PTT contexts, intervals from the repaired PPG peaks (flow.window_peaks), windows with >= 10 intervals. Each "
    "window is commanded with its own mean rate and the 5th-95th percentiles of its instantaneous rate; R0 and R1 each "
    "generate one interval sequence per window (seed 20261021) of the same length. Features: lag-1 and lag-2 "
    "autocorrelation of the intervals and RMSSD/SDNN, each scored as the Wasserstein-1 distance between generated "
    "and real values divided by the real interquartile range, and the range term, the mean of |ln(achieved 5th-95th "
    "percentile rate width / commanded width)|. Score per dataset: mean of the four terms; overall score: mean over "
    "datasets. R1 replaces R0 if its "
    "overall score is lower than R0's by more than 20% and its mean absolute error of the mean rate is <= 1 bpm. Guard "
    "for the deployed generators: with the chosen model encoded into z, the PhysioFlow and PhysioMix strips must keep "
    "a mean rate error <= 1 bpm against the command on the same windows.")


# Second rule, written after RULE_RHYTHM's outcome (R1 better rhythm statistics, guard failed: R0 kept) and before
# anything below was run. Diagnosis on the RULE_RHYTHM validation windows: an AR sequence centred over 160 beats has an
# in-window mean that drifts from the command (0.25-2.2 bpm by dataset), and the peak detector misreads wrist strips
# (about 4.6 bpm) whatever the rhythm. It is judged on the test split, which no rhythm decision has used.
RULE_RHYTHM_2 = (
    "Rhythm rule 2, fixed before it was run. R1c = R1 with the log-interval deviations re-centred over the beats that "
    "fall inside the 30 s window (DURATION + one mean interval), so the in-window mean rate equals the command. Real "
    "windows: test split of the six original datasets and the three PTT contexts, otherwise as RULE_RHYTHM (same "
    "features, score and seed). R1c replaces R0 if its overall score is lower than R0's by more than 20% and its mean "
    "absolute error of the mean rate is <= 1 bpm. Guard, relative: for each deployed generator (PhysioMix, PhysioFlow), "
    "on up to 24 test windows per original dataset, the mean absolute error between the strip's detected rate "
    "(flow.window_peaks) and the command with R1c encoded into z must not exceed the same error with R0 encoded by more "
    "than 0.5 bpm.")
DURATION = 30.


def range_sigma(lo, hi):
    return float(np.clip(math.log(hi/lo)/(2*Z95), *SIGMA_RANGE))


def ar_fit(series, p_max=P_MAX):
    """Least-squares AR(p) of pooled standardised log-interval deviations; p by AIC. Returns (coefficients, residual
    SD, stationary SD) for unit-variance input."""
    best = None
    for p in range(1, p_max+1):
        x, y = [], []
        for s in series:
            if len(s) <= p+2:
                continue
            for t in range(p, len(s)):
                x.append(s[t-p:t][::-1])
                y.append(s[t])
        x, y = np.asarray(x), np.asarray(y)
        coef, *_ = np.linalg.lstsq(x, y, rcond=None)
        resid = y-x@coef
        aic = len(y)*math.log(max(resid.var(), 1e-12))+2*p
        if best is None or aic < best[0]:
            best = (aic, coef, float(resid.std()))
    _, coef, sd = best
    if np.any(np.abs(np.roots(np.r_[1, -coef])) >= 1):
        raise ValueError("Non-stationary AR fit")
    return coef, sd


def ar_simulate(coef, innovation_sd, n, rng, burn=200):
    p = len(coef)
    x = np.zeros(n+burn+p)
    e = rng.standard_normal(len(x))*innovation_sd
    for t in range(p, len(x)):
        x[t] = coef@x[t-p:t][::-1]+e[t]
    x = x[-n:]
    return (x-x.mean())/max(x.std(), 1e-9)


def log_deviations(times):
    ibi = np.diff(times)
    d = np.log(ibi/ibi.mean())
    return (d-d.mean())/max(d.std(), 1e-9)


class RhythmModel:
    """R0 or R1 for one dataset: intervals (s) for a rate range."""
    def __init__(self, kind, coef=None, innovation_sd=None):
        if kind not in ("R0", "R1"):
            raise ValueError(kind)
        self.kind, self.coef, self.innovation_sd = kind, coef, innovation_sd

    def intervals(self, lo, hi, n, rng, mean_bpm=None, centre_window=False):
        """centre_window (R1c): re-centre u over the beats inside DURATION + one mean interval (two passes)."""
        f = (mean_bpm if mean_bpm is not None else (lo+hi)/2)/60
        sigma = range_sigma(lo, hi)
        u = rng.standard_normal(n) if self.kind == "R0" else ar_simulate(self.coef, self.innovation_sd, n, rng)
        if centre_window:
            for _ in range(2):
                ibi = np.exp(sigma*u-.5*sigma**2)/f
                k = int(np.searchsorted(np.cumsum(ibi), DURATION+1/f))+1
                u = u.copy()
                u[:k] -= u[:k].mean()
        return np.exp(sigma*u-.5*sigma**2)/f, sigma, u


def fit_models(signals, domains, peaks_of):
    """{domain: RhythmModel R1} from training windows; peaks_of(row) -> peak times in samples or None."""
    by_domain = {}
    for x, d in zip(signals, domains):
        times = peaks_of(x)
        if times is not None and len(times) >= 11:
            by_domain.setdefault(str(d), []).append(log_deviations(times))
    out = {}
    for d, series in by_domain.items():
        coef, sd = ar_fit(series)
        out[d] = RhythmModel("R1", coef, sd)
    return out


def encode(z, u, model):
    """Write the standardised interval noise u (len <= BEATS) into the positions the deployed generator reads.
    z: (LENGTH,) numpy; model 'physiomix' or 'physioflow'. Positions beyond len(u) keep their random values."""
    z = np.array(z, dtype=np.float32, copy=True)
    u = np.asarray(u, np.float32)[:BEATS]
    if model == "physiomix":
        z[32:32+len(u)] = u
    elif model == "physioflow":
        z[len(z)-len(u):] = u[::-1]
    else:
        raise ValueError(model)
    return z


def features(times_s):
    """Sequential and range features of one interval sequence (times in seconds)."""
    ibi = np.diff(times_s)
    d = ibi-ibi.mean()
    acf = lambda k: float(np.dot(d[:-k], d[k:])/max(np.dot(d, d), 1e-12))
    hr = 60/ibi
    return dict(lag1=acf(1), lag2=acf(2), rmssd_sdnn=float(np.sqrt(np.mean(np.diff(ibi)**2))/max(ibi.std(), 1e-9)),
                range_lo=float(np.percentile(hr, 5)), range_hi=float(np.percentile(hr, 95)),
                mean_bpm=float(60/ibi.mean()))


def window_times(ibi, duration=30.):
    t = np.cumsum(ibi)
    return np.r_[0., t[t < duration]]
