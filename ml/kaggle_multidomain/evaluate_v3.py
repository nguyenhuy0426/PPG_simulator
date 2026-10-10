"""Frozen-checkpoint evaluation: the sealed GXU finger test is opened here, once, for every run.

Nothing computed here feeds back into any choice. Old test/external splits are exploratory.
The deterministic Gaussian shaper and train replay are report-only references.
"""
import json
from pathlib import Path

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import LENGTH, mmd2, save_json
from ml.kaggle_multidomain import control
from ml.kaggle_multidomain.benchmark import cpu_latency, sample
from ml.kaggle_multidomain.data import balanced_indices
from ml.kaggle_multidomain.data_gxu import STATES, STATE_CODES
from ml.kaggle_multidomain.experiment import QualityEvaluator
from ml.kaggle_multidomain.experiment_v3 import (BASELINES, POOLS, PromptedEvaluator, VIEW, c2st, conditions_for,
                                                 config, load_best, pr_metrics, sampler)
from ml.kaggle_multidomain.models import networks
from ml.kaggle_multidomain.physio import view_mask

STATE_OF = {code: STATES[state] for state, code in STATE_CODES.items()}


def subject_bootstrap(evaluator, fake_blocks, real_blocks, subjects, repeats, seed=1803):
    unique = np.unique(subjects)
    if len(unique) < 2 or repeats <= 0:
        return None
    rng = np.random.default_rng(seed)
    totals = []
    for _ in range(repeats):
        ids = np.concatenate([np.flatnonzero(subjects == s) for s in rng.choice(unique, len(unique))])
        fi = rng.integers(len(fake_blocks[0]), size=len(fake_blocks[0]))
        totals.append(sum(mmd2(a[fi], b[ids], bw) for a, b, bw in zip(fake_blocks, real_blocks, evaluator.bandwidths)))
    return np.quantile(totals, [.025, .975]).tolist()


class FreshTest:
    """GXU test reference (all sealed windows), overall and per acquisition state."""
    def __init__(self, evaluator, pack):
        self.evaluator = evaluator
        mask = (pack["domain"] == "gxu_finger") & (pack["split"] == "test")
        self.ids = np.flatnonzero(mask)
        self.signal, self.subject = pack["signal"][self.ids], pack["subject"][self.ids]
        self.state = pack["activity_label"][self.ids]
        self.blocks = evaluator.blocks(self.signal)

    def score(self, fake, fake_by_state, repeats):
        ev = self.evaluator
        fake_blocks = ev.blocks(fake)
        result = dict(windows=int(len(self.ids)), subjects=int(len(np.unique(self.subject))),
                      **self._quality(fake_blocks, self.blocks),
                      subject_bootstrap_total_mmd_ci95=subject_bootstrap(ev, fake_blocks, self.blocks, self.subject, repeats))
        result["states"] = {}
        for code, fake_state in fake_by_state.items():
            rows = self.state == code
            if rows.sum() < 6 or fake_state is None:
                continue
            real = tuple(b[rows] for b in self.blocks)
            result["states"][STATE_OF[code]] = dict(windows=int(rows.sum()), **self._quality(ev.blocks(fake_state), real))
        return result

    def _quality(self, fake_blocks, real_blocks):
        mmd = [mmd2(a, b, bw) for a, b, bw in zip(fake_blocks, real_blocks, self.evaluator.bandwidths)]
        out = dict(acf_mmd2=mmd[0], log_psd_mmd2=mmd[1], morphology_mmd2=mmd[2], total_mmd=float(sum(mmd)),
                   **pr_metrics(fake_blocks[2], real_blocks[2]))
        out["Q"] = out["total_mmd"]+.5*(1-out["recall"])+.25*(1-out["precision"])
        return out


def state_prompts(development, conditions, code, n, seed):
    ids = np.flatnonzero((development["split"] == "train") & (development["domain"] == "gxu_finger")
                         & (development["activity_label"] == code))
    if not len(ids):
        return None
    return conditions.for_ids(np.random.default_rng(seed).choice(ids, n))


def c2st_floor(evaluator, device):
    """Real-vs-real probe on subject-disjoint validation halves: the AUC a perfect generator would get."""
    pack = evaluator.pack
    ids = np.flatnonzero(pack["split"] == "validation")
    subjects = np.unique(pack["subject"][ids])
    rng = np.random.default_rng(77)
    half = set(rng.permutation(subjects)[:len(subjects)//2])
    a = ids[np.isin(pack["subject"][ids], list(half))]
    b = ids[~np.isin(pack["subject"][ids], list(half))]
    ra, rb = rng.permutation(a), rng.permutation(b)
    split_a, split_b = len(ra)//2, len(rb)//2
    from ml.kaggle_multidomain import experiment_v3
    return control.c2st_auc(pack["signal"][ra[:split_a]], pack["signal"][rb[:split_b]],
                            pack["signal"][ra[split_a:]], pack["signal"][rb[split_b:]], device,
                            steps=experiment_v3.C2ST_STEPS)


def evaluate_frozen(rows, pack, output, frozen, device, bootstrap, n):
    output = Path(output)
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    evaluator = PromptedEvaluator(development, n)
    legacy = QualityEvaluator(pack, 128)
    fresh = FreshTest(evaluator, pack)
    references = dict(prompted_validation_replay_floor=evaluator.floors(), c2st_real_vs_real_floor=c2st_floor(evaluator, device))
    v2 = conditions_for(development, "v2")
    gaussian = {}
    for i, name in enumerate(POOLS):
        prompts = evaluator.prompts(v2, name)
        rates = prompts[:, -3]*v2.scale[0]+v2.center[0]
        strips = control.gaussian_reference(rates, view_mask(VIEW), seed=i)
        gaussian[name] = evaluator.pool_quality(strips, evaluator.pools[name]["reference"])[0]
    gxu_rates = evaluator.prompts(v2, "gxu_finger")[:, -3]*v2.scale[0]+v2.center[0]
    gaussian["gxu_fresh_test"] = fresh.score(control.gaussian_reference(gxu_rates, view_mask(VIEW), seed=9), {}, 0)
    replay = development["signal"][balanced_indices(development, "train", np.random.default_rng(2110), n, ["gxu_finger"])]
    references.update(gaussian_shaper=gaussian, gxu_train_replay_on_fresh_test=fresh.score(replay, {}, bootstrap))
    save_json(output/"references.json", references)
    results = []
    for row in rows:
        arm, seed = row["arm"], row["seed"]
        run_dir = output/f"{arm}_seed{seed}"
        if arm in BASELINES:
            model, _ = networks(arm)
            model.load_state_dict(torch.load(run_dir/"best.pt", map_location="cpu", weights_only=True)["generator"])
            model.to(device).eval()
            mixture = sample(model, seed+20000, device, n)
            metrics = dict(**row, unconditional=True, hr_control=False,
                           gxu_fresh_test=fresh.score(mixture, {}, bootstrap),
                           latency=cpu_latency(model))
        else:
            cfg = config(arm, frozen)
            conditions = conditions_for(development, cfg["version"])
            model, cfg = load_best(arm, run_dir, conditions, frozen, device)
            run = sampler(model, cfg, device)
            mixture = run(torch.randn(n, LENGTH, generator=torch.Generator().manual_seed(seed+20000)),
                          conditions.draw(seed+20073, n))
            gxu = run(torch.randn(n, LENGTH, generator=torch.Generator().manual_seed(seed+21000)),
                      evaluator.prompts(conditions, "gxu_finger", 900))
            by_state = {}
            for code in STATE_OF:
                prompts = state_prompts(development, conditions, code, n, seed+code)
                by_state[code] = None if prompts is None else run(
                    torch.randn(n, LENGTH, generator=torch.Generator().manual_seed(seed+22000+code)), prompts)
            metrics = dict(**row, unconditional=False, hr_control=True,
                           gxu_fresh_test=fresh.score(gxu, by_state, bootstrap),
                           c2st_raw_auc=c2st(evaluator, run, conditions, seed+33000, device, derivative=False, width=32))
            np.savez_compressed(run_dir/"gxu_samples.npz", generated=gxu)
        metrics.update(exploratory_old_test=legacy.evaluate(mixture, "test", 0),
                       exploratory_external=legacy.evaluate(mixture, "external", 0),
                       diagnostics=legacy.diagnostics(mixture))
        np.savez_compressed(run_dir/"samples.npz", generated=mixture)
        save_json(run_dir/"metrics.json", metrics)
        results.append(metrics)
        save_json(output/"results.json", dict(models=results))
    return results
