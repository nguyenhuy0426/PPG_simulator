"""In-kernel evaluation of a trained generator on the held-out people, so a training kernel ends with its own scores.

Generated windows (the judge's fit + inner + eval sizes, 9,000 by default) go through judge_physigpt in features mode
(the 22-feature target report against the held-out people, the feature-only classifiers, the 14-feature fidelity
tier) and, with strict_seeds, the strict judge (C2ST) on the GPU. summary.json gathers the numbers a reader asks for
first: the mean similarity (1 - KS) in percent next to the real-vs-real value, every feature's percent, the tree
classifier accuracy, the features below the floor and the verdict. Engineering evaluation of normalised waveform shape;
not clinical validation.
"""
import json
from pathlib import Path

import numpy as np

from ml.kaggle_physigpt import judge_physigpt as jp


def generated_sets(sample, sizes=None):
    """The judge's three sets drawn with the seeds the sample kernel uses: sample(n, seed) -> [n, 1200]."""
    sizes = sizes or jp.SIZES
    return np.concatenate([sample(sizes[k], seed) for k, seed in (("fit", 1_000_000), ("inner", 2_000_000),
                                                                  ("eval", 3_000_000))]).astype(np.float32)


def summarise(target, judge=None):
    gen, ref = target["generated"], target["real_other_people"]
    diagnostic = set(target.get("diagnostic_only", ()))
    out = dict(
        verdict=target["verdict"],
        mean_similarity_percent=round(100*gen["full"]["mean_similarity"], 2),
        real_vs_real_percent=round(100*ref["full"]["mean_similarity"], 2),
        relative_to_real_percent=round(100*gen["full"]["mean_similarity"]/ref["full"]["mean_similarity"], 2),
        tree_accuracy=gen["classifier"]["trees"]["accuracy"],
        below_floor=gen["below_floor"],
        lowest=gen["lowest"],
        # the 22 scored features; the two diagnostic beat features are reported apart and do not enter the mean
        feature_percent={k: round(100*v, 1) for k, v in gen["similarity"].items() if k not in diagnostic},
        real_vs_real_feature_percent={k: round(100*v, 1) for k, v in ref["similarity"].items() if k not in diagnostic},
        diagnostic_percent={k: round(100*gen["similarity"][k], 1) for k in diagnostic if k in gen["similarity"]},
        criteria=target["criteria"])
    if judge is not None:
        out["strict_judge_auc"] = judge["result"]["mean_auc"]
    return out


def evaluate(windows, data, output, device="cpu", strict_seeds=(), threads=4, sizes=None):
    """Score windows [n, 1200] (the judge's three sets, in order) against the held-out people of the shards `data`."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    path = output/"generated.npy"
    np.save(path, np.asarray(windows, np.float32))
    extra = ["--sizes", *map(str, (sizes["fit"], sizes["inner"], sizes["eval"]))] if sizes else []
    jp.main([str(output), "--data", *data, "--mode", "features", "--generated", str(path), "--threads", str(threads),
             *extra])
    target = json.loads((output/"target.json").read_text())
    judge = None
    if strict_seeds:
        jp.main([str(output), "--data", *data, "--mode", "model", "--generated", str(path), "--device", device,
                 "--seeds", *map(str, strict_seeds), "--threads", str(threads), *extra])
        judge = json.loads((output/"generated_judge.json").read_text())
    summary = summarise(target, judge)
    (output/"summary.json").write_text(json.dumps(summary, indent=1))
    np.save(path, np.asarray(windows, np.float16))   # halves the kernel output; the scores are already written
    print("EVALUATION", json.dumps(summary), flush=True)
    return summary
