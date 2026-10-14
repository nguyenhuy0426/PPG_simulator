"""Fresh external test on GalaxyPPG (Park et al., Scientific Data 2025, CC BY 4.0; Zenodo 10.5281/zenodo.14635823).

No model in this project was trained, selected or tuned on GalaxyPPG, so it judges the app models without the
optimism of a validation split reused for many rounds. Source: Empatica E4 wrist BVP (64 Hz) of 24 people over a
~60 min protocol (rest, stress tasks, typing, standing, walking, jogging, running); reference rate from the Polar H10
chest strap (1 Hz HR). Windows go through the same v3 view (0.5-8 Hz, 40 Hz, 30 s, per-window normalised) as the
training data.

Every app model is prompted as the wrist domain with the labels of real windows of one half of the people and
compared with real windows of the other half (3 random halvings). The decision rule is fixed in RULE before any
score is computed. Engineering evaluation of normalised waveform shape and rate following only: no SpO2, no paired
IR/RED, no Pi/DAC/OPT101 measurement, not clinical validation.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import FS, LENGTH, save_json
from ml.kaggle_multidomain import control
from ml.kaggle_multidomain.data_gxu import load_input
from ml.kaggle_multidomain.data_more import finite_windows
from ml.kaggle_multidomain.experiment_v3 import PROTOCOL, PromptedEvaluator
from ml.kaggle_multidomain.labels import robust_labels
from ml.kaggle_multidomain.physio import view_mask
from ml.kaggle_multidomain.realism import grouped_c2st, lsm_source

ZIP_MD5 = "d9a48bfcd07928fb22b96dc40cf2e7d4"
E4_FS = 64.
# The Polar phone clock is Korean local time written as a Unix epoch; E4 and Event.csv are UTC. prepare() reports
# the PPG-vs-Polar rate error at both offsets so a wrong offset is visible.
POLAR_OFFSET_MS = 9*3600*1000
MIN_POLAR_SAMPLES = 20
GALAXY_SPLIT_SEED = 20261014
GROUPS = {"rest": ("adaptation", "baseline", "meditation-1", "meditation-2", "rest-1", "rest-2", "rest-3", "rest-4",
                   "rest-5", "screen-reading"),
          "cognitive": ("tsst-prep", "tsst-speech", "ssst-prep", "ssst-sing", "keyboard-typing", "mobile-typing",
                        "standing"),
          "walking": ("walking",), "jogging_running": ("jogging", "running")}
SOURCES = ("physiomix", "physioflow", "lsm_gan", "gaussian_shaper")
RULE = ("Fresh GalaxyPPG test, fixed before scoring. Primary: mean 'indistinguishable' 100(1-|2AUC-1|) of a "
        "person-grouped derivative-CNN C2ST over 3 random halvings of the people. PhysioFlow replaces PhysioMix as the "
        "app model only if its mean exceeds PhysioMix's by more than 2x the larger halving SD, AND its GalaxyPPG Q is "
        "not worse by more than 0.05, AND its median |rate error| against the prompted Polar HR is not worse by more "
        "than 2 bpm. Otherwise PhysioMix stays. LSM-GAN and the Gaussian shaper are reported only.")


def _rows(z, name):
    with z.open(name) as handle:
        return list(csv.DictReader(io.TextIOWrapper(handle, "utf-8")))


def sessions(z, uid):
    """[(session, enter_ms, exit_ms)]; one 'unlabeled' span when a participant has no Event.csv."""
    name = f"Dataset/{uid}/Event.csv"
    if name not in z.namelist():
        return [("unlabeled", -np.inf, np.inf)]
    open_at, out = {}, []
    for row in _rows(z, name):
        t = int(row["timestamp"])
        if row["status"] == "ENTER":
            open_at[row["session"]] = t
        elif row["status"] == "EXIT" and row["session"] in open_at:
            out.append((row["session"], open_at.pop(row["session"]), t))
    return out


def group_of(session):
    return next((g for g, names in GROUPS.items() if session in names), "unlabeled")


def prepare(zip_path, output, md5=ZIP_MD5):
    """Windows of every participant's E4 BVP per session, with the Polar median HR of each window."""
    zip_path, output = Path(zip_path), Path(output)
    if md5 is not None and hashlib.md5(zip_path.read_bytes()).hexdigest() != md5:
        raise ValueError("GalaxyPPG archive checksum mismatch")
    out = {k: [] for k in ("signal", "subject", "session", "group", "start_ms", "polar_hr", "polar_hr_utc")}
    with zipfile.ZipFile(zip_path) as z:
        uids = [r["UID"] for r in _rows(z, "Dataset/Meta.csv")]
        for uid in uids:
            bvp = np.array([(float(r["value"]), int(r["timestamp"])/1000) for r in _rows(z, f"Dataset/{uid}/E4/BVP.csv")])
            polar = np.array([(int(r["phoneTimestamp"]), float(r["hr"])) for r in _rows(z, f"Dataset/{uid}/PolarH10/HR.csv")])
            for session, enter, leave in sessions(z, uid):
                keep = (bvp[:, 1] >= enter) & (bvp[:, 1] < leave)
                if keep.sum() < 30*E4_FS:
                    continue
                t0 = bvp[keep, 1][0]
                clips, _ = finite_windows(bvp[keep, 0], E4_FS, "v3")
                for start, wave in clips:
                    begin = t0+1000*start/FS
                    out["signal"].append(wave)
                    out["subject"].append("galaxyppg:"+uid)
                    out["session"].append(session)
                    out["group"].append(group_of(session))
                    out["start_ms"].append(begin)
                    for key, offset in (("polar_hr", POLAR_OFFSET_MS), ("polar_hr_utc", 0)):
                        inside = (polar[:, 0]-offset >= begin) & (polar[:, 0]-offset < begin+30000)
                        out[key].append(float(np.median(polar[inside, 1])) if inside.sum() >= MIN_POLAR_SAMPLES
                                        else float("nan"))
            print(uid, sum(s == "galaxyppg:"+uid for s in out["subject"]), "windows", flush=True)
    pack = {k: np.asarray(v, dtype=np.float32 if k == "signal" else None) for k, v in out.items()}
    rate, _, _ = robust_labels(pack["signal"])
    # None: no window overlaps the Polar record at that clock offset.
    errors = {key: (float(np.nanmedian(np.abs(rate-pack[key]))) if np.isfinite(rate-pack[key]).any() else None)
              for key in ("polar_hr", "polar_hr_utc")}
    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output/"galaxyppg_windows.npz", **pack)
    manifest = dict(source="GalaxyPPG, Zenodo 10.5281/zenodo.14635823, CC BY 4.0", archive_md5=md5,
                    windows=int(len(pack["signal"])), people=int(len(set(pack["subject"]))),
                    per_group={g: int((pack["group"] == g).sum()) for g in (*GROUPS, "unlabeled")},
                    ppg_vs_polar_median_abs_bpm=errors, polar_offset_ms=POLAR_OFFSET_MS,
                    view="v3 0.5-8 Hz, 40 Hz, 30 s", channel="Empatica E4 BVP (wrist), 64 Hz")
    save_json(output/"manifest.json", manifest)
    return pack, manifest


def person_split(people, seed=GALAXY_SPLIT_SEED):
    """Fixed before any GalaxyPPG training: half of the people may train, the other half are only ever tested."""
    order = np.random.default_rng(seed).permutation(sorted(set(people)))
    return {p: ("train" if i < len(order)//2 else "external") for i, p in enumerate(order)}


def extend_pack(v3_root, galaxy_root, output):
    """The verified v3 pack plus the GalaxyPPG windows as wrist: training people in 'train', test people in
    'external' (never trained on, never used for checkpoint selection). Labels: Polar HR as the ECG-gated rate
    reference, walking / jogging-running mapped to the wrist walk / run activity codes."""
    from ml.kaggle_multidomain.data import digest, validate_pack
    from ml.kaggle_multidomain.experiment_v3 import DATA_SHA256_V3
    pack, base = load_input(v3_root, "ppg_physiomix_v3")
    if base["windows_sha256"] != DATA_SHA256_V3:
        raise ValueError("Extend only the verified v3 pack")
    g = load_galaxy(galaxy_root)
    split = person_split(g["subject"])
    n = len(g["signal"])
    activity = np.select([g["group"] == "walking", g["group"] == "jogging_running"], [0, 1], -1).astype(np.int8)
    extra = dict(signal=g["signal"].astype(np.float32), subject=g["subject"], domain=np.full(n, "wrist"),
                 split=np.array([split[s] for s in g["subject"]]), record=np.char.add(np.char.add(g["subject"], ":"),
                                                                                     g["session"]),
                 start=np.round(g["start_ms"]).astype(np.int64), activity_label=activity,
                 rhythm_label=np.full(n, -1, np.int8), reference_hr_bpm=g["polar_hr"].astype(np.float32))
    merged = {k: np.concatenate([pack[k], extra[k].astype(pack[k].dtype) if k not in ("subject", "record", "split",
                                                                                         "domain") else extra[k]])
              for k in pack}
    validate_pack(merged)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output/"windows.npz", **merged)
    for side in Path(v3_root).rglob("gxu_red_windows.npz"):
        (output/side.name).write_bytes(side.read_bytes())
    people = {s: sorted(p for p, v in split.items() if v == s) for s in ("train", "external")}
    manifest = {**base, "protocol": "ppg_physiomix_v3g", "windows_sha256": digest(output/"windows.npz"),
                "base_windows_sha256": base["windows_sha256"],
                "galaxyppg": dict(source=json.loads((Path(galaxy_root)/"manifest.json").read_text()),
                                  split_seed=GALAXY_SPLIT_SEED, people=people,
                                  windows={s: int((extra["split"] == s).sum()) for s in ("train", "external")})}
    save_json(output/"manifest.json", manifest)
    return merged, manifest


def load_galaxy(root):
    with np.load(Path(root)/"galaxyppg_windows.npz", allow_pickle=False) as source:
        return {k: source[k] for k in source.files}


def wrist_prompts(meta, signal, polar_hr):
    """App condition rows (wrist one-hot, both labels known) from real windows: Polar HR where available, otherwise
    the PPG consensus rate, otherwise the wrist default; robust IBI CV; the window's own std."""
    rate, irr, _ = robust_labels(signal)
    rate = np.where(np.isfinite(polar_hr), polar_hr, rate)
    default_irr, _ = meta["domain_defaults"]["wrist"]
    lo, hi = meta["hr_support_bpm"]
    rate = np.clip(np.where(np.isfinite(rate), rate, np.nanmedian(rate)), lo, hi)
    irr = np.clip(np.where(np.isfinite(irr), irr, default_irr), 0, .35)
    raw = np.c_[rate, irr, signal.std(1)]
    onehot = np.array([[float(d == "wrist") for d in meta["domains"]]]*len(signal))
    flags = np.ones((len(signal), 2)) if meta.get("condition_version") == "v2" else np.zeros((len(signal), 0))
    return np.c_[onehot, flags, (raw-meta["center"])/meta["scale"]].astype(np.float32), rate


def app_sources(bundle):
    """name -> (generate(condition rows, prompted rates, seed), condition metadata) for the exact TorchScript files
    the app ships."""
    bundle = Path(bundle)
    manifest = json.loads((bundle/"manifest.json").read_text())
    sources, meta = {}, manifest["physiomix"]
    for slot in ("physiomix", "physioflow"):
        entry = manifest["models"][f"{slot}_generator"]
        path = bundle/entry["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"{slot} checksum mismatch")
        model = torch.jit.load(str(path), map_location="cpu").eval()

        def generate(rows, rates, seed, model=model):
            z = torch.randn(len(rows), LENGTH, generator=torch.Generator().manual_seed(seed))
            with torch.inference_mode():
                parts = [model(a, b) for a, b in zip(z.split(32), torch.from_numpy(rows).split(32))]
            return torch.cat(parts)[:, 0].numpy().astype(np.float32)
        sources[slot] = (generate, manifest[slot])
    lsm = lsm_source(bundle/manifest["models"]["lsm_generator"]["file"])
    # Unconditioned / rate-only sources still need the shared prompt rates; any app schema gives them.
    sources["lsm_gan"] = (lambda rows, rates, seed: lsm(np.arange(len(rows)), seed), meta)
    sources["gaussian_shaper"] = (lambda rows, rates, seed: np.asarray(
        control.gaussian_reference(rates, view_mask("v3"), seed), np.float32), meta)
    return sources


def checkpoint_source(development, run_dir, arm):
    """(generate, condition metadata) for a trained checkpoint (best.pt in run_dir), in the app's schema layout."""
    from ml.kaggle_multidomain.experiment_v3 import conditions_for, config, load_best, sampler
    cfg = config(arm)
    conditions = conditions_for(development, cfg["version"])
    model, cfg = load_best(arm, Path(run_dir), conditions, None, "cpu")
    run = sampler(model, cfg, "cpu")
    meta = dict(domains=conditions.domains, center=conditions.center.tolist(), scale=conditions.scale.tolist(),
                domain_defaults=conditions.defaults, condition_version=cfg["version"], hr_support_bpm=[40., 180.])

    def generate(rows, rates, seed):
        return run(torch.randn(len(rows), LENGTH, generator=torch.Generator().manual_seed(seed)), rows).astype(np.float32)
    return generate, meta


def balanced(subjects, ids, n, rng):
    """Up to n distinct windows of ids, every person weighted equally."""
    _, inverse, counts = np.unique(subjects[ids], return_inverse=True, return_counts=True)
    p = 1/counts[inverse]
    return rng.choice(ids, min(n, len(ids)), replace=False, p=p/p.sum())


def rate_error(x, prompted):
    """|measured - prompted| bpm per window (PPG consensus rate of the generated window; NaN if unmeasurable)."""
    measured, _, _ = robust_labels(x)
    return np.abs(measured-prompted)


def median_or_none(err):
    """Median |rate error| over measurable windows; None (JSON null) when no window is measurable."""
    err = err[np.isfinite(err)]
    return float(np.median(err)) if len(err) else None


def evaluate(galaxy, development, sources, n=256, halvings=3, folds=4, steps=600, seed=0, groups=tuple(GROUPS),
             people=None):
    """Per halving: target = real windows of half the people; candidates = real windows of the other half and
    every source prompted with that other half's labels. Overall C2ST/Q/coverage, then rate error per group.
    people: restrict to these people (e.g. the GalaxyPPG test people after some were used for training)."""
    evaluator = PromptedEvaluator(development, 16)
    people = np.unique(galaxy["subject"]) if people is None else np.asarray(sorted(people))
    usable = np.flatnonzero((galaxy["group"] != "unlabeled") & np.isin(galaxy["subject"], people))
    per_halving = []
    for h in range(halvings):
        rng = np.random.default_rng(seed+100*h)
        target_people = set(rng.permutation(people)[:len(people)//2])
        in_target = np.array([s in target_people for s in galaxy["subject"]])
        target = balanced(galaxy["subject"], usable[in_target[usable]], n, rng)
        other = balanced(galaxy["subject"], usable[~in_target[usable]], n, rng)
        real = galaxy["signal"][target]
        reference = evaluator.blocks(real)
        # Real windows of the other people are scored against the same prompted rates (their own labels).
        _, rates = wrist_prompts(next(iter(sources.values()))[1], galaxy["signal"][other], galaxy["polar_hr"][other])
        candidates = dict(real_other_people=(galaxy["signal"][other], galaxy["subject"][other], rates))
        for name, (generate, meta) in sources.items():
            rows, prompted = wrist_prompts(meta, galaxy["signal"][other], galaxy["polar_hr"][other])
            candidates[name] = (generate(rows, prompted, seed+100*h+1), None, prompted)
        entry = {}
        for name, (x, x_groups, rates) in candidates.items():
            quality, _ = evaluator.pool_quality(x, reference)
            auc, used = grouped_c2st(real, galaxy["subject"][target], x, x_groups, folds, steps, seed+h)
            err = rate_error(x, rates)
            entry[name] = dict(indistinguishable=100*(1-abs(2*auc-1)), c2st_auc=auc, folds=used, Q=quality["Q"],
                               fidelity=quality["precision"], coverage=quality["recall"],
                               rate_error_median_bpm=median_or_none(err),
                               rate_within_5bpm=float(np.mean(err <= 5)),
                               rate_error_by_group={g: median_or_none(err[galaxy["group"][other] == g])
                                                    for g in groups if (galaxy["group"][other] == g).any()})
            print("halving", h, name, {k: round(v, 3) for k, v in entry[name].items() if isinstance(v, float)}, flush=True)
        per_halving.append(entry)
    return summarize(per_halving), per_halving


def summarize(per_halving):
    names = list(per_halving[0])
    out = {}
    for name in names:
        values = {k: [h[name][k] for h in per_halving] for k in ("indistinguishable", "Q", "fidelity", "coverage",
                                                               "rate_error_median_bpm", "rate_within_5bpm")}
        # An unmeasurable halving (None) makes the summary unmeasurable; the rules count that as a failed check.
        out[name] = {k: dict(mean=None, sd=None) if None in v else
                     dict(mean=float(np.mean(v)), sd=float(np.std(v, ddof=1)) if len(v) > 1 else 0.)
                     for k, v in values.items()}
    return out


def rate_not_worse(mine, app, bpm=2):
    """Median |rate error| not worse than the app's by more than bpm; unmeasurable fails."""
    mine, app = mine["rate_error_median_bpm"]["mean"], app["rate_error_median_bpm"]["mean"]
    return mine is not None and app is not None and mine <= app+bpm


def decide(summary):
    """RULE applied to the summary; returns the app model to keep or adopt and the reasons."""
    mix, flow = summary["physiomix"], summary["physioflow"]
    margin = 2*max(mix["indistinguishable"]["sd"], flow["indistinguishable"]["sd"])
    gap = flow["indistinguishable"]["mean"]-mix["indistinguishable"]["mean"]
    checks = dict(realism=gap > margin,
                  q=flow["Q"]["mean"] <= mix["Q"]["mean"]+.05,
                  rate=rate_not_worse(flow, mix))
    return dict(rule=RULE, gap=gap, margin=margin, checks=checks,
                app_model="physioflow" if all(checks.values()) else "physiomix")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", help="GalaxyPPG.zip; prepares windows into --galaxy first")
    parser.add_argument("--galaxy", required=True, help="Directory of galaxyppg_windows.npz")
    parser.add_argument("--data", help="Verified v3 pack (fits the evaluator's feature scales)")
    parser.add_argument("--bundle", default="assets/neural")
    parser.add_argument("--output")
    parser.add_argument("--samples", type=int, default=256)
    parser.add_argument("--halvings", type=int, default=3)
    parser.add_argument("--c2st-steps", type=int, default=600)
    parser.add_argument("--threads", type=int, default=8)
    a = parser.parse_args(argv)
    torch.set_num_threads(a.threads)
    if a.zip:
        prepare(a.zip, a.galaxy)
    if not a.output:
        return None
    pack, manifest = load_input(a.data, PROTOCOL)
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    summary, per_halving = evaluate(load_galaxy(a.galaxy), development, app_sources(a.bundle), a.samples, a.halvings,
                                    steps=a.c2st_steps)
    result = dict(rule=RULE, decision=decide(summary), summary=summary, per_halving=per_halving,
                  galaxy=json.loads((Path(a.galaxy)/"manifest.json").read_text()), data_sha256=manifest["windows_sha256"],
                  scope="CPU engineering evaluation of normalised 30 s wrist PPG shape and rate following; "
                        "not clinical validation, not measured on the Pi/DAC/OPT101")
    save_json(Path(a.output), result)
    return result


if __name__ == "__main__":
    main()
