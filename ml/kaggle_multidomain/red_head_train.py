"""Train the red head (red_head.py) on real (infrared, red) training windows and report residual realism on held-out
windows next to the infrared copy and the coloured-residual baseline. Laptop CPU; no data leaves the machine.

Exploratory on the v4 validation windows (FINGER, PTT): these people already decided rounds 11 and 12, so this run
informs the design only; RULE_13's decision uses fresh validation people.

    PPG_DRY_RUN=1 .venv/bin/python -m ml.kaggle_multidomain.red_head_train --pack ml/runs/physioflow2-data-v4 \
        --output ml/runs/red-head-dev-v1 --steps 6000
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import LENGTH, save_json
from ml.kaggle_multidomain.data import balanced_pool
from ml.kaggle_multidomain.data_dual import load_dual
from ml.kaggle_multidomain.experiment_v3 import learning_rate
from ml.kaggle_multidomain.physio import ema_model, update_ema
from ml.kaggle_multidomain.red_head import (HEAD_DOMAINS, ColouredResidual, HeadConditions, RedHead, compose, head_loss,
                                            residual_score, residual_target)

RECIPE = dict(lr=1e-3, schedule="cosine", batch=64, warmup=300, deriv=1., spectral=.1, amplitude=.1, sample_steps=8)


def red_rows(pack, split, domains=HEAD_DOMAINS):
    ids = np.flatnonzero((pack["split"] == split) & np.isin(pack["domain"], domains) & pack["red_known"])
    y, a, valid = residual_target(pack["signal"][ids].astype(np.float64), pack["red"][ids].astype(np.float64))
    return ids[valid], y[valid]


def head_red(head, conditions, pack, ids, seed):
    """Red windows (n, L) from the head with the real infrared of the given windows (on the head's device; the noise
    is drawn on the CPU so a seed gives the same draws on any device)."""
    device = next(head.parameters()).device
    domains, ratio = pack["domain"][ids], pack["ratio_r"][ids].astype(np.float32)
    ir = torch.tensor(pack["signal"][ids].astype(np.float32))
    z = torch.randn(len(ids), LENGTH, generator=torch.Generator().manual_seed(seed))
    cond = torch.tensor(conditions.rows(domains, ratio))
    with torch.no_grad():
        return torch.cat([head(a.to(device), b.to(device), c.to(device), d.to(device)).cpu()
                          for a, b, c, d in zip(z.split(64), ir.split(64), cond.split(64), torch.tensor(ratio).split(64))]).numpy()


def candidates(head, conditions, pack, ids, seed, train_domains=HEAD_DOMAINS):
    """Red windows of the head, the coloured-residual baseline (training spectra) and the infrared copy."""
    domains, ratio = pack["domain"][ids], pack["ratio_r"][ids].astype(np.float32)
    ir = pack["signal"][ids].astype(np.float32)
    train_ids, train_y = red_rows(pack, "train", train_domains)
    coloured = ColouredResidual(train_y, pack["domain"][train_ids])
    return dict(head=head_red(head, conditions, pack, ids, seed),
                coloured=compose(ir, coloured.sample(domains, np.random.default_rng(seed)), ratio),
                copy=compose(ir, np.zeros_like(ir), ratio))


def evaluate(head, conditions, pack, ids, y_real, seed, threads, train_domains=HEAD_DOMAINS):
    """Residual score with the real infrared of each held-out window (the head isolated from the infrared generator)."""
    torch.set_num_threads(threads)
    domains, ratio = pack["domain"][ids], pack["ratio_r"][ids].astype(np.float32)
    ir = pack["signal"][ids].astype(np.float64)
    out = {}
    for name, x in candidates(head, conditions, pack, ids, seed, train_domains).items():
        y, _, valid = residual_target(ir, x.astype(np.float64))
        total, per = residual_score(y[valid], y_real, domains[valid], domains)
        out[name] = dict(score=total, datasets=per,
                         R_abs_error_median=float(np.median(np.abs(np.ptp(x, -1)-ratio))))
    return out


def train_head(pack, ids, y, seed, steps, threads, log=print, device="cpu"):
    """Train one red head on the given red windows (ids into pack, residual targets y); returns (EMA head, conditions,
    history). Batches are balanced over datasets and people as in every earlier round."""
    torch.manual_seed(seed)
    torch.set_num_threads(threads)
    rng = np.random.default_rng(seed)
    pool, weights = balanced_pool(pack, "train", sorted(set(pack["domain"][ids])))
    keep = np.isin(pool, ids)
    pool, weights = pool[keep], weights[keep]/weights[keep].sum()
    row_of = {int(i): k for k, i in enumerate(ids)}
    conditions = HeadConditions(pack["domain"][ids], pack["ratio_r"][ids])
    cond_all = torch.tensor(conditions.rows(pack["domain"][ids], pack["ratio_r"][ids]))
    cond_all = cond_all.to(device)
    ir_all, y_all = torch.tensor(pack["signal"][ids].astype(np.float32), device=device), torch.tensor(y, device=device)
    head = RedHead(conditions.size, RECIPE["sample_steps"]).to(device)
    ema = ema_model(head)
    optimizer = torch.optim.AdamW(head.net.parameters(), lr=RECIPE["lr"], betas=(.9, .99), weight_decay=.01)
    history, start = [], time.monotonic()
    for step in range(1, steps+1):
        head.train()
        for group in optimizer.param_groups:
            group["lr"] = learning_rate(RECIPE, step-1, steps)*min(1., step/RECIPE["warmup"])
        rows = torch.tensor([row_of[int(i)] for i in rng.choice(pool, RECIPE["batch"], p=weights)], device=device)
        loss = head_loss(head.net, y_all[rows], ir_all[rows], cond_all[rows], RECIPE["deriv"], RECIPE["spectral"],
                         RECIPE["amplitude"])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(head.net.parameters(), 1.)
        optimizer.step()
        update_ema(ema, head, min(.999, (1+step)/(10+step)))
        if step % 250 == 0:
            history.append(dict(step=step, loss=float(loss), seconds=time.monotonic()-start))
            log(json.dumps(history[-1]))
    return ema.eval(), conditions, history


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=6000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--split", default="validation")
    a = parser.parse_args(argv)
    pack, manifest = load_dual(a.pack)
    ids, y = red_rows(pack, "train")
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    ema, conditions, history = train_head(pack, ids, y, a.seed, a.steps, a.threads)
    torch.save(dict(head=ema.state_dict(), conditions=conditions.metadata(), recipe=RECIPE, steps=a.steps, seed=a.seed),
               out/"red_head.pt")
    held_ids, held_y = red_rows(pack, a.split)
    result = dict(pack_windows_sha256=manifest["windows_sha256"], recipe=RECIPE, steps=a.steps, seed=a.seed,
                  split=a.split, training_windows=int(len(ids)), held_out_windows=int(len(held_ids)),
                  training_seconds=time.monotonic()-start, parameters=sum(p.numel() for p in ema.net.parameters()),
                  history=history, evaluation=evaluate(ema, conditions, pack, held_ids, held_y, a.seed+1, a.threads),
                  scope="Exploratory: v4 validation people already decided rounds 11-12; laptop CPU")
    save_json(out/"result.json", result)
    print(json.dumps({k: v["score"] for k, v in result["evaluation"].items()}, indent=1))


if __name__ == "__main__":
    main()
