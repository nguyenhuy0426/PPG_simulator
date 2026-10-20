"""Apply RULE_RHYTHM (rhythm.py): R0 versus R1 on validation windows, then the deployed-generator guard. Laptop CPU.

    PPG_DRY_RUN=1 .venv/bin/python -m ml.kaggle_multidomain.rhythm_eval --pack ml/runs/physioflow2-data-v4 \
        --output ml/runs/rhythm-v1/rhythm_eval.json
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import iqr, wasserstein_distance

from ml.kaggle_lsm.train_lsm import FS, save_json
from ml.kaggle_multidomain.data_dual import load_dual
from ml.kaggle_multidomain.experiment_v3 import TRAIN_DOMAINS
from ml.kaggle_multidomain.flow import window_peaks
from ml.kaggle_multidomain.rhythm import (BEATS, RULE_RHYTHM, RhythmModel, encode, features, fit_models, range_sigma,
                                          window_times)

DOMAINS = sorted(TRAIN_DOMAINS)+["ptt_sit", "ptt_walk", "ptt_run"]
SEED = 20261021
GUARD_PER_DOMAIN = 24


def real_sequences(pack, split):
    out = {}
    for d in DOMAINS:
        for i in np.flatnonzero((pack["domain"] == d) & (pack["split"] == split)):
            times = window_peaks(pack["signal"][i])
            if times is not None and len(times) >= 11:
                out.setdefault(d, []).append((int(i), times/FS))
    return out


def score(real, generated):
    terms = {}
    for k in ("lag1", "lag2", "rmssd_sdnn"):
        r, g = np.array([f[k] for f in real]), np.array([f[k] for f in generated])
        terms[k] = float(wasserstein_distance(r, g)/max(iqr(r), 1e-9))
    width = lambda f: f["range_hi"]-f["range_lo"]
    terms["range"] = float(np.mean([abs(np.log(max(width(g), 1e-6)/max(width(r), 1e-6))) for r, g in zip(real, generated)]))
    return float(np.mean(list(terms.values()))), terms


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True)
    parser.add_argument("--output", required=True)
    a = parser.parse_args(argv)
    pack, manifest = load_dual(a.pack)
    train = real_sequences(pack, "train")
    r1 = fit_models([pack["signal"][i] for d in train for i, _ in train[d]],
                    [d for d in train for _ in train[d]], window_peaks)
    valid = real_sequences(pack, "validation")
    rng = np.random.default_rng(SEED)
    result = dict(rule=RULE_RHYTHM, pack_windows_sha256=manifest["windows_sha256"], datasets={},
                  ar={d: dict(order=len(m.coef), coef=m.coef.tolist(), innovation_sd=m.innovation_sd) for d, m in r1.items()})
    totals = {"R0": [], "R1": []}
    mean_err = {"R0": [], "R1": []}
    commands = {}
    for d in DOMAINS:
        real_f, gen_f = [], {"R0": [], "R1": []}
        for i, times in valid.get(d, []):
            f = features(times)
            real_f.append(f)
            n = len(times)-1
            commands.setdefault(d, []).append((i, f["range_lo"], f["range_hi"], f["mean_bpm"]))
            for kind, model in (("R0", RhythmModel("R0")), ("R1", r1[d])):
                ibi, _, _ = model.intervals(f["range_lo"], f["range_hi"], n, rng, f["mean_bpm"])
                g = features(np.r_[0., np.cumsum(ibi)])
                gen_f[kind].append(g)
                mean_err[kind].append(abs(g["mean_bpm"]-f["mean_bpm"]))
        if not real_f:
            continue
        entry = dict(windows=len(real_f), real={k: float(np.median([f[k] for f in real_f])) for k in ("lag1", "lag2", "rmssd_sdnn")})
        for kind in ("R0", "R1"):
            s, terms = score(real_f, gen_f[kind])
            totals[kind].append(s)
            entry[kind] = dict(score=s, terms=terms,
                               median={k: float(np.median([f[k] for f in gen_f[kind]])) for k in ("lag1", "lag2", "rmssd_sdnn")})
        result["datasets"][d] = entry
        print(d, len(real_f), "R0", round(entry["R0"]["score"], 3), "R1", round(entry["R1"]["score"], 3), entry["real"],
              flush=True)
    overall = {k: float(np.mean(v)) for k, v in totals.items()}
    mae = {k: float(np.mean(v)) for k, v in mean_err.items()}
    replace = overall["R1"] < .8*overall["R0"] and mae["R1"] <= 1.
    chosen = "R1" if replace else "R0"
    result.update(overall=overall, mean_rate_abs_error_bpm=mae, R1_replaces_R0=bool(replace), chosen=chosen)
    # Guard: the deployed generators with the chosen rhythm encoded into z.
    from core.neural_preview import PhysioMixGenerator
    import torch
    torch.set_num_threads(8)
    guard = {}
    for name, slot in (("physiomix", "physiomix"), ("physioflow", "physioflow")):
        g = PhysioMixGenerator(slot=slot)
        errors = []
        for d in sorted(TRAIN_DOMAINS):
            for i, lo, hi, mean in commands.get(d, [])[:GUARD_PER_DOMAIN]:
                model = RhythmModel("R0") if chosen == "R0" else r1[d]
                mean = float(np.clip(mean, 40, 180))
                _, sigma, u = model.intervals(lo, hi, BEATS, rng, mean)
                z = encode(rng.standard_normal(1200), u, name)
                c = torch.tensor([g.condition(d, mean, sigma)])
                with torch.no_grad():
                    y = g.model(torch.tensor(z[None]), c)[0, 0].numpy()
                times = window_peaks(y)
                if times is None or len(times) < 3:
                    errors.append(20.)
                    continue
                errors.append(abs(60*FS/np.mean(np.diff(times))-mean))
        guard[name] = dict(windows=len(errors), mean_rate_abs_error_bpm=float(np.mean(errors)),
                           median=float(np.median(errors)), ok=bool(np.mean(errors) <= 1.))
        print("guard", name, guard[name], flush=True)
    result["guard"] = guard
    result["decision"] = chosen if all(v["ok"] for v in guard.values()) else ("R0" if chosen == "R1" else "R0 (guard failed)")
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    save_json(Path(a.output), result)
    print(json.dumps(dict(overall=overall, mae=mae, chosen=chosen, decision=result["decision"]), indent=1))


if __name__ == "__main__":
    main()
