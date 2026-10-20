"""Round 11: PhysioFlow-2, a paired infrared/red generator (flow2), pilot of two backbones then a 3-seed final.

One kernel runs the whole round under RULE_11, which is fixed here before training and reads validation data only:
pilot (seed 42) of the U-Net (U2) and the diffusion transformer (T2) on the two GPUs, the pilot rule picks one, the
final trains it at seeds 123 and 2026 and the decisions D1 and D2 are written. Test splits are not opened here.

Infrared is scored exactly as in rounds 3-10 (locked criterion S_real, C, derivative C2ST -> S_arm, prompted
validation pools, gates) through flow2.InfraredView, so S_arm is comparable with PhysioMix round 9 and PhysioFlow F6.
Red is scored on the validation windows that have red (FINGER and PTT): the error of the generated ratio of ratios
against the prompted one, and a two-channel C2ST against the real (infrared, red) windows, next to the same C2ST for
an infrared copy, red = R x (infrared - mean), which is what the app does today with its fixed ratio.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import math
import multiprocessing
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ml.kaggle_lsm.train_lsm import LENGTH, save_json
from ml.kaggle_multidomain import control
from ml.kaggle_multidomain.data import balanced_indices, balanced_pool
from ml.kaggle_multidomain.data_dual import PROTOCOL, load_dual
from ml.kaggle_multidomain.experiment_v3 import (CONTROL_N, CRITERION_SHA256, TRAIN_DOMAINS, PromptedEvaluator, c2st,
                                                 learning_rate)
from ml.kaggle_multidomain.flow import real_scaffolds
from ml.kaggle_multidomain.flow2 import DOMAIN_SLOTS, DualConditions, DualFlowGenerator, InfraredView, dual_flow_loss
from ml.kaggle_multidomain.labels import robust_labels
from ml.kaggle_multidomain.physio import ema_model, update_ema

ARMS = {"U2": dict(backbone="unet"), "T2": dict(backbone="dit")}
RECIPE = dict(lr=3e-4, schedule="cosine", steps=20000, batch=128, interval=2000, warmup=500, sample_steps=16,
              deriv=1., spectral=.1, t_dist="uniform", cond_drop=.1, scaffold_drop=.15, latency_limit_ms=5000.)
PILOT_SEED, FINAL_SEEDS = 42, (123, 2026)
RED_DOMAINS = ("gxu_finger", "ptt_sit", "ptt_walk", "ptt_run")
RED_TRAIN_N, RED_VALID_N, RED_C2ST_STEPS = 512, 256, 600
# Incumbents on the same locked criterion (validation, three seeds): PhysioFlow F6 (research mode) and PhysioMix R9
# (app default), from docs/physioflow/rules/DECISION_ROUND10.json and the round-9 decision.
F6 = dict(S_arm=(0.4750, 0.4998, 0.4719), S_real=None)
R9 = dict(S_arm_mean=0.52985, S_arm_sd=0.02928, S_real_mean=0.34375)
LIMITS = dict(R_mae=.05, S_arm_abs=.559, wrist_Q=.587, S_real_margin=.05, tie=.02)
RULE_11 = (
    f"Round 11 (PhysioFlow-2), fixed before training. Pack {PROTOCOL}. Arms U2 (two-channel U-Net) and T2 (DiT-1D), "
    "recipe: uniform flow times, first-difference weight 1 and stop-band log-PSD weight 0.1 on each channel, red terms "
    "only where red is known, 20000 steps, batch 128, AdamW 3e-4 with cosine decay, 16 Heun steps; checkpoints every "
    "2000 steps on infrared S_real + 0.5C. Gates: finite, not flat, rho in [0.75, 1.25], TorchScript agreement, "
    "single-thread latency < 5000 ms. Pilot (seed 42): an arm is eligible if it passes every gate and the median "
    f"|R_generated - R_prompted| on the red validation windows is <= {LIMITS['R_mae']}; the winner is the eligible arm "
    f"with the lowest S_arm, U2 within {LIMITS['tie']}; with no eligible arm the round stops. Final: the winner at "
    "seeds 123 and 2026 plus the pilot seed. D1 (the two-channel model replaces PhysioFlow F6 as the research mode): "
    "every seed eligible; seed-mean S_arm <= F6 mean + pooled SD; seed-mean wrist-exercise Q <= 0.587; seed-mean "
    "two-channel 'indistinguishable' on the red validation windows exceeds the infrared-copy baseline's by more than "
    "2 x max(seed SD of the model, seed SD of the copy). D2 (the two-channel model replaces PhysioMix R9 as the app "
    "default): D1 and the R9 rule of round 10: S_arm gap to R9 > pooled SD, seed-mean S_real <= R9 S_real + 0.05, "
    "seed-mean S_arm <= 0.559. Shipped seed: the eligible seed with the lowest S_arm. Validation only; test splits "
    "are not used.")


def evaluation_view(pack):
    """The pack as the locked criterion saw it in rounds 3-10: only the six original datasets take part (the others
    are marked 'excluded'), with row indices unchanged so condition lookups still match. The evaluator's
    standardisation, bandwidths and pools are then the round-10 ones."""
    view = dict(pack)
    view["split"] = np.where(np.isin(pack["domain"], sorted(TRAIN_DOMAINS)), pack["split"], "excluded")
    return view


class CriterionDomains:
    """Controllability over the six original datasets only, as in rounds 3-10."""
    def __init__(self, conditions):
        self.domains = [d for d in conditions.domains if d in TRAIN_DOMAINS]
        self.prompt = conditions.prompt


def run_ir(model, device):
    """(z, condition rows) -> (n, LENGTH) numpy infrared, chunked, as experiment_v3.sampler."""
    view = InfraredView(model)

    @torch.no_grad()
    def run(z, condition):
        condition = torch.as_tensor(np.asarray(condition, dtype=np.float32), device=device)
        return torch.cat([view(a.to(device), b) for a, b in zip(z.split(64), condition.split(64))]).cpu().numpy()[:, 0]
    return run


def run_pair(model, device):
    @torch.no_grad()
    def run(z, condition):
        condition = torch.as_tensor(np.asarray(condition, dtype=np.float32), device=device)
        return torch.cat([model(a.to(device), b) for a, b in zip(z.split(64), condition.split(64))]).cpu().numpy()
    return run


class PairProbe(nn.Module):
    """The derivative C2ST probe on two channels: (infrared, red) and their first and second differences."""
    def __init__(self, width=16):
        super().__init__()
        self.net = nn.Sequential(nn.Conv1d(6, width, 7, 2, 3), nn.LeakyReLU(.2), nn.Conv1d(width, 2*width, 7, 2, 3),
                                 nn.LeakyReLU(.2), nn.Conv1d(2*width, 2*width, 7, 2, 3), nn.LeakyReLU(.2))
        self.head = nn.Linear(2*width, 1)

    def forward(self, x):
        d1 = 10*F.pad(torch.diff(x, dim=-1), (1, 0))
        d2 = 20*F.pad(torch.diff(x, n=2, dim=-1), (1, 1))
        return self.head(self.net(torch.cat((x, d1, d2), 1)).mean(-1))[:, 0]


def pair_c2st(real_train, fake_train, real_valid, fake_valid, device, steps=RED_C2ST_STEPS, seed=0):
    torch.manual_seed(seed)
    probe = PairProbe().to(device)
    optimizer = torch.optim.Adam(probe.parameters(), lr=1e-3)
    rng = np.random.default_rng(seed)
    tensor = lambda a: torch.tensor(np.asarray(a, np.float32), device=device)
    real_train, fake_train = tensor(real_train), tensor(fake_train)
    for _ in range(steps):
        r, f = real_train[rng.integers(len(real_train), size=32)], fake_train[rng.integers(len(fake_train), size=32)]
        logits = probe(torch.cat((r, f)))
        target = torch.cat((torch.zeros(32, device=device), torch.ones(32, device=device)))
        optimizer.zero_grad(set_to_none=True)
        F.binary_cross_entropy_with_logits(logits, target).backward()
        optimizer.step()
    probe.eval()
    with torch.no_grad():
        rs = torch.cat([probe(p) for p in tensor(real_valid).split(256)]).cpu().numpy()
        fs = torch.cat([probe(p) for p in tensor(fake_valid).split(256)]).cpu().numpy()
    return control.auc(rs, fs)


def red_prompts(pack, conditions, ids):
    """Condition rows for real windows with red: their domain, ECG reference rate (else PPG consensus), the domain's
    default irregularity and their own R. Validation windows are not in the training-only bank, so rows are built."""
    rate, _, _ = robust_labels(pack["signal"][ids])
    reference = pack["reference_hr_bpm"][ids]
    rate = np.where(np.isfinite(reference), reference, rate)
    rows = []
    for i, r, ratio in zip(ids, rate, pack["ratio_r"][ids]):
        domain = str(pack["domain"][i])
        bpm = float(np.clip(r if np.isfinite(r) else 75., 40., 180.))
        rows.append(conditions.prompt(domain, bpm, conditions.defaults[domain][0], 1, float(ratio))[0])
    return np.asarray(rows, np.float32)


def red_metrics(model, pack, conditions, device, seed):
    """R error and two-channel C2ST of the model and of the infrared copy, on validation windows with red."""
    run = run_pair(model, device)
    out = {}
    pairs = lambda ids: np.stack((pack["signal"][ids], pack["red"][ids]), 1)
    train_ids = balanced_indices(pack, "train", np.random.default_rng(8101), RED_TRAIN_N, list(RED_DOMAINS))
    train_ids = train_ids[pack["red_known"][train_ids]]
    valid_pool = np.flatnonzero((pack["split"] == "validation") & np.isin(pack["domain"], RED_DOMAINS) & pack["red_known"])
    valid_ids = np.random.default_rng(8102).choice(valid_pool, min(RED_VALID_N, len(valid_pool)), replace=False)
    fake = {}
    for name, ids, s in (("train", train_ids, seed+1), ("valid", valid_ids, seed+2)):
        prompts = red_prompts(pack, conditions, ids)
        z = torch.randn(len(ids), LENGTH, generator=torch.Generator().manual_seed(s))
        fake[name] = run(z, prompts)
    ratio_gen = np.ptp(fake["valid"][:, 1], axis=1)
    ratio_cmd = pack["ratio_r"][valid_ids]
    error = np.abs(ratio_gen-ratio_cmd)
    out["R_abs_error_median"] = float(np.median(error))
    out["R_abs_error_by_domain"] = {d: float(np.median(error[pack["domain"][valid_ids] == d]))
                                    for d in RED_DOMAINS if (pack["domain"][valid_ids] == d).any()}
    out["R_spearman"] = float(control.spearmanr(ratio_cmd, ratio_gen).statistic)
    copy = lambda x, r: np.stack((x[:, 0], r[:, None]*(x[:, 0]-x[:, 0].mean(1, keepdims=True))), 1)
    copies = dict(train=copy(fake["train"], pack["ratio_r"][train_ids]), valid=copy(fake["valid"], ratio_cmd))
    for key, data in (("model", fake), ("copy", copies)):
        auc = pair_c2st(pairs(train_ids), data["train"], pairs(valid_ids), data["valid"], device, seed=seed+3)
        out[f"pair_auc_{key}"] = float(auc)
        out[f"pair_indistinguishable_{key}"] = float(100*(1-abs(2*auc-1)))
    out.update(red_validation_windows=int(len(valid_ids)), red_train_windows=int(len(train_ids)))
    return out


def export_gates(model, conditions):
    """TorchScript agreement and single-thread latency (Kaggle host CPU; the Pi is not measured here)."""
    model = model.cpu().eval()
    domain = conditions.domains[0]
    traced = model.export(torch.randn(2, LENGTH), torch.tensor(conditions.prompt(domain, 75., .02, 2)))
    for n, bpm, sigma, d in ((1, 45., .02, conditions.domains[0]), (2, 130., .2, conditions.domains[-1]),
                             (5, 175., .1, "gxu_finger")):
        z, c = torch.randn(n, LENGTH), torch.tensor(conditions.prompt(d, bpm, sigma, n))
        with torch.no_grad():
            torch.testing.assert_close(traced(z, c), model(z, c))
    threads = torch.get_num_threads()
    torch.set_num_threads(1)
    z, c = torch.randn(1, LENGTH), torch.tensor(conditions.prompt("gxu_finger", 80., .02, 1))
    with torch.no_grad():
        for _ in range(2):
            traced(z, c)
        times = []
        for _ in range(7):
            start = time.perf_counter()
            traced(z, c)
            times.append(1000*(time.perf_counter()-start))
    torch.set_num_threads(threads)
    return traced, dict(median_ms=float(np.median(times)), cpu_threads=1, hardware_scope="Kaggle host CPU")


def score(arm, seed, pack, evaluator, conditions, run_dir, device):
    model = DualFlowGenerator(conditions.bank.shape[1], conditions.center, conditions.scale, ARMS[arm]["backbone"],
                              RECIPE["sample_steps"])
    model.load_state_dict(torch.load(run_dir/"best.pt", map_location="cpu", weights_only=True)["generator"])
    model = model.to(device).eval()
    run = run_ir(model, device)
    real_score = evaluator.s_real(run, conditions, seed+30000)
    ctrl = control.controllability(run, CriterionDomains(conditions), CONTROL_N, seed=seed+30000)
    auc = c2st(evaluator, run, conditions, seed+31000, device)
    red = red_metrics(model, pack, conditions, device, seed+33000)
    prompts = evaluator.prompts(conditions, "gxu_finger")[:64]
    probe = run(torch.randn(len(prompts), LENGTH, generator=torch.Generator().manual_seed(seed+32000)), prompts)
    gates = dict(finite=bool(np.isfinite(probe).all()), flat=bool((np.ptp(probe, axis=1) < 1e-6).any()),
                 rho_ok=.75 <= real_score["rho"] <= 1.25)
    try:
        traced, latency = export_gates(model, conditions)
        traced.save(str(run_dir/"generator_cpu.ts"))
        gates["trace_ok"] = True
    except (RuntimeError, AssertionError) as error:
        latency, gates["trace_ok"], gates["trace_error"] = None, False, str(error)[:300]
    model.to(device)
    gates["latency_ok"] = bool(latency and latency["median_ms"] < RECIPE["latency_limit_ms"])
    eligible = gates["finite"] and not gates["flat"] and gates["rho_ok"] and gates["trace_ok"] and gates["latency_ok"]
    return dict(S_arm=real_score["S_real"]+.5*ctrl["C"]+.5*max(0, auc-.5), S_real_fresh=real_score["S_real"],
                C_fresh=ctrl["C"], c2st_derivative_auc=auc, control=ctrl, prompted_validation=real_score,
                wrist_Q=real_score["pools"]["wrist"]["Q"], red=red, gates=gates, eligible=bool(eligible),
                latency=latency)


def train(arm, seed, pack, evaluator, output, device, steps):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    cuda = torch.device(device).type == "cuda"
    conditions = DualConditions(pack)
    g = DualFlowGenerator(conditions.bank.shape[1], conditions.center, conditions.scale, ARMS[arm]["backbone"],
                          RECIPE["sample_steps"]).to(device)
    ema = ema_model(g)
    optimizer = torch.optim.AdamW(g.net.parameters(), lr=RECIPE["lr"], betas=(.9, .99), weight_decay=.01)
    scaler = torch.cuda.amp.GradScaler(enabled=cuda)
    run_dir = Path(output)/f"{arm}_seed{seed}"
    run_dir.mkdir(parents=True)
    save_json(run_dir/"conditions.json", conditions.metadata())
    ids_all = conditions.ids
    signal = pack["signal"][ids_all]
    phase, usable = real_scaffolds(signal, conditions.raw[:, 0], conditions.known[:, 0] > 0)
    domain_of = pack["domain"][ids_all]
    save_json(run_dir/"scaffolds.json", dict(usable_share={d: float(usable[domain_of == d].mean()) for d in conditions.domains},
                                             red_share={d: float(conditions.red_known[domain_of == d].mean())
                                                        for d in conditions.domains}))
    ir = torch.tensor(signal[:, None], device=device)
    red = torch.tensor(pack["red"][ids_all][:, None], device=device)
    red_known = torch.tensor(conditions.red_known, device=device)
    phase, usable = torch.tensor(phase, device=device), torch.tensor(usable, device=device)
    bank = torch.tensor(conditions.bank, device=device)
    ids, weights = balanced_pool(pack, "train")
    cfg = dict(RECIPE, arm=arm, **ARMS[arm])
    best, best_step, history = float("inf"), 0, []
    stability = dict(updates=steps, nonfinite_losses=0, max_grad_norm=0., clipped=0)
    start = time.monotonic()
    interval = min(RECIPE["interval"], steps)
    for step in range(1, steps+1):
        g.train()
        for group in optimizer.param_groups:
            group["lr"] = learning_rate(cfg, step-1, steps)*min(1., step/RECIPE["warmup"])
        rows = torch.tensor([conditions.lookup[int(i)] for i in rng.choice(ids, RECIPE["batch"], p=weights)],
                            device=device)
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast("cuda", enabled=cuda):
            loss = dual_flow_loss(g.net, ir[rows], red[rows], red_known[rows], phase[rows], usable[rows], bank[rows],
                                  RECIPE["cond_drop"], RECIPE["scaffold_drop"], RECIPE["deriv"], RECIPE["spectral"],
                                  RECIPE["t_dist"])
        if not torch.isfinite(loss):
            stability["nonfinite_losses"] += 1
            if stability["nonfinite_losses"] > max(10, .01*steps):
                raise RuntimeError(f"Nonfinite objective: {arm}/{seed}/{step}")
            continue
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        norm = torch.nn.utils.clip_grad_norm_(g.net.parameters(), 1.)
        stability["max_grad_norm"] = max(stability["max_grad_norm"], float(norm) if torch.isfinite(norm) else 0.)
        stability["clipped"] += int(norm > 1)
        scaler.step(optimizer)
        scaler.update()
        update_ema(ema, g, min(.999, (1+step)/(10+step)))
        if (step >= min(2*interval, steps) and step % interval == 0) or step == steps:
            ema.eval()
            run = run_ir(ema, device)
            real_score = evaluator.s_real(run, conditions, seed+10000)
            ctrl = control.controllability(run, CriterionDomains(conditions), CONTROL_N)
            value = real_score["S_real"]+.5*ctrl["C"]
            history.append(dict(step=step, loss=float(loss.detach()), checkpoint_score=value, S_real=real_score["S_real"],
                                rho=real_score["rho"], C=ctrl["C"], wrist_Q=real_score["pools"]["wrist"]["Q"],
                                seconds=time.monotonic()-start))
            if value < best:
                best, best_step = value, step
                torch.save(dict(generator=ema.state_dict(), arm=arm, seed=seed, step=step, checkpoint_score=value),
                           run_dir/"best.pt")
            save_json(run_dir/"history.json", history)
            print(arm, seed, json.dumps(history[-1]), flush=True)
    result = dict(arm=arm, seed=seed, best_step=best_step, checkpoint_score=best, recipe=cfg,
                  training_seconds=time.monotonic()-start, generator_parameters=sum(p.numel() for p in g.net.parameters()),
                  training_device=str(device), stability=stability,
                  peak_cuda_bytes=torch.cuda.max_memory_allocated(device) if cuda else 0)
    result.update(score(arm, seed, pack, evaluator, conditions, run_dir, device))
    save_json(run_dir/"training_result.json", result)
    return result


def worker(device, jobs, input_root, output, steps, n, threads=2):
    torch.set_num_threads(threads)
    if device.startswith("cuda"):
        torch.cuda.set_device(device)
    pack, _ = load_dual(input_root)
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    evaluator = PromptedEvaluator(evaluation_view(development), n)
    return [train(arm, seed, development, evaluator, output, device, steps) for arm, seed in jobs]


def run_jobs(jobs, devices, input_root, output, steps, n):
    if devices == ["cpu"]:
        return worker("cpu", jobs, input_root, output, steps, n, 4)
    rows = []
    with ProcessPoolExecutor(max_workers=len(devices), mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(worker, device, jobs[i::len(devices)], input_root, output, steps, n)
                   for i, device in enumerate(devices)]
        for future in futures:
            rows.extend(future.result())
    return rows


def pilot_rule(rows):
    candidates = []
    for r in rows:
        ok = r["eligible"] and r["red"]["R_abs_error_median"] <= LIMITS["R_mae"]
        candidates.append(dict(arm=r["arm"], S_arm=r["S_arm"], eligible=bool(ok), gates=r["gates"],
                               R_abs_error_median=r["red"]["R_abs_error_median"]))
    eligible = [c for c in candidates if c["eligible"]]
    if not eligible:
        return dict(winner=None, candidates=candidates, reason="no eligible arm; the round stops")
    best = min(c["S_arm"] for c in eligible)
    near = [c for c in eligible if c["S_arm"] <= best+LIMITS["tie"]]
    near.sort(key=lambda c: (c["arm"] != "U2", c["S_arm"]))
    return dict(winner=near[0]["arm"], candidates=candidates, reason=f"lowest S_arm; U2 within {LIMITS['tie']}")


def pooled(a, b):
    return math.sqrt((np.var(a, ddof=1)+np.var(b, ddof=1))/2)


def final_rule(rows):
    s_arm = np.array([r["S_arm"] for r in rows])
    s_real = np.array([r["S_real_fresh"] for r in rows])
    wrist = np.array([r["wrist_Q"] for r in rows])
    ind_model = np.array([r["red"]["pair_indistinguishable_model"] for r in rows])
    ind_copy = np.array([r["red"]["pair_indistinguishable_copy"] for r in rows])
    f6_sd = pooled(s_arm, np.array(F6["S_arm"]))
    r9_sd = math.sqrt((np.var(s_arm, ddof=1)+R9["S_arm_sd"]**2)/2)
    red_margin = 2*max(np.std(ind_model, ddof=1), np.std(ind_copy, ddof=1))
    checks = dict(
        every_seed_eligible=all(r["eligible"] for r in rows),
        R_error_ok=bool(np.mean([r["red"]["R_abs_error_median"] for r in rows]) <= LIMITS["R_mae"]),
        S_arm_vs_F6=bool(s_arm.mean() <= np.mean(F6["S_arm"])+f6_sd),
        wrist_Q_ok=bool(wrist.mean() <= LIMITS["wrist_Q"]),
        red_beats_copy=bool(ind_model.mean()-ind_copy.mean() > red_margin))
    d1 = all(checks.values())
    d2_checks = dict(S_arm_gap_vs_R9=bool(R9["S_arm_mean"]-s_arm.mean() > r9_sd),
                     S_real_non_inferior=bool(s_real.mean() <= R9["S_real_mean"]+LIMITS["S_real_margin"]),
                     S_arm_abs=bool(s_arm.mean() <= LIMITS["S_arm_abs"]))
    d2 = d1 and all(d2_checks.values())
    eligible = [r for r in rows if r["eligible"]]
    ship = min(eligible, key=lambda r: r["S_arm"])["seed"] if eligible else None
    return dict(D1=d1, D2=d2, checks=checks, d2_checks=d2_checks, ship_seed=ship,
                S_arm=dict(mean=float(s_arm.mean()), sd=float(s_arm.std(ddof=1)), values=s_arm.tolist()),
                S_real=dict(mean=float(s_real.mean()), values=s_real.tolist()),
                wrist_Q=dict(mean=float(wrist.mean()), values=wrist.tolist()),
                pair_indistinguishable=dict(model=ind_model.tolist(), copy=ind_copy.tolist(), margin=float(red_margin)),
                F6_pooled_sd=f6_sd, R9_pooled_sd=r9_sd)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=RECIPE["steps"])
    parser.add_argument("--eval-samples", type=int, default=256)
    parser.add_argument("--allow-cpu", action="store_true", help="Smoke run only: CPU, few steps, no decision value")
    a = parser.parse_args(argv)
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and (len(names) != 2 or any("T4" not in n for n in names)):
        raise RuntimeError(f"Two T4 GPUs required, allocated {names}")
    devices = ["cpu"] if a.allow_cpu else ["cuda:0", "cuda:1"]
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    _, manifest = load_dual(a.input_root)
    save_json(output/"RULE_11.json", dict(rule=RULE_11, recipe=RECIPE, arms=ARMS, limits=LIMITS, incumbents=dict(F6=F6, R9=R9),
                                          criterion_sha256=CRITERION_SHA256, pack=dict(protocol=PROTOCOL,
                                          windows_sha256=manifest["windows_sha256"],
                                          content_sha256=manifest["content_sha256"]), domain_slots=DOMAIN_SLOTS))
    start = time.monotonic()
    pilot = run_jobs([("U2", PILOT_SEED), ("T2", PILOT_SEED)], devices, a.input_root, output/"pilot", a.steps,
                     a.eval_samples)
    selection = pilot_rule(pilot)
    save_json(output/"PILOT_SELECTION_11.json", dict(selection, rule=RULE_11, rows=pilot))
    print("PILOT", json.dumps({k: selection[k] for k in ("winner", "reason")}), flush=True)
    if selection["winner"] is None:
        return selection
    final = run_jobs([(selection["winner"], s) for s in FINAL_SEEDS], devices, a.input_root, output/"final", a.steps,
                     a.eval_samples)
    rows = [r for r in pilot if r["arm"] == selection["winner"]]+final
    decision = final_rule(rows)
    save_json(output/"DECISION_11.json", dict(decision, winner=selection["winner"], rule=RULE_11,
                                               wall_seconds=time.monotonic()-start,
                                               rows=[{k: r[k] for k in ("arm", "seed", "S_arm", "S_real_fresh", "C_fresh",
                                                                         "c2st_derivative_auc", "wrist_Q", "red",
                                                                         "gates", "eligible", "latency", "best_step")}
                                                     for r in rows]))
    print("DECISION", json.dumps({k: decision[k] for k in ("D1", "D2", "ship_seed")}), flush=True)
    return decision


if __name__ == "__main__":
    main()
