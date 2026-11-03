"""RSR-FlowGAN: adversarial fine-tuning of RSR-Flow (the app's PhysioFlow, arm F6_flow_flag_deriv_unif_s16_w1) against
a strict-view critic, with the APFT-GAN recipe (ml/kaggle_physigpt/gan.py), then judged in the same kernel.

What it changes against P4's flow-GAN (G3, strict AUC 0.73 -> 0.97, see experiment_p5): no distillation to a 4-step
student pulled to a frozen teacher; the generator keeps its own 16-step Heun sampler and its own flow-matching loss on
real windows as the anchor; checkpoints are chosen on realism (feature similarity), not on S_real + 0.5C.
- generator: FlowGenerator with the app's U-Net weights (the TorchScript bundle's traced network; the eager copy is
  checked to give the bundle's windows exactly), rhythm scaffold constructed from the prompt as in the app; the
  critic's gradient flows back through all 16 Heun steps (each U-Net call checkpointed);
- critic (v2): strict_judge.JudgeCritic, the strict judge's own network (unconditional), behind PhysioGAN-R's adaptive
  augmentation; relativistic pairing loss, no R1/R2 by default. v1 used StrictCritic conditioned by projection with
  R1/R2 at gamma 1, which a CPU probe showed stuck near AUC 0.6 (see JudgeCritic);
- the generator moves only while the critic separates the classes (rt EMA >= --rt-gate), and only the last
  --grad-steps Heun steps carry the critic's gradient;
- anchor: flow_loss as F6 trained (deriv 1, uniform flow times, condition and scaffold dropout) on real training
  windows with their peak scaffolds; the adversarial term carries the adaptive weight of Esser et al. 2021 (ratio of
  the gradient norms at the U-Net's output convolution) times --adv-weight;
- EMA of the generator (0.999) is what selection, release and the judge use;
- selection every --eval-every steps: windows prompted with the conditions of training people of the strict judge's
  control_eval share, against those people's real windows, mean 1 - KS over the 14 judge_physigpt features.
  Validation people are used only by the judge stage. --patience N stops a seed after N evaluations in a row without
  a new best (0, the default: no early stop); an evaluation counts only if the generator moved since the last one,
  and train_summary.json says why the seed stopped.
Two seeds train at once, one per T4. The judge stage then builds the strict judge's sets (validation people) for the
app's RSR-Flow, each seed's RSR-FlowGAN and the real_other_people null, reports the feature tier first
(judge_physigpt.fidelity_report) and then fits the strict judge per source and seed.
Engineering evaluation of normalised 30 s PPG shape; not clinical validation, not measured on the Pi/DAC/OPT101.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import time

import numpy as np
from scipy import stats
import torch
from torch.utils.checkpoint import checkpoint

from ml.kaggle_lsm.train_lsm import LENGTH, save_json
from ml.kaggle_multidomain import strict_judge as sj
from ml.kaggle_multidomain.data import balanced_pool
from ml.kaggle_multidomain.data_gxu import load_input
from ml.kaggle_multidomain.flow import FlowGenerator, flow_loss, real_scaffolds
from ml.kaggle_multidomain.physio import Conditions
from ml.kaggle_multidomain.physiogan_r import Balanced, d_loss, g_loss, penalty
from ml.kaggle_physigpt.judge_physigpt import SIZES, fidelity_report, signal_features

PROTOCOL = "ppg_physiomix_v3"
ARM = dict(name="F6_flow_flag_deriv_unif_s16_w1", sample_steps=16, flag_scaffold=True, deriv=1., t_dist="uniform")
CRITIC = dict(width=32, minibatch_std=True, band=True)
SEEDS = (42, 123)
SELECT_PER_DOMAIN, SELECT_SEED = 64, 20261101
JUDGE_SEEDS = (0, 1)


class Inputs:
    """The v3 pack (external rows dropped), its train+validation view with the app's v2 condition bank, and the app's
    RSR-Flow bundle, checked against the manifest (sha256, condition schema)."""

    def __init__(self, root):
        pack, self.manifest = load_input(root, PROTOCOL)
        self.pack = {k: v[pack["split"] != "external"] for k, v in pack.items()}
        self.keep = np.flatnonzero(np.isin(self.pack["split"], ["train", "validation"]))
        self.view = {k: v[self.keep] for k, v in self.pack.items()}
        self.conditions = Conditions(self.view, "v2")
        self.bundle = next(p.parent for p in Path(root).rglob("manifest.json")
                           if (p.parent/"physioflow_generator.ts").exists())
        app = json.loads((self.bundle/"manifest.json").read_text())
        meta, entry = app["physioflow"], app["models"]["physioflow_generator"]
        c = self.conditions
        if meta["domains"] != c.domains or not np.allclose(meta["center"], c.center, rtol=1e-5) \
                or not np.allclose(meta["scale"], c.scale, rtol=1e-5):
            raise ValueError("RSR-Flow: app condition schema differs from the v3 pack's")
        if meta["arm"] != ARM["name"]:
            raise ValueError(f"RSR-Flow: the app ships {meta['arm']}, this recipe is for {ARM['name']}")
        self.app_path = self.bundle/entry["file"]
        if hashlib.sha256(self.app_path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("physioflow_generator checksum mismatch")

    def generator(self):
        """FlowGenerator holding the app's U-Net, checked against the TorchScript bundle on 4 windows (CPU)."""
        c = self.conditions
        g = FlowGenerator(c.bank.shape[1], c.center, c.scale, sample_steps=ARM["sample_steps"],
                          flag_scaffold=ARM["flag_scaffold"])
        app = torch.jit.load(str(self.app_path), map_location="cpu").eval()
        g.net.load_state_dict(app.net.state_dict())
        z, rows = torch.randn(4, LENGTH, generator=torch.Generator().manual_seed(0)), torch.from_numpy(c.bank[:4])
        with torch.no_grad():
            error = float((g.eval()(z, rows)-app(z, rows)).abs().max())
        if error > 1e-4:
            raise ValueError(f"eager RSR-Flow differs from the app bundle by {error}")
        return g.train()


def sample(g, z, condition, use_checkpoint=False, grad_steps=None):
    """FlowGenerator.forward (t_end 0, no finishing filter, guidance 1), each U-Net call optionally checkpointed so the
    critic's gradient can run back through the Heun steps; grad_steps: only the last ones carry gradient (None: all)."""
    s = g.scaffold_of(z, condition)
    x, ones = z[:, None], torch.ones(len(z), device=z.device)
    net = (lambda *a: checkpoint(g.net, *a, use_reentrant=False)) if use_checkpoint else g.net
    steps = g.sample_steps
    frozen = 0 if grad_steps is None else steps-grad_steps
    for i in range(steps):
        t, t_next = 1-i/steps, 1-(i+1)/steps
        with torch.set_grad_enabled(torch.is_grad_enabled() and i >= frozen):
            v = net(x, ones*t, s, condition, ones)
            proposal = x+(t_next-t)*v
            x = x+(t_next-t)*.5*(v+net(proposal, ones*t_next, s, condition, ones)) if i < steps-1 else proposal
    return (x-x.amin(-1, keepdim=True))/(x.amax(-1, keepdim=True)-x.amin(-1, keepdim=True)).clamp_min(1e-6)


def windows(g, rows, seed, device, chunk=256):
    """(n, LENGTH) numpy windows of g for condition rows (numpy), noise from seed."""
    z = torch.randn(len(rows), LENGTH, generator=torch.Generator().manual_seed(seed))
    rows = torch.as_tensor(rows)
    g.eval()
    with torch.no_grad():
        out = torch.cat([sample(g, a.to(device), b.to(device)).float().cpu()
                         for a, b in zip(z.split(chunk), rows.split(chunk))])
    return out[:, 0].numpy()


def selection_set(inputs):
    """View ids of real windows of the training people in the strict judge's control_eval share, per domain equal."""
    view = inputs.view
    train = np.flatnonzero(view["split"] == "train")
    people = sj.people_split(view, train)["control_eval"]
    ids = train[np.isin(view["subject"][train], people)]
    return sj.sample(view, ids, SELECT_PER_DOMAIN, np.random.default_rng(SELECT_SEED), replace=False)


def similarity(real_features, fake):
    f = signal_features(fake)
    return {k: float(1-stats.ks_2samp(real_features[k], f[k]).statistic) for k in real_features}


def finite(record):
    return {k: (v if not isinstance(v, float) or math.isfinite(v) else None) for k, v in record.items()}


def train(rank, root, output, args):
    """One seed on one device: fine-tune, select, release (EMA)."""
    seed = args.seeds[rank]
    cuda = torch.cuda.is_available() and not args.cpu
    device = torch.device(f"cuda:{rank % torch.cuda.device_count()}" if cuda else "cpu")
    if cuda:
        torch.cuda.set_device(device)
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    begin, run = time.time(), Path(output)/f"seed{seed}"
    run.mkdir(parents=True, exist_ok=True)
    inputs = Inputs(root)
    c, view = inputs.conditions, inputs.view
    g = inputs.generator().to(device)
    ema = copy.deepcopy(g).eval().requires_grad_(False)
    critic = Balanced(sj.JudgeCritic() if args.critic == "judge" else
                      sj.StrictCritic(size=c.bank.shape[1], **CRITIC)).to(device)
    g_opt = torch.optim.AdamW(g.net.parameters(), lr=args.lr, betas=(.5, .99), weight_decay=0.)
    d_opt = torch.optim.Adam(critic.parameters(), lr=args.d_lr, betas=(0., .99))
    scaler = torch.amp.GradScaler("cuda", enabled=cuda)
    phase, usable = real_scaffolds(view["signal"][c.ids], c.raw[:, 0], c.known[:, 0] > 0)
    signal = torch.tensor(view["signal"][c.ids][:, None], device=device)
    phase, usable = torch.tensor(phase, device=device), torch.tensor(usable, device=device)
    bank = torch.tensor(c.bank, device=device)
    ids, weights = balanced_pool(view, "train")
    select = selection_set(inputs)
    select_rows, real_features = c.for_ids(select), signal_features(view["signal"][select])
    last_layer = g.net.out.weight
    save_json(run/"run_config.json", dict(vars(args), seed=seed, arm=ARM, critic=CRITIC, device=str(device),
                                          generator_parameters=sum(p.numel() for p in g.net.parameters()),
                                          critic_parameters=sum(p.numel() for p in critic.parameters()),
                                          train_windows=int(len(ids)), selection_windows=int(len(select)),
                                          pack_sha256=inputs.manifest["windows_sha256"]))
    log = (run/"metrics.jsonl").open("a")
    best, step, step_seconds, tick = dict(step=None, mean_similarity=-math.inf), 0, None, None
    rt_ema, g_updates, stale, scored_updates, stop_reason = None, 0, 0, 0, "steps"

    def evaluate(at):
        nonlocal best, stale, scored_updates
        sim = similarity(real_features, windows(ema, select_rows, SELECT_SEED, device))
        record = dict(step=at, mean_similarity=float(np.mean(list(sim.values()))), similarity=sim,
                      hours=round((time.time()-begin)/3600, 4))
        if record["mean_similarity"] > best["mean_similarity"]:
            best, stale = dict(step=at, mean_similarity=record["mean_similarity"]), 0
            torch.save(dict(net=ema.net.state_dict(), arm=ARM, seed=seed, step=at, select=record), run/"best.pt")
        elif g_updates > scored_updates:   # a generator that did not move says nothing about further training
            stale += 1
        scored_updates = g_updates
        record.update(best=best, stale=stale)
        log.write(json.dumps(record)+"\n")
        log.flush()
        print(f"seed {seed}", json.dumps({k: record[k] for k in ("step", "mean_similarity", "best")}), flush=True)

    def draw(n):
        picked = rng.choice(ids, n, p=weights)
        return torch.tensor([c.lookup[int(i)] for i in picked], device=device)

    evaluate(0)
    while step < args.steps and time.time()-begin < args.hours*3600:
        g.train()
        rows = draw(args.batch+args.anchor)
        real, cond = signal[rows[:args.batch]], bank[rows[:args.batch]]
        z = torch.randn(args.batch, LENGTH, device=device)
        # The generator moves only once the critic separates the classes (rt_ema >= --rt-gate; v1: loss_d stayed at
        # ln 2 and the adaptive weight scaled a gradient of noise). Its batch is sampled once: the early Heun steps
        # without gradient, the last --grad-steps with it (DRaFT-K, Clark et al. 2024); the critic sees it detached.
        moving = step >= args.critic_warmup and rt_ema is not None and rt_ema >= args.rt_gate
        with torch.autocast("cuda", torch.float16, enabled=cuda), torch.set_grad_enabled(moving):
            fake_g = sample(g, z, cond, use_checkpoint=True, grad_steps=args.grad_steps if moving else 0)
        fake = fake_g.detach().float()
        critic.requires_grad_(True)
        for k in range(args.d_steps):
            if k:
                more = draw(args.batch)
                real, cond_k = signal[more], bank[more]
            else:
                cond_k = cond
            # the generated side keeps its own prompts; a later real batch brings its own
            r, f = critic(real, cond_k), critic(fake, cond)
            loss_d = d_loss(r, f)
            if args.gamma and (step*args.d_steps+k) % args.lazy == 0:
                loss_d = loss_d+args.gamma/2*args.lazy*(penalty(critic, real, cond_k)+penalty(critic, fake, cond))
            d_opt.zero_grad(set_to_none=True)
            loss_d.backward()
            d_grad = torch.nn.utils.clip_grad_norm_(critic.parameters(), args.d_clip)
            d_opt.step()
            rt = float(torch.sign(r-f).mean())
            critic.augment.adjust(rt, args.batch)
        rt_ema = rt if rt_ema is None else .9*rt_ema+.1*rt
        record = dict(step=step+1, loss_d=float(loss_d.detach()), rt=rt, rt_ema=rt_ema, ada_p=float(critic.augment.p),
                      d_grad=float(d_grad), d_real=float(r.detach().mean()), d_fake=float(f.detach().mean()),
                      g_updates=g_updates)
        if moving:
            critic.requires_grad_(False)
            real = signal[rows[:args.batch]]
            with torch.no_grad():
                r_now = critic(real, cond)
            a = rows[args.batch:]
            with torch.autocast("cuda", torch.float16, enabled=cuda):
                fm = flow_loss(g.net, signal[a], phase[a], usable[a], bank[a], deriv=ARM["deriv"],
                               t_dist=ARM["t_dist"])
            adv = g_loss(r_now, critic(fake_g.float(), cond))
            # flow gradient at the scaler's scale (fp16 underflow), adversarial gradient unscaled (at the scale it
            # overflowed fp16 on every step of the v2 run: lam 0 throughout)
            s = scaler.get_scale() if cuda else 1.
            g_fm, = torch.autograd.grad(fm*s, last_layer, retain_graph=True)
            g_adv, = torch.autograd.grad(adv, last_layer, retain_graph=True)
            n_fm, n_adv = float(g_fm.float().norm())/s, float(g_adv.float().norm())
            lam = min(n_fm/(n_adv+1e-4), args.max_lambda) if math.isfinite(n_fm) and math.isfinite(n_adv) else 0.
            for group in g_opt.param_groups:
                group["lr"] = args.lr*min(1., (g_updates+1)/max(1, args.warmup))
            loss_g = fm+args.adv_weight*lam*adv
            g_opt.zero_grad(set_to_none=True)
            scaler.scale(loss_g).backward()
            scaler.unscale_(g_opt)
            g_grad = torch.nn.utils.clip_grad_norm_(g.net.parameters(), args.clip)
            scaler.step(g_opt)
            scaler.update()
            with torch.no_grad():
                for e, p in zip(ema.net.parameters(), g.net.parameters()):
                    e.lerp_(p, 1-args.ema)
            g_updates += 1
            record.update(adv=float(adv), fm=float(fm), lam=lam, grad_norm_fm=n_fm, grad_norm_adv=n_adv, loss_g=float(loss_g), g_grad=float(g_grad),
                          scale=float(scaler.get_scale()))
        step += 1
        if step == 10:
            tick = time.time()
        elif step == 40 and tick:
            step_seconds = (time.time()-tick)/30
        if step % args.log_every == 0 or step == 1:
            record.update(hours=round((time.time()-begin)/3600, 4), step_seconds=step_seconds)
            log.write(json.dumps(finite(record))+"\n")
            log.flush()
            print(f"seed {seed}", json.dumps(finite(record)), flush=True)
        if step % args.eval_every == 0:
            evaluate(step)
            if args.patience and step < args.steps and stale >= args.patience:
                stop_reason = "patience"
                break
    if stop_reason == "steps" and step < args.steps:
        stop_reason = "hours"
    if step % args.eval_every:
        evaluate(step)
    save_json(run/"train_summary.json", dict(seed=seed, steps=step, planned=args.steps, stop_reason=stop_reason,
                                             patience=args.patience, stale_evals=stale, step_seconds=step_seconds,
                                             hours=(time.time()-begin)/3600, best=best, generator_updates=g_updates,
                                             rt_ema=rt_ema,
                                             max_memory_gb=torch.cuda.max_memory_allocated(device)/2**30 if cuda else None))
    log.close()


def checkpoint_source(inputs, path, device):
    state = torch.load(path, map_location="cpu", weights_only=False)
    c = inputs.conditions
    g = FlowGenerator(c.bank.shape[1], c.center, c.scale, sample_steps=ARM["sample_steps"],
                      flag_scaffold=ARM["flag_scaffold"])
    g.net.load_state_dict(state["net"])
    g.to(device).eval()
    view_of = sj.ConditionsView(c, inputs.keep)

    def generate(ids, conditions, seed):
        return windows(g, view_of.for_ids(ids), seed, device).astype(np.float32)
    return generate


def judge(root, output, seeds, judge_seeds=JUDGE_SEEDS):
    """Strict-judge sets on validation people for the app's RSR-Flow and every seed's RSR-FlowGAN; the feature tier
    first, then the strict judge per source and seed."""
    output = Path(output)
    inputs = Inputs(root)
    devices = [f"cuda:{i}" for i in range(torch.cuda.device_count())] or ["cpu"]
    bank = sj.ConditionsView(inputs.conditions, inputs.keep)
    sources = {"rsr_flow_app": sj.torchscript_generator(inputs.app_path, devices[0], len(bank.domains)+5)}
    sources.update({f"rsr_flowgan_seed{s}": checkpoint_source(inputs, output/f"seed{s}"/"best.pt", devices[0])
                    for s in seeds if (output/f"seed{s}"/"best.pt").exists()})
    arrays, info = sj.build_sets(inputs.pack, bank, sources, "validation", controls=("real_other_people",))
    fidelity = {name: fidelity_report(arrays["real_train"], arrays["real_eval"], arrays["real_other_people_eval"],
                                      arrays[f"{name}_train"], arrays[f"{name}_eval"]) for name in sources}
    save_json(output/"fidelity.json", dict(info=dict(counts=info["counts"]), fidelity=fidelity))
    for name, report in fidelity.items():
        g = report["generated"]
        print("FIDELITY", name, f"mean 1-KS {g['mean_similarity']:.3f} (real-vs-real "
              f"{report['real_other_people']['mean_similarity']:.3f}), relative {g['relative_similarity']:.3f}, "
              f"trees acc {g['classifier']['trees']['accuracy']:.3f}", flush=True)
    data_path = Path("/tmp")/"rsr_flowgan_sets.npz" if devices != ["cpu"] else output/"sets.npz"
    np.savez(data_path, **arrays)
    jobs = [("strict", name, seed) for seed in judge_seeds for name in [*sources, "real_other_people"]]
    rows = sj.run_jobs(jobs, devices, data_path, output, bands=False)
    summary = {name: dict(auc=[r["auc"] for r in rows if r["source"] == name],
                          mean_auc=float(np.mean([r["auc"] for r in rows if r["source"] == name])))
               for name in [*sources, "real_other_people"]}
    save_json(output/"judge_summary.json", dict(split="validation", judge="strict", judge_seeds=list(judge_seeds),
                                                summary=summary, rows=[{k: v for k, v in r.items() if k != "history"}
                                                                       for r in rows]))
    for name, s in summary.items():
        print("STRICT", name, f"AUC {s['mean_auc']:.3f}", s["auc"], flush=True)
    if devices != ["cpu"]:
        os.remove(data_path)
    return summary


def app_sources(inputs, device):
    """The app's RSH-GAN (PhysioMix) and RSR-Flow (PhysioFlow) generators, checked against the bundle's manifest (sha256,
    condition schema)."""
    bank = sj.ConditionsView(inputs.conditions, inputs.keep)
    app = json.loads((inputs.bundle/"manifest.json").read_text())
    sources = {}
    for name, slot in (("rsh_gan_app", "physiomix"), ("rsr_flow_app", "physioflow")):
        meta, entry = app[slot], app["models"][f"{slot}_generator"]
        if meta["domains"] != bank.domains or not np.allclose(meta["center"], bank.center, rtol=1e-5) \
                or not np.allclose(meta["scale"], bank.scale, rtol=1e-5):
            raise ValueError(f"{slot}: app condition schema differs from the v3 pack's")
        path = inputs.bundle/entry["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"{slot} checksum mismatch")
        sources[name] = sj.torchscript_generator(path, device, len(bank.domains)+5)
    return sources


def app_fidelity(root, output):
    """Feature tier only, on the same sets as judge(): the app's generators against the real_other_people reference, so
    they are compared on one measure (14 judge_physigpt features, validation people)."""
    output = Path(output)
    inputs = Inputs(root)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    bank = sj.ConditionsView(inputs.conditions, inputs.keep)
    sources = app_sources(inputs, device)
    arrays, info = sj.build_sets(inputs.pack, bank, sources, "validation", controls=("real_other_people",))
    fidelity = {name: fidelity_report(arrays["real_train"], arrays["real_eval"], arrays["real_other_people_eval"],
                                      arrays[f"{name}_train"], arrays[f"{name}_eval"]) for name in sources}
    output.mkdir(parents=True, exist_ok=True)
    save_json(output/"fidelity.json", dict(info=dict(counts=info["counts"]), fidelity=fidelity))
    for name, report in fidelity.items():
        g = report["generated"]
        print("FIDELITY", name, f"mean 1-KS {g['mean_similarity']:.3f} (real-vs-real "
              f"{report['real_other_people']['mean_similarity']:.3f}), relative {g['relative_similarity']:.3f}, "
              f"trees acc {g['classifier']['trees']['accuracy']:.3f}", flush=True)
    return fidelity


def domain_prompts(view, conditions, domain, n, rng):
    """View ids of n prompts, training windows of the domain, each person weighted equally as judge_physigpt.Real.draw.
    Drawn with replacement: a person's condition may repeat, the noise of the window does not."""
    rows = np.flatnonzero((view["split"] == "train") & (view["domain"] == domain))
    if not len(rows):
        raise ValueError(f"no training windows of {domain}")
    _, inverse, counts = np.unique(view["subject"][rows], return_inverse=True, return_counts=True)
    weight = 1/counts[inverse]
    ids = rng.choice(rows, n, p=weight/weight.sum())
    conditions.for_ids(ids)   # refuses anything but training rows
    return ids


def app_samples(root, output, domain="perform_large", seed=SELECT_SEED):
    """generated_<name>.npy (fit + inner + eval windows, float16, as judge_physigpt writes generated.npy) of the app's
    generators, prompted with the conditions of the domain's training people, known flags included; to be scored with
    judge_physigpt --mode features --generated. <name>_prompts.npz keeps each window's condition row and person."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    inputs = Inputs(root)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    sets = (("fit", SIZES["fit"], 1_000_000), ("inner", SIZES["inner"], 2_000_000), ("eval", SIZES["eval"], 3_000_000))
    record = dict(domain=domain, prompts="training people, person-balanced, Conditions.for_ids", device=device,
                  sets={k: n for k, n, _ in sets}, pack_sha256=inputs.manifest["windows_sha256"], models={})
    app = json.loads((inputs.bundle/"manifest.json").read_text())
    for name, generate in app_sources(inputs, device).items():
        rng = np.random.default_rng(seed)   # both generators see the same prompts
        slot = "physiomix" if name == "rsh_gan_app" else "physioflow"
        started = time.monotonic()
        ids = {k: domain_prompts(inputs.view, inputs.conditions, domain, n, rng) for k, n, _ in sets}
        fake = np.concatenate([generate(ids[k], inputs.conditions, s) for k, _, s in sets])
        np.save(output/f"generated_{name}.npy", fake.astype(np.float16))
        every = np.concatenate([ids[k] for k, _, _ in sets])
        np.savez_compressed(output/f"{name}_prompts.npz", condition=inputs.conditions.for_ids(every),
                            person=inputs.view["subject"][every], person_eval=inputs.view["subject"][ids["eval"]])
        record["models"][name] = dict(
            variant=app[slot]["variant"], arm=app[slot]["arm"], seed=app[slot]["seed"], best_step=app[slot]["best_step"],
            file=app["models"][f"{slot}_generator"]["file"], sha256=app["models"][f"{slot}_generator"]["sha256"],
            seconds=time.monotonic()-started, min=float(fake.min()), max=float(fake.max()),
            non_finite=int((~np.isfinite(fake)).sum()), generated_sha256=hashlib.sha256((output/f"generated_{name}.npy").read_bytes()).hexdigest())
        save_json(output/"app_samples.json", record)
        print("SAMPLED", name, record["models"][name], flush=True)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, help="holds the verified v3 pack and the app bundle")
    parser.add_argument("--output", required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS), help="one per device")
    parser.add_argument("--steps", type=int, default=6000)
    parser.add_argument("--hours", type=float, default=9., help="training time per seed")
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--anchor", type=int, default=64)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--d-lr", type=float, default=2e-4)
    parser.add_argument("--critic", default="judge", choices=("judge", "strict"),
                        help="judge: strict_judge.JudgeCritic, unconditional (v2); strict: conditioned StrictCritic (v1)")
    parser.add_argument("--d-steps", type=int, default=1, help="critic updates per step")
    parser.add_argument("--rt-gate", type=float, default=.2,
                        help="the generator moves only while the critic's rt (EMA) is at least this (-1: always)")
    parser.add_argument("--grad-steps", type=int, default=4, help="last Heun steps that carry the critic's gradient")
    parser.add_argument("--warmup", type=int, default=200, help="generator learning-rate warmup (generator updates)")
    parser.add_argument("--critic-warmup", type=int, default=300)
    parser.add_argument("--adv-weight", type=float, default=.5)
    parser.add_argument("--max-lambda", type=float, default=1., help="cap of the adaptive weight (v1: 1e4)")
    parser.add_argument("--gamma", type=float, default=0.,
                        help="R1/R2 weight (v1: 1, which kept the critic at chance; 0.01 already does on JudgeCritic)")
    parser.add_argument("--lazy", type=int, default=4)
    parser.add_argument("--clip", type=float, default=1.)
    parser.add_argument("--d-clip", type=float, default=10.)
    parser.add_argument("--ema", type=float, default=.999)
    parser.add_argument("--log-every", type=int, default=50)
    parser.add_argument("--eval-every", type=int, default=500)
    parser.add_argument("--patience", type=int, default=0,
                        help="stop a seed after this many evaluations in a row without a new best (0: no early stop)")
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--fidelity-only", action="store_true",
                        help="no training: feature tier of the app's RSH-GAN, RSR-Flow and LSM-GAN (app_fidelity)")
    parser.add_argument("--app-samples", action="store_true",
                        help="no training: the app generators' windows for judge_physigpt --mode features (app_samples)")
    parser.add_argument("--smoke", action="store_true", help="tiny judge (CPU tests)")
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args(argv)
    if args.patience < 0:
        parser.error("--patience must be 0 (off) or positive")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.fidelity_only:
        return app_fidelity(args.input_root, output)
    if args.app_samples:
        return app_samples(args.input_root, output)
    devices = torch.cuda.device_count() if torch.cuda.is_available() and not args.cpu else 1
    if len(args.seeds) > max(devices, 1) and devices > 1:
        raise ValueError(f"{len(args.seeds)} seeds on {devices} devices")
    if devices > 1 and len(args.seeds) > 1:
        torch.multiprocessing.spawn(train, args=(args.input_root, str(output), args), nprocs=len(args.seeds), join=True)
    else:
        for rank in range(len(args.seeds)):
            train(rank, args.input_root, str(output), args)
    if args.skip_judge:
        return None
    if args.smoke:
        sj.PER_DOMAIN_TRAIN, sj.PER_DOMAIN_INNER, sj.PER_DOMAIN_EVAL, sj.EVAL_EVERY = 16, 8, 8, 2
        sj.JUDGES["strict"].update(steps=4, batch=8)
    return judge(args.input_root, output, args.seeds, JUDGE_SEEDS[:1] if args.smoke else JUDGE_SEEDS)


if __name__ == "__main__":
    main()
