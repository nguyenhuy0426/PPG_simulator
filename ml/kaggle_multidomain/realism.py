"""Per-dataset realism and condition-following checks for the PPG simulator (CPU, report only).

Realism per dataset uses windows of people never used for training (validation + test splits; validation
also chose checkpoints, so these numbers are slightly optimistic):
- fidelity: share of generated windows inside the real k-NN manifold (k=5, train-standardised morphology);
- coverage: share of real windows inside the generated manifold;
- indistinguishable: 100(1-|2AUC-1|) for a derivative CNN probe cross-validated with people grouped.
Each metric is repeated with real windows of the training people in place of the generator: the level
that real recordings of other people reach.

Condition following: a CNN trained only on real training windows names the dataset/state. It is applied
to windows generated for each state, and to the same noise prompted for every state in turn. Datasets
also differ in sensor site and population, so this shows that the command selects the matching recording
context (wrist during exercise vs finger at rest), not that the model understands motion. Nothing here
feeds back into training or selection, and none of it is clinical validation.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ml.kaggle_lsm.train_lsm import LENGTH, save_json
from ml.kaggle_multidomain import control
from ml.kaggle_multidomain.data_gxu import load_input
from ml.kaggle_multidomain.experiment_v3 import PROTOCOL, PromptedEvaluator, conditions_for, config, load_best, \
    pr_metrics, sampler
from ml.kaggle_multidomain.labels import robust_labels
from ml.kaggle_multidomain.physio import view_mask

DATASETS = ("gxu_finger", "perform_large", "bidmc", "perform_af", "perform_non_af", "wrist")
# GXU activity codes: 4 rest, 5/6 the two post-exercise recordings (seated, after exercise).
STATES = {"bidmc": ("bidmc", None), "perform_af": ("perform_af", None), "perform_non_af": ("perform_non_af", None),
          "perform_large": ("perform_large", None), "gxu_rest": ("gxu_finger", (4,)),
          "gxu_post_exercise": ("gxu_finger", (5, 6)), "wrist_exercise": ("wrist", None)}
UNSEEN = ("validation", "test")


def rows(pack, splits, domain, activities=None):
    mask = np.isin(pack["split"], splits) & (pack["domain"] == domain)
    if activities is not None:
        mask &= np.isin(pack["activity_label"], activities)
    return np.flatnonzero(mask)


def balanced(pack, ids, n, rng, replace=False):
    """n windows, every person weighted equally; distinct windows unless replace."""
    _, inverse, counts = np.unique(pack["subject"][ids], return_inverse=True, return_counts=True)
    weights = 1/counts[inverse]
    return rng.choice(ids, n if replace else min(n, len(ids)), replace=replace, p=weights/weights.sum())


def development_of(pack):
    """Train+validation view (what the condition banks were fitted on) and a full-pack -> view index map."""
    keep = np.flatnonzero(np.isin(pack["split"], ["train", "validation"]))
    return {k: v[keep] for k, v in pack.items()}, lambda ids: np.searchsorted(keep, ids)


def model_source(development, to_dev, run_dir, arm, alias=None):
    """generate(train window ids of the full pack, seed) -> windows prompted with those windows' labels."""
    frozen = dict(aliases={arm: alias}) if alias else None
    cfg = config(arm, frozen)
    conditions = conditions_for(development, cfg["version"])
    model, cfg = load_best(arm, Path(run_dir), conditions, frozen, "cpu")
    run = sampler(model, cfg, "cpu")

    def generate(train_ids, seed):
        z = torch.randn(len(train_ids), LENGTH, generator=torch.Generator().manual_seed(seed))
        return run(z, conditions.for_ids(to_dev(train_ids)))
    return generate


def gaussian_source(development, to_dev):
    """The app's previous three-Gaussian shaper: it follows the rate only."""
    conditions = conditions_for(development, "v2")

    def generate(train_ids, seed):
        rates = conditions.for_ids(to_dev(train_ids))[:, -3]*conditions.scale[0]+conditions.center[0]
        return control.gaussian_reference(rates, view_mask("v3"), seed)
    return generate


def folds_of(groups, folds, rng):
    unique = rng.permutation(np.unique(groups))
    fold = {g: i % folds for i, g in enumerate(unique)}
    return np.array([fold[g] for g in groups])


def grouped_c2st(real, real_groups, other, other_groups, folds, steps, seed):
    """Mean out-of-fold AUC; a person never appears on both sides of a fold."""
    rng = np.random.default_rng(seed)
    folds = min(folds, len(np.unique(real_groups)), len(np.unique(other_groups)) if other_groups is not None else folds)
    real_fold = folds_of(real_groups, folds, rng)
    other_fold = folds_of(other_groups, folds, rng) if other_groups is not None else rng.permutation(len(other)) % folds
    values = [control.c2st_auc(real[real_fold != k], other[other_fold != k], real[real_fold == k],
                               other[other_fold == k], "cpu", steps=steps, seed=seed+k) for k in range(folds)]
    return float(np.mean(values)), folds


def realism(pack, evaluator, sources, n=256, folds=4, steps=600, seed=0, repeats=1):
    """repeats: C2ST fold assignments averaged; few-person datasets make one assignment noisy."""
    result = {}
    for d, domain in enumerate(DATASETS):
        unseen = balanced(pack, rows(pack, UNSEEN, domain), n, np.random.default_rng(seed+10*d))
        train = rows(pack, ("train",), domain)
        size = min(n, len(train))
        others = balanced(pack, train, size, np.random.default_rng(seed+10*d+1))
        prompts = balanced(pack, train, size, np.random.default_rng(seed+10*d+2))
        real = pack["signal"][unseen]
        reference = evaluator.blocks(real)[2]
        candidates = dict(real_other_people=(pack["signal"][others], pack["subject"][others]))
        candidates.update({name: (generate(prompts, seed+10*d+3), None) for name, generate in sources.items()})
        entry = dict(people=int(len(np.unique(pack["subject"][unseen]))), windows=int(len(unseen)), compared=size)
        for name, (x, groups) in candidates.items():
            pr = pr_metrics(evaluator.blocks(x)[2], reference)
            aucs = []
            for r in range(repeats):
                auc, used = grouped_c2st(real, pack["subject"][unseen], x, groups, folds, steps, seed+d+1000*r)
                aucs.append(auc)
            entry[name] = dict(fidelity=pr["precision"], coverage=pr["recall"], c2st_auc=float(np.mean(aucs)),
                               c2st_auc_range=[float(min(aucs)), float(max(aucs))],
                               indistinguishable=float(np.mean([1-abs(2*v-1) for v in aucs])), c2st_folds=used)
            print(domain, name, {k: round(v, 3) for k, v in entry[name].items() if isinstance(v, float)}, flush=True)
        result[domain] = entry
    return result


class StateNet(nn.Module):
    """Derivative-channel CNN, wider than the C2ST probe, with one logit per state."""
    def __init__(self, classes, width=24):
        super().__init__()
        self.probe = control.Probe(True, width)
        self.head = nn.Linear(2*width, classes)

    def forward(self, x):
        x = torch.cat((x, 10*F.pad(torch.diff(x, dim=-1), (1, 0)), 20*F.pad(torch.diff(x, n=2, dim=-1), (1, 1))), 1)
        return self.head(self.probe.net(x).mean(-1))


def physiology(x):
    """Interpretable per-window statistics: consensus rate, IBI CV, rate-measurable share, periodicity."""
    rate, irr, _ = robust_labels(x)
    centered = x-x.mean(1, keepdims=True)
    acf = np.fft.irfft(np.abs(np.fft.rfft(centered, n=2*LENGTH, axis=1))**2, n=2*LENGTH, axis=1)[:, :80]
    periodicity = (acf[:, 8:68]/np.maximum(acf[:, :1], 1e-12)).max(1)
    finite = np.isfinite(rate)
    return dict(hr_median=float(np.median(rate[finite])) if finite.any() else None,
                ibi_cv_median=float(np.nanmedian(irr)) if np.isfinite(irr).any() else None,
                rate_measurable=float(finite.mean()), periodicity_median=float(np.median(periodicity)))


def condition_following(pack, sources, steps=2500, n=128, swap=64, seed=0):
    names = list(STATES)
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    train = {s: rows(pack, ("train",), *STATES[s]) for s in names}
    unseen = {s: rows(pack, UNSEEN, *STATES[s]) for s in names}
    net = StateNet(len(names))
    optimizer = torch.optim.Adam(net.parameters(), lr=1e-3)
    signal = torch.tensor(pack["signal"][:, None])
    for _ in range(steps):
        ids = np.concatenate([balanced(pack, train[s], 10, rng, replace=True) for s in names])
        target = torch.arange(len(names)).repeat_interleave(10)
        optimizer.zero_grad(set_to_none=True)
        F.cross_entropy(net(signal[ids]), target).backward()
        optimizer.step()
    net.eval()

    @torch.no_grad()
    def predict(x):
        logits = torch.cat([net(torch.tensor(np.asarray(part, np.float32)[:, None])) for part in np.array_split(x, max(1, len(x)//256))])
        return logits.argmax(1).numpy(), logits.softmax(1).numpy()

    def confusion(by_state):
        matrix = np.zeros((len(names), len(names)), int)
        motion = {}
        for i, s in enumerate(names):
            label, prob = predict(by_state[s])
            matrix[i] = np.bincount(label, minlength=len(names))
            motion[s] = float(prob[:, names.index("wrist_exercise")].mean())
        accuracy = {s: float(matrix[i, i]/matrix[i].sum()) for i, s in enumerate(names)}
        return dict(confusion=matrix.tolist(), accuracy=accuracy, balanced_accuracy=float(np.mean(list(accuracy.values()))),
                    motion_probability=motion)
    real = {s: pack["signal"][balanced(pack, unseen[s], n, np.random.default_rng(seed+i))] for i, s in enumerate(names)}
    result = dict(states=names, chance=1/len(names), real_unseen=confusion(real),
                  physiology=dict(real_unseen={s: physiology(x) for s, x in real.items()}))
    for name, generate in sources.items():
        prompts = {s: balanced(pack, train[s], n, np.random.default_rng(seed+100+i), replace=True) for i, s in enumerate(names)}
        generated = {s: generate(prompts[s], seed+200+i) for i, s in enumerate(names)}
        entry = confusion(generated)
        # Same noise, every state command in turn: a model ignoring the command would give one answer per noise.
        votes = np.stack([predict(generate(balanced(pack, train[s], swap, np.random.default_rng(seed+300+i), replace=True),
                                           seed+999))[0] for i, s in enumerate(names)])
        entry["swap_following"] = float((votes == np.arange(len(names))[:, None]).mean())
        entry["swap_distinct_answers_per_noise"] = float(np.mean([len(set(votes[:, j])) for j in range(swap)]))
        result[name] = entry
        result["physiology"][name] = {s: physiology(x) for s, x in generated.items()}
        print(name, "balanced accuracy", round(entry["balanced_accuracy"], 3), "swap", round(entry["swap_following"], 3), flush=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="Directory holding the verified v3 pack")
    parser.add_argument("--run", action="append", default=[], help="name=run_dir:arm[:alias]")
    parser.add_argument("--gaussian", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=256)
    parser.add_argument("--c2st-steps", type=int, default=600)
    parser.add_argument("--c2st-repeats", type=int, default=3)
    parser.add_argument("--state-steps", type=int, default=2500)
    parser.add_argument("--threads", type=int, default=8)
    a = parser.parse_args(argv)
    torch.set_num_threads(a.threads)
    pack, manifest = load_input(a.data, PROTOCOL)
    development, to_dev = development_of(pack)
    sources = {}
    for spec in a.run:
        name, rest = spec.split("=", 1)
        run_dir, arm, *alias = rest.split(":")
        sources[name] = model_source(development, to_dev, run_dir, arm, alias[0] if alias else None)
    if a.gaussian:
        sources["gaussian_shaper"] = gaussian_source(development, to_dev)
    evaluator = PromptedEvaluator(development, 16)
    result = dict(data_sha256=manifest["windows_sha256"], unseen_splits=list(UNSEEN), sources=list(sources),
                  realism=realism(pack, evaluator, sources, a.samples, steps=a.c2st_steps,
                                          repeats=a.c2st_repeats),
                  condition_following=condition_following(pack, sources, a.state_steps))
    save_json(Path(a.output), result)
    return result


if __name__ == "__main__":
    main()
