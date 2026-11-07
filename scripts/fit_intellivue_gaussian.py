#!/usr/bin/env python3
"""Fit the simulator's Gaussian pulse (models/waveform.py) to a Pleth trace photographed on a patient monitor.

Input: a photo of a Philips IntelliVue screen supplied by the user (normal rhythm, 75 bpm, SpO2 99 %, RR 16). The
cyan Pleth trace is digitised column by column (median row of the trace pixels), turned upward, split at its feet
(troughs) into beats, each beat de-trended between its two feet, resampled to BEAT_POINTS phase points and min-max
normalised, then the beats are averaged. PulseMorphology is fitted to that mean beat (mean squared error, global
search) with the same PulseShaper the app plays. The photo itself is not stored; assets/gaussian/intellivue_fit.json keeps the mean beat,
the per-beat spread, the fitted parameters and the fit error.

Limits: a monitor Pleth is the monitor's own filtered, auto-gained display trace, photographed (perspective, line
width, pixel quantisation); this fits that displayed shape, not a raw photodiode signal, and one patient's trace is
not a population reference. Engineering shape target; not clinical validation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models.waveform import PulseMorphology, PulseShaper, REFERENCE_CYCLE_MS, WAVE_PPG  # noqa: E402

BEAT_POINTS = 256
# Pleth panel of the photo (pixels): the trace lies inside these rows/columns; labels and numerics are outside.
PANEL_ROWS = (580, 840)
PANEL_COLS = (0, 1270)
MIN_BEAT_PX = 120          # feet closer than this are one foot (the photo shows ~180 px per beat)
# Bounds of the fitted fields (fractions of the cycle; amplitudes relative to the systolic component).
FIELDS = ("systolic_pos", "notch_pos", "diastolic_pos", "systolic_width", "notch_width", "diastolic_width",
          "diastolic_amplitude", "dicrotic_depth")
LOWER = (0.05, 0.15, 0.20, 0.02, 0.01, 0.03, 0.0, 0.0)
UPPER = (0.45, 0.70, 0.85, 0.20, 0.15, 0.35, 1.5, 1.0)
FIT_SEED = 0


def trace_pixels(image):
    """Boolean mask of the cyan trace (green and blue high, red low) inside the Pleth panel."""
    rgb = np.asarray(image.convert("RGB")).astype(int)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mask = (g > 120) & (b > 100) & (r < 120) & (np.abs(g-b) < 90)
    return mask[PANEL_ROWS[0]:PANEL_ROWS[1], PANEL_COLS[0]:PANEL_COLS[1]]


def trace_signal(mask):
    """Per column: minus the median trace row (up is positive); NaN where the column has no trace pixel."""
    out = np.full(mask.shape[1], np.nan)
    for x in range(mask.shape[1]):
        rows = np.flatnonzero(mask[:, x])
        if len(rows):
            out[x] = -float(np.median(rows))
    return out


def feet(signal):
    """Columns of the beat feet: the lowest point before each systolic upstroke."""
    valid = np.isfinite(signal)
    s = np.where(valid, signal, np.inf)
    found = []
    for x in range(1, len(s)-1):
        lo, hi = max(0, x-MIN_BEAT_PX//2), min(len(s), x+MIN_BEAT_PX//2)
        if valid[x] and s[x] == np.min(s[lo:hi]) and valid[lo:hi].mean() > .9:
            if not found or x-found[-1] >= MIN_BEAT_PX:
                found.append(x)
    return found


def beats(signal, foot):
    """Each complete beat between consecutive feet, de-trended and resampled to BEAT_POINTS, min-max normalised."""
    out = []
    grid = np.linspace(0, 1, BEAT_POINTS)
    for a, b in zip(foot[:-1], foot[1:]):
        x = np.arange(a, b+1)
        y = signal[a:b+1]
        ok = np.isfinite(y)
        if ok.mean() < .95:
            continue
        y = np.interp(x, x[ok], y[ok])
        y = y-(y[0]+(y[-1]-y[0])*(x-a)/(b-a))
        y = np.interp(grid, (x-a)/(b-a), y)
        out.append((y-y.min())/np.ptp(y))
    if len(out) < 3:
        raise ValueError(f"Only {len(out)} complete beats found; check PANEL_ROWS/PANEL_COLS")
    return np.array(out), [int(b-a) for a, b in zip(foot[:-1], foot[1:])]


def shape(params, phase=None):
    shaper = PulseShaper(PulseMorphology(**dict(zip(FIELDS, params))))
    phase = np.linspace(0, 1, BEAT_POINTS) if phase is None else phase
    return np.array([shaper.sample(WAVE_PPG, float(p)) for p in np.clip(phase, 0, 1-1e-9)])


def fit(target):
    """Global search (local least squares from fixed starts stops in a worse basin, RMSE ~0.042 against ~0.020).

    The notch centre is left free: pinned to the visible notch (0.40-0.55 of the cycle) the formula reaches only
    RMSE ~0.043, because its symmetric systolic Gaussian then cannot follow the steep upstroke and faster fall.
    DN is therefore the local-attenuation centre of the formula, not the visible notch (docs/ppg_morphology.md)."""
    from scipy.optimize import differential_evolution
    phase = np.linspace(0, 1, BEAT_POINTS)

    def cost(p):
        # The app requires SP < DN < DP (models/ppg_model.py set_feature_times).
        order = max(0., p[0]+.01-p[1])+max(0., p[1]+.01-p[2])
        return float(np.mean((shape(p, phase)-target)**2))+10*order
    return differential_evolution(cost, list(zip(LOWER, UPPER)), seed=FIT_SEED, maxiter=60, popsize=12, tol=1e-7,
                                  polish=True).x


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True, help="Photo of the monitor screen (not stored)")
    parser.add_argument("--output", type=Path, default=ROOT/"assets/gaussian/intellivue_fit.json")
    a = parser.parse_args(argv)
    from PIL import Image
    raw = a.image.read_bytes()
    signal = trace_signal(trace_pixels(Image.open(a.image)))
    foot = feet(signal)
    each, lengths = beats(signal, foot)
    mean = each.mean(0)
    target = (mean-mean.min())/np.ptp(mean)
    params = fit(target)
    model = shape(params)
    rmse = float(np.sqrt(np.mean((model-target)**2)))
    spread = float(np.sqrt(np.mean(each.std(0)**2)))
    morphology = {k: round(float(v), 4) for k, v in zip(FIELDS, params)}
    report = dict(
        schema=1, source="Philips IntelliVue Pleth trace, photo supplied by the user (not stored)",
        source_settings=dict(heart_rate_bpm=75, spo2_pct=99, resp_rate_brpm=16, rhythm="normal"),
        image_sha256=hashlib.sha256(raw).hexdigest(), beats=len(each), beat_lengths_px=lengths,
        formula="models/waveform.py PulseShaper (two Gaussians, local Gaussian notch attenuation, edge taper)",
        morphology=morphology,
        feature_times_ms_at_60_bpm=dict(sp=round(morphology["systolic_pos"]*REFERENCE_CYCLE_MS),
                                        dn=round(morphology["notch_pos"]*REFERENCE_CYCLE_MS),
                                        dp=round(morphology["diastolic_pos"]*REFERENCE_CYCLE_MS)),
        fit_rmse=round(rmse, 4), beat_to_beat_rms_sd=round(spread, 4),
        mean_beat=[round(float(v), 4) for v in target], fitted_beat=[round(float(v), 4) for v in model],
        limitations=["Monitor display trace (filtered, auto-gained), photographed; not a raw sensor signal",
                     "One patient, one screen; a shape target, not a population or clinical reference"])
    a.output.write_text(json.dumps(report, indent=1)+"\n")
    print(json.dumps({k: report[k] for k in ("beats", "beat_lengths_px", "morphology", "feature_times_ms_at_60_bpm",
                                              "fit_rmse", "beat_to_beat_rms_sd")}, indent=1))


if __name__ == "__main__":
    main()
