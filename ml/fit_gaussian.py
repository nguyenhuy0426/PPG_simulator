"""Fit the existing three-Gaussian family on train only; audit validation once."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from models.waveform import PulseMorphology, PulseShaper, WAVE_PPG
from ml.independent_ppg_eval import landmarks, metrics

PREPARED_SHA256 = "25c830dc1613a0dbf9c3775fc87b95b966492fc0962a828c84543422fa278dcf"
PHASE = np.linspace(0, 1, 256)
KEYS = ("systolic_pos", "notch_pos", "diastolic_pos", "systolic_width",
        "notch_width", "diastolic_width", "diastolic_amplitude", "dicrotic_depth")
LOW = np.array([.06, .14, .22, .025, .008, .035, .05, 0.])
HIGH = np.array([.48, .75, .90, .25, .16, .35, 1.2, .80])


def vector_shape(params):
    sp, dn, dp, sw, nw, dw, da, depth = params
    g = lambda centre, width: np.exp(-.5*((PHASE-centre)/width)**2)
    edge = np.minimum(PHASE, 1-PHASE)/.05
    taper = np.where(edge < 1, edge*edge*(3-2*edge), 1.)
    y = taper*(g(sp,sw)+da*g(dp,dw))*(1-depth*g(dn,nw))
    return y/y.max()


def train_template(x, subjects):
    # Every subject has equal weight, irrespective of record length.
    return np.mean([x[subjects == s].mean(0) for s in np.unique(subjects)], axis=0)


def fit_template(target, seed=2909, starts=24, preserve_notch=False):
    lm = landmarks(target) if preserve_notch else None
    def residual(p):
        order = [max(0., p[0]+.015-p[1]), max(0., p[1]+.015-p[2])]
        y = vector_shape(p)
        features = []
        if lm and lm["notch"]:
            dn, dp = int(round(lm["dn"]*255)), int(round(lm["dp"]*255))
            rebound = max(.04, .8*float(target[dp]-target[dn]))
            features = [max(0., rebound-y[dp]+y[dn]),
                        max(0., y[dn]-y[dn-4]), max(0., y[dn]-y[dn+4]),
                        max(0., y[dp-4]-y[dp]), max(0., y[dp+4]-y[dp])]
        return np.r_[y-target, 10*np.asarray(order), 10*np.asarray(features)]
    rng = np.random.default_rng(seed)
    candidates = []
    for i in range(starts):
        initial = np.array([.18,.4,.55,.09,.04,.20,.4,.15]) if i == 0 else rng.uniform(LOW,HIGH)
        result = least_squares(residual, initial, bounds=(LOW,HIGH), max_nfev=1500,
                               ftol=1e-10, xtol=1e-10, gtol=1e-10)
        if result.x[0] < result.x[1] < result.x[2]:
            candidates.append(result)
    best = min(candidates, key=lambda r: np.sum(r.fun**2))
    morphology = PulseMorphology(**dict(zip(KEYS,map(float,best.x))))
    shaper = PulseShaper(morphology)
    pulse = np.array([shaper.sample(WAVE_PPG,float(t)) for t in PHASE])
    # Continuous peak normalization must agree with the numerical fitting grid.
    assert np.max(abs(pulse-vector_shape(best.x))) < .001
    return asdict(morphology), pulse, float(np.sqrt(np.mean((pulse-target)**2)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=Path("ml/runs/kaggle-v1/ppg_run/prepared.npz"))
    parser.add_argument("--output", type=Path, default=Path("ml/runs/gaussian-fit-final"))
    args = parser.parse_args()
    if hashlib.sha256(args.prepared.read_bytes()).hexdigest() != PREPARED_SHA256:
        raise ValueError("Prepared data hash mismatch")
    with np.load(args.prepared, allow_pickle=False) as data:
        x,c,subjects = data["pulse"],data["condition"],data["subject"]
        train,valid = data["train"].astype(bool),data["validation"].astype(bool)
    assert not set(subjects[train]) & set(subjects[valid])
    args.output.mkdir(parents=True, exist_ok=False)
    profiles, curves, templates = {}, {}, {}
    for label, mask in (("Balanced",train),("No notch",train & (c[:,-1]<=.5)),
                        ("With notch",train & (c[:,-1]>.5))):
        target = train_template(x[mask],subjects[mask])
        exemplar = None
        if label != "Balanced":
            # Averages smear features occurring at different phases. Choose a
            # real train exemplar nearest the balanced mean, whose morphology
            # is also detected by the independent algorithm. No validation search.
            candidates = np.flatnonzero(mask)
            candidates = candidates[np.argsort(np.mean((x[candidates]-target)**2,axis=1))]
            def suitable(i):
                marks = landmarks(x[i])
                if label == "No notch":
                    return not marks["notch"]
                return marks["notch"] and x[i,round(marks["dp"]*255)]-x[i,round(marks["dn"]*255)] >= .07
            exemplar = next(int(i) for i in candidates if suitable(i))
            target = x[exemplar]
        profile, curve, rmse = fit_template(target, preserve_notch=label == "With notch")
        profiles[label] = dict(morphology=profile, train_template_rmse=rmse,
                               reference_waveform=target.tolist(),
                               train_exemplar_index=exemplar, detected_notch=landmarks(curve)["notch"],
                               train_pulses=int(mask.sum()),train_subjects=len(np.unique(subjects[mask])))
        curves[label],templates[label] = curve,target
        print(label, rmse, profile,flush=True)
    manifest = dict(schema=1, formula="existing_three_gaussian_local_attenuation",
                    prepared_sha256=PREPARED_SHA256, profiles=profiles,
                    fit="24-start bounded least squares; balanced mean plus nearest real train class exemplars; notch extrema/rebound constraints for notch exemplar",
                    labels="Old automatic notch labels; not human-reviewed ground truth",
                    default="Balanced", source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (args.output/"profiles.json").write_text(json.dumps(manifest,indent=2)+"\n")
    # Evaluation is downstream of frozen train-fitted profiles; never used to refit.
    ids = np.flatnonzero(valid)
    real,condition = x[ids],c[ids]
    original = PulseShaper()
    old = np.array([original.sample(WAVE_PPG,float(t)) for t in PHASE])
    outputs = {"Original":np.repeat(old[None],len(ids),axis=0),
               "Fitted balanced":np.repeat(curves["Balanced"][None],len(ids),axis=0),
               "Fitted class presets":np.where((condition[:,-1]>.5)[:,None],curves["With notch"],curves["No notch"])}
    results = {}
    for name,generated in outputs.items():
        row = metrics(generated,condition,real)
        row["waveform_rmse"] = float(np.sqrt(np.mean((generated-real)**2)))
        row["by_subject"] = {}
        for subject in np.unique(subjects[ids]):
            mask=subjects[ids]==subject
            sub=metrics(generated[mask],condition[mask],real[mask])
            sub["waveform_rmse"]=float(np.sqrt(np.mean((generated[mask]-real[mask])**2)))
            row["by_subject"][str(subject)]=sub
        results[name]=row
    report = dict(split="validation",samples=len(ids),subjects=len(np.unique(subjects[ids])),results=results,
                  caveats=["Exploratory; test has been viewed previously but is not used here",
                           "One fixed template cannot reproduce population diversity",
                           "Class presets use old automatic condition labels; balanced preset does not",
                           "Pulse-phase metrics are not comparable to LSM long-strip metrics"])
    (args.output/"metrics.json").write_text(json.dumps(report,indent=2)+"\n")
    np.savez_compressed(args.output/"samples.npz",reference=real,condition=condition,indices=ids,
                        **outputs,**{"template_"+k:v for k,v in templates.items()})
    print(json.dumps({k:{m:v[m] for m in ('waveform_rmse','phase_acf_rmse','phase_log_psd_rmse','above_5hz_power_fraction','real_above_5hz_power_fraction')} for k,v in results.items()},indent=2))


if __name__ == "__main__":
    main()
