"""Direct waveform comparison before any judge (P5 v2): generated v3 windows against the dataset's, per domain.

The user and the agent read this report (SIMILARITY_P5.json, the figures, the sample windows) and decide to fix or
keep a generator before the strict judge sees it. It is descriptive, not a pass test: every distance is reported
next to the same distance between two sets of real windows (training people vs validation people), so "as close as
real is to real" has a number.

Per domain, against the validation people's real windows (target):
- log-PSD: the median Welch log10 power, mean absolute difference over 0.5-8 Hz (pulse band) and 8-20 Hz (stop band);
- ACF up to 5 s: RMS difference of the mean autocorrelation;
- morphology (benchmark.morphology: rate, IBI CV, width, rise, SD, skew, slope, curvature, >5 Hz share): each
  feature's Wasserstein distance divided by the target's IQR of that feature, and their mean;
- sample values: Kolmogorov-Smirnov statistic of all samples (the min-max amplitude distribution);
- nearest training window (RMS), the copy check's distance, median.
Engineering comparison of normalised 30 s PPG shape; not clinical validation.
"""
from pathlib import Path

import numpy as np
from scipy.signal import welch
from scipy.stats import ks_2samp, wasserstein_distance

from ml.kaggle_lsm.train_lsm import FS, save_json
from ml.kaggle_multidomain.benchmark import MORPH_NAMES, morphology

PULSE, STOP = (.5, 8.), (8., 20.)
LAGS = 5*FS
FIGURE_WINDOWS = 4


def log_psd(x):
    f, power = welch(np.asarray(x, np.float64), fs=FS, nperseg=8*FS, noverlap=4*FS, axis=-1)
    return f, np.log10(np.maximum(power, 1e-20))


def acf(x):
    x = np.asarray(x, np.float64)
    x = x-x.mean(-1, keepdims=True)
    n = x.shape[-1]
    r = np.fft.irfft(np.abs(np.fft.rfft(x, 2*n, axis=-1))**2, 2*n, axis=-1)[:, :LAGS+1]
    return r/np.maximum(r[:, :1], 1e-12)


def distances(candidate, target):
    """The report's distances of candidate windows to target windows (one domain)."""
    f, pc = log_psd(candidate)
    _, pt = log_psd(target)
    diff = np.abs(np.median(pc, 0)-np.median(pt, 0))
    band = lambda b: float(diff[(f >= b[0]) & (f < b[1])].mean())
    mc, mt = morphology(candidate), morphology(target)
    iqr = np.maximum(np.subtract(*np.percentile(mt, [75, 25], 0)), 1e-6)
    morph = {name: float(wasserstein_distance(mc[:, i], mt[:, i])/iqr[i]) for i, name in enumerate(MORPH_NAMES)}
    return dict(psd_pulse=band(PULSE), psd_stop=band(STOP),
                acf=float(np.sqrt(np.mean((acf(candidate).mean(0)-acf(target).mean(0))**2))),
                morphology=float(np.mean(list(morph.values()))), morphology_features=morph,
                values_ks=float(ks_2samp(np.ravel(candidate), np.ravel(target)).statistic),
                psd=dict(freq=f.tolist(), candidate=np.median(pc, 0).tolist(), target=np.median(pt, 0).tolist()))


def compare(sources, target, target_domain, reference, reference_domain, nearest=None):
    """{domain: {name: distances}} with 'real_train_people' (reference windows) as the real-vs-real row.
    sources: {name: (windows, domain labels)}; nearest: optional {name: median nearest-training RMS}."""
    out = {}
    for d in sorted(set(target_domain)):
        t = target[target_domain == d]
        rows = {"real_train_people": distances(reference[reference_domain == d], t)}
        for name, (x, dom) in sources.items():
            if (dom == d).any():
                rows[name] = distances(x[dom == d], t)
        out[d] = rows
    summary = {}
    for name in ["real_train_people", *sources]:
        keys = ("psd_pulse", "psd_stop", "acf", "morphology", "values_ks")
        per = [out[d][name] for d in out if name in out[d]]
        summary[name] = {k: float(np.mean([p[k] for p in per])) for k in keys}
        real = summary.get("real_train_people")
        if name != "real_train_people":
            summary[name]["ratio_to_real"] = {k: summary[name][k]/max(real[k], 1e-9) for k in keys}
        if nearest and name in nearest:
            summary[name]["nearest_training_rms"] = nearest[name]
    return dict(per_domain=out, summary=summary)


def figures(folder, sources, target, target_domain, report):
    """Per domain: FIGURE_WINDOWS real validation windows and the same count per source, with PSD and ACF overlays."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    t = np.arange(target.shape[1])/FS
    paths = []
    for d, rows in report["per_domain"].items():
        names = ["real_validation", *[n for n in sources if n in rows]]
        fig, axes = plt.subplots(len(names)+1, 1, figsize=(14, 2.2*(len(names)+1)))
        for ax, name in zip(axes, names):
            x = target[target_domain == d] if name == "real_validation" else sources[name][0][sources[name][1] == d]
            for k, row in enumerate(x[:FIGURE_WINDOWS]):
                ax.plot(t, row+1.1*k, lw=.6)
            ax.set_title(f"{d}: {name}", fontsize=9)
            ax.set_yticks([])
        ax = axes[-1]
        any_row = next(iter(rows.values()))
        ax.plot(any_row["psd"]["freq"], any_row["psd"]["target"], "k", lw=1.5, label="real validation")
        for name, r in rows.items():
            ax.plot(r["psd"]["freq"], r["psd"]["candidate"], lw=.8, label=name)
        ax.set_xlabel("Hz")
        ax.set_ylabel("median log10 PSD")
        ax.legend(fontsize=6, ncol=3)
        fig.tight_layout()
        path = folder/f"waveforms_{d}.png"
        fig.savefig(path, dpi=110)
        plt.close(fig)
        paths.append(str(path))
    return paths


def report(folder, sources, target, target_domain, reference, reference_domain, nearest=None):
    """SIMILARITY_P5.json, the figures and samples.npz (the windows compared) under folder."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    result = compare(sources, target, target_domain, reference, reference_domain, nearest)
    result["figures"] = figures(folder/"figures", sources, target, target_domain, result)
    np.savez_compressed(folder/"samples.npz", real_validation=target, real_validation_domain=target_domain,
                        **{f"{n}": x for n, (x, _) in sources.items()},
                        **{f"{n}_domain": dom for n, (_, dom) in sources.items()})
    save_json(folder/"SIMILARITY_P5.json", result)
    return result
