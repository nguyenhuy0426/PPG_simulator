"""95% intervals for the realism table (precision, recall, indistinguishable) by a subject bootstrap.

Repeats ml/kaggle_multidomain/realism.realism() with the same seeds, folds and probe, using the deployed
TorchScript generators, and keeps every out-of-fold probe score. The point estimates must reproduce
docs/paper/evidence/realism-v1/realism_round10.json; the script stops if they do not.

Intervals: unseen subjects (and, for real windows of training subjects, those subjects) are resampled with
replacement, generated windows independently. Precision and recall indicators and the probe scores are kept
fixed, so the interval reflects which subjects were sampled, not retraining of the probe or of the manifolds.
Laptop CPU run.

    PPG_DRY_RUN=1 .venv/bin/python docs/paper/analysis/realism_ci.py
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

DATA = Path("/home/huynn/final_project/PPG_simulator_raspi/ml/runs/physio3-data-v1")
EVIDENCE = ROOT/"docs/paper/evidence/realism-v1/realism_round10.json"
SOURCES = ("real_other_people", "round9", "physioflow", "lsm_gan", "gaussian_shaper")
N, FOLDS, STEPS, REPEATS, SEED, BOOT = 256, 4, 600, 3, 0, 2000


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT/"docs/paper/data/realism_ci.json"))
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--datasets", nargs="+", help="recompute only these datasets and keep the others in --out")
    a = parser.parse_args(argv)
    import torch
    from torch.nn import functional as F
    from scipy.spatial.distance import cdist
    from ml.kaggle_lsm.train_lsm import LENGTH
    from ml.kaggle_multidomain import control
    from ml.kaggle_multidomain.data_gxu import load_input
    from ml.kaggle_multidomain.experiment_v3 import PROTOCOL, PromptedEvaluator, conditions_for, pr_metrics
    from ml.kaggle_multidomain.physio import view_mask
    from ml.kaggle_multidomain.realism import DATASETS, UNSEEN, balanced, development_of, folds_of, lsm_source, rows
    torch.set_num_threads(a.threads)

    pack, manifest = load_input(str(DATA), PROTOCOL)
    development, to_dev = development_of(pack)
    conditions = conditions_for(development, "v2")
    neural = ROOT/"assets/neural"

    def deployed(name):
        model = torch.jit.load(str(neural/name), map_location="cpu").eval()

        def generate(train_ids, seed):
            z = torch.randn(len(train_ids), LENGTH, generator=torch.Generator().manual_seed(seed))
            c = torch.tensor(conditions.for_ids(to_dev(train_ids)))
            with torch.inference_mode():
                return torch.cat([model(zz, cc) for zz, cc in zip(z.split(64), c.split(64))])[:, 0].numpy()
        return generate

    def gaussian(train_ids, seed):
        rates = conditions.for_ids(to_dev(train_ids))[:, -3]*conditions.scale[0]+conditions.center[0]
        return control.gaussian_reference(rates, view_mask("v3"), seed)

    generators = dict(round9=deployed("physiomix_generator.ts"), physioflow=deployed("physioflow_generator.ts"),
                      lsm_gan=lsm_source(neural/"lsm_generator.ts"), gaussian_shaper=gaussian)
    evaluator = PromptedEvaluator(development, 16)
    published = json.loads(EVIDENCE.read_text())["realism"]

    def scores(real_train, fake_train, real_valid, fake_valid, seed):
        """control.c2st_auc, returning the validation scores as well."""
        torch.manual_seed(seed)
        probe = control.Probe(True, 16)
        optimizer = torch.optim.Adam(probe.parameters(), lr=1e-3)
        rng = np.random.default_rng(seed)
        tensor = lambda x: torch.tensor(np.asarray(x, dtype=np.float32)[:, None])
        real_train, fake_train = tensor(real_train), tensor(fake_train)
        for _ in range(STEPS):
            r = real_train[rng.integers(len(real_train), size=32)]
            f = fake_train[rng.integers(len(fake_train), size=32)]
            logits = probe(torch.cat((r, f)))
            target = torch.cat((torch.zeros(32), torch.ones(32)))
            optimizer.zero_grad(set_to_none=True)
            F.binary_cross_entropy_with_logits(logits, target).backward()
            optimizer.step()
        probe.eval()
        with torch.no_grad():
            rs = torch.cat([probe(p) for p in tensor(real_valid).split(256)]).numpy()
            fs = torch.cat([probe(p) for p in tensor(fake_valid).split(256)]).numpy()
        return rs, fs

    result = dict(method=__doc__.split("\n\n")[1].replace("\n", " "), bootstrap=BOOT, datasets={})
    if a.datasets and Path(a.out).exists():
        result["datasets"] = json.loads(Path(a.out).read_text())["datasets"]
    for d, domain in enumerate(DATASETS):
        if a.datasets and domain not in a.datasets:
            continue
        unseen = balanced(pack, rows(pack, UNSEEN, domain), N, np.random.default_rng(SEED+10*d))
        train = rows(pack, ("train",), domain)
        size = min(N, len(train))
        others = balanced(pack, train, size, np.random.default_rng(SEED+10*d+1))
        prompts = balanced(pack, train, size, np.random.default_rng(SEED+10*d+2))
        real, real_groups = pack["signal"][unseen], pack["subject"][unseen]
        reference = evaluator.blocks(real)[2]
        candidates = dict(real_other_people=(pack["signal"][others], pack["subject"][others]))
        candidates.update({name: (g(prompts, SEED+10*d+3), None) for name, g in generators.items()})
        entry = dict(people=int(len(np.unique(real_groups))), windows=int(len(unseen)))
        for name in SOURCES:
            x, groups = candidates[name]
            features = evaluator.blocks(x)[2]
            pr = pr_metrics(features, reference)
            # Per-window indicators behind precision and recall (experiment_v3.pr_metrics)
            rr, ff, rf = cdist(reference, reference), cdist(features, features), cdist(reference, features)
            np.fill_diagonal(rr, np.inf)
            np.fill_diagonal(ff, np.inf)
            k = min(5, len(features)-1, len(reference)-1)
            radius_r, radius_f = np.partition(rr, k-1, 1)[:, k-1], np.partition(ff, k-1, 1)[:, k-1]
            in_real = (rf <= radius_r[:, None]).any(0)   # per generated window
            covered = (rf <= radius_f[None, :]).any(1)   # per real window
            assert abs(in_real.mean()-pr["precision"]) < 1e-12 and abs(covered.mean()-pr["recall"]) < 1e-12
            # Out-of-fold scores, as realism.grouped_c2st
            runs = []
            for r in range(REPEATS):
                seed = SEED+d+1000*r
                rng = np.random.default_rng(seed)
                folds = min(FOLDS, len(np.unique(real_groups)), len(np.unique(groups)) if groups is not None else FOLDS)
                real_fold = folds_of(real_groups, folds, rng)
                other_fold = folds_of(groups, folds, rng) if groups is not None else rng.permutation(len(x)) % folds
                rs, fs = np.full(len(real), np.nan), np.full(len(x), np.nan)
                for f in range(folds):
                    a_, b_ = scores(real[real_fold != f], x[other_fold != f], real[real_fold == f], x[other_fold == f], seed+f)
                    rs[real_fold == f], fs[other_fold == f] = a_, b_
                runs.append((real_fold, other_fold, rs, fs, folds))

            def indist(real_pick, other_pick):
                values = []
                for real_fold, other_fold, rs, fs, folds in runs:
                    aucs = [control.auc(rs[real_pick][real_fold[real_pick] == f], fs[other_pick][other_fold[other_pick] == f])
                            for f in range(folds)]
                    values.append(1-abs(2*np.nanmean(aucs)-1))
                return float(np.mean(values))

            point = indist(np.arange(len(real)), np.arange(len(x)))
            ref = published[domain][name]
            check = dict(precision=pr["precision"]-ref["fidelity"], recall=pr["recall"]-ref["coverage"],
                         indistinguishable=point-ref["indistinguishable"])
            if abs(check["precision"]) > 2/N or abs(check["recall"]) > 2/N or abs(check["indistinguishable"]) > .005:
                raise SystemExit(f"{domain} {name}: does not reproduce the published record {check}")
            names, inverse = np.unique(real_groups, return_inverse=True)
            members = [np.flatnonzero(inverse == i) for i in range(len(names))]
            if groups is not None:
                onames, oinverse = np.unique(groups, return_inverse=True)
                omembers = [np.flatnonzero(oinverse == i) for i in range(len(onames))]
            rng = np.random.default_rng(99+d)
            draws = []
            for _ in range(BOOT):
                real_pick = np.concatenate([members[i] for i in rng.integers(len(members), size=len(members))])
                other_pick = (np.concatenate([omembers[i] for i in rng.integers(len(omembers), size=len(omembers))])
                              if groups is not None else rng.integers(len(x), size=len(x)))
                draws.append((in_real[other_pick].mean(), covered[real_pick].mean(), indist(real_pick, other_pick)))
            # With very few subjects on both sides, a resample can leave no fold with windows on both sides;
            # such draws have no C2ST value and are dropped (counted in invalid_draws).
            draws = 100*np.asarray(draws)
            invalid = int(np.isnan(draws[:, 2]).sum())
            lo, hi = np.nanpercentile(draws, 2.5, 0), np.nanpercentile(draws, 97.5, 0)
            entry[name] = dict(precision=100*pr["precision"], recall=100*pr["recall"], indistinguishable=100*point,
                               published_indistinguishable=100*ref["indistinguishable"],
                               ci95=dict(precision=[lo[0], hi[0]], recall=[lo[1], hi[1]], indistinguishable=[lo[2], hi[2]]),
                               invalid_draws=invalid)
            print(domain, name, invalid, {k_: round(v, 1) for k_, v in entry[name].items() if isinstance(v, float)},
                  {k_: [round(v[0], 1), round(v[1], 1)] for k_, v in entry[name]["ci95"].items()}, flush=True)
        result["datasets"][domain] = entry
    Path(a.out).write_text(json.dumps(result, indent=1)+"\n")


if __name__ == "__main__":
    main()
