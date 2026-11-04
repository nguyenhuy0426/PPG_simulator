"""Step C: independent judges of generated PPG (report only, CPU).

The project's C2ST judge (control.Probe, a 3-layer derivative CNN trained from scratch for 600 steps on a few hundred
windows) only learns whatever separates the two sets it is given; it has no prior knowledge of real PPG. Three checks
that do not share its blind spots:

1. PaPaGei-S (Pillai et al., ICLR 2025; ml/third_party/papagei): a ResNet encoder pre-trained on ~57,000 h of real
   PPG from public datasets, frozen. Real and generated windows go through the same path (40 Hz -> 125 Hz, three
   10 s segments, z-scored, mean 512-d embedding per window); then a person-grouped linear C2ST on the embeddings,
   the Frechet distance and k-NN fidelity/coverage, each next to the level real windows of other people reach.
2. Physiological features of each window computed by a separate signal-processing path (beat template, dicrotic
   notch, systolic upstroke share, APG b/a, pulse amplitude variation, beat-to-beat shape consistency): distance to
   real as a ratio to the real-vs-real distance (1 = as close as another person's recording).
3. Which frequency band the CNN judge relies on: the same C2ST with real and generated windows both restricted to
   one band at a time (0.5-1.5, 1.5-3, 3-5, 5-8 Hz).

Nothing here feeds back into training or model selection. Engineering evaluation of normalised 30 s PPG shape;
not clinical validation, not measured on the Pi/DAC/OPT101.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.linalg import sqrtm
from scipy.signal import resample_poly
from scipy.stats import wasserstein_distance
import torch
from torch.nn import functional as F

from ml.kaggle_lsm.train_lsm import FS, LENGTH, save_json
from ml.kaggle_multidomain import control
from ml.kaggle_multidomain.data_gxu import load_input
from ml.kaggle_multidomain.flow import window_peaks
from ml.kaggle_multidomain.fresh_galaxy import app_sources, balanced, checkpoint_source, load_galaxy, wrist_prompts
from ml.kaggle_multidomain.realism import folds_of, grouped_c2st, lsm_source, rows

# papagei_s.pt of Zenodo record 13983110 (23,339,216 bytes, Zenodo md5 a4cdb32392e2a7b25999128af92813b5).
PAPAGEI_SHA256 = "79d68671e51bdc951fee853e5a8241099e38148ff26ed888b843849332e0b988"
PAPAGEI_CONFIG = dict(in_channels=1, base_filters=32, kernel_size=3, stride=2, groups=1, n_block=18, n_classes=512,
                      n_experts=3)
PAPAGEI_FS, SEGMENT_S = 125, 10
BANDS = {"0.5-1.5 Hz": (.5, 1.5), "1.5-3 Hz": (1.5, 3.), "3-5 Hz": (3., 5.), "5-8 Hz": (5., 8.)}
FEATURES = ("rise_fraction", "amplitude_cv", "beat_consistency", "notch_share", "notch_phase", "apg_b_over_a",
            "ibi_cv")
V3_ARENAS = ("gxu_finger", "perform_large", "bidmc", "wrist")


# ---------------------------------------------------------------- PaPaGei
def load_papagei(path, sha256):
    from ml.third_party.papagei.resnet import ResNet1DMoE
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("PaPaGei weights checksum mismatch")
    state = torch.load(path, map_location="cpu", weights_only=True)
    state = {k[7:] if k.startswith("module.") else k: v for k, v in state.items()}
    model = ResNet1DMoE(**PAPAGEI_CONFIG)
    model.load_state_dict(state)
    return model.eval()


def papagei_segments(x):
    """(n, 1200) at 40 Hz -> (3n, 1, 1250): resampled to 125 Hz (polyphase 25/8), cut into 10 s, z-scored."""
    y = resample_poly(np.asarray(x, np.float64), 25, 8, axis=1)  # 40 Hz * 25/8 = 125 Hz
    size = PAPAGEI_FS*SEGMENT_S
    parts = y[:, :y.shape[1]//size*size].reshape(len(y), -1, size).reshape(-1, size)
    parts = (parts-parts.mean(1, keepdims=True))/np.maximum(parts.std(1, keepdims=True), 1e-8)
    return torch.tensor(parts[:, None], dtype=torch.float32), y.shape[1]//size


def papagei_embed(model, x, batch=96):
    segments, per_window = papagei_segments(x)
    with torch.inference_mode():
        out = torch.cat([model(part)[0] for part in segments.split(batch)]).numpy()
    return out.reshape(len(x), per_window, -1).mean(1)


def frechet(a, b):
    mu, nu = a.mean(0), b.mean(0)
    ca, cb = np.cov(a, rowvar=False), np.cov(b, rowvar=False)
    root = sqrtm(ca@cb)
    return float(((mu-nu)**2).sum()+np.trace(ca+cb-2*np.real(root)))


def linear_c2st(real, real_groups, other, other_groups, folds=4, seed=0, steps=300, decay=1e-2):
    """Person-grouped linear probe on frozen embeddings; mean out-of-fold AUC."""
    rng = np.random.default_rng(seed)
    folds = min(folds, len(np.unique(real_groups)), len(np.unique(other_groups)) if other_groups is not None else folds)
    rf = folds_of(real_groups, folds, rng)
    of = folds_of(other_groups, folds, rng) if other_groups is not None else rng.permutation(len(other)) % folds
    aucs = []
    for k in range(folds):
        train = np.r_[real[rf != k], other[of != k]]
        mean, std = train.mean(0), np.maximum(train.std(0), 1e-6)
        x = torch.tensor((train-mean)/std, dtype=torch.float32)
        y = torch.tensor(np.r_[np.zeros((rf != k).sum()), np.ones((of != k).sum())], dtype=torch.float32)
        torch.manual_seed(seed+k)
        layer = torch.nn.Linear(x.shape[1], 1)
        optimizer = torch.optim.Adam(layer.parameters(), lr=1e-2, weight_decay=decay)
        for _ in range(steps):
            optimizer.zero_grad(set_to_none=True)
            F.binary_cross_entropy_with_logits(layer(x)[:, 0], y).backward()
            optimizer.step()
        with torch.no_grad():
            score = lambda a: layer(torch.tensor((a-mean)/std, dtype=torch.float32))[:, 0].numpy()
            aucs.append(control.auc(score(real[rf == k]), score(other[of == k])))
    return float(np.mean(aucs))


def knn_pr(fake, real, k=5):
    from scipy.spatial.distance import cdist
    rr, ff, rf = cdist(real, real), cdist(fake, fake), cdist(real, fake)
    np.fill_diagonal(rr, np.inf)
    np.fill_diagonal(ff, np.inf)
    k = min(k, len(fake)-1, len(real)-1)
    radius_r, radius_f = np.partition(rr, k-1, 1)[:, k-1], np.partition(ff, k-1, 1)[:, k-1]
    return float((rf <= radius_r[:, None]).any(0).mean()), float((rf <= radius_f[None, :]).any(1).mean())


# ---------------------------------------------------------------- physiology
def beat_template(row, peaks, size=256):
    """Mean foot-to-foot beat (resampled to size points, min-max normalised) and the per-beat arrays."""
    ibi = np.median(np.diff(peaks))
    feet, beats, amps, rises = [], [], [], []
    for p in peaks:
        lo = int(max(0, p-.6*ibi))
        if int(p) <= lo:
            continue
        feet.append(lo+int(np.argmin(row[lo:int(p)+1])))
    for a, b, p in zip(feet[:-1], feet[1:], peaks):
        if b-a < 8:
            continue
        beat = np.interp(np.linspace(a, b, size), np.arange(len(row)), row)
        amps.append(row[int(round(p))]-row[a])
        rises.append((p-a)/(b-a))
        beats.append((beat-beat.min())/max(np.ptp(beat), 1e-9))
    if len(beats) < 3:
        return None
    beats = np.asarray(beats)
    return beats.mean(0), beats, np.asarray(amps), np.asarray(rises)


def physiology(x):
    """(n, len(FEATURES)) independent per-window physiology features; NaN where no beat sequence is found."""
    out = np.full((len(x), len(FEATURES)), np.nan)
    for i, row in enumerate(np.asarray(x, np.float64)):
        peaks = window_peaks(row)
        if peaks is None or len(peaks) < 5:
            continue
        found = beat_template(row, peaks)
        if found is None:
            continue
        template, beats, amps, rises = found
        corr = [np.corrcoef(b, template)[0, 1] for b in beats]
        notch = [has_notch(b) for b in beats]
        apg = np.gradient(np.gradient(np.convolve(template, np.ones(9)/9, mode="same")))
        a_index = int(np.argmax(apg[:96]))
        b_value = apg[a_index:a_index+48].min() if a_index < 200 else np.nan
        ibi = np.diff(peaks)
        out[i] = (np.median(rises), np.std(amps)/max(abs(np.mean(amps)), 1e-9), np.median(corr),
                  np.mean([n is not None for n in notch]),
                  np.median([n for n in notch if n is not None]) if any(n is not None for n in notch) else np.nan,
                  b_value/max(apg[a_index], 1e-9), ibi.std()/ibi.mean())
    return out


def has_notch(beat):
    """Phase (0-1) of a dicrotic notch, None if absent: after the steepest descent of the downslope, either a local
    minimum followed by a diastolic rise of at least 2% of the beat, or a shoulder where the slope eases (a local
    maximum of the first derivative) and then steepens again by at least 5% of the steepest slope."""
    smooth = np.convolve(beat, np.ones(9)/9, mode="same")
    peak = int(np.argmax(smooth[:180]))
    d1 = np.gradient(smooth)
    for j in range(peak+8, 230):
        if d1[j-1] < 0 <= d1[j] and smooth[j+1:j+40].max()-smooth[j] >= .02:
            return j/255
    start = peak+4
    slope = d1[start:235]
    if len(slope) < 10:
        return None
    steep = int(np.argmin(slope))
    for k in range(steep+1, len(slope)-1):
        if slope[k] > slope[k-1] and slope[k] >= slope[k+1] and slope[k] < 0 \
                and slope[k+1:k+60].min() < slope[k]-.05*abs(slope[steep]):
            return (start+k)/255
    return None


def feature_distance(target, candidate, reference_gap):
    """Per feature: W1(candidate, target) / W1(real other people, target); NaN-safe; plus share measurable."""
    out = {}
    for j, name in enumerate(FEATURES):
        t, c = target[:, j][np.isfinite(target[:, j])], candidate[:, j][np.isfinite(candidate[:, j])]
        if len(t) < 10 or len(c) < 10:
            out[name] = dict(ratio=None, median=float(np.median(c)) if len(c) else None)
            continue
        gap = wasserstein_distance(t, c)
        out[name] = dict(w1=float(gap), median=float(np.median(c)), real_median=float(np.median(t)),
                         ratio=float(gap/max(reference_gap[name], 1e-9)) if reference_gap else 1.)
    # notch_phase is NaN for a beat template without a notch; a window is measurable when its beats were found.
    out["measurable_share"] = float(np.isfinite(candidate[:, 0]).mean())
    return out


# ---------------------------------------------------------------- band diagnostic
def band_limit(x, lo, hi):
    f = np.fft.rfftfreq(LENGTH, 1/FS)
    y = np.fft.irfft(np.fft.rfft(np.asarray(x, np.float64), axis=1)*((f >= lo) & (f < hi)), n=LENGTH, axis=1)
    y = (y-y.min(1, keepdims=True))/np.maximum(np.ptp(y, 1, keepdims=True), 1e-9)
    return y.astype(np.float32)


def indistinguishable(auc):
    return 100*(1-abs(2*auc-1))


# ---------------------------------------------------------------- one comparison
def judge_all(real, real_groups, candidates, papagei, steps, seed, bands=True):
    """candidates: name -> (windows, groups or None). Every judge on the same windows."""
    target_embed = papagei_embed(papagei, real) if papagei is not None else None
    target_phys = physiology(real)
    other = candidates.get("real_other_people")
    other_phys = physiology(other[0]) if other is not None else None
    reference_gap = None
    if other_phys is not None:
        reference_gap = {}
        for j, name in enumerate(FEATURES):
            t, o = target_phys[:, j], other_phys[:, j]
            t, o = t[np.isfinite(t)], o[np.isfinite(o)]
            reference_gap[name] = wasserstein_distance(t, o) if len(t) >= 10 and len(o) >= 10 else np.nan
    out = {}
    for name, (x, groups) in candidates.items():
        entry = {}
        auc, _ = grouped_c2st(real, real_groups, x, groups, 4, steps, seed)
        entry["cnn"] = dict(auc=auc, indistinguishable=indistinguishable(auc))
        if bands:
            entry["cnn_by_band"] = {}
            for band, (lo, hi) in BANDS.items():
                b_auc, _ = grouped_c2st(band_limit(real, lo, hi), real_groups, band_limit(x, lo, hi), groups, 4, steps,
                                        seed)
                entry["cnn_by_band"][band] = indistinguishable(b_auc)
        if papagei is not None:
            emb = papagei_embed(papagei, x)
            p_auc = linear_c2st(target_embed, real_groups, emb, groups, seed=seed)
            precision, recall = knn_pr(emb, target_embed)
            entry["papagei"] = dict(auc=p_auc, indistinguishable=indistinguishable(p_auc), frechet=frechet(target_embed, emb),
                                    fidelity=precision, coverage=recall)
        entry["physiology"] = feature_distance(target_phys, physiology(x), reference_gap if name != "real_other_people"
                                               else None)
        out[name] = entry
        print(name, json.dumps({"cnn": round(entry["cnn"]["indistinguishable"], 1),
                                "papagei": round(entry.get("papagei", {}).get("indistinguishable", float("nan")), 1),
                                "bands": {k: round(v, 1) for k, v in entry.get("cnn_by_band", {}).items()}}), flush=True)
    return out


# ---------------------------------------------------------------- arenas
def galaxy_arena(galaxy, sources, people, papagei, n, halvings, steps, seed=0):
    """GalaxyPPG people (everyday E4 wrist): half are the target, the other half's labels prompt every source."""
    people = np.asarray(sorted(people))
    usable = np.flatnonzero((galaxy["group"] != "unlabeled") & np.isin(galaxy["subject"], people))
    result = []
    for h in range(halvings):
        rng = np.random.default_rng(seed+100*h)
        target_people = set(rng.permutation(people)[:len(people)//2])
        inside = np.array([s in target_people for s in galaxy["subject"]])
        target = balanced(galaxy["subject"], usable[inside[usable]], n, rng)
        other = balanced(galaxy["subject"], usable[~inside[usable]], n, rng)
        candidates = dict(real_other_people=(galaxy["signal"][other], galaxy["subject"][other]))
        for name, (generate, meta) in sources.items():
            prompts, rates = wrist_prompts(meta, galaxy["signal"][other], galaxy["polar_hr"][other])
            candidates[name] = (generate(prompts, rates, seed+100*h+1), None)
        print("galaxy halving", h, flush=True)
        result.append(judge_all(galaxy["signal"][target], galaxy["subject"][target], candidates, papagei, steps, seed+h))
    return result


def v3_arena(pack, sources, domain, papagei, n, steps, seed=0, bands=True):
    """Unseen people of one v3 dataset (validation + test) against real windows of training people and every source
    prompted with training windows' labels (as realism.realism)."""
    from ml.kaggle_multidomain.realism import balanced as balanced_pack
    d = V3_ARENAS.index(domain)
    unseen = balanced_pack(pack, rows(pack, ("validation", "test"), domain), n, np.random.default_rng(seed+10*d))
    train = rows(pack, ("train",), domain)
    size = min(n, len(train))
    others = balanced_pack(pack, train, size, np.random.default_rng(seed+10*d+1))
    prompts = balanced_pack(pack, train, size, np.random.default_rng(seed+10*d+2))
    candidates = dict(real_other_people=(pack["signal"][others], pack["subject"][others]))
    candidates.update({name: (generate(prompts, seed+10*d+3), None) for name, generate in sources.items()})
    print("v3 arena", domain, flush=True)
    return judge_all(pack["signal"][unseen], pack["subject"][unseen], candidates, papagei, steps, seed+d, bands)


def app_v3_sources(bundle, pack):
    """The app's TorchScript generators prompted with v3 training-window labels; LSM-GAN and the Gaussian shaper."""
    from ml.kaggle_multidomain.experiment_v3 import conditions_for
    from ml.kaggle_multidomain.realism import development_of, gaussian_source
    development, to_dev = development_of(pack)
    conditions = conditions_for(development, "v2")
    manifest = json.loads((Path(bundle)/"manifest.json").read_text())
    if not np.allclose(conditions.center, manifest["physiomix"]["center"], rtol=1e-4) or \
            list(conditions.domains) != manifest["physiomix"]["domains"]:
        raise ValueError("Condition layout differs from the app's")
    out = {}
    for slot in ("physiomix", "physioflow"):
        model = torch.jit.load(str(Path(bundle)/manifest["models"][f"{slot}_generator"]["file"]), map_location="cpu").eval()

        def generate(ids, seed, model=model):
            z = torch.randn(len(ids), LENGTH, generator=torch.Generator().manual_seed(seed))
            c = torch.from_numpy(conditions.for_ids(to_dev(ids)))
            with torch.inference_mode():
                return torch.cat([model(a, b) for a, b in zip(z.split(32), c.split(32))])[:, 0].numpy()
        out[slot] = generate
    out["lsm_gan"] = lsm_source(Path(bundle)/manifest["models"]["lsm_generator"]["file"])
    out["gaussian_shaper"] = gaussian_source(development, to_dev)
    return out


def summarize_halvings(per_halving):
    """Mean +- SD over halvings of the headline numbers of each candidate."""
    out = {}
    for name in per_halving[0]:
        values = lambda f: [f(h[name]) for h in per_halving]
        stat = lambda v: dict(mean=float(np.nanmean(v)), sd=float(np.nanstd(v, ddof=1)) if len(v) > 1 else 0.)
        entry = dict(cnn=stat(values(lambda e: e["cnn"]["indistinguishable"])))
        if "cnn_by_band" in per_halving[0][name]:
            entry["cnn_by_band"] = {b: stat(values(lambda e, b=b: e["cnn_by_band"][b])) for b in BANDS}
        if "papagei" in per_halving[0][name]:
            entry["papagei"] = {k: stat(values(lambda e, k=k: e["papagei"][k]))
                                for k in ("indistinguishable", "frechet", "fidelity", "coverage")}
        entry["physiology_ratio"] = {f: stat([np.nan if h[name]["physiology"][f].get("ratio") is None
                                              else h[name]["physiology"][f]["ratio"] for h in per_halving])
                                     for f in FEATURES}
        entry["physiology_median"] = {f: stat([np.nan if h[name]["physiology"][f].get("median") is None
                                               else h[name]["physiology"][f]["median"] for h in per_halving])
                                      for f in FEATURES}
        out[name] = entry
    return out


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="Directory holding the verified v3 pack")
    parser.add_argument("--galaxy", required=True, help="Directory of galaxyppg_windows.npz")
    parser.add_argument("--galaxy-manifest", required=True, help="v3g manifest.json (the 12 GalaxyPPG test people)")
    parser.add_argument("--bundle", default="assets/neural")
    parser.add_argument("--papagei", required=True)
    parser.add_argument("--papagei-sha256", default=PAPAGEI_SHA256)
    parser.add_argument("--extra", action="append", default=[],
                        help="name=run_dir:arm:prompt_domain:pack_root:protocol (a retrained checkpoint, GalaxyPPG only)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=192)
    parser.add_argument("--halvings", type=int, default=3)
    parser.add_argument("--c2st-steps", type=int, default=600)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--skip-v3", action="store_true")
    a = parser.parse_args(argv)
    torch.set_num_threads(a.threads)
    papagei = load_papagei(a.papagei, a.papagei_sha256)
    pack, manifest = load_input(a.data, "ppg_physiomix_v3")
    galaxy = load_galaxy(a.galaxy)
    test_people = json.loads(Path(a.galaxy_manifest).read_text())["galaxyppg"]["people"]["external"]
    app = app_sources(a.bundle)
    galaxy_sources = {k: app[k] for k in ("physiomix", "physioflow", "lsm_gan", "gaussian_shaper")}
    for spec in a.extra:
        name, rest = spec.split("=", 1)
        run_dir, arm, prompt_domain, pack_root, protocol = rest.split(":")
        extra_pack, _ = load_input(pack_root, protocol)
        development = {k: v[np.isin(extra_pack["split"], ["train", "validation"])] for k, v in extra_pack.items()}
        galaxy_sources[name] = checkpoint_source(development, run_dir, arm, prompt_domain=prompt_domain)
    result = dict(scope=__doc__.split("\n\n")[-1].strip(), papagei=dict(sha256=a.papagei_sha256, config=PAPAGEI_CONFIG,
                  source="Zenodo 10.5281/zenodo.13983110 papagei_s.pt; code BSD-3-Clause-Clear, Nokia Bell Labs"),
                  data_sha256=manifest["windows_sha256"], test_people=test_people, bands=BANDS, features=FEATURES)
    per_halving = galaxy_arena(galaxy, galaxy_sources, test_people, papagei, a.samples, a.halvings, a.c2st_steps)
    result["galaxy_test"] = dict(summary=summarize_halvings(per_halving), per_halving=per_halving)
    save_json(Path(a.output), result)
    if not a.skip_v3:
        v3_sources = app_v3_sources(a.bundle, pack)
        result["v3_unseen"] = {}
        for domain in V3_ARENAS:
            entry = v3_arena(pack, v3_sources, domain, papagei, a.samples, a.c2st_steps)
            result["v3_unseen"][domain] = dict(summary=summarize_halvings([entry]), detail=entry)
            save_json(Path(a.output), result)
    return result


if __name__ == "__main__":
    main()
