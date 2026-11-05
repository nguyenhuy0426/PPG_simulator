"""Confidence intervals and paired differences of target_report's mean 1 - KS, across models scored on one real set.

Reads the target_inputs.npz and target.json that judge_physigpt --mode features writes (run after the kernel, no
waveforms, no data mounted). Every round resamples held-out people with replacement; all models and the real-vs-real
reference share that resample, which is what pairs the differences. The other side of each comparison is resampled on
its own: real other people by person, generated windows by the person who supplied the prompt where there is one, else
one by one. Resampling repeats values and so inflates a KS distance: bootstrap means sit below the point estimate, and
the bias is reported next to the plain percentile interval and removed from the corrected one. The pass rule stays
target_report's, on the point estimates; these intervals only say how far to trust them.
Engineering evaluation of normalised waveform shape; not clinical validation.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from ml.kaggle_physigpt.judge_physigpt import BEAT_DIAGNOSTIC, BEAT_SCORED, finite_similarity

ROUNDS, SEED = 2000, 20261102


def sorted_finite(a):
    return np.sort(a[np.isfinite(a)])


def similarity_sorted(a, b):
    """finite_similarity of two sorted finite arrays, without the p-value ks_2samp also computes."""
    if not len(a) or not len(b):
        return 0.
    points = np.r_[a, b]
    return float(1-np.abs(np.searchsorted(a, points, "right")/len(a)-np.searchsorted(b, points, "right")/len(b)).max())


def group_rows(groups):
    """Row indices per group; an int n makes every one of n rows its own group."""
    if isinstance(groups, (int, np.integer)):
        return [np.array([i]) for i in range(groups)]
    _, inverse = np.unique(groups, return_inverse=True)
    order = np.argsort(inverse, kind="stable")
    return np.split(order, np.flatnonzero(np.diff(inverse[order]))+1)


def resample(rows, rng):
    return np.concatenate([rows[i] for i in rng.integers(len(rows), size=len(rows))])


def means(reference, side, keys, reference_rows, side_rows):
    """Mean over the keys of 1 - KS, for one resample of each side."""
    return float(np.mean([similarity_sorted(sorted_finite(reference[k][reference_rows]),
                                            sorted_finite(side[k][side_rows])) for k in keys]))


def load_side(data, side):
    prefix = side+"/"
    return {name[len(prefix):]: data[name] for name in data.keys() if name.startswith(prefix)}


def score_sets(names):
    """The two scored sets of target_report: fourteen signal features, and those plus the beat layer."""
    fourteen = [k for k in names if k not in BEAT_SCORED+BEAT_DIAGNOSTIC]
    return dict(fourteen=fourteen, full=[*fourteen, *BEAT_SCORED])


def interval(point, values):
    bias = float(np.mean(values)-point)
    low, high = np.percentile(values, [2.5, 97.5])
    return dict(point=point, bootstrap_mean=float(np.mean(values)), bias=bias, percentile_95=[float(low), float(high)],
                corrected_95=[float(low-bias), float(high-bias)])


def paired(point, values):
    out = interval(point, values)
    out["share_rounds_above_zero"] = float((np.asarray(values) > 0).mean())
    return out


def compare(runs, rounds=ROUNDS, seed=SEED):
    """runs: name -> dict(inputs=npz-like mapping, groups=None or the person behind each generated window).
    Refuses runs that did not score the same real people."""
    names = list(runs)
    first = runs[names[0]]["inputs"]
    for name in names[1:]:
        other = runs[name]["inputs"]
        for key in ("held_person", "other_person"):
            if not np.array_equal(first[key], other[key]):
                raise ValueError(f"{name}: {key} differs from {names[0]}'s, the runs are not paired")
    held, other = load_side(first, "held"), load_side(first, "other")
    sides = {name: load_side(runs[name]["inputs"], "generated") for name in names}
    for name, side in sides.items():
        if set(side) != set(held):
            raise ValueError(f"{name}: features differ from the real side's")
    keys = score_sets(list(held))
    size = len(next(iter(held.values())))
    held_all, other_all = np.arange(size), np.arange(len(next(iter(other.values()))))
    points = {
        part: {name: means(held, sides[name], k, held_all, np.arange(len(next(iter(sides[name].values())))))
               for name in names} | {"real_other_people": means(held, other, k, held_all, other_all)}
        for part, k in keys.items()}
    held_groups, other_groups = group_rows(first["held_person"]), group_rows(first["other_person"])
    side_groups = {name: group_rows(runs[name]["groups"] if runs[name].get("groups") is not None
                                    else len(next(iter(sides[name].values())))) for name in names}
    rng_held, rng_other = np.random.default_rng([seed, 0]), np.random.default_rng([seed, 1])
    rng_side = {name: np.random.default_rng([seed, 2+i]) for i, name in enumerate(names)}
    values = {part: {name: np.empty(rounds) for name in [*names, "real_other_people"]} for part in keys}
    for r in range(rounds):
        held_rows, other_rows = resample(held_groups, rng_held), resample(other_groups, rng_other)
        rows = {name: resample(side_groups[name], rng_side[name]) for name in names}
        for part, k in keys.items():
            for name in names:
                values[part][name][r] = means(held, sides[name], k, held_rows, rows[name])
            values[part]["real_other_people"][r] = means(held, other, k, held_rows, other_rows)
    out = dict(rounds=rounds, seed=seed, held_people=len(held_groups), other_people=len(other_groups), sets={})
    for part in keys:
        v, p = values[part], points[part]
        out["sets"][part] = dict(
            features=len(keys[part]),
            means={name: interval(p[name], v[name]) for name in v},
            differences={f"{a} - {b}": paired(p[a]-p[b], v[a]-v[b])
                         for i, a in enumerate(names) for b in names[i+1:]},
            against_real={name: paired(p[name]-p["real_other_people"], v[name]-v["real_other_people"]) for name in names})
    return out


def table(runs_dir, comparison):
    """The report's row per model, from each target.json and the comparison."""
    rows = {}
    for name, path in runs_dir.items():
        t = json.loads((Path(path)/"target.json").read_text())
        g, reference = t["generated"], t["real_other_people"]
        rows[name] = dict(verdict=t["verdict"], fourteen=g["fourteen"]["mean_similarity"], beat=g["beat"]["mean_similarity"],
                          full=g["full"]["mean_similarity"], lowest=g["lowest"], lowest_value=g["similarity"][g["lowest"]],
                          trees_accuracy=g["classifier"]["trees"]["accuracy"], trees_auc=g["classifier"]["trees"]["auc"],
                          below_floor=g["below_floor"], windows_with_beats=g["windows_with_beats"],
                          real_fourteen=reference["fourteen"]["mean_similarity"], real_beat=reference["beat"]["mean_similarity"],
                          real_full=reference["full"]["mean_similarity"],
                          ci_fourteen=comparison["sets"]["fourteen"]["means"][name]["corrected_95"],
                          ci_full=comparison["sets"]["full"]["means"][name]["corrected_95"])
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="comparison.json to write")
    parser.add_argument("--run", nargs="+", required=True, metavar="NAME=DIR[:GROUPS]",
                        help="a judge_physigpt features directory; GROUPS: npz with person_eval (prompted generators)")
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    runs, dirs = {}, {}
    for item in args.run:
        name, _, rest = item.partition("=")
        path, _, groups = rest.partition(":")
        dirs[name] = path
        runs[name] = dict(inputs=np.load(Path(path)/"target_inputs.npz"),
                          groups=np.load(groups)["person_eval"] if groups else None)
    comparison = compare(runs, args.rounds, args.seed)
    comparison["runs"] = dirs
    comparison["table"] = table(dirs, comparison)
    Path(args.output).write_text(json.dumps(comparison, indent=1))
    return comparison


if __name__ == "__main__":
    main()
