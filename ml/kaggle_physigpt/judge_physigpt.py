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
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
from scipy import stats
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

    def draw(self, role, n):
        """n windows of the role, each record weighted equally. Training roles never repeat a window (the sets stay
        disjoint); the evaluation roles (held_out, control_eval) return the same windows on every call."""
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
        return (self.data.rows(np.sort(pick)).astype(np.float32)/65535).copy()


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


def feature_matrix(x):
    f = signal_features(x)
    return list(f), np.stack([f[k] for k in f], 1)


def fidelity_report(real_fit, real_held, real_other, gen_fit, gen_eval):
    """Per-feature similarity and feature-only classifiers (train: real_fit vs gen_fit; test: held-out people)."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    names, held = feature_matrix(real_held)
    other, fit, gfit, geval = (feature_matrix(x)[1] for x in (real_other, real_fit, gen_fit, gen_eval))

    def similarity(a, b):
        return np.array([1-stats.ks_2samp(a[:, j], b[:, j]).statistic for j in range(a.shape[1])])

    def classify(train_real, train_fake, test_real, test_fake):
        x = np.vstack([train_real, train_fake])
        y = np.r_[np.zeros(len(train_real)), np.ones(len(train_fake))]
        mu, sd = x.mean(0), x.std(0)+1e-9
        yt = np.r_[np.zeros(len(test_real)), np.ones(len(test_fake))]
        out = {}
        for name, model in (("logreg", LogisticRegression(max_iter=3000)),
                            ("trees", HistGradientBoostingClassifier(max_iter=200))):
            score = model.fit((x-mu)/sd, y).predict_proba((np.vstack([test_real, test_fake])-mu)/sd)[:, 1]
            order = np.argsort(np.argsort(score))+1
            pos = yt == 1
            out[name] = dict(auc=float((order[pos].sum()-pos.sum()*(pos.sum()+1)/2)/(pos.sum()*(~pos).sum())),
                             accuracy=float(((score > .5) == pos).mean()))
        return out

    def summary(s, c2st):
        return dict(similarity=dict(zip(names, s.tolist())), mean_similarity=float(s.mean()),
                    share_at_least_95=float((s >= FIDELITY_SIM).mean()), classifier=c2st)

    half = len(fit)//2
    generated = summary(similarity(held, geval), classify(fit, gfit, held, geval))
    reference = summary(similarity(held, other), classify(fit[:half], fit[half:], held, other))
    generated["passes"] = bool(generated["mean_similarity"] >= FIDELITY_SIM
                               and generated["classifier"]["trees"]["accuracy"] <= FIDELITY_ACC)
    return dict(generated=generated, real_other_people=reference,
                criteria=dict(mean_similarity_at_least=FIDELITY_SIM, tree_classifier_accuracy_at_most=FIDELITY_ACC))


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
        real_eval = real.draw("held_out", SIZES["eval"])
        report = feature_report(real_eval, real.draw("control_eval", SIZES["eval"]), fakes[2])
        (output/"features.json").write_text(json.dumps(report, indent=1))
        fidelity = fidelity_report(real.draw("fit", SIZES["fit"]), real_eval, real.draw("control_eval", SIZES["eval"]),
                                   fakes[0], fakes[2])
        (output/"fidelity.json").write_text(json.dumps(fidelity, indent=1))
        return
    result = judge_source("generated", real, fakes, args.kind, args.seeds, args.device, output)
    (output/"generated_judge.json").write_text(json.dumps(dict(info=info, result=result)))


if __name__ == "__main__":
    main()
