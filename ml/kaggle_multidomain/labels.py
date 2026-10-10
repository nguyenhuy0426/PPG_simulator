"""Robust PPG rate and irregularity labels for conditioning and control metrics.

Three independent estimators (zero-padded spectral peak, first major ACF peak, relative-
prominence beat intervals) must agree before a window gets a PPG rate label. Where an ECG
reference exists the label is the ECG rate, kept only if the PPG consensus agrees with it.
These are engineering labels for a simulator, not clinical heart-rate measurements.
"""
import numpy as np
from scipy.signal import find_peaks

from ml.kaggle_lsm.train_lsm import FS, LENGTH

IRR_MAX = .35


def spectral_hr(x, lo=.6, hi=3.3, n=16384):
    x = np.atleast_2d(x)
    centered = (x-x.mean(1, keepdims=True))*np.hanning(x.shape[1])
    power = np.abs(np.fft.rfft(centered, n=n, axis=1))**2
    freq = np.fft.rfftfreq(n, 1/FS)
    band = (freq >= lo) & (freq <= hi)
    return 60*freq[band][power[:, band].argmax(1)]


def acf_hr(x, min_bpm=36, max_bpm=200, rel=.5):
    """First ACF peak reaching rel*max avoids locking onto two-beat lags."""
    x = np.atleast_2d(x)
    centered = x-x.mean(1, keepdims=True)
    acf = np.fft.irfft(np.abs(np.fft.rfft(centered, n=2*x.shape[1], axis=1))**2, n=2*x.shape[1], axis=1)
    acf = acf[:, :int(60*FS/min_bpm)+2]/np.maximum(acf[:, :1], 1e-12)
    lo = int(np.floor(60*FS/max_bpm))
    out = np.full(len(x), np.nan)
    for i, row in enumerate(acf):
        peaks, _ = find_peaks(row[lo:])
        if not len(peaks) or row[peaks+lo].max() <= 0:
            continue
        peaks = peaks+lo
        j = peaks[row[peaks] >= rel*row[peaks].max()][0]
        a, b, c = row[j-1], row[j], row[min(j+1, len(row)-1)]
        shift = .5*(a-c)/(a-2*b+c) if a-2*b+c else 0.
        out[i] = 60*FS/(j+shift)
    return out


def beat_stats(x, fs=FS, rel_prom=.3):
    """(N, 3): span rate bpm, IBI CV, RMSSD/mean IBI; NaN when fewer than 5 beats."""
    x = np.atleast_2d(x)
    out = np.full((len(x), 3), np.nan)
    for i, row in enumerate(x):
        span = np.percentile(row, 95)-np.percentile(row, 5)
        peaks, _ = find_peaks(row, distance=round(.3*fs), prominence=rel_prom*max(span, 1e-9))
        peaks = peaks[(peaks > 0) & (peaks < len(row)-1)]
        if len(peaks) < 5:
            continue
        a, b, c = row[peaks-1], row[peaks], row[peaks+1]
        den = a-2*b+c
        times = (peaks+.5*(a-c)/np.where(den == 0, 1, den))/fs
        ibi = np.diff(times)
        # A missed weak beat doubles one interval; count it as two beats for the span rate.
        beats = np.clip(np.round(ibi/np.median(ibi)), 1, None).sum()
        out[i] = (60*beats/(times[-1]-times[0]), ibi.std()/ibi.mean(),
                  np.sqrt(np.mean(np.diff(ibi)**2))/ibi.mean())
    return out


def robust_labels(x, ecg_hr=None, tol_abs=5., tol_rel=.07, ecg_abs=6., ecg_rel=.08):
    """Return rate, irregularity (NaN = unknown) and the label source per window."""
    x = np.atleast_2d(x)
    stats = beat_stats(x)
    estimates = np.stack([spectral_hr(x), acf_hr(x), stats[:, 0]], 1)
    with np.errstate(all="ignore"):
        median = np.nanmedian(estimates, 1)
        tolerance = np.maximum(tol_abs, tol_rel*median)
        agree = np.abs(estimates-median[:, None]) <= tolerance[:, None]
        valid = (agree.sum(1) >= 2) & np.isfinite(median)
        rate = np.where(valid, np.nanmedian(np.where(agree, estimates, np.nan), 1), np.nan)
    source = np.where(valid, "ppg_consensus", "masked").astype(object)
    if ecg_hr is not None:
        ecg_hr = np.asarray(ecg_hr, dtype=np.float64)
        has_ecg = np.isfinite(ecg_hr)
        close = valid & (np.abs(rate-ecg_hr) <= np.maximum(ecg_abs, ecg_rel*np.where(has_ecg, ecg_hr, 0)))
        rate = np.where(has_ecg, np.where(close, ecg_hr, np.nan), rate)
        source = np.where(has_ecg, np.where(close, "ecg_gated", "masked"), source)
    beat_ok = valid & agree[:, 2]
    irr = np.where(beat_ok & np.isfinite(rate), np.clip(stats[:, 1], 0, IRR_MAX), np.nan)
    return rate, irr, source.astype(str)
