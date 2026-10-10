"""PhysioMix v2 round on the v3 data view: locked validation criterion, 2x2 pilot, frozen benchmark.

Stages: `pilot` trains P0-P4 (seed 42) and applies the pre-registered selection rule;
`final` retrains baselines, the v1 control and the selected v2 variant on three seeds, then
opens the sealed GXU finger test exactly once. Workers only ever receive train+validation.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import platform
import time

import numpy as np
from scipy.spatial.distance import cdist, pdist
from scipy.stats import wasserstein_distance
import torch
from torch.nn import functional as F

from ml.kaggle_lsm.train_lsm import LENGTH, mmd2, prepare_discriminator_for_generator, save_json
from ml.kaggle_multidomain import control
from ml.kaggle_multidomain.benchmark import MORPH_NAMES, cpu_latency, sample
from ml.kaggle_multidomain.data import balanced_indices, balanced_pool
from ml.kaggle_multidomain.data_gxu import load_input
from ml.kaggle_multidomain.experiment import QualityEvaluator
from ml.kaggle_multidomain.models import distribution_loss, networks
from ml.kaggle_multidomain.physio import (CROP_PAD, CleanDenoiser, ConditionedCritic, Conditions, DerivCritic,
                                        PhysioMix, PhysioMixH, PhysioMixR, clean_diffusion_loss, draw, ema_model,
                                        update_ema, view_mask)
from ml.kaggle_multidomain.train import train_one

PROTOCOL, VIEW = "ppg_physiomix_v3", "v3"
DATA_SHA256_V3 = "5036fb647d0460a00c388b29043b708f711c9627331cf2911cde7cbbce766433"  # ml/runs/physio3-data-v1/VERIFICATION.json
POOLS = {"gxu_finger": ["gxu_finger"], "perform_large": ["perform_large"], "bidmc": ["bidmc"],
         "perform_cohort": ["perform_af", "perform_non_af"], "wrist": ["wrist"]}
WEIGHTS = {"gxu_finger": .35, "perform_large": .25, "bidmc": .15, "perform_cohort": .15, "wrist": .10}
TRAIN_DOMAINS = {"bidmc", "perform_af", "perform_non_af", "perform_large", "wrist", "gxu_finger"}
ARMS = {"P0_physiomix_no_div_v3": dict(version="v1"), "P1_v2_lab": dict(version="v2"),
        "P2_v2_osc": dict(version="v2", osc=True), "P3_v2_dc": dict(version="v2", dc=True),
        "P4_v2_osc_dc": dict(version="v2", osc=True, dc=True),
        "physiomix_no_div": dict(version="v1"),
        "physiodiffusion": dict(version="v1", diffusion=True, guidance=1.5, sample_steps=32)}
# Round 4 (experiment_v4): lower cosine-decayed learning rate, then the drift and beat-timing fixes.
LOW_LR = dict(version="v2", osc=True, dc=True, lr=1e-4, schedule="cosine")
ARMS.update({"L1_v2_lr": LOW_LR, "L2_rel_lr": dict(LOW_LR, rel=True),
             "L3_rel_beat_lr": dict(LOW_LR, rel=True, beat=True),
             "L4_rel_beat_dom_lr": dict(LOW_LR, rel=True, beat=True, domloss=True)})
# Round 5 (experiment_v5): the round-4 winner with a cropped, non-circular output window.
ARMS.update({f"{arm}_crop": dict(ARMS[arm], rel=True, pad=CROP_PAD)
             for arm in ("L1_v2_lr", "L2_rel_lr", "L3_rel_beat_lr", "L4_rel_beat_dom_lr")})
PILOTS = ("P0_physiomix_no_div_v3", "P1_v2_lab", "P2_v2_osc", "P3_v2_dc", "P4_v2_osc_dc")
COMPLEXITY = {"P1_v2_lab": 1, "P2_v2_osc": 2, "P3_v2_dc": 2, "P4_v2_osc_dc": 3}
BASELINES = ("lsm_multi", "hybrid_multi")
CRITERION = """PhysioMix v2 locked validation criterion (train/validation only; GXU test sealed).
Pools/weights: gxu_finger .35, perform_large .25, bidmc .15, perform_cohort(af+non_af) .15, wrist .10.
Q_d = MMD2_acf + MMD2_logpsd + MMD2_morph + 0.5(1-recall_d) + 0.25(1-precision_d), domain-prompted from TRAIN banks,
n_d = min(256, validation windows), references subject-balanced (rng 9001).
S_real = sum w_d Q_d + 0.25|ln rho|, rho = median pdist(fakes)/median pdist(domain-matched train replay, rng 2109).
C = 0.5 min(MAE_in/10,2) + 0.25 min(MAE_ext/10,2) + 0.25(1-Spearman) + 0.25(1-AUC_irr), HR grid 40..180 step 10.
Checkpoint (every 500 from 1000): conditional GAN S_real + 0.5C; diffusion S_real; unconditional legacy mixture.
Arm score with fresh seed (+30000): S_arm = S_real + 0.5C + 0.5 max(0, AUC_c2st_derivative - 0.5).
Gates: finite, no flat output, no nonfinite loss, d_clipped <= 1% of steps, rho in [0.75, 1.25], trace assert_close,
x86 1-thread latency < 50 ms. Non-inferiority: S_real <= S_real(P0) + 0.05.
Pilot winner: argmin S_arm over eligible P1-P4; within 0.02 prefer fewer changes (P1 < P2 = P3 < P4), then lower AUC;
none eligible -> P1. Final claim only if the mean S_arm gap exceeds the pooled seed SD and non-inferiority holds."""
CRITERION_SHA256 = hashlib.sha256(CRITERION.encode()).hexdigest()
# Budget knobs fixed by the criterion; tests shrink them for CPU smoke runs only.
CONTROL_N, C2ST_TRAIN, C2ST_VALID, C2ST_STEPS = 8, 2048, 512, 1000
_CONDITIONS = {}


def config(arm, frozen=None):
    if arm == "physiomix_v2":
        if not frozen or "physiomix_v2" not in frozen.get("aliases", {}):
            raise ValueError("physiomix_v2 needs the frozen pilot selection")
        arm = frozen["aliases"]["physiomix_v2"]
    return {**dict(diffusion=False, osc=False, dc=False, guidance=1., sample_steps=32, lr=2e-4, schedule=None,
                   rel=False, beat=False, domloss=False, pad=0), **ARMS[arm]}


def conditions_for(pack, version):
    key = (id(pack), version)
    if key not in _CONDITIONS:
        _CONDITIONS[key] = Conditions(pack, version)
    return _CONDITIONS[key]


def build(cfg, conditions):
    size = conditions.bank.shape[1]
    if cfg["diffusion"]:
        return CleanDenoiser(size), None
    if cfg.get("rel"):
        generator = PhysioMixR(size, conditions.center, conditions.scale, view=VIEW, beat=cfg.get("beat", False),
                               pad=cfg.get("pad", 0))
    else:
        generator = (PhysioMixH if cfg["osc"] else PhysioMix)(size, conditions.center, conditions.scale, view=VIEW)
    return generator, (DerivCritic if cfg["dc"] else ConditionedCritic)(size)


def sampler(model, cfg, device):
    """(z, condition rows) -> (n, LENGTH) numpy, chunked; works for every conditional arm."""
    @torch.no_grad()
    def run(z, condition):
        condition = torch.as_tensor(np.asarray(condition, dtype=np.float32), device=device)
        parts = [draw(model, a.to(device), b, cfg["diffusion"], cfg["guidance"], cfg["sample_steps"], VIEW)
                 for a, b in zip(z.split(64), condition.split(64))]
        return torch.cat(parts).cpu().numpy()[:, 0]
    return run


def learning_rate(cfg, step, steps):
    """Constant, or cosine-decayed to 10% of the initial rate at the last step."""
    if cfg.get("schedule") != "cosine":
        return cfg["lr"]
    return cfg["lr"]*(.1+.45*(1+math.cos(math.pi*min(step, steps)/steps)))


def domain_distribution_loss(fake, real, domain):
    """distribution_loss inside each domain of the batch: a mixed batch can match the pooled spectra
    while one small domain stays narrow."""
    total, count = fake.new_zeros(()), 0
    for d in domain.unique():
        rows = domain == d
        n = int(rows.sum())
        if n >= 3:
            total = total+n*distribution_loss(fake[rows], real[rows])
            count += n
    return total/max(count, 1)


def pr_metrics(fake, real):
    """k=5 feature precision/recall, two-sample 1-NN and per-feature Wasserstein (train-standardized)."""
    rr, ff, rf = cdist(real, real), cdist(fake, fake), cdist(real, fake)
    np.fill_diagonal(rr, np.inf)
    np.fill_diagonal(ff, np.inf)
    k = min(5, len(fake)-1, len(real)-1)
    radius_r, radius_f = np.partition(rr, k-1, 1)[:, k-1], np.partition(ff, k-1, 1)[:, k-1]
    both = np.r_[real, fake]
    dist = cdist(both, both)
    np.fill_diagonal(dist, np.inf)
    labels = np.r_[np.zeros(len(real)), np.ones(len(fake))]
    return dict(precision=float((rf <= radius_r[:, None]).any(0).mean()),
                recall=float((rf <= radius_f[None, :]).any(1).mean()),
                one_nn=float((labels[dist.argmin(1)] == labels).mean()),
                wasserstein={n: float(wasserstein_distance(fake[:, i], real[:, i])) for i, n in enumerate(MORPH_NAMES)})


class PromptedEvaluator(QualityEvaluator):
    """Domain-prompted pools on validation; train replay floors are reported, never subtracted."""
    def __init__(self, pack, n=256):
        super().__init__(pack, 128)
        self.pools = {}
        for name, domains in POOLS.items():
            ids, weights = balanced_pool(pack, "validation", domains)
            count = min(n, len(ids))
            reference = np.random.default_rng(9001).choice(ids, count, replace=False, p=weights)
            replay = pack["signal"][balanced_indices(pack, "train", np.random.default_rng(2109), count, domains)]
            self.pools[name] = dict(domains=domains, n=count, reference_ids=reference,
                                    reference=self.blocks(pack["signal"][reference]), replay=replay)
        replay = np.concatenate([p["replay"] for p in self.pools.values()])
        self.replay_spread = float(np.median(pdist(self.blocks(replay)[2])))

    def pool_quality(self, fake, reference_blocks):
        blocks = self.blocks(fake)
        mmd = [mmd2(a, b, bw) for a, b, bw in zip(blocks, reference_blocks, self.bandwidths)]
        result = dict(acf_mmd2=mmd[0], log_psd_mmd2=mmd[1], morphology_mmd2=mmd[2], total_mmd=float(sum(mmd)),
                      **pr_metrics(blocks[2], reference_blocks[2]))
        result["Q"] = result["total_mmd"]+.5*(1-result["recall"])+.25*(1-result["precision"])
        return result, blocks[2]

    def prompts(self, conditions, name, seed_offset=0):
        pool = self.pools[name]
        index = list(POOLS).index(name)
        ids = balanced_indices(self.pack, "train", np.random.default_rng(4242+index+seed_offset), pool["n"], pool["domains"])
        return conditions.for_ids(ids)

    def s_real(self, run, conditions, seed):
        per_pool, features = {}, []
        for i, name in enumerate(POOLS):
            prompts = self.prompts(conditions, name)
            z = torch.randn(len(prompts), LENGTH, generator=torch.Generator().manual_seed(seed+i))
            fake = run(z, prompts)
            per_pool[name], morph = self.pool_quality(fake, self.pools[name]["reference"])
            features.append(morph)
        rho = float(np.median(pdist(np.concatenate(features))))/max(self.replay_spread, 1e-8)
        score = sum(WEIGHTS[n]*per_pool[n]["Q"] for n in POOLS)+.25*abs(math.log(max(rho, 1e-6)))
        return dict(S_real=float(score), rho=rho, pools=per_pool)

    def floors(self):
        return {name: self.pool_quality(pool["replay"], pool["reference"])[0] for name, pool in self.pools.items()}


def c2st(evaluator, run, conditions, seed, device, derivative=True, width=16):
    pack = evaluator.pack
    per_pool = {n: math.ceil(C2ST_TRAIN/len(POOLS)) for n in POOLS}
    real_train, prompts = [], []
    for i, (name, domains) in enumerate(POOLS.items()):
        real_train.append(pack["signal"][balanced_indices(pack, "train", np.random.default_rng(7001+i), per_pool[name], domains)])
        prompts.append(conditions.for_ids(balanced_indices(pack, "train", np.random.default_rng(7101+i), per_pool[name], domains)))
    prompts = np.concatenate(prompts)
    fake_train = run(torch.randn(len(prompts), LENGTH, generator=torch.Generator().manual_seed(seed)), prompts)
    real_valid = np.concatenate([pack["signal"][balanced_indices(pack, "validation", np.random.default_rng(7002+i),
                                                                 math.ceil(C2ST_VALID/len(POOLS)), d)] for i, d in enumerate(POOLS.values())])
    valid_prompts = np.concatenate([evaluator.prompts(conditions, n, 500)[:math.ceil(C2ST_VALID/len(POOLS))] for n in POOLS])
    fake_valid = run(torch.randn(len(valid_prompts), LENGTH, generator=torch.Generator().manual_seed(seed+1)), valid_prompts)
    return control.c2st_auc(np.concatenate(real_train), fake_train, real_valid, fake_valid, device, derivative, width,
                            C2ST_STEPS)


def deployment_gates(model, conditions):
    model = model.cpu().eval()
    z, c = torch.randn(2, LENGTH), torch.tensor(conditions.prompt(conditions.domains[0], 75., .02, 2))
    traced = torch.jit.trace(model, (z, c))
    for n, bpm, sigma in ((1, 45., .02), (2, 130., .2), (5, 175., .1)):
        z = torch.randn(n, LENGTH)
        c = torch.tensor(conditions.prompt(conditions.domains[-1], bpm, sigma, n))
        torch.testing.assert_close(traced(z, c), model(z, c))
    torch.set_num_threads(1)
    z, c = torch.randn(1, LENGTH), torch.tensor(conditions.prompt(conditions.domains[0], 80., .02, 1))
    with torch.no_grad():
        for _ in range(3):
            traced(z, c)
        times = []
        for _ in range(20):
            start = time.perf_counter()
            traced(z, c)
            times.append((time.perf_counter()-start)*1000)
    return traced, dict(median_ms=float(np.median(times)), p95_ms=float(np.quantile(times, .95)),
                        cpu_threads=1, hardware_scope="Kaggle host CPU; Pi not measured")


def train_conditional(arm, seed, pack, evaluator, output, steps, batch, interval, device, frozen):
    cfg = config(arm, frozen)
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    cuda = torch.device(device).type == "cuda"
    if cuda:
        torch.cuda.reset_peak_memory_stats(device)
    conditions = conditions_for(pack, cfg["version"])
    g, d = build(cfg, conditions)
    g.to(device)
    if d is not None:
        d.to(device)
    ema, diffusion = ema_model(g), cfg["diffusion"]
    optg = torch.optim.Adam(g.parameters(), lr=cfg["lr"], betas=(0., .99))
    optd = torch.optim.Adam(d.parameters(), lr=cfg["lr"], betas=(0., .99)) if d is not None else None
    run_dir = Path(output)/f"{arm}_seed{seed}"
    run_dir.mkdir()
    save_json(run_dir/"conditions.json", conditions.metadata())
    ids, weights = balanced_pool(pack, "train")
    domains = len(conditions.domains)
    center = torch.tensor(conditions.center, device=device)
    scale = torch.tensor(conditions.scale, device=device)
    best, best_step, history = float("inf"), 0, []
    stability = dict(updates=steps, nonfinite_losses=0, g_clipped=0, d_clipped=0, max_g_grad_norm=0.,
                     max_d_grad_norm=0., r1_updates=0)
    start = time.monotonic()
    for step in range(1, steps+1):
        g.train()
        for optimizer in (optg, optd):
            for group in getattr(optimizer, "param_groups", ()):
                group["lr"] = learning_rate(cfg, step-1, steps)
        chosen = rng.choice(ids, batch, p=weights)
        real = torch.tensor(pack["signal"][chosen, None], device=device)
        c = torch.tensor(conditions.for_ids(chosen), device=device)
        optg.zero_grad(set_to_none=True)
        ld, r1, margin = (real.new_zeros(()) for _ in range(3))
        if diffusion:
            lg = clean_diffusion_loss(g, real, c, True, VIEW)
        else:
            d.train().requires_grad_(True)
            fake = g(torch.randn(batch, LENGTH, device=device), c)
            optd.zero_grad(set_to_none=True)
            regularize = step % 16 == 0
            real.requires_grad_(regularize)
            pr, pf = d(real, c), d(fake.detach(), c)
            shifted = c.roll(1, 0)
            wrong = F.relu(1+d(real, shifted)).mean(1)
            if cfg["version"] == "v2":
                # Only genuinely mismatched pairs are negatives: another domain, or both rates known and >10 bpm apart.
                rate = c[:, -3]*scale[0]+center[0]
                known = (c[:, domains] > .5) & (shifted[:, domains] > .5)
                mask = ((c[:, :domains].argmax(1) != shifted[:, :domains].argmax(1)) |
                        (known & ((rate-rate.roll(1, 0)).abs() > 10))).float()
                wrong_term = (wrong*mask).sum()/mask.sum().clamp_min(1)
            else:
                wrong_term = wrong.mean()
            ld = F.relu(1-pr).mean()+.5*F.relu(1+pf).mean()+.5*wrong_term
            margin = (pr.mean()-pf.mean()).detach()
            if regularize:
                grad = torch.autograd.grad(pr.mean(1).sum(), real, create_graph=True)[0]
                r1 = .5*16*grad.square().flatten(1).sum(1).mean()
                ld = ld+r1
                stability["r1_updates"] += 1
            ld.backward()
            dn = torch.nn.utils.clip_grad_norm_(d.parameters(), 10, error_if_nonfinite=True)
            stability["max_d_grad_norm"] = max(stability["max_d_grad_norm"], float(dn))
            stability["d_clipped"] += int(dn > 10)
            optd.step()
            real = real.detach()
            prepare_discriminator_for_generator(d)
            lg = -d(fake, c).mean()+.5*distribution_loss(fake, real)
            if cfg.get("domloss"):
                lg = lg+.5*domain_distribution_loss(fake, real, c[:, :domains].argmax(1))
        if not torch.isfinite(lg+ld):
            raise RuntimeError(f"Nonfinite objective: {arm}/{seed}/{step}")
        lg.backward()
        gn = torch.nn.utils.clip_grad_norm_(g.parameters(), 10, error_if_nonfinite=True)
        stability["max_g_grad_norm"] = max(stability["max_g_grad_norm"], float(gn))
        stability["g_clipped"] += int(gn > 10)
        optg.step()
        update_ema(ema, g)
        if (step >= min(1000, steps) and step % interval == 0) or step == steps:
            ema.eval()
            run = sampler(ema, cfg, device)
            real_score = evaluator.s_real(run, conditions, seed+10000)
            ctrl = control.controllability(run, conditions, CONTROL_N)
            value = real_score["S_real"]+(0 if diffusion else .5*ctrl["C"])
            row = dict(step=step, loss_g=float(lg.detach()), loss_d=float(ld.detach()), r1=float(r1.detach()),
                       critic_margin=float(margin), g_grad_norm=float(gn), checkpoint_score=value,
                       S_real=real_score["S_real"], rho=real_score["rho"], C=ctrl["C"],
                       control={k: ctrl[k] for k in ("mae_in", "mae_ext", "spearman", "auc_irr", "lock_rate")},
                       pools={n: {k: v["Q"] if k == "Q" else v[k] for k in ("Q", "total_mmd", "precision", "recall")}
                              for n, v in real_score["pools"].items()},
                       d_clipped=stability["d_clipped"], seconds=time.monotonic()-start)
            history.append(row)
            if value < best:
                best, best_step = value, step
                torch.save(dict(generator=ema.state_dict(), arm=arm, seed=seed, step=step, checkpoint_score=value,
                                config=cfg), run_dir/"best.pt")
            save_json(run_dir/"history.json", history)
            print(arm, seed, json.dumps({k: row[k] for k in ("step", "checkpoint_score", "S_real", "C", "rho")}), flush=True)
    torch.save(dict(generator=g.state_dict(), ema=ema.state_dict(), discriminator=d.state_dict() if d else None,
                    arm=arm, seed=seed, step=steps), run_dir/"last_training_state.pt")
    result = dict(arm=arm, seed=seed, best_step=best_step, checkpoint_score=best, config=cfg,
                  training_seconds=time.monotonic()-start, generator_parameters=sum(p.numel() for p in g.parameters()),
                  training_device=str(device), worker_pid=os.getpid(), stability=stability,
                  peak_cuda_bytes=torch.cuda.max_memory_allocated(device) if cuda else 0)
    result.update(score_arm(arm, seed, pack, evaluator, run_dir, device, frozen, steps))
    save_json(run_dir/"training_result.json", result)
    return result


def load_best(arm, run_dir, conditions, frozen, device):
    cfg = config(arm, frozen)
    model, _ = build(cfg, conditions)
    model.load_state_dict(torch.load(run_dir/"best.pt", map_location="cpu", weights_only=True)["generator"])
    return model.to(device).eval(), cfg


def score_arm(arm, seed, pack, evaluator, run_dir, device, frozen, steps):
    """Fresh-seed arm score at the chosen checkpoint plus every hard gate (validation only)."""
    cfg = config(arm, frozen)
    conditions = conditions_for(pack, cfg["version"])
    model, cfg = load_best(arm, run_dir, conditions, frozen, device)
    run = sampler(model, cfg, device)
    real_score = evaluator.s_real(run, conditions, seed+30000)
    ctrl = control.controllability(run, conditions, CONTROL_N, seed=seed+30000)
    auc = c2st(evaluator, run, conditions, seed+31000, device)
    stats = json.loads((run_dir/"history.json").read_text())
    prompts = evaluator.prompts(conditions, "gxu_finger")[:64]
    probe = run(torch.randn(len(prompts), LENGTH, generator=torch.Generator().manual_seed(seed+32000)), prompts)
    gates = dict(finite=bool(np.isfinite(probe).all()), flat=bool((np.ptp(probe, axis=1) < 1e-6).any()),
                 rho_ok=.75 <= real_score["rho"] <= 1.25,
                 d_clipped_ok=(stats[-1].get("d_clipped", 0) <= .01*steps))
    latency = None
    if not cfg["diffusion"]:
        try:
            traced, latency = deployment_gates(model, conditions)
            traced.save(str(run_dir/"generator_cpu.ts"))
            gates["trace_ok"] = True
        except (RuntimeError, AssertionError) as error:
            gates["trace_ok"] = False
            gates["trace_error"] = str(error)[:300]
        gates["latency_ok"] = bool(latency and latency["median_ms"] < 50)
    eligible = gates["finite"] and not gates["flat"] and gates["rho_ok"] and gates["d_clipped_ok"] and \
        gates.get("trace_ok", True) and gates.get("latency_ok", True)
    return dict(S_arm=real_score["S_real"]+.5*ctrl["C"]+.5*max(0, auc-.5), S_real_fresh=real_score["S_real"],
                C_fresh=ctrl["C"], c2st_derivative_auc=auc, control=ctrl, prompted_validation=real_score,
                gates=gates, eligible=bool(eligible), latency=latency)


def worker(device, jobs, input_root, output, steps, batch, interval, n, frozen, threads=2):
    torch.set_num_threads(threads)
    if device.startswith("cuda"):
        torch.cuda.set_device(device)
    pack, _ = load_input(input_root, PROTOCOL)
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    evaluator = PromptedEvaluator(development, n)
    print("WORKER", device, os.getpid(), jobs, flush=True)
    rows = []
    for arm, seed in jobs:
        if arm in BASELINES:
            row = train_one(arm, seed, development, evaluator, Path(output), steps, batch, interval, device)
        else:
            row = train_conditional(arm, seed, development, evaluator, output, steps, batch, interval, device, frozen)
        rows.append(row)
    return rows


def parallel(jobs, devices, input_root, output, steps, batch, interval, n, frozen, threads=2):
    Path(output).mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    if devices == ["cpu"]:
        rows = worker("cpu", jobs, input_root, output, steps, batch, interval, n, frozen, threads)
    else:
        rows = []
        with ProcessPoolExecutor(max_workers=len(devices), mp_context=multiprocessing.get_context("spawn")) as pool:
            futures = [pool.submit(worker, device, jobs[i::len(devices)], input_root, output, steps, batch,
                                   interval, n, frozen, threads) for i, device in enumerate(devices)]
            for future in as_completed(futures):
                rows.extend(future.result())
                save_json(Path(output)/"selection_progress.json", rows)
    by_job = {(r["arm"], r["seed"]): r for r in rows}
    if set(by_job) != set(jobs) or len(rows) != len(jobs):
        raise RuntimeError("Missing or duplicate training runs")
    ordered = [by_job[job] for job in jobs]
    save_json(Path(output)/"training_execution.json", dict(
        wall_seconds=time.monotonic()-start, workers=len(devices), steps=steps,
        allocated_gpus=[torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],
        threads_per_worker=threads, cpu_count=os.cpu_count(), runs=ordered))
    return ordered


def select_pilot(rows):
    """The pre-registered rule; it reads validation-derived fields only."""
    by_arm = {r["arm"]: r for r in rows}
    control_row = by_arm["P0_physiomix_no_div_v3"]
    limit = control_row["S_real_fresh"]+.05
    candidates = [dict(arm=a, S_arm=by_arm[a]["S_arm"], auc=by_arm[a]["c2st_derivative_auc"],
                       eligible=by_arm[a]["eligible"] and by_arm[a]["S_real_fresh"] <= limit,
                       non_inferior=by_arm[a]["S_real_fresh"] <= limit, gates=by_arm[a]["gates"])
                  for a in COMPLEXITY]
    eligible = [c for c in candidates if c["eligible"]]
    if not eligible:
        winner, reason = "P1_v2_lab", "no eligible variant; fallback rule"
    else:
        best = min(c["S_arm"] for c in eligible)
        near = [c for c in eligible if c["S_arm"] <= best+.02]
        near.sort(key=lambda c: (COMPLEXITY[c["arm"]], c["auc"], c["S_arm"]))
        winner, reason = near[0]["arm"], "argmin S_arm with 0.02 tie margin, fewer changes, lower AUC"
    return dict(winner=winner, reason=reason, control_S_real=control_row["S_real_fresh"],
                non_inferiority_limit=limit, candidates=candidates, criterion_sha256=CRITERION_SHA256)


def sealed_subjects(pack):
    subjects = sorted(set(pack["subject"][(pack["domain"] == "gxu_finger") & (pack["split"] == "test")]))
    return hashlib.sha256("\n".join(subjects).encode()).hexdigest(), len(subjects)


def check_pack(pack, manifest, allow_cpu):
    if not allow_cpu and manifest["windows_sha256"] != DATA_SHA256_V3:
        raise ValueError("Use the independently verified v3 pack")
    if manifest.get("view") != VIEW:
        raise ValueError("Pack view must be v3")
    for split in ("train", "validation", "test"):
        if set(pack["domain"][pack["split"] == split]) != TRAIN_DOMAINS:
            raise ValueError(f"Missing domains in {split}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stage", choices=("pilot", "final"), required=True)
    parser.add_argument("--pilot-root", help="Directory holding PILOT_SELECTION.json for the final stage")
    parser.add_argument("--steps", type=int, default=6000)
    parser.add_argument("--pilot-steps", type=int, default=3000)
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 2026])
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--interval", type=int, default=500)
    parser.add_argument("--eval-samples", type=int, default=256)
    parser.add_argument("--bootstrap", type=int, default=200)
    parser.add_argument("--time-limit", type=float, default=9600.)
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and (len(names) != 2 or any("T4" not in name for name in names)):
        raise RuntimeError(f"Two T4 GPUs required, allocated {names}")
    devices = ["cpu"] if a.allow_cpu else ["cuda:0", "cuda:1"]
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    seal, sealed_count = sealed_subjects(pack)
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    save_json(output/"FROZEN_CRITERION.json", dict(text=CRITERION, sha256=CRITERION_SHA256))
    save_json(output/"data_manifest.json", manifest)
    save_json(output/"configuration.json", dict(args=vars(a), python=platform.python_version(), torch=torch.__version__,
              allocated_gpus=names, training_workers=len(devices), data_sha256=manifest["windows_sha256"], view=VIEW,
              criterion_sha256=CRITERION_SHA256, gxu_test_subject_sha256=seal, gxu_test_subjects=sealed_count))
    if a.stage == "pilot":
        rows = parallel([(arm, 42) for arm in PILOTS], devices, a.input_root, output/"pilot", a.pilot_steps,
                        a.batch, a.interval, a.eval_samples, None)
        selection = select_pilot(rows)
        save_json(output/"PILOT_SELECTION.json", selection)
        save_json(output/"COMPLETE.json", dict(status="pilot_complete", winner=selection["winner"],
                  pilot_runs=len(rows), data_sha256=manifest["windows_sha256"], wall_seconds=time.monotonic()-started))
        print("PILOT COMPLETE", selection["winner"], flush=True)
        return
    pilot = json.loads(next(Path(a.pilot_root).rglob("PILOT_SELECTION.json")).read_text())
    if pilot["criterion_sha256"] != CRITERION_SHA256:
        raise ValueError("Pilot used a different criterion")
    arms = list(BASELINES)+["physiomix_no_div", "physiodiffusion", "physiomix_v2"]
    frozen = dict(arms=arms, aliases={"physiomix_v2": pilot["winner"]}, seeds=a.seeds, steps=a.steps, batch=a.batch,
                  criterion_sha256=CRITERION_SHA256, gxu_test_subject_sha256=seal, pilot_selection=pilot,
                  holdout_rule="GXU test opened once after this file; old test/external splits exploratory only")
    save_json(output/"FROZEN_PROTOCOL.json", frozen)
    rows = parallel([(arm, seed) for arm in arms for seed in a.seeds], devices, a.input_root, output/"benchmark",
                    a.steps, a.batch, a.interval, a.eval_samples, frozen)
    from ml.kaggle_multidomain.evaluate_v3 import evaluate_frozen
    results = evaluate_frozen(rows, pack, output/"benchmark", frozen, devices[0], a.bootstrap, a.eval_samples)
    from ml.kaggle_multidomain.report_v3 import report
    report(output, results, frozen)
    save_json(output/"COMPLETE.json", dict(status="complete", trained_runs=len(rows), winner_alias=pilot["winner"],
              data_sha256=manifest["windows_sha256"], wall_seconds=time.monotonic()-started, deployment="research_only"))
    print("COMPLETE", pilot["winner"], flush=True)


if __name__ == "__main__":
    main()
