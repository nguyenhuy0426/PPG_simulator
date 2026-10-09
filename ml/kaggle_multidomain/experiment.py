"""Bounded validation-only improvement round, followed by one frozen two-T4 benchmark."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import multiprocessing
import os
from pathlib import Path
import platform
import time

import numpy as np
import torch
from torch.nn import functional as F

from ml.kaggle_lsm.train_lsm import LENGTH, prepare_discriminator_for_generator, save_json
from ml.kaggle_multidomain.benchmark import Evaluator, cpu_latency, morphology, sample
from ml.kaggle_multidomain.data import balanced_pool
from ml.kaggle_multidomain.data_more import load_input
from ml.kaggle_multidomain.models import distribution_loss, networks
from ml.kaggle_multidomain.physio import (CleanDenoiser, ConditionedCritic, Conditions, PhysioMix,
                                        clean_diffusion_loss, descriptors, draw, ema_model, joint_loss, update_ema)
from ml.kaggle_multidomain.train import ARMS, train_one

CANDIDATES = ("physiomix_no_div", "physiomix", "physiodiffusion_plain", "physiodiffusion")


class QualityEvaluator(Evaluator):
    def validation(self, generated):
        mmd, per_domain = super().validation(generated)
        metrics = self.evaluate(generated, "validation", bootstrap=0)
        d = self.diagnostics(generated)
        ratio = d["morphology_pairwise_distance_median"]/max(d["train_morphology_pairwise_distance_median"], 1e-8)
        # Fixed before training: discourage both mode collapse and noise-driven overdispersion.
        score = mmd+.25*abs(np.log(max(ratio, 1e-6)))+.5*np.mean([1-v["feature_recall"] for v in metrics.values()])
        return float(score), per_domain


def custom_network(arm, conditions):
    size = conditions.bank.shape[1]
    if arm.startswith("physiodiffusion"):
        return CleanDenoiser(size), None
    return PhysioMix(size, conditions.center, conditions.scale), ConditionedCritic(size)


@torch.no_grad()
def custom_sample(model, conditions, seed, device, n, diffusion=False, guidance=1., sample_steps=32):
    rng = torch.Generator(device=device).manual_seed(seed)
    z = torch.randn(n, LENGTH, generator=rng, device=device)
    c = torch.tensor(conditions.draw(seed+73, n), device=device)
    return torch.cat([draw(model, part, cond, diffusion, guidance, sample_steps)
                      for part, cond in zip(z.split(16), c.split(16))]).cpu().numpy()[:, 0]


def train_custom(arm, seed, pack, evaluator, output, steps, batch, interval, device, options):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    cuda = torch.device(device).type == "cuda"
    if cuda:
        torch.cuda.reset_peak_memory_stats(device)
    conditions = Conditions(pack)
    g, d = custom_network(arm, conditions)
    g.to(device)
    if d is not None:
        d.to(device)
    ema = ema_model(g)
    diffusion = d is None
    optg = torch.optim.Adam(g.parameters(), lr=2e-4, betas=(0., .99))
    optd = torch.optim.Adam(d.parameters(), lr=2e-4, betas=(0., .99)) if d is not None else None
    run = Path(output)/f"{arm}_seed{seed}"
    run.mkdir()
    save_json(run/"conditions.json", conditions.metadata())
    ids, weights = balanced_pool(pack, "train")
    best, history, best_step = float("inf"), [], 0
    start = time.monotonic()
    stability = dict(updates=steps, nonfinite_losses=0, g_clipped=0, d_clipped=0,
                     max_g_grad_norm=0., max_d_grad_norm=0., r1_updates=0)
    for step in range(1, steps+1):
        g.train()
        chosen = rng.choice(ids, batch, p=weights)
        real = torch.tensor(pack["signal"][chosen, None], device=device)
        c = torch.tensor(conditions.for_ids(chosen), device=device)
        optg.zero_grad(set_to_none=True)
        ld, r1, mode, margin = (real.new_zeros(()) for _ in range(4))
        if diffusion:
            lg = clean_diffusion_loss(g, real, c, arm == "physiodiffusion")
        else:
            d.train().requires_grad_(True)
            fake = g(torch.randn(batch, LENGTH, device=device), c)
            optd.zero_grad(set_to_none=True)
            regularize = step % 16 == 0
            real.requires_grad_(regularize)
            pr, pf = d(real, c), d(fake.detach(), c)
            wrong = d(real, c.roll(1, 0))
            ld = F.relu(1-pr).mean()+.5*F.relu(1+pf).mean()+.5*F.relu(1+wrong).mean()
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
            if arm == "physiomix":
                other = g(torch.randn(batch, LENGTH, device=device), c)
                distance = (descriptors(fake)-descriptors(other)).abs().mean(1)
                mode = F.relu(.05-distance).mean()
                lg = lg+joint_loss(fake, real)+.1*mode
        if not torch.isfinite(lg+ld):
            raise RuntimeError(f"Nonfinite objective: {arm}/{seed}/{step}")
        lg.backward()
        gn = torch.nn.utils.clip_grad_norm_(g.parameters(), 10, error_if_nonfinite=True)
        stability["max_g_grad_norm"] = max(stability["max_g_grad_norm"], float(gn))
        stability["g_clipped"] += int(gn > 10)
        optg.step()
        update_ema(ema, g)
        if step == 1 or step % interval == 0 or step == steps:
            generated = custom_sample(ema, conditions, seed+10000, device, evaluator.n, diffusion, **options)
            value, per_domain = evaluator.validation(generated)
            vd = evaluator.diagnostics(generated)
            vm = evaluator.evaluate(generated, "validation", 0)
            row = dict(step=step, loss_g=float(lg.detach()), loss_d=float(ld.detach()),
                       r1=float(r1.detach()), mode_penalty=float(mode.detach()), critic_margin=float(margin),
                       g_grad_norm=float(gn), validation_score=value, per_domain=per_domain,
                       diversity_ratio=vd["morphology_pairwise_distance_median"]/max(vd["train_morphology_pairwise_distance_median"], 1e-8),
                       validation_recall=float(np.mean([v["feature_recall"] for v in vm.values()])),
                       seconds=time.monotonic()-start)
            history.append(row)
            if value < best:
                best, best_step = value, step
                torch.save(dict(generator=ema.state_dict(), arm=arm, seed=seed, step=step,
                                validation_score=value, options=options), run/"best.pt")
            save_json(run/"history.json", history)
            print(arm, seed, json.dumps(row), flush=True)
    torch.save(dict(generator=g.state_dict(), ema=ema.state_dict(), discriminator=d.state_dict() if d else None,
                    optimizer_g=optg.state_dict(), optimizer_d=optd.state_dict() if optd else None,
                    torch_rng=torch.get_rng_state(), cuda_rng=torch.cuda.get_rng_state(device) if cuda else None,
                    numpy_rng=rng.bit_generator.state, arm=arm, seed=seed, step=steps), run/"last_training_state.pt")
    result = dict(arm=arm, seed=seed, best_step=best_step, validation_score=best, options=options,
                  training_seconds=time.monotonic()-start, generator_parameters=sum(p.numel() for p in g.parameters()),
                  training_device=str(device), worker_pid=os.getpid(),
                  peak_cuda_bytes=torch.cuda.max_memory_allocated(device) if cuda else 0, stability=stability)
    save_json(run/"training_result.json", result)
    return result


def worker(device, jobs, input_root, output, steps, batch, interval, n, options):
    torch.set_num_threads(2)
    if device.startswith("cuda"):
        torch.cuda.set_device(device)
    pack, _ = load_input(input_root)
    # Training/validation machinery has no test/external signals in its reference tables.
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    evaluator = QualityEvaluator(development, n)
    print("WORKER", device, os.getpid(), jobs, flush=True)
    return [train_custom(arm, seed, development, evaluator, output, steps, batch, interval, device,
                         options.get(arm, {})) if arm in CANDIDATES else
            train_one(arm, seed, development, evaluator, Path(output), steps, batch, interval, device)
            for arm, seed in jobs]


def parallel(jobs, devices, input_root, output, steps, batch, interval, n, options):
    Path(output).mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    if devices == ["cpu"]:
        rows = worker("cpu", jobs, input_root, output, steps, batch, interval, n, options)
    else:
        rows = []
        with ProcessPoolExecutor(max_workers=len(devices), mp_context=multiprocessing.get_context("spawn")) as pool:
            futures = [pool.submit(worker, device, jobs[i::len(devices)], input_root, output,
                                   steps, batch, interval, n, options) for i, device in enumerate(devices)]
            for future in as_completed(futures):
                rows.extend(future.result())
                save_json(Path(output)/"selection_progress.json", rows)
    by_job = {(r["arm"], r["seed"]): r for r in rows}
    if set(by_job) != set(jobs) or len(rows) != len(jobs):
        raise RuntimeError("Missing or duplicate training runs")
    ordered = [by_job[job] for job in jobs]
    save_json(Path(output)/"training_execution.json", dict(wall_seconds=time.monotonic()-start,
              workers=len(devices), allocated_gpus=[torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],
              runs=ordered))
    return ordered


def select_pilot(rows, output, development, device, n):
    evaluator = QualityEvaluator(development, n)
    conditions = Conditions(development)
    choices = []
    for row in rows:
        arm = row["arm"]
        model, _ = custom_network(arm, conditions)
        model.load_state_dict(torch.load(Path(output)/f"{arm}_seed42"/"best.pt", weights_only=True,
                                        map_location="cpu")["generator"])
        model.to(device).eval()
        configurations = [dict(guidance=g, sample_steps=s) for g in (1., 1.5) for s in (32, 64)] if arm.startswith("physiodiffusion") else [{}]
        for options in configurations:
            generated = custom_sample(model, conditions, 10042, device, n, arm.startswith("physiodiffusion"), **options)
            score, _ = evaluator.validation(generated)
            choices.append(dict(arm=arm, options=options, score=score))
    gan = min((r for r in choices if r["arm"].startswith("physiomix")), key=lambda r: r["score"])
    diffusion = min((r for r in choices if r["arm"].startswith("physiodiffusion")), key=lambda r: r["score"])
    save_json(Path(output)/"PILOT_SELECTION.json", dict(gan=gan, diffusion=diffusion, candidates=choices,
              rule="Only development validation; no test/external signals available to pilot evaluator"))
    return {r["arm"]: r["options"] for r in (gan, diffusion)}


@torch.no_grad()
def custom_latency(model, conditions, diffusion, options):
    model.cpu().eval()
    torch.set_num_threads(1)
    z = torch.randn(1, LENGTH)
    c = torch.tensor(conditions.draw(492, 1))
    for _ in range(3):
        draw(model, z, c, diffusion, **options)
    times = []
    for _ in range(20):
        start = time.perf_counter()
        draw(model, z, c, diffusion, **options)
        times.append((time.perf_counter()-start)*1000)
    return dict(median_ms=float(np.median(times)), p95_ms=float(np.quantile(times, .95)),
                cpu_threads=1, hardware_scope="Kaggle host CPU; Pi not measured")


def evaluate_frozen(rows, pack, output, n, bootstrap, device):
    evaluator, conditions = QualityEvaluator(pack, n), Conditions(pack)
    results = []
    for row in rows:
        arm, seed = row["arm"], row["seed"]
        run = Path(output)/f"{arm}_seed{seed}"
        custom = arm in CANDIDATES
        diffusion = arm.startswith("physiodiffusion") or arm == "diffusion_multi"
        model, _ = custom_network(arm, conditions) if custom else networks(arm)
        model.load_state_dict(torch.load(run/"best.pt", map_location="cpu", weights_only=True)["generator"])
        model.to(device).eval()
        generated = (custom_sample(model, conditions, seed+20000, device, n, diffusion, **row["options"])
                     if custom else sample(model, seed+20000, device, n, diffusion))
        metrics = dict(**row, validation=evaluator.evaluate(generated, "validation", 0),
                       test=evaluator.evaluate(generated, "test", bootstrap),
                       external=evaluator.evaluate(generated, "external", bootstrap),
                       diagnostics=evaluator.diagnostics(generated),
                       latency=custom_latency(model, conditions, diffusion, row["options"]) if custom else cpu_latency(model, diffusion))
        if custom:
            controlled = []
            # Valid support only: commands sampled from training prompt ranges.
            for domain in range(len(conditions.domains)):
                for bpm in (60., 90., 120.):
                    if not conditions.raw[:, 0].min() <= bpm <= conditions.raw[:, 0].max():
                        continue
                    prompts = conditions.draw(318, 16)
                    prompts[:, :len(conditions.domains)] = 0
                    prompts[:, domain] = 1
                    prompts[:, -3] = (bpm-conditions.center[0])/conditions.scale[0]
                    z = torch.randn(16, LENGTH, generator=torch.Generator().manual_seed(31), device="cpu").to(next(model.parameters()).device)
                    y = draw(model, z, torch.tensor(prompts, device=z.device), diffusion, **row["options"]).cpu().numpy()[:, 0]
                    estimated = morphology(y)[:, 0]
                    controlled.append(dict(domain=conditions.domains[domain], requested_proxy_bpm=bpm,
                                           generated_proxy_bpm_mean=float(estimated.mean()), proxy_mae_bpm=float(np.abs(estimated-bpm).mean())))
            metrics["conditioning_probe"] = controlled
        if custom and not diffusion:
            example = (torch.randn(2, LENGTH), torch.tensor(conditions.draw(17, 2)))
            traced = torch.jit.trace(model, example)
            torch.testing.assert_close(traced(example[0][:1], example[1][:1]), model(example[0][:1], example[1][:1]))
            traced.save(str(run/"generator_cpu.ts"))
        np.savez_compressed(run/"samples.npz", generated=generated)
        save_json(run/"metrics.json", metrics)
        results.append(metrics)
        save_json(Path(output)/"results.json", dict(models=results))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=6000)
    parser.add_argument("--pilot-steps", type=int, default=2000)
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 2026])
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--interval", type=int, default=500)
    parser.add_argument("--eval-samples", type=int, default=128)
    parser.add_argument("--bootstrap", type=int, default=100)
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    if min(a.steps, a.pilot_steps, a.batch, a.interval, a.eval_samples) < 2 or a.bootstrap < 0 or len(set(a.seeds)) != len(a.seeds):
        raise ValueError("Invalid or duplicate experiment budget")
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and (len(names) != 2 or any("T4" not in name for name in names)):
        raise RuntimeError(f"Two T4 GPUs required, allocated {names}")
    devices = ["cpu"] if a.allow_cpu else ["cuda:0", "cuda:1"]
    pack, manifest = load_input(a.input_root)
    domains = {"bidmc", "perform_af", "perform_non_af", "perform_large", "wrist"}
    for split in ("train", "validation", "test"):
        if set(pack["domain"][pack["split"] == split]) != domains:
            raise ValueError(f"Missing domains in {split}")
    if not a.allow_cpu and set(pack["domain"][pack["split"] == "external"]) != {"capnobase", "ptt_run", "ptt_sit", "ptt_walk"}:
        raise ValueError("CapnoBase and PTT external domains required")
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    save_json(output/"data_manifest.json", manifest)
    configuration = dict(args=vars(a), python=platform.python_version(), torch=torch.__version__,
                         allocated_gpus=names, training_workers=len(devices),
                         selection="validation macro MMD + 0.25*abs(log diversity ratio) + 0.5*(1-macro feature recall)",
                         pilot_candidates=list(CANDIDATES),
                         primary_holdouts=["wrist/test", "capnobase/external"],
                         secondary_previously_viewed=["bidmc", "perform_*", "ptt_*"],
                         limitations=["Finite search, 3 seeds, not globally best or clinical validity",
                                      "New generator has a band-limited periodic prior and PPG proxy conditioning",
                                      "GAN R1/EMA/condition mechanisms are jointly changed; no isolated causal attribution",
                                      "All benchmark prompts drawn from training only; no held-out metadata supplied",
                                      "Wrist only 2 test participants; CapnoBase grouped by source case",
                                      "Frozen old tests/PTT are exploratory and cannot prove unbiased improvement",
                                      "No calibrated DC/AC, SpO2 or paired IR/RED; no Pi/DAC deployment"])
    save_json(output/"configuration.json", configuration)
    overall_start = time.monotonic()
    pilot = parallel([(arm, 42) for arm in CANDIDATES], devices, a.input_root, output/"pilot",
                     a.pilot_steps, a.batch, a.interval, a.eval_samples, {})
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    options = select_pilot(pilot, output/"pilot", development, devices[0], a.eval_samples)
    arms = list(ARMS)+list(options)
    save_json(output/"FROZEN_PROTOCOL.json", dict(arms=arms, options=options, seeds=a.seeds, steps=a.steps,
              batch=a.batch, test_unseen=True, holdout_rule="No further tuning/restarts based on test/PTT/CapnoBase"))
    rows = parallel([(arm, seed) for arm in arms for seed in a.seeds], devices, a.input_root, output/"benchmark",
                    a.steps, a.batch, a.interval, a.eval_samples, options)
    averages = {arm: float(np.mean([r["validation_score"] for r in rows if r["arm"] == arm])) for arm in arms}
    winner = min(averages, key=averages.get)
    save_json(output/"benchmark"/"selection.json", dict(winner=winner, mean_validation=averages, runs=rows))
    # This is the first access to held-out metrics. Every choice and checkpoint is already frozen.
    results = evaluate_frozen(rows, pack, output/"benchmark", a.eval_samples, a.bootstrap, devices[0])
    evaluator = QualityEvaluator(pack, a.eval_samples)
    pool, weights = balanced_pool(pack, "train")
    replay = pack["signal"][np.random.default_rng(2109).choice(pool, a.eval_samples, p=weights)]
    save_json(output/"controls.json", dict(balanced_train_replay=dict(
        test=evaluator.evaluate(replay, "test", a.bootstrap),
        external=evaluator.evaluate(replay, "external", a.bootstrap),
        meaning="Distribution gap lower-bound context; training replay is not novel generation")))
    from ml.kaggle_multidomain.report_more import report
    report(output, results, winner)
    save_json(output/"COMPLETE.json", dict(status="complete", trained_runs=len(rows), pilot_runs=len(pilot),
              winner_by_validation=winner, data_sha256=manifest["windows_sha256"],
              wall_seconds=time.monotonic()-overall_start, deployment="research_only"))
    print("COMPLETE", winner, flush=True)


if __name__ == "__main__":
    main()
