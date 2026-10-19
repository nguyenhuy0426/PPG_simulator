"""Do published PPG beat detectors behave on generated strips as they do on real recordings?

For every real window with an independent reference rate (ECG, or a Polar chest strap for GalaxyPPG) the
deployed generators produce one strip at that reference rate. Three detectors from NeuroKit2 (Elgendi 2013,
MSPTD of Bishop and Ercole 2018, MSPTDfast of Charlton et al. 2024) then estimate the rate of every real and
generated window. A simulator is useful for testing detectors only if their errors on its strips resemble
their errors on real data; a strip that is too easy overstates detector performance.

Truth for a generated strip is the median interval of the beats that its rhythm scaffold places inside the
window (reconstructed from the same noise vector), which matches the median-IBI definition of the ECG
reference. Laptop CPU run; not hardware, not clinical validation.

    PPG_DRY_RUN=1 .venv/bin/python docs/paper/analysis/downstream_detectors.py --pylib <dir with neurokit2>
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

FS, LENGTH, BEATS = 40, 1200, 160
V3G = Path("/home/huynn/final_project/PPG_simulator_raspi/ml/runs/physio3g-data-v1/physio3g_data")
# Context: (pack domain, pack splits, generator domain prompted, reference)
CONTEXTS = {
    "FINGER": ("gxu_finger", ("validation", "test"), "gxu_finger", "ECG"),
    "WRIST-EX": ("wrist", ("validation", "test"), "wrist", "ECG"),
    "GalaxyPPG": ("wrist", ("external",), "wrist", "Polar H10"),
    "CapnoBase": ("capnobase", ("external",), "perform_large", "ECG"),
}
DETECTORS = {"Elgendi": "elgendi", "MSPTD": "bishop", "MSPTDfast": "charlton"}
IRREGULARITY = .05      # IBI CV command for every generated strip (resting sinus rhythm)
WITHIN_BPM = 5.
MAX_WINDOWS = 256
RATE_RANGE = (40., 180.)  # generators' command range; windows outside it are excluded for every source
BOOT = 2000


def balanced(subjects, ids, n, rng):
    _, inverse, counts = np.unique(subjects[ids], return_inverse=True, return_counts=True)
    w = 1/counts[inverse]
    return rng.choice(ids, min(n, len(ids)), replace=False, p=w/w.sum())


def scaffold_truth(z, rate, sigma, model):
    """Median in-window beat interval (s) of the strip a generator builds from noise z (see physio.py / flow.py)."""
    hz = np.clip(rate/60, .6, 3.3)
    sigma = np.clip(sigma, 0, .35)
    if model == "PhysioMix":   # PhysioMixB.beats_of: onsets, window time 0..30 s (padding already subtracted)
        u = z[32:32+BEATS]
        ibi = np.exp(sigma*u-.5*sigma**2)/hz
        beats = np.cumsum(ibi)-ibi-ibi[0]/(1+np.exp(-z[0]))-240/FS
    else:                      # PhysioFlowSampler.scaffold_of: systolic peaks from the reversed noise
        u = z[::-1]
        ibi = np.exp(sigma*u[:BEATS]-.5*sigma**2)/hz
        beats = -ibi[0]/(1+np.exp(-u[BEATS]))+np.cumsum(ibi)-ibi
    inside = beats[(beats >= 0) & (beats < LENGTH/FS)]
    return float(np.median(np.diff(inside)))


def detect_rate(nk, x, method):
    try:
        peaks = np.asarray(nk.ppg_findpeaks(np.asarray(x, np.float64), sampling_rate=FS, method=method)["PPG_Peaks"])
    except Exception:  # a detector that raises on a window has failed on it, like one that finds no beats
        return math.nan
    if len(peaks) < 3:
        return math.nan
    return 60*FS/float(np.median(np.diff(peaks)))


def cluster_ci(values, subjects, rng, stat):
    """Percentile 95% interval, resampling subjects (with all their windows) with replacement."""
    names, inverse = np.unique(subjects, return_inverse=True)
    groups = [np.flatnonzero(inverse == i) for i in range(len(names))]
    draws = []
    for _ in range(BOOT):
        pick = np.concatenate([groups[i] for i in rng.integers(len(groups), size=len(groups))])
        draws.append(stat(values[pick]))
    return [float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))]


def summarise(errors, subjects, rng):
    within = np.where(np.isfinite(errors), errors <= WITHIN_BPM, False).astype(float)
    finite = np.isfinite(errors)
    clipped = np.where(finite, errors, 20.)  # a failed window counts as 20 bpm, as in the criterion C
    return dict(within_5bpm=float(within.mean()), within_5bpm_ci95=cluster_ci(within, subjects, rng, np.mean),
                mae=float(clipped.mean()), mae_ci95=cluster_ci(clipped, subjects, rng, np.mean),
                median_abs_error=float(np.median(clipped)), failed=float((~finite).mean()))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--pylib", required=True, help="Directory holding neurokit2 (appended to sys.path)")
    parser.add_argument("--out", default=str(ROOT/"docs/paper/data/downstream.json"))
    parser.add_argument("--threads", type=int, default=8)
    a = parser.parse_args(argv)
    sys.path.append(a.pylib)
    import neurokit2 as nk
    import torch
    from core.neural_preview import PhysioMixGenerator
    from ml.kaggle_multidomain import control
    from ml.kaggle_multidomain.physio import view_mask
    torch.set_num_threads(a.threads)

    pack = np.load(V3G/"windows.npz", allow_pickle=True)
    digest = hashlib.sha256((V3G/"windows.npz").read_bytes()).hexdigest()
    generators = {name: PhysioMixGenerator(slot=slot) for name, slot in (("PhysioMix", "physiomix"), ("PhysioFlow", "physioflow"))}
    for g in generators.values():
        g.torch.set_num_threads(a.threads)
    result = dict(scope=__doc__.split("\n\n")[0], pack_sha256=digest, irregularity_command=IRREGULARITY,
                  detectors={k: f"neurokit2 {nk.__version__} ppg_findpeaks method='{v}'" for k, v in DETECTORS.items()},
                  model_sha256={k: g.sha256 for k, g in generators.items()}, contexts={})
    for c, (context, (domain, splits, prompt, reference)) in enumerate(CONTEXTS.items()):
        rng = np.random.default_rng(1000+c)
        ids = np.flatnonzero((pack["domain"] == domain) & np.isin(pack["split"], splits)
                             & (pack["reference_hr_bpm"] >= RATE_RANGE[0]) & (pack["reference_hr_bpm"] <= RATE_RANGE[1]))
        excluded = int(((pack["domain"] == domain) & np.isin(pack["split"], splits)).sum()-len(ids))
        ids = np.sort(balanced(pack["subject"], ids, MAX_WINDOWS, rng))
        rates = pack["reference_hr_bpm"][ids].astype(np.float64)
        subjects = pack["subject"][ids]
        z = torch.randn(len(ids), LENGTH, generator=torch.Generator().manual_seed(2026+c))
        windows, truth = {"Real": pack["signal"][ids]}, {"Real": rates}
        for name, g in generators.items():
            cond = torch.tensor([g.condition(prompt, float(r), IRREGULARITY) for r in rates], dtype=torch.float32)
            with torch.inference_mode():
                windows[name] = torch.cat([g.model(zz, cc) for zz, cc in zip(z.split(32), cond.split(32))])[:, 0].numpy()
            truth[name] = np.array([60/scaffold_truth(zz.numpy().astype(np.float64), r, IRREGULARITY, name)
                                    for zz, r in zip(z, rates)])
        windows["Gaussian"] = control.gaussian_reference(rates, view_mask("v3"), seed=3000+c)
        truth["Gaussian"] = rates
        entry = dict(reference=reference, prompted_domain=prompt, windows=len(ids), people=int(len(np.unique(subjects))),
                     excluded_outside_40_180_bpm=excluded, sources={})
        for source, x in windows.items():
            entry["sources"][source] = {}
            for det, method in DETECTORS.items():
                estimate = np.array([detect_rate(nk, row, method) for row in x])
                errors = np.abs(estimate-truth[source])
                entry["sources"][source][det] = summarise(errors, subjects, np.random.default_rng(7+c))
            print(context, source, {d: round(v["within_5bpm"], 3) for d, v in entry["sources"][source].items()}, flush=True)
        result["contexts"][context] = entry
    # Agreement with real data over all context x detector cells, per source
    result["agreement"] = {}
    for source in ("PhysioMix", "PhysioFlow", "Gaussian"):
        real, gen = [], []
        for entry in result["contexts"].values():
            for det in DETECTORS:
                real.append(entry["sources"]["Real"][det]["within_5bpm"])
                gen.append(entry["sources"][source][det]["within_5bpm"])
        real, gen = np.array(real), np.array(gen)
        from scipy.stats import spearmanr
        result["agreement"][source] = dict(cells=len(real), mean_abs_gap_pp=float(100*np.mean(np.abs(gen-real))),
                                           mean_gap_pp=float(100*np.mean(gen-real)),
                                           spearman=float(spearmanr(real, gen).statistic))
    Path(a.out).write_text(json.dumps(result, indent=1)+"\n")
    print(json.dumps(result["agreement"], indent=1))


if __name__ == "__main__":
    main()
