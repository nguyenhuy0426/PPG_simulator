"""Strict-judge C2ST and feature check of PPG-physiGPT samples against MIMIC-III WDB windows.

Reuses the project's StrictJudge (ml.kaggle_multidomain.strict_judge: time + spectral + acf views, ~3 M parameters,
random 25.6 s crops, early stopping on held-out people) unchanged; only the data are new.
People are MIMIC records (a record is the person unit of the shard's own people-level split; two records may belong
to one patient, which the shard metadata cannot tell). Real windows come in three kinds:
- fit / inner / control_train / control_eval: training records (windows the generator saw), split by record
  60/10/15/15; the judge fits on `fit`, stops early on `inner`;
- held-out: the shard's valid records, never trained on by the generator. They are the real class of every final score.
  They also chose best.pt (a single scalar), so they are a test set for the judge, not for checkpoint selection.
Sources judged by the same procedure (a fresh judge per source and seed; AUC scored on people the judge never saw):
- real_other_people (null control): real windows of other records; the judge should stay near AUC 0.5;
- noise_1pct, phase_randomized, circular_filter: real windows damaged on purpose; a judge that cannot separate
  them has no power and says nothing about the generator;
- generated: windows from the model (seeds differ between fit, inner and final sets).
Scores: AUC, balanced accuracy / accuracy / precision / recall / F1 at logit 0 with generated or damaged = positive,
ROC points. Engineering evaluation of normalised waveform shape at 40 Hz; not clinical validation.
Mode features is the pass criterion of the feature goal (target_report): the 14 signal features and the beat layer
against held-out people, written to target.json. The strict judge stays as a record and no longer decides a pass.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy import stats
from scipy.signal import find_peaks
import torch

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain import control, strict_judge as sj
from ml.kaggle_physigpt.mimic_wdb import rate_features
from ml.kaggle_physigpt.model import CONFIGS, PhysiGPT
from ml.kaggle_physigpt.train import Windows

SEED = 20261029
SHARES = (("fit", .6), ("inner", .1), ("control_train", .15), ("control_eval", .15))
SIZES = dict(fit=6000, inner=1000, eval=2000)
EVAL_ROLES = ("held_out", "control_eval")
BANDS = {"0.5-1.5 Hz": (.5, 1.5), "1.5-3 Hz": (1.5, 3.), "3-5 Hz": (3., 5.), "5-8 Hz": (5., 8.), "8-20 Hz": (8., 20.)}


class Real:
    """Real windows by role, drawn person-balanced from the records of that role."""

    def __init__(self, roots, seed=SEED):
        self.data = Windows(roots)
        record, valid = self.data.record, np.zeros(len(self.data.record), bool)
        valid[self.data.valid] = True
        rng = np.random.default_rng(seed)
        people = rng.permutation(np.unique(record[~valid]))
        cut = np.cumsum([int(round(share*len(people))) for _, share in SHARES])
        cut[-1] = len(people)
        self.rows = {}
        for name, part in zip((n for n, _ in SHARES), np.split(people, cut[:-1])):
            self.rows[name] = np.flatnonzero(np.isin(record, part))
        self.rows["held_out"] = self.data.valid
        self.record = record
        self.rng = np.random.default_rng(seed+1)
        self.used = set()

    def people(self, role):
        return len(np.unique(self.record[self.rows[role]]))

    def pick(self, role, n):
        """Sorted rows of n windows of the role, each record weighted equally. Training roles never repeat a window (the
        sets stay disjoint); the evaluation roles (held_out, control_eval) return the same rows on every call."""
        evaluation = role in EVAL_ROLES
        rows = self.rows[role]
        if not evaluation and self.used:
            rows = rows[~np.isin(rows, np.fromiter(self.used, np.int64))]
        if len(rows) < n:
            raise ValueError(f"{role}: {len(rows)} windows available, need {n}")
        _, inverse, counts = np.unique(self.record[rows], return_inverse=True, return_counts=True)
        weight = 1/counts[inverse]
        rng = np.random.default_rng(SEED+3) if evaluation else self.rng
        pick = rng.choice(rows, n, replace=False, p=weight/weight.sum())
        if not evaluation:
            self.used.update(pick.tolist())
        return np.sort(pick)

    def windows(self, rows):
        return (self.data.rows(rows).astype(np.float32)/65535).copy()

    def draw(self, role, n):
        return self.windows(self.pick(role, n))


def damaged(real, damage):
    """(fit, inner, final) windows of a damaged-real source; the final set is built from control_eval people."""
    rng = np.random.default_rng(SEED+2)
    return (damage(real.draw("fit", SIZES["fit"]), rng), damage(real.draw("inner", SIZES["inner"]), rng),
            damage(real.draw("control_eval", SIZES["eval"]), rng))


DAMAGE = dict(noise_1pct=lambda x, rng: sj.noisy(x, rng),
              phase_randomized=lambda x, rng: sj.phase_randomized(x, rng),
              circular_filter=lambda x, rng: sj.circular_filter(x))


def confusion(real_score, fake_score):
    tp, fn = int((fake_score > 0).sum()), int((fake_score <= 0).sum())
    fp, tn = int((real_score > 0).sum()), int((real_score <= 0).sum())
    precision, recall = tp/max(tp+fp, 1), tp/max(tp+fn, 1)
    return dict(tp=tp, fn=fn, fp=fp, tn=tn, precision=precision, recall=recall,
                f1=2*precision*recall/max(precision+recall, 1e-12),
                accuracy=(tp+tn)/(tp+tn+fp+fn), balanced_accuracy=.5*(recall+tn/max(tn+fp, 1)))


def roc_points(real_score, fake_score, n=41):
    cuts = np.quantile(np.r_[real_score, fake_score], np.linspace(0, 1, n))
    return [dict(threshold=float(c), fpr=float((real_score > c).mean()), tpr=float((fake_score > c).mean()))
            for c in cuts]


def bootstrap_auc(real_score, fake_score, rounds=200, seed=0):
    rng = np.random.default_rng(seed)
    values = [control.auc(real_score[rng.integers(len(real_score), size=len(real_score))],
                          fake_score[rng.integers(len(fake_score), size=len(fake_score))]) for _ in range(rounds)]
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


def judge_source(name, real, fake_sets, kind, seeds, device, output):
    fit_fake, inner_fake, eval_fake = fake_sets
    real_fit, real_inner = real.draw("fit", SIZES["fit"]), real.draw("inner", SIZES["inner"])
    real_eval = real.draw("held_out", SIZES["eval"])
    runs = []
    for seed in seeds:
        started = time.time()
        model, history = sj.fit(kind, real_fit, fit_fake, real_inner, inner_fake, device, seed)
        a, b = sj.scores(model, kind, real_eval, torch.device(device)), sj.scores(model, kind, eval_fake,
                                                                                torch.device(device))
        auc = control.auc(a, b)
        run = dict(seed=seed, auc=auc, auc_ci95=bootstrap_auc(a, b), indistinguishable=100*(1-abs(2*auc-1)),
                   inner_auc=max(h["inner_auc"] for h in history), minutes=(time.time()-started)/60,
                   **confusion(a, b), roc=roc_points(a, b))
        np.savez_compressed(output/f"scores_{name}_seed{seed}.npz", real=a, fake=b)
        print(f"{name} seed {seed}: AUC {auc:.3f} {run['auc_ci95']} F1 {run['f1']:.3f} "
              f"bal.acc {run['balanced_accuracy']:.3f} ({run['minutes']:.1f} min)", flush=True)
        runs.append(run)
    return dict(source=name, runs=runs, mean_auc=float(np.mean([r["auc"] for r in runs])))


# ------------------------------------------------------------------ features
def signal_features(x):
    """Per-window features for distribution comparison (x in [0, 1], [n, LENGTH])."""
    acf, rate = rate_features(x)
    spectrum = np.abs(np.fft.rfft(x-x.mean(1, keepdims=True), axis=1))**2
    freq = np.fft.rfftfreq(LENGTH, 1/FS)
    power = spectrum/np.maximum(spectrum[:, 1:].sum(1, keepdims=True), 1e-12)
    out = dict(rate_bpm=rate, acf_peak=acf, diff_std=np.diff(x, axis=1).std(1),
               diff2_std=np.diff(x, 2, axis=1).std(1), skew=stats.skew(x, axis=1),
               kurtosis=stats.kurtosis(x, axis=1), diff_skew=stats.skew(np.diff(x, axis=1), axis=1),
               mean_level=x.mean(1), centroid_hz=(power*freq).sum(1))
    for label, (lo, hi) in BANDS.items():
        out[f"power_{label}"] = np.log10(power[:, (freq >= lo) & (freq < hi)].sum(1)+1e-9)
    return out


def distance(a, b):
    return dict(ks=float(stats.ks_2samp(a, b).statistic),
                wasserstein_over_real_std=float(stats.wasserstein_distance(a, b)/max(a.std(), 1e-9)),
                real_median=float(np.median(a)), fake_median=float(np.median(b)),
                real_iqr=[float(np.percentile(a, 25)), float(np.percentile(a, 75))],
                fake_iqr=[float(np.percentile(b, 25)), float(np.percentile(b, 75))])


def feature_report(real_eval, other_people, generated):
    """Generated vs held-out real, next to real vs real of other people (the distance people alone produce)."""
    r, o, g = signal_features(real_eval), signal_features(other_people), signal_features(generated)
    return {k: dict(generated=distance(r[k], g[k]), real_other_people=distance(r[k], o[k])) for k in r}


# ------------------------------------------------------------------ feature fidelity
# A second, coarser tier next to the strict judge (which is unchanged): do the generated windows have the dataset's
# signal features? Per feature 1 - KS against held-out real people, and a classifier that sees only those features.
# Real people against other real people set the reference, since no generator can be closer than that.
FIDELITY_SIM = .95    # mean over the features of 1 - KS
FIDELITY_ACC = .60    # accuracy of the feature classifier (0.5 = indistinguishable)
# V1 criterion: the generated mean similarity reaches 95% of real people against other real people (about 0.96, so
# the absolute 0.95 asks for 99% of what real data reach). The absolute pair above stays as the stricter V2 target.
FIDELITY_REL = .95


def feature_matrix(x):
    f = signal_features(x)
    return list(f), np.stack([f[k] for k in f], 1)


def classify(train_real, train_fake, test_real, test_fake, seed=None):
    """Feature-only classifiers, real against generated: fitted on the train sets, scored on the test sets."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    x = np.vstack([train_real, train_fake])
    y = np.r_[np.zeros(len(train_real)), np.ones(len(train_fake))]
    mu, sd = x.mean(0), x.std(0)+1e-9
    yt = np.r_[np.zeros(len(test_real)), np.ones(len(test_fake))]
    out = {}
    for name, model in (("logreg", LogisticRegression(max_iter=3000)),
                        ("trees", HistGradientBoostingClassifier(max_iter=200, random_state=seed))):
        score = model.fit((x-mu)/sd, y).predict_proba((np.vstack([test_real, test_fake])-mu)/sd)[:, 1]
        order = np.argsort(np.argsort(score))+1
        pos = yt == 1
        out[name] = dict(auc=float((order[pos].sum()-pos.sum()*(pos.sum()+1)/2)/(pos.sum()*(~pos).sum())),
                         accuracy=float(((score > .5) == pos).mean()))
    return out


def fidelity_report(real_fit, real_held, real_other, gen_fit, gen_eval):
    """Per-feature similarity and feature-only classifiers (train: real_fit vs gen_fit; test: held-out people)."""
    names, held = feature_matrix(real_held)
    other, fit, gfit, geval = (feature_matrix(x)[1] for x in (real_other, real_fit, gen_fit, gen_eval))

    def similarity(a, b):
        return np.array([1-stats.ks_2samp(a[:, j], b[:, j]).statistic for j in range(a.shape[1])])

    def summary(s, c2st):
        return dict(similarity=dict(zip(names, s.tolist())), mean_similarity=float(s.mean()),
                    share_at_least_95=float((s >= FIDELITY_SIM).mean()), classifier=c2st)

    half = len(fit)//2
    generated = summary(similarity(held, geval), classify(fit, gfit, held, geval))
    reference = summary(similarity(held, other), classify(fit[:half], fit[half:], held, other))
    generated["passes"] = bool(generated["mean_similarity"] >= FIDELITY_SIM
                               and generated["classifier"]["trees"]["accuracy"] <= FIDELITY_ACC)
    generated["relative_similarity"] = generated["mean_similarity"]/reference["mean_similarity"]
    generated["passes_relative"] = bool(generated["relative_similarity"] >= FIDELITY_REL)
    return dict(generated=generated, real_other_people=reference,
                criteria=dict(mean_similarity_at_least=FIDELITY_SIM, tree_classifier_accuracy_at_most=FIDELITY_ACC,
                              relative_mean_similarity_at_least=FIDELITY_REL))


# ------------------------------------------------------------------ beat morphology
# A layer of its own, not part of signal_features: gan.py and rsr_flowgan.py select checkpoints on the mean over
# signal_features, and the 14-feature scores on record must stay comparable. Measured on the v3 view (0.5-8 Hz,
# min-max, 40 Hz), so these describe the filtered waveform, not raw physiology: an 8 Hz band limit and 25 ms samples
# bound how short a rise can look. Engineering shape features; not clinical measurements.
BEAT_MIN_S, BEAT_MAX_S = .3, 2.     # beat length, the 30-200 bpm of RATE_LAGS
# Of the window's 5-95 percentile span, as labels.beat_stats. On real perform_large windows 0.2-0.5 left the shape
# medians nearly unchanged; ibi_cv is the sensitive one (median 0.058 at 0.2, 0.061 at 0.3, 0.088 at 0.5).
BEAT_PROMINENCE = .3
BEAT_SMOOTH = 3                     # samples of moving average, for finding peaks only
BEAT_MIN_BEATS = 3                  # two intervals, the fewest that have a spread
BEAT_POINTS = 64                    # samples per beat when beats are compared with their template
BEAT_SLOPE = 5                      # template points over which the slope of the fall is taken
BEAT_SCORED = ("beat_coverage", "rise_time_s", "systolic_fraction", "width_50_s", "area_fraction", "template_corr",
               "amp_cv", "ibi_cv")
# Dicrotic notch traces, reported but outside every score: under 1% noise the Spearman correlation with the clean value
# is 0.69 and 0.86 on real perform_large windows, against at least 0.96 for the scored features, and most of these
# band-limited windows have no rebound at all (median 0.000).
BEAT_DIAGNOSTIC = ("dicrotic_rebound", "descent_flatness")


def crossing(y, top, level, step):
    """Interpolated sample where y first falls below level, walking from top by step (-1 back, +1 ahead)."""
    i = top
    while 0 <= i+step < len(y) and y[i+step] >= level:
        i += step
    if not 0 <= i+step < len(y):
        return float(i)
    return i+step*(y[i]-level)/max(y[i]-y[i+step], 1e-12)


def beats_of(x):
    """(foot, next foot, peak offset, amplitude, beat with the foot line removed and peak 1) of each whole beat."""
    span = np.percentile(x, 95)-np.percentile(x, 5)
    smooth = np.convolve(x, np.ones(BEAT_SMOOTH)/BEAT_SMOOTH, mode="same")
    peaks = find_peaks(smooth[1:-1], distance=int(BEAT_MIN_S*FS), prominence=max(BEAT_PROMINENCE*span, 1e-9))[0]+1
    feet = [lo+int(np.argmin(x[lo:hi+1])) for lo, hi in zip(peaks, peaks[1:])]
    beats = []
    for a, b in zip(feet, feet[1:]):
        if not BEAT_MIN_S*FS <= b-a <= BEAT_MAX_S*FS:
            continue
        y = x[a:b+1]-(x[a]+(x[b]-x[a])*np.arange(b-a+1)/(b-a))
        top = int(np.argmax(y))
        if y[top] > 0 and 0 < top < b-a:
            beats.append((a, b, top, y[top], y/y[top]))
    return beats


def window_beats(x):
    """Medians over the beats of one window; beat_coverage alone is defined when the window has too few beats."""
    x = np.asarray(x, np.float64)
    out = dict.fromkeys(BEAT_SCORED+BEAT_DIAGNOSTIC, np.nan)
    beats = beats_of(x) if np.isfinite(x).all() else []
    out["beat_coverage"] = sum(b-a for a, b, *_ in beats)/len(x)
    if len(beats) < BEAT_MIN_BEATS:
        return out
    rise, fraction, width, area, amplitude, shape, peak = [], [], [], [], [], [], []
    for a, b, top, amp, y in beats:
        rise.append((crossing(y, top, .9, -1)-crossing(y, top, .1, -1))/FS)
        fraction.append(top/(b-a))
        width.append((crossing(y, top, .5, 1)-crossing(y, top, .5, -1))/FS)
        area.append(y.mean())
        amplitude.append(amp)
        shape.append(np.interp(np.linspace(0, b-a, BEAT_POINTS), np.arange(b-a+1), y))
        i, curve = a+top, x[a+top-1]-2*x[a+top]+x[a+top+1]   # interpolated: 25 ms steps alone give a CV near 0.01
        peak.append(i+(.5*(x[i-1]-x[i+1])/curve if curve < 0 else 0.))
    shape, interval = np.array(shape), np.diff(peak)/FS
    template = np.median(shape, 0)
    fall = template[int(np.argmax(template)):]
    slope = (fall[BEAT_SLOPE:]-fall[:-BEAT_SLOPE])/BEAT_SLOPE*(BEAT_POINTS-1)
    middle = (fall[:-BEAT_SLOPE] < .8) & (fall[:-BEAT_SLOPE] > .2)
    z = (shape-shape.mean(1, keepdims=True))/np.maximum(shape.std(1, keepdims=True), 1e-9)
    out.update(rise_time_s=np.median(rise), systolic_fraction=np.median(fraction), width_50_s=np.median(width),
               area_fraction=np.median(area), amp_cv=np.std(amplitude)/max(np.mean(amplitude), 1e-9),
               template_corr=np.mean(z@((template-template.mean())/max(template.std(), 1e-9))/BEAT_POINTS),
               ibi_cv=interval.std()/interval.mean(), dicrotic_rebound=(fall-np.minimum.accumulate(fall)).max(),
               descent_flatness=slope[middle].max() if middle.any() else np.nan)
    return out


def beat_features(x):
    """Per-window beat features, name to array ([n, LENGTH] in [0, 1]). NaN marks a window with too few beats; that is
    data, not a gap to fill: beat_coverage carries it into the comparison."""
    rows = [window_beats(w) for w in x]
    return {k: np.array([r[k] for r in rows], np.float64) for k in BEAT_SCORED+BEAT_DIAGNOSTIC}


# ------------------------------------------------------------------ target: features like the dataset's
# The pass criterion of the feature goal. The strict judge (raw-waveform C2ST) is no longer a pass criterion: it reaches
# AUC 1.0 on every model and on 1% noise while real against real stays near 0.53. Its code and evidence stay as a
# record. All three values below are proposals awaiting the user's decision (see the hand-over report).
TARGET_MEAN = FIDELITY_SIM      # mean 1 - KS over signal_features + BEAT_SCORED
TARGET_FLOOR = .90              # every scored feature, or what real people reach against other real people if lower
TARGET_ACC = FIDELITY_ACC       # accuracy of the feature classifier on held-out people (0.5 = indistinguishable)


def finite_similarity(a, b):
    """1 - KS over the finite values; 0 when one side has none (no beats found is as far as a feature can be)."""
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    return float(1-stats.ks_2samp(a, b).statistic) if len(a) and len(b) else 0.


def all_features(x):
    return {**signal_features(x), **beat_features(x)}


def target_matrix(features, fill=None):
    """Scored features as a matrix for the classifiers, NaN filled with the given medians (default: its own)."""
    names = [k for k in features if k not in BEAT_DIAGNOSTIC]
    m = np.stack([features[k] for k in names], 1)
    fill = np.nanmedian(m, 0) if fill is None else fill
    return np.where(np.isfinite(m), m, fill), fill


def target_verdict(mean, floors_missed, accuracy, reference_mean):
    """pass; fail; or inconclusive when real people themselves miss the mean on this set, so the set cannot show it."""
    if mean >= TARGET_MEAN and not floors_missed and accuracy <= TARGET_ACC:
        return "pass"
    return "inconclusive" if reference_mean < TARGET_MEAN else "fail"


def target_report(real_fit, real_held, real_other, gen_fit, gen_eval, seed=0):
    """Generated windows against held-out people on the 14 features and the beat layer, reported apart and together.
    Same sets as fidelity_report, so its 14-feature mean is this report's fourteen.mean_similarity."""
    held, other, geval = all_features(real_held), all_features(real_other), all_features(gen_eval)
    fourteen = [k for k in held if k not in BEAT_SCORED+BEAT_DIAGNOSTIC]
    scored = [*fourteen, *BEAT_SCORED]

    def similarity(side):
        return {k: finite_similarity(held[k], side[k]) for k in held}

    def part(sim, keys):
        return dict(mean_similarity=float(np.mean([sim[k] for k in keys])), features=len(keys))

    def summary(side):
        sim = similarity(side)
        return dict(similarity=sim, fourteen=part(sim, fourteen), beat=part(sim, BEAT_SCORED), full=part(sim, scored),
                    windows_with_beats=float(np.isfinite(side["rise_time_s"]).mean()),
                    lowest=min(scored, key=sim.get))

    generated, reference = summary(geval), summary(other)
    fit, fill = target_matrix(all_features(real_fit))
    gfit = target_matrix(all_features(gen_fit), fill)[0]
    generated["classifier"] = classify(fit, gfit, target_matrix(held, fill)[0], target_matrix(geval, fill)[0], seed)
    floor = {k: min(TARGET_FLOOR, reference["similarity"][k]) for k in scored}
    generated["below_floor"] = sorted(k for k in scored if generated["similarity"][k] < floor[k])
    generated["relative_similarity"] = generated["full"]["mean_similarity"]/reference["full"]["mean_similarity"]
    verdict = target_verdict(generated["full"]["mean_similarity"], generated["below_floor"],
                             generated["classifier"]["trees"]["accuracy"], reference["full"]["mean_similarity"])
    return dict(verdict=verdict, generated=generated, real_other_people=reference, floor=floor,
                diagnostic_only=list(BEAT_DIAGNOSTIC), windows=dict(held=len(real_held), other=len(real_other),
                                                                    generated=len(gen_eval)),
                criteria=dict(mean_similarity_at_least=TARGET_MEAN, floor_at_least=TARGET_FLOOR,
                              tree_classifier_accuracy_at_most=TARGET_ACC))


def target_inputs(output, real, held_rows, other_rows, fit_rows, gen_eval):
    """What compare_target needs after the kernel is gone: per-window features with each real window's record, and
    digests that show two runs scored the same real windows. Features only, no waveforms."""
    sets = {}
    for role, rows in (("held", held_rows), ("other", other_rows), ("fit", fit_rows)):
        sets[role] = dict(windows=len(rows), people=len(np.unique(real.record[rows])),
                          rows_sha256=hashlib.sha256(np.asarray(rows, np.int64).tobytes()).hexdigest(),
                          records_sha256=hashlib.sha256(np.asarray(real.record[rows], np.int64).tobytes()).hexdigest(),
                          windows_sha256=hashlib.sha256(real.data.rows(rows).tobytes()).hexdigest())
    arrays = dict(held_person=real.record[held_rows], other_person=real.record[other_rows])
    for side, x in (("held", real.windows(held_rows)), ("other", real.windows(other_rows)), ("generated", gen_eval)):
        arrays.update({f"{side}/{k}": v for k, v in all_features(x).items()})
    np.savez_compressed(Path(output)/"target_inputs.npz", **arrays)
    (Path(output)/"real_sets.json").write_text(json.dumps(sets, indent=1))


# ------------------------------------------------------------------ generation
def generate(checkpoint, n, seed, device, batch=250, steps=32, clamp=True):
    state = torch.load(checkpoint, map_location="cpu", weights_only=False)
    model = PhysiGPT(CONFIGS[state["config"]]).to(device).eval()
    model.load_state_dict(state["model"])
    parts = [model.generate(min(batch, n-i), steps=steps, seed=seed+i, device=device,
                           clamp=clamp).float().cpu().numpy()
             for i in range(0, n, batch)]
    return np.concatenate(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--data", nargs="+", required=True, help="shard roots (manifest.json under each)")
    parser.add_argument("--mode", choices=("controls", "model", "features"), required=True)
    parser.add_argument("--checkpoint", help="release.pt / best.pt of the stage (mode model, features)")
    parser.add_argument("--generated", help="npy of generated windows to reuse instead of sampling")
    parser.add_argument("--kind", default="strict", choices=sorted(set(sj.JUDGES)-{"probe"}))
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument("--only", nargs="*", help="controls: subset of null, noise_1pct, phase_randomized, ...")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--sizes", type=int, nargs=3, metavar=("FIT", "INNER", "EVAL"),
                        help="windows per set (smoke tests only; record it in the report)")
    parser.add_argument("--no-clamp", action="store_true", help="sample patches without clipping them to [0, 1]")
    parser.add_argument("--gen-steps", type=int, default=32, help="Heun steps per patch when sampling the generator")
    parser.add_argument("--steps", type=int, help="override judge steps (smoke tests only; record it in the report)")
    args = parser.parse_args(argv)
    torch.set_num_threads(args.threads)
    if args.sizes:
        SIZES.update(zip(("fit", "inner", "eval"), args.sizes))
    if args.steps:
        sj.JUDGES[args.kind]["steps"] = args.steps
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    real = Real(args.data)
    info = dict(kind=args.kind, parameters=sj.parameters(args.kind), judge_steps=sj.JUDGES[args.kind]["steps"],
                people={k: real.people(k) for k in ("fit", "inner", "control_train", "control_eval", "held_out")},
                windows={k: int(len(v)) for k, v in real.rows.items()}, sizes=SIZES, seeds=args.seeds,
                gen_steps=args.gen_steps, clamp=not args.no_clamp)
    print(json.dumps(info), flush=True)
    if args.mode == "controls":
        results = []
        wanted = args.only or ["null", *DAMAGE]
        for name in wanted:
            if name == "null":
                fakes = (real.draw("control_train", SIZES["fit"]), real.draw("control_train", SIZES["inner"]),
                         real.draw("control_eval", SIZES["eval"]))
                results.append(judge_source("real_other_people", real, fakes, args.kind, args.seeds, args.device,
                                            output))
            else:
                results.append(judge_source(name, real, damaged(real, DAMAGE[name]), args.kind, args.seeds,
                                            args.device, output))
            (output/f"controls_{'_'.join(wanted)}.json").write_text(json.dumps(dict(info=info, results=results)))
        return
    if args.generated:
        generated = np.load(args.generated).astype(np.float32)
    else:
        generated = np.concatenate([generate(args.checkpoint, n, seed, args.device, steps=args.gen_steps,
                                             clamp=not args.no_clamp) for n, seed in
                                    ((SIZES["fit"], 1_000_000), (SIZES["inner"], 2_000_000),
                                     (SIZES["eval"], 3_000_000))])
        np.save(output/"generated.npy", generated.astype(np.float16))
    cut = np.cumsum([SIZES["fit"], SIZES["inner"]])
    fakes = tuple(np.split(generated, cut))
    if args.mode == "features":
        held_rows = real.pick("held_out", SIZES["eval"])
        real_eval = real.windows(held_rows)
        report = feature_report(real_eval, real.draw("control_eval", SIZES["eval"]), fakes[2])
        (output/"features.json").write_text(json.dumps(report, indent=1))
        fit_rows, other_rows = real.pick("fit", SIZES["fit"]), real.pick("control_eval", SIZES["eval"])
        real_fit, real_other = real.windows(fit_rows), real.windows(other_rows)
        fidelity = fidelity_report(real_fit, real_eval, real_other, fakes[0], fakes[2])
        (output/"fidelity.json").write_text(json.dumps(fidelity, indent=1))
        target = target_report(real_fit, real_eval, real_other, fakes[0], fakes[2])
        (output/"target.json").write_text(json.dumps(target, indent=1))
        target_inputs(output, real, held_rows, other_rows, fit_rows, fakes[2])
        return
    result = judge_source("generated", real, fakes, args.kind, args.seeds, args.device, output)
    (output/"generated_judge.json").write_text(json.dumps(dict(info=info, result=result)))


if __name__ == "__main__":
    main()
