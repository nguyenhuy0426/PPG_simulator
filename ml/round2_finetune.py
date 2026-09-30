"""Controlled TCN fine-tuning gated on human-reviewed train/validation labels.

--smoke runs two CPU steps on old automatic labels to verify plumbing only.
It never produces a promoted model or claims reviewed-data training.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

import numpy as np
import torch

from ml.kaggle_arch.train_architectures import (
    make_networks, balanced_batch, infer, load_prepared, stratified_indices,
    morphology_loss, spectral_loss, derivative_loss, auxiliary_loss, gradient_penalty)
from ml.independent_ppg_eval import metrics
from ml.round2_review import curated_data

ARMS = ("control", "relative_derivative", "time_warp")
DEFAULT_PARENT = Path("ml/runs/architecture-kaggle-v1/architecture_sweep/tcn_film_projection/seed_42/best.pt")


def warp_batch(real, condition, strengths):
    """Small monotone within-cycle warp; transform event phases and levels too."""
    phase = np.linspace(0, 1, 256)
    x, c = np.asarray(real).copy(), np.asarray(condition).copy()
    strengths = np.asarray(strengths)
    if strengths.shape != (len(x),) or not np.isfinite(strengths).all() or np.any(abs(strengths) > .01):
        raise ValueError("Warp strengths must be finite and within +/-0.01")
    for i, a in enumerate(strengths):
        query = phase + a * np.sin(2*np.pi*phase)
        x[i] = np.interp(query, phase, real[i])
        x[i] -= x[i].min()
        x[i] /= max(float(np.ptp(x[i])), 1e-8)
        for column in ((1, 2, 3) if c[i, -1] > .5 else (1,)):
            c[i, column] = np.interp(condition[i, column], query, phase)
        if c[i, -1] > .5:
            c[i, 4] = np.interp(c[i, 2], phase, x[i])
            c[i, 5] = np.interp(c[i, 3], phase, x[i])
    return x.astype(np.float32), c.astype(np.float32)


def relative_derivative_loss(fake, real):
    f = torch.diff(fake, n=2, dim=1).abs().mean(1)
    r = torch.diff(real, n=2, dim=1).abs().mean(1).detach()
    return ((f/(r+1e-4)-1)**2).mean()


def run_arm(arm, seed, x, c, masks, parent, output, args):
    torch.manual_seed(seed)
    device = torch.device(args.device)
    g, d = make_networks("tcn_film_projection")
    state = torch.load(parent, map_location="cpu", weights_only=True)
    if state["architecture"] != "tcn_film_projection":
        raise ValueError("TCN checkpoint required")
    g.load_state_dict(state["generator"]); d.load_state_dict(state["discriminator"])
    g.to(device); d.to(device)
    og = torch.optim.Adam(g.parameters(), lr=args.lr, betas=(0., .9))
    od = torch.optim.Adam(d.parameters(), lr=args.lr, betas=(0., .9))
    train_x, train_c = x[masks["train"]], c[masks["train"]]
    tx, tc = torch.tensor(train_x, device=device), torch.tensor(train_c, device=device)
    pos = torch.nonzero(tc[:, -1] > .5).flatten()
    neg = torch.nonzero(tc[:, -1] <= .5).flatten()
    rng = torch.Generator(device=device).manual_seed(seed+1000)
    noise = torch.Generator(device=device).manual_seed(seed+2000)
    gp_rng = torch.Generator(device=device).manual_seed(seed+3000)
    warp_rng = np.random.default_rng(seed+4000)
    vc, vx = c[masks["validation"]], x[masks["validation"]]
    vz = np.random.default_rng(9000+seed).standard_normal((len(vc), 32)).astype(np.float32)
    folder = output / arm / ("seed_" + str(seed))
    folder.mkdir(parents=True, exist_ok=False)
    initial = metrics(infer(g, vc, vz, device, batch=16), vc, vx)
    best, best_step, history = initial["development_score"], 0, [dict(step=0, validation=initial)]

    def save(step, evaluation):
        torch.save(dict(generator=g.state_dict(), discriminator=d.state_dict(), optimizer_g=og.state_dict(),
                        optimizer_d=od.state_dict(), step=step, validation=evaluation, arm=arm, seed=seed,
                        parent_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
                        torch_rng=torch.get_rng_state(), data_rng=rng.get_state(), noise_rng=noise.get_state(),
                        gp_rng=gp_rng.get_state(), warp_rng=warp_rng.bit_generator.state,
                        cuda_rng=torch.cuda.get_rng_state_all() if device.type == "cuda" else [],
                        note="New optimizers; original sweep did not save optimizer state"), folder / "best.pt")

    save(0, initial)
    for step in range(1, args.steps+1):
        g.train(); d.train()
        for _ in range(args.ncritic):
            idx = balanced_batch(pos, neg, args.batch, rng)
            real, condition = tx[idx], tc[idx]
            if arm == "time_warp":
                real_np, c_np = warp_batch(real.cpu().numpy(), condition.cpu().numpy(),
                                           warp_rng.uniform(-.01, .01, args.batch))
                real, condition = torch.tensor(real_np, device=device), torch.tensor(c_np, device=device)
            wrong = condition.roll(args.batch//2, 0)
            with torch.no_grad():
                fake = g(torch.randn(args.batch, 32, device=device, generator=noise), condition)
            od.zero_grad(set_to_none=True)
            rs, ra = d(real, condition); fs, _ = d(fake, condition); ws, _ = d(real, wrong)
            ld = (.5*(fs.mean()+ws.mean())-rs.mean() + 10*gradient_penalty(d, real, fake, condition, gp_rng)
                  + 2*auxiliary_loss(ra, condition))
            ld.backward(); od.step()
        for p in d.parameters():
            p.requires_grad_(False)
        og.zero_grad(set_to_none=True)
        fake = g(torch.randn(args.batch, 32, device=device, generator=noise), condition)
        fs, fa = d(fake, condition)
        lg = (-fs.mean()+5*auxiliary_loss(fa, condition)+20*morphology_loss(fake, condition)
              +.5*spectral_loss(fake, real)+5*derivative_loss(fake, real)
              +5*(fake[:, 1].square()+fake[:, -2].square()).mean())
        if arm == "relative_derivative":
            lg = lg+.05*relative_derivative_loss(fake, real)
        if not torch.isfinite(lg+ld):
            raise RuntimeError("Nonfinite fine-tune loss")
        lg.backward(); og.step()
        for p in d.parameters():
            p.requires_grad_(True)
        if step % args.evaluate_every == 0 or step == args.steps:
            evaluation = metrics(infer(g, vc, vz, device, batch=16), vc, vx)
            history.append(dict(step=step, validation=evaluation, loss_g=float(lg.detach()), loss_d=float(ld.detach())))
            if evaluation["development_score"] < best:
                best, best_step = evaluation["development_score"], step
                save(step, evaluation)
            print(arm, seed, step, evaluation["development_score"], flush=True)
    (folder / "history.json").write_text(json.dumps(history, indent=2)+"\n")
    last = dict(generator=g.state_dict(), discriminator=d.state_dict(), optimizer_g=og.state_dict(),
                optimizer_d=od.state_dict(), step=args.steps, arm=arm, seed=seed)
    torch.save(last, folder / "last.pt")
    chosen = torch.load(folder / "best.pt", map_location="cpu", weights_only=True)
    g.load_state_dict(chosen["generator"]); d.load_state_dict(chosen["discriminator"])
    g.cpu().eval(); d.cpu().eval()
    z, conditions = torch.randn(3, 32), torch.tensor(vc[:3])
    with torch.inference_mode():
        generated = g(z, conditions)
        tg = torch.jit.trace(g, (z, conditions)); td = torch.jit.trace(d, (generated, conditions))
        torch.testing.assert_close(tg(z, conditions), generated)
        for actual, expected in zip(td(generated, conditions), d(generated, conditions)):
            torch.testing.assert_close(actual, expected)
    tg.save(str(folder / "generator_cpu.ts")); td.save(str(folder / "critic_cpu.ts"))
    result = dict(arm=arm, seed=seed, best_step=best_step, before=initial, after=chosen["validation"],
                  checkpoint_kept_parent=best_step == 0, export_parity=True)
    (folder / "result.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=Path("ml/runs/kaggle-v1/ppg_run/prepared.npz"))
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--parent", type=Path, default=DEFAULT_PARENT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--ncritic", type=int, default=3)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--evaluate-every", type=int, default=50)
    parser.add_argument("--seeds", nargs="+", type=int, default=[41, 42, 43])
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if min(args.steps, args.batch, args.ncritic, args.evaluate_every) < 1 or args.batch < 2 or args.batch % 2:
        parser.error("Positive parameters and even batch >= 2 required")
    if not np.isfinite(args.lr) or args.lr <= 0:
        parser.error("Positive finite learning rate required")
    torch.set_num_threads(2)
    if args.smoke:
        x, c, masks = load_prepared(args.prepared)
        ids = np.concatenate([stratified_indices(masks[s], c, maximum_per_class=8) for s in ("train", "validation")])
        masks = {s: masks[s][ids] for s in ("train", "validation")}
        x, c = x[ids], c[ids]
        args.steps, args.batch, args.ncritic, args.evaluate_every, args.seeds = 2, 4, 1, 1, [42]
        provenance = dict(status="PIPELINE_SMOKE_ONLY", labels="old automatic labels, NOT human reviewed")
    else:
        if args.annotations is None:
            parser.error("--annotations with human-reviewed labels is required; use --smoke only for plumbing")
        x, c, masks, subjects, provenance = curated_data(args.prepared, args.annotations)
    args.output.mkdir(parents=True, exist_ok=False)
    config = dict(provenance=provenance, settings={k: str(v) if isinstance(v, Path) else v for k,v in vars(args).items()},
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  selection="Independent development evaluator; checkpoint starts with frozen parent at step 0",
                  promotion="Never automatically installed into app; human audit and external evaluation still required")
    (args.output / "configuration.json").write_text(json.dumps(config, indent=2)+"\n")
    results = [run_arm(arm, seed, x, c, masks, args.parent, args.output, args) for arm in ARMS for seed in args.seeds]
    summary = dict(status="PIPELINE_SMOKE_ONLY" if args.smoke else "REVIEWED_DEVELOPMENT_EXPERIMENT",
                   results=results, installed_in_app=False, external_test_performed=False)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print("COMPLETE", summary["status"], flush=True)


if __name__ == "__main__":
    main()
