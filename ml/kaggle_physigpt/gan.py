"""APFT-GAN: adversarial fine-tuning of APFT-L (the PPG-physiGPT large V1 release) against a strict-view critic.

A hybrid of an autoregressive patch-flow transformer and a GAN, as SeqGAN and TimeGAN pair a sequence model with a
discriminator and Flow-GAN / Denoising Diffusion GAN pair an iterative sampler with one:
- generator: the APFT model with its own sampler (30 patches, a Heun ODE of --gen-steps per patch, patches clipped to
  [0, 1], window min-max), started from the V1 release;
- critic (v2): strict_judge.JudgeCritic, the strict judge's own network, behind PhysioGAN-R's adaptive augmentation
  (ADA), relativistic pairing loss (physiogan_r, after Huang et al. 2024), no R1/R2 by default. v1 used StrictCritic
  (spectral norm, -30 dB relative STFT floor) with R1/R2 at gamma 1; its loss stayed at ln 2 for 2550 steps;
- gradient path: a batch is sampled autoregressively without gradient, keeping every patch's start noise. One
  teacher-forced pass of the transformer over the sampled patches then gives each patch the context state the sampler
  used (h_i depends on patches < i only), and the ODE is re-run from the same noise with gradient, each head call
  checkpointed. The critic's gradient reaches the flow head and, through h, the transformer; a patch's effect on
  later contexts is not differentiated (truncated, as in teacher forcing);
- anchor: the generator keeps its flow-matching and logit-Laplace loss on real windows. The adversarial term is
  scaled by the adaptive weight of Esser et al. 2021 (the ratio of the two losses' gradient norms at the flow head's
  output layer) times --adv-weight, so the critic cannot pull the model off the data's flow;
- selection: at step 0 (the V1 model, at this sampler) and every --eval-every steps, 1024 windows are sampled and
  compared with 2048 windows of training records on the target's 22 features (mean 1 - KS; v1 used the 14 signal
  features alone, and its best state lost beat shape on held-out people); gan_release.pt is the best state by that.
  The judge's real class (the shards' held-out records) is used neither in training nor in selection.
  --patience N stops after N evaluations in a row without a new best (0, the default: no early stop); an evaluation
  counts only if the generator moved since the last one, and gan_summary.json says why the run stopped;
Two T4s: one process per GPU with gradients averaged by all-reduce. Not DDP: the generator and critic steps freeze
each other's parameters, which DDP's fixed gradient buckets do not allow. fp16 autocast for the generator, fp32
critic. Engineering evaluation of normalised 30 s waveform shape; not clinical validation.
"""
import argparse
import json
import math
from pathlib import Path
import time

import numpy as np
import torch
import torch.distributed as dist
from torch.utils.checkpoint import checkpoint

from ml.kaggle_lsm.train_lsm import save_json
from ml.kaggle_multidomain.physiogan_r import Balanced, d_loss, g_loss, penalty
from ml.kaggle_multidomain.strict_judge import JudgeCritic, StrictCritic
from ml.kaggle_physigpt.judge_physigpt import BEAT_DIAGNOSTIC, all_features, finite_similarity
from ml.kaggle_physigpt.model import CONFIGS, PhysiGPT, describe
from ml.kaggle_physigpt.train import Windows, evaluate, synthetic_shard, warm_cache

CRITIC = dict(width=32, minibatch_std=True, band=True)
SELECT_REAL, SELECT_FAKE, SELECT_SEED = 2048, 1024, 20261101


def windows_of(patches):
    """[n, 30, 40] patches in [0, 1] -> [n, 1200] windows, min-max normalised as PhysiGPT.generate does."""
    x = patches.reshape(len(patches), -1)
    lo, hi = x.amin(1, keepdim=True), x.amax(1, keepdim=True)
    return (x-lo)/(hi-lo).clamp_min(1e-6)


def rollout(model, n, steps, generator, device):
    """Autoregressive sampling as PhysiGPT.generate, without gradient: the clipped patches [n, 30, 40] and the start
    noise of every patch."""
    cfg = model.cfg
    noise = torch.randn(n, cfg.patches, cfg.patch, device=device, generator=generator)
    domain = torch.zeros(n, dtype=torch.long, device=device)
    patches = torch.zeros(n, cfg.patches, cfg.patch, device=device)
    with torch.no_grad():
        for i in range(cfg.patches):
            h = model.hidden(patches[:, :i+1], domain)[:, i]
            patches[:, i] = ((model.integrate(noise[:, i], h, steps)+1)/2).clamp(0, 1)
    return patches, noise


def regenerate(model, patches, noise, steps, use_checkpoint=True):
    """The windows of rollout again, now differentiable: the contexts of all patches in one teacher-forced pass over
    the sampled patches, then the ODE from the same start noise."""
    n, p, d = patches.shape
    h = model.hidden(patches, torch.zeros(n, dtype=torch.long, device=patches.device)).reshape(n*p, -1)
    flow = (lambda x, t, c: checkpoint(model.flow, x, t, c, use_reentrant=False)) if use_checkpoint else None
    x = model.integrate(noise.reshape(n*p, d), h, steps, flow)
    return windows_of(((x+1)/2).clamp(0, 1).view(n, p, d))


def similarity(real_features, windows):
    """Per-feature 1 - KS of generated windows against the selection's real windows, on the target's scored features."""
    fake = all_features(windows)
    return {k: finite_similarity(real_features[k], fake[k]) for k in real_features if k not in BEAT_DIAGNOSTIC}


def select_score(model, real_features, steps, device):
    model.eval()
    parts = [model.generate(min(256, SELECT_FAKE-i), steps=steps, seed=SELECT_SEED+i, device=device).float().cpu().numpy()
             for i in range(0, SELECT_FAKE, 256)]
    model.train()
    sim = similarity(real_features, np.concatenate(parts))
    return dict(mean_similarity=float(np.mean(list(sim.values()))), similarity=sim)


def average(params, world):
    """All-reduce mean of the gradients, one flat buffer (a missing gradient counts as zero on that rank)."""
    if world == 1:
        return
    grads = [p.grad if p.grad is not None else torch.zeros_like(p) for p in params]
    flat = torch.cat([g.reshape(-1) for g in grads])
    dist.all_reduce(flat)
    flat /= world
    offset = 0
    for p, g in zip(params, grads):
        p.grad = flat[offset:offset+g.numel()].view_as(g).clone()
        offset += g.numel()


def mean_over_ranks(value, world, device):
    value = torch.as_tensor(float(value), device=device)
    if world > 1:
        dist.all_reduce(value)
        value /= world
    return float(value)


def finite(record):
    return {k: (v if not isinstance(v, float) or math.isfinite(v) else None) for k, v in record.items()}


def save_state(path, **state):
    tmp = Path(str(path)+".partial")
    torch.save(state, tmp)
    tmp.replace(path)


def worker(rank, world, args):
    cuda = torch.cuda.is_available() and not args.cpu
    if world > 1:
        dist.init_process_group("nccl" if cuda else "gloo", init_method=f"tcp://127.0.0.1:{args.port}", rank=rank,
                                world_size=world)
    device = torch.device(f"cuda:{rank}" if cuda else "cpu")
    if cuda:
        torch.cuda.set_device(device)
        torch.backends.cuda.matmul.allow_tf32 = True
    begin, output = time.time(), Path(args.output)
    torch.manual_seed(args.seed)   # same critic initialisation on every rank
    model = PhysiGPT(CONFIGS[args.config]).to(device)
    critic = Balanced(JudgeCritic() if args.critic == "judge" else StrictCritic(**CRITIC)).to(device)
    if args.init:
        state = torch.load(args.init, map_location=device, weights_only=False)
        if state["config"] != args.config:
            raise ValueError(f"--init config {state['config']} != {args.config}")
        model.load_state_dict(state["model"])
        del state
    g_opt = torch.optim.AdamW(model.parameters(), lr=args.lr, betas=(.5, .99), weight_decay=0.)
    d_opt = torch.optim.Adam(critic.parameters(), lr=args.d_lr, betas=(0., .99))
    scaler = torch.amp.GradScaler("cuda", enabled=cuda)
    data = Windows(args.data)
    selection = np.sort(np.random.default_rng(SELECT_SEED).choice(data.train, min(SELECT_REAL, len(data.train)),
                                                                    replace=False))
    real_features = all_features(data.rows(selection).astype(np.float32)/65535)
    step, best, rt_ema, g_updates = 0, dict(step=None, mean_similarity=-math.inf), None, 0
    stale, scored_updates, stop_reason = 0, 0, "steps"
    if args.resume:
        state = torch.load(args.resume, map_location=device, weights_only=False)
        model.load_state_dict(state["model"])
        critic.load_state_dict(state["critic"])
        g_opt.load_state_dict(state["g_opt"])
        d_opt.load_state_dict(state["d_opt"])
        if state["scaler"]:
            scaler.load_state_dict(state["scaler"])
        step, best, rt_ema, g_updates = state["step"], state["best"], state["rt_ema"], state["g_updates"]
        stale, scored_updates = state.get("stale", 0), state.get("scored_updates", 0)
        del state
    if rank == 0:
        output.mkdir(parents=True, exist_ok=True)
        save_json(output/"run_config.json", dict(vars(args), world=world, model=describe(model), critic=CRITIC,
                                                 critic_parameters=sum(p.numel() for p in critic.parameters()),
                                                 train_windows=int(len(data.train)), valid_windows=int(len(data.valid)),
                                                 selection_windows=int(len(selection)), shards=data.shards,
                                                 start_step=step))
        print(f"warm cache: {warm_cache(data)/2**30:.2f} GB", flush=True)
    if world > 1:
        dist.barrier()
    params, critic_params = list(model.parameters()), list(critic.parameters())
    last_layer = model.flow.outp.weight
    log = (output/"metrics.jsonl").open("a") if rank == 0 else None
    last_save, step_seconds, tick = time.time(), None, None

    def checkpoint_select(at):
        """Rank 0 scores the selection and keeps the best state; the others wait."""
        nonlocal best, stale, scored_updates
        if rank == 0:
            record = dict(step=at, select=select_score(model, real_features, args.gen_steps, device),
                          **evaluate(model, data, device, cuda), hours=round((time.time()-begin)/3600, 4))
            if record["select"]["mean_similarity"] > best["mean_similarity"]:
                best, stale = dict(step=at, mean_similarity=record["select"]["mean_similarity"]), 0
                torch.save(dict(model=model.state_dict(), config=args.config, describe=describe(model), step=at,
                                gen_steps=args.gen_steps, select=record["select"]), output/"gan_release.pt")
            elif g_updates > scored_updates:   # a generator that did not move says nothing about further training
                stale += 1
            scored_updates = g_updates
            record.update(best=best, stale=stale)
            log.write(json.dumps(record)+"\n")
            log.flush()
            print(json.dumps(record), flush=True)
        if world > 1:
            dist.barrier()

    if step == 0:
        checkpoint_select(0)
    while step < args.steps:
        rng = np.random.default_rng([args.seed, step, rank])
        x = torch.from_numpy(data.rows(rng.choice(data.train, args.batch+args.anchor)).astype(np.float32)/65535).to(device)
        real, anchor = x[:args.batch], x[args.batch:]
        generator = torch.Generator(device).manual_seed(args.seed*1_000_003+step*world+rank)
        with torch.autocast("cuda", torch.float16, enabled=cuda):
            patches, noise = rollout(model, args.batch, args.gen_steps, generator, device)
        fake = windows_of(patches).float()

        # critic: relativistic pairing, R1 and R2 every --lazy steps (scaled by lazy); --d-steps updates per step, the
        # later ones on fresh real windows against the same generated batch
        critic.requires_grad_(True)
        for k in range(args.d_steps):
            if k:
                real = torch.from_numpy(data.rows(rng.choice(data.train, args.batch)).astype(np.float32)/65535).to(device)
            r, f = critic(real[:, None], None), critic(fake[:, None], None)
            loss_d = d_loss(r, f)
            if args.gamma and (step*args.d_steps+k) % args.lazy == 0:
                loss_d = loss_d+args.gamma/2*args.lazy*(penalty(critic, real[:, None], None)
                                                        + penalty(critic, fake[:, None], None))
            d_opt.zero_grad(set_to_none=True)
            loss_d.backward()
            average(critic_params, world)
            d_grad = torch.nn.utils.clip_grad_norm_(critic_params, args.d_clip)
            d_opt.step()
            rt = mean_over_ranks(torch.sign(r-f).mean().item(), world, device)
            critic.augment.adjust(rt, args.batch*world)
        rt_ema = rt if rt_ema is None else .9*rt_ema+.1*rt

        record = dict(step=step+1, loss_d=float(loss_d.detach()), rt=rt, rt_ema=rt_ema, ada_p=float(critic.augment.p),
                      d_grad=float(d_grad), d_real=float(r.detach().mean()), d_fake=float(f.detach().mean()),
                      g_updates=g_updates)
        # The generator moves only once the critic separates the classes (rt_ema >= --rt-gate): a critic at chance
        # gives a gradient of noise, which the adaptive weight would scale up (v1 runs: loss_d stayed at ln 2).
        if step >= args.critic_warmup and rt_ema >= args.rt_gate:
            critic.requires_grad_(False)
            with torch.no_grad():
                r_now = critic(real[:, None], None)
            with torch.autocast("cuda", torch.float16, enabled=cuda):
                fake_g = regenerate(model, patches, noise, args.gen_steps)
                fm, parts = model(anchor, torch.zeros(len(anchor), dtype=torch.long, device=device), aux=args.aux,
                                  repeats=args.repeats, generator=generator)
            adv = g_loss(r_now, critic(fake_g.float()[:, None], None))
            # Adaptive weight (Esser et al. 2021). The flow loss's gradient is taken at the scaler's scale (its fp16
            # gradients underflow unscaled), the adversarial one unscaled: at the scale it overflowed fp16 on every
            # step of the v2 RSR run (lam 0 throughout) once the critic separated the classes.
            s = scaler.get_scale() if cuda else 1.
            g_fm, = torch.autograd.grad(fm*s, last_layer, retain_graph=True)
            g_adv, = torch.autograd.grad(adv, last_layer, retain_graph=True)
            n_fm, n_adv = float(g_fm.float().norm())/s, float(g_adv.float().norm())
            # a remaining overflow gives no weight, not the max_lambda cap
            lam = min(n_fm/(n_adv+1e-4), args.max_lambda) if math.isfinite(n_fm) and math.isfinite(n_adv) else 0.
            lam = mean_over_ranks(lam, world, device)
            for group in g_opt.param_groups:
                group["lr"] = args.lr*min(1., (g_updates+1)/max(1, args.warmup))
            loss_g = fm+args.adv_weight*lam*adv
            g_opt.zero_grad(set_to_none=True)
            scaler.scale(loss_g).backward()
            average(params, world)   # before unscale_, so an overflow on one rank skips the step on every rank
            scaler.unscale_(g_opt)
            g_grad = torch.nn.utils.clip_grad_norm_(params, args.clip)
            scaler.step(g_opt)
            scaler.update()
            g_updates += 1
            record.update(adv=float(adv), lam=lam, grad_norm_fm=n_fm, grad_norm_adv=n_adv, loss_g=float(loss_g), g_grad=float(g_grad), lr=g_opt.param_groups[0]["lr"],
                          scale=float(scaler.get_scale()), **{k: float(v) for k, v in parts.items()})
        step += 1
        if step == 10:
            tick = time.time()
        elif step == 40 and tick:
            step_seconds = (time.time()-tick)/30
        # every rank stops at the same step: rank 0's clock decides
        stop = torch.tensor(float(time.time()-begin > args.hours*3600-args.reserve_minutes*60), device=device)
        if world > 1:
            dist.broadcast(stop, 0)
        stop = bool(stop.item())
        if rank == 0 and (step % args.log_every == 0 or step == 1):
            record.update(hours=round((time.time()-begin)/3600, 4), step_seconds=step_seconds)
            log.write(json.dumps(finite(record))+"\n")
            log.flush()
            print(json.dumps(finite(record)), flush=True)
        if step % args.eval_every == 0 or step == args.steps or stop:
            checkpoint_select(step)
            if args.patience and step < args.steps:
                # only rank 0 scores, so its count decides and every rank stops at the same step
                exhausted = torch.tensor(float(stale >= args.patience), device=device)
                if world > 1:
                    dist.broadcast(exhausted, 0)
                if exhausted.item() and not stop:
                    stop_reason = "patience"
        if stop:
            stop_reason = "hours"
        if rank == 0 and (time.time()-last_save > args.save_minutes*60 or step == args.steps or stop_reason != "steps"):
            save_state(output/"last.pt", model=model.state_dict(), critic=critic.state_dict(), g_opt=g_opt.state_dict(),
                       d_opt=d_opt.state_dict(), scaler=scaler.state_dict(), step=step, best=best, config=args.config,
                       rt_ema=rt_ema, g_updates=g_updates, stale=stale, scored_updates=scored_updates)
            last_save = time.time()
        if stop_reason != "steps":
            break
    if rank == 0:
        save_json(output/"gan_summary.json", dict(steps=step, planned=args.steps, hours=(time.time()-begin)/3600,
                                                  stop_reason=stop_reason, patience=args.patience, stale_evals=stale,
                                                  step_seconds=step_seconds, best=best, gen_steps=args.gen_steps,
                                                  generator_updates=g_updates, rt_ema=rt_ema,
                                                  max_memory_gb=torch.cuda.max_memory_allocated(device)/2**30
                                                  if cuda else None,
                                                  note="selection on training records only; realism is judged by the "
                                                       "strict judge and the feature tier on held-out people"))
        log.close()
    if world > 1:
        dist.barrier()
        dist.destroy_process_group()


def smoke(root, steps=6):
    """A few steps of the tiny config on synthetic windows through the device path (all-reduce, fp16, critic,
    selection, release) before the kernel spends hours. It proves the code runs on the GPUs, nothing about the model."""
    root = Path(root)
    if not (root/"shard"/"manifest.json").exists():
        synthetic_shard(root/"shard")
    main(["--data", str(root/"shard"), "--output", str(root/"run"), "--config", "tiny", "--steps", str(steps),
          "--batch", "8", "--anchor", "8", "--critic-warmup", "2", "--gen-steps", "2", "--eval-every", "3",
          "--log-every", "1", "--port", "29523", "--rt-gate", "-1"])
    return json.loads((root/"run"/"gan_summary.json").read_text())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", nargs="+", required=True, help="roots holding the shards (manifest.json)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="large", choices=sorted(CONFIGS))
    parser.add_argument("--init", default=None, help="release.pt of the model to fine-tune (none: random, smoke only)")
    parser.add_argument("--resume", default=None, help="last.pt of this run after a stop")
    parser.add_argument("--steps", type=int, default=8000)
    parser.add_argument("--batch", type=int, default=64, help="generated and real windows per device for the critic")
    parser.add_argument("--anchor", type=int, default=128, help="real windows per device for the flow anchor")
    parser.add_argument("--gen-steps", type=int, default=16, help="Heun steps per patch of the sampler")
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--d-lr", type=float, default=2e-4)
    parser.add_argument("--critic", default="judge", choices=("judge", "strict"),
                        help="judge: strict_judge.JudgeCritic (v2); strict: StrictCritic with CRITIC (v1, stayed at chance)")
    parser.add_argument("--d-steps", type=int, default=1, help="critic updates per generator step")
    parser.add_argument("--rt-gate", type=float, default=.2,
                        help="the generator moves only while the critic's rt (EMA) is at least this (-1: always)")
    parser.add_argument("--warmup", type=int, default=200, help="generator learning-rate warmup (generator updates)")
    parser.add_argument("--critic-warmup", type=int, default=300, help="critic-only steps before the generator moves")
    parser.add_argument("--adv-weight", type=float, default=.5, help="factor on the adaptive adversarial weight")
    parser.add_argument("--max-lambda", type=float, default=1.,
                        help="cap of the adaptive weight (v1: 1e4 let it reach ~10 on a critic at chance)")
    parser.add_argument("--gamma", type=float, default=0.,
                        help="R1/R2 weight (v1: 1, which kept the critic at chance; 0.01 already does on JudgeCritic)")
    parser.add_argument("--lazy", type=int, default=4, help="penalty every this many critic steps")
    parser.add_argument("--aux", type=float, default=.1, help="weight of the logit-Laplace NLL in the anchor")
    parser.add_argument("--repeats", type=int, default=4)
    parser.add_argument("--clip", type=float, default=1., help="generator gradient-norm clip")
    parser.add_argument("--d-clip", type=float, default=10., help="critic gradient-norm clip (PhysioGAN-R's)")
    parser.add_argument("--hours", type=float, default=11.)
    parser.add_argument("--reserve-minutes", type=float, default=20.)
    parser.add_argument("--save-minutes", type=float, default=30.)
    parser.add_argument("--log-every", type=int, default=50)
    parser.add_argument("--eval-every", type=int, default=500)
    parser.add_argument("--patience", type=int, default=0,
                        help="stop after this many evaluations in a row without a new best (0: no early stop)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--port", type=int, default=29521)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--cpu-world", type=int, default=1, help="CPU (gloo) processes; checks the all-reduce path")
    args = parser.parse_args(argv)
    if args.patience < 0:
        parser.error("--patience must be 0 (off) or positive")
    world = args.cpu_world if args.cpu or not torch.cuda.is_available() else torch.cuda.device_count()
    if world > 1:
        torch.multiprocessing.spawn(worker, args=(world, args), nprocs=world, join=True)
    else:
        worker(0, 1, args)


if __name__ == "__main__":
    main()
