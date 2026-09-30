"""Separate signal-processing evaluator, not the training detector or critic.

Algorithmic independence is not an independent cohort or clinical ground truth.
Phase spectra/ACF describe pulses; they are not 30-second strip metrics.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.signal import savgol_filter
from scipy.spatial.distance import cdist


def landmarks(pulse):
    y = np.asarray(pulse, dtype=float)
    if y.shape != (256,) or not np.isfinite(y).all() or np.ptp(y) < 1e-8:
        raise ValueError("Expected a finite nonflat 256-point pulse")
    y = (y-y.min())/np.ptp(y)
    smooth = savgol_filter(y, 11, 3, mode="interp")
    derivative = np.gradient(smooth)
    maxima = np.flatnonzero((derivative[:-1] > 0) & (derivative[1:] <= 0)) + 1
    minima = np.flatnonzero((derivative[:-1] < 0) & (derivative[1:] >= 0)) + 1
    sp = int(np.argmax(smooth))
    result = dict(sp=sp/255, dn=None, dp=None, notch=False)
    for dn in minima:
        if dn <= sp+5 or dn >= 238:
            continue
        after = maxima[(maxima > dn+3) & (maxima < 244)]
        if len(after) and smooth[after[0]]-smooth[dn] >= .03:
            result.update(dn=float(dn/255), dp=float(after[0]/255), notch=True)
            break
    return result


def metrics(samples, requested, reference):
    samples, requested, reference = map(np.asarray, (samples, requested, reference))
    if samples.shape != reference.shape or samples.shape[1:] != (256,) or requested.shape != (len(samples), 7):
        raise ValueError("Expected matching pulse arrays and seven conditions")
    if not all(np.isfinite(v).all() for v in (samples, requested, reference)):
        raise ValueError("Nonfinite evaluation data")
    observed = [landmarks(y) for y in samples]
    found = np.array([m["notch"] for m in observed])
    positive = requested[:, -1] > .5
    recall = float(found[positive].mean()) if positive.any() else None
    specificity = float((~found[~positive]).mean()) if (~positive).any() else None
    errors = {}
    for field, column in (("sp", 1), ("dn", 2), ("dp", 3)):
        active = np.ones(len(samples), dtype=bool) if field == "sp" else positive
        values = [1. if item[field] is None else abs(item[field]-target[column])
                  for item, target, use in zip(observed, requested, active) if use]
        errors[field + "_phase_mae"] = float(np.mean(values)) if values else None
    def features(x):
        centered = x-x.mean(1, keepdims=True)
        f = np.fft.rfft(centered, n=512, axis=1)
        acf = np.fft.irfft(abs(f)**2, n=512, axis=1)[:, :128]
        acf /= np.maximum(acf[:, :1], 1e-12)
        psd = abs(np.fft.rfft(centered*np.hanning(256), axis=1))**2
        psd /= np.maximum(psd.sum(1, keepdims=True), 1e-12)
        return acf, psd
    acf, psd = features(samples)
    real_acf, real_psd = features(reference)
    physical_hz = np.arange(psd.shape[1])[None] * requested[:, 0, None]*200/60
    high = physical_hz > 5
    result = dict(**errors, requested_notch_recall=recall, requested_no_notch_specificity=specificity,
                  phase_acf_rmse=float(np.sqrt(np.mean((acf.mean(0)-real_acf.mean(0))**2))),
                  phase_log_psd_rmse=float(np.sqrt(np.mean((np.log10(psd+1e-8).mean(0)-
                                                          np.log10(real_psd+1e-8).mean(0))**2))),
                  above_5hz_power_fraction=float((psd*high).sum(1).mean()),
                  real_above_5hz_power_fraction=float((real_psd*high).sum(1).mean()),
                  roughness=float(np.abs(np.diff(samples, n=2, axis=1)).mean()),
                  real_roughness=float(np.abs(np.diff(reference, n=2, axis=1)).mean()),
                  boundary_value_jump=float(np.abs(samples[:, 0]-samples[:, -1]).mean()))
    if recall is not None and specificity is not None:
        result["development_score"] = (errors["sp_phase_mae"] + .25*(2-recall-specificity)
                                        + .25*(errors["dn_phase_mae"]+errors["dp_phase_mae"])
                                        + .1*result["phase_log_psd_rmse"]
                                        + result["phase_acf_rmse"]
                                        + abs(result["above_5hz_power_fraction"]-result["real_above_5hz_power_fraction"]))
    return result


def audit_current(prepared, architecture, pilot, output):
    import torch
    from ml.kaggle_arch.train_architectures import load_prepared, stratified_indices, infer
    from models.waveform import PulseShaper, WAVE_PPG
    torch.set_num_threads(1)
    x, c, masks = load_prepared(prepared)
    subjects = np.load(prepared, allow_pickle=False)["subject"]
    ids = stratified_indices(masks["validation"], c, maximum_per_class=128, seed=2809)
    reference, condition = x[ids], c[ids]
    z = np.random.default_rng(2809).standard_normal((len(ids), 32)).astype(np.float32)
    shaper = PulseShaper()
    gaussian = np.array([shaper.sample(WAVE_PPG, i/255) for i in range(256)])
    generated = {"Gaussian_original_fixed_preset": np.repeat(gaussian[None], len(ids), axis=0)}
    for name, path in (("cWGAN_pilot_v1", pilot / "generator_cpu.ts"),
                       ("TCN_seed42_step2800", architecture / "generator_cpu.ts")):
        g = torch.jit.load(str(path), map_location="cpu").eval()
        generated[name] = infer(g, condition, z, "cpu", batch=32)
    result = {}
    bank = x[masks["train"]][::max(1, int(masks["train"].sum())//2048)]
    for name, values in generated.items():
        result[name] = metrics(values, condition, reference)
        result[name]["nearest_train_rmse_median"] = float(np.median(np.sqrt(cdist(values, bank, "sqeuclidean").min(1)/256)))
        result[name]["by_subject"] = {str(s): metrics(values[subjects[ids] == s], condition[subjects[ids] == s],
                                                   reference[subjects[ids] == s]) for s in np.unique(subjects[ids])}
    output.mkdir(parents=True, exist_ok=False)
    (output / "metrics.json").write_text(json.dumps(dict(split="validation", samples=len(ids), results=result,
         evaluator="Savitzky-Golay derivative sign changes; independent implementation, not clinical truth",
         caveats=["Conditions still use old automatic labels until human review",
                  "No test data used; no retraining or promotion",
                  "Gaussian fixed preset is not conditioned on requested morphology",
                  "Pulse-grid metrics cannot be compared numerically to the LSM strip table"]), indent=2)+"\n")
    np.savez_compressed(output / "samples.npz", reference=reference, condition=condition, indices=ids, **generated)
    print(json.dumps({k: {m: v[m] for m in ("phase_acf_rmse", "phase_log_psd_rmse", "roughness")}
                      for k, v in result.items()}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=Path("ml/runs/kaggle-v1/ppg_run/prepared.npz"))
    parser.add_argument("--architecture", type=Path, default=Path("ml/runs/architecture-kaggle-v1/architecture_sweep/tcn_film_projection/seed_42"))
    parser.add_argument("--pilot", type=Path, default=Path("ml/runs/kaggle-v1/ppg_run"))
    parser.add_argument("--output", type=Path, default=Path("ml/runs/round2-independent-validation"))
    args = parser.parse_args()
    audit_current(args.prepared, args.architecture, args.pilot, args.output)
