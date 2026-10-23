"""PhysioFlow round 10: pilot (arms x samplers, seed 42) then a frozen 3-seed run against the shipped PhysioMix.

Same data (v3 pack), same locked criterion terms (S_real, C, derivative C2ST -> S_arm), validation only. The one
declared change for flows: the 50 ms latency gate of a single GAN pass becomes a 5 s limit per 30 s window
(median, one CPU thread, Kaggle host), because a flow integrates the U-Net 15-31 times and the app generates
whole windows off the DAC thread. The Pi is not measured here.

pilot: train every FLOW_BASES arm on seed 42; score each under every FLOW_SAMPLERS sampler; the winner is the
eligible (arm, sampler) with the lowest S_arm. final: retrain the winner on three seeds, decide against the
incumbent (round 9) with the rule frozen before training, then score the GXU test (opened at round 3; report only).
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import time

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import save_json
from ml.kaggle_multidomain import control
from ml.kaggle_multidomain.data import balanced_pool
from ml.kaggle_multidomain.data_gxu import load_input
from ml.kaggle_multidomain.experiment_v3 import (CONTROL_N, CRITERION_SHA256, FLOW_BASES, FLOW_SAMPLERS, PROTOCOL,
                                                 VIEW, build, check_pack, conditions_for, config, learning_rate, parallel,
                                                 Snapshots, sampler, score_arm, sealed_subjects)
from ml.kaggle_multidomain.flow import FINISH_PAD, flow_loss, real_scaffolds, slow_wrist_bank, swap_slow
from ml.kaggle_multidomain.physio import view_mask
from ml.kaggle_multidomain.physio import ema_model, update_ema
from ml.kaggle_multidomain.report_v3 import fmt, stat, summarize

WARMUP = 500
INCUMBENT_ARM = "L3_rel_beat_lr_crop_r1w_motion_dom"
DESCRIPTION = {"F1_flow": "PhysioFlow: constructed peak-phase scaffold + conditional rectified-flow 1D U-Net "
                          "(6.9M parameters, attention at 150/75 samples), velocity MSE, logit-normal times",
               "F2_flow_deriv": "PhysioFlow with an added first-difference loss on the x0 estimate (weight 1, "
                                "low-noise weighted)",
               "F3_flow_flag_deriv": "PhysioFlow (6.9M-parameter U-Net, rectified flow) whose rhythm scaffold is given "
                                     "only when the rate is known (as in training), plus the x0 first-difference loss "
                                     "(weight 1)",
               "F4_flow_flag_deriv03": "PhysioFlow with the flag-gated rhythm scaffold and the x0 first-difference loss "
                                       "at weight 0.3",
               "F5_flow_flag_deriv_mix": "PhysioFlow (6.9M-parameter U-Net, rectified flow, flag-gated rhythm scaffold, "
                                         "x0 first-difference loss 1) trained on a half logit-normal, half uniform "
                                         "flow-time mixture",
               "F6_flow_flag_deriv_unif": "PhysioFlow (flag-gated rhythm scaffold, x0 first-difference loss 1) trained "
                                          "on uniform flow times",
               "F7_flow_unif_stop1": "PhysioFlow (flag-gated rhythm scaffold, x0 first-difference loss 1, uniform flow "
                                     "times) plus a stop-band log-PSD loss of the x0 estimate at low t (weight 1)",
               "F8_flow_unif_stop3": "PhysioFlow (flag-gated rhythm scaffold, x0 first-difference loss 1, uniform flow "
                                     "times) plus a stop-band log-PSD loss of the x0 estimate at low t (weight 3)",
               "F9_flow_unif_stop03": "PhysioFlow (flag-gated rhythm scaffold, x0 first-difference loss 1, uniform flow "
                                      "times) plus a stop-band log-PSD loss of the x0 estimate at low t (weight 0.3)",
               "F10_flow_unif_stop01": "PhysioFlow (flag-gated rhythm scaffold, x0 first-difference loss 1, uniform flow "
                                       "times) plus a stop-band log-PSD loss of the x0 estimate at low t (weight 0.1)",
               "F11_flow_stop03_wslow": "PhysioFlow with the stop-band log-PSD loss (weight 0.3) and half of the "
                                        "scaffolded wrist training windows slowed in time to 40 bpm..their own rate",
               "F12_flow_stop01_wslow": "PhysioFlow with the stop-band log-PSD loss (weight 0.1) and half of the "
                                        "scaffolded wrist training windows slowed in time to 40 bpm..their own rate"}
# Loop 5 (wrist) go/no-go for a 3-seed final, fixed before its pilot ran: the seed-42 pilot must reach the round-10
# wrist bound (round-9 mean 0.527 + round-10 pooled SD 0.074) and keep S_arm within one round-10 seed SD (0.015) of
# round 10's own seed 42 (0.472). Validation only. Loop 6 keeps the same limits.
GO_LIMITS = dict(wrist_Q=.601, S_arm=.487)
# Loop 7, fixed before its pilot: the loop-6 final missed the wrist guard (bound 0.527 + pooled SD 0.046 = 0.573) after
# a seed-42 pilot of 0.581, so the pilot must sit one loop-6 seed SD of wrist Q (0.027) under that bound.
GO_LIMITS_LOOP7 = dict(wrist_Q=.546, S_arm=.487)
GO = {"loop5": GO_LIMITS, "loop7": GO_LIMITS_LOOP7}


def sampler_arms(arm):
    return [f"{arm}_s{s}_w{w:g}" for s, w in FLOW_SAMPLERS]


def base_of(arm):
    return next(b for b in FLOW_BASES if arm == b or arm.startswith(b+"_s"))


def train_flow(arm, seed, pack, evaluator, output, steps, batch, interval, device, frozen=None):
    """Train one flow arm; checkpoint on S_real + 0.5C of the EMA weights under the arm's own sampler."""
    cfg = config(arm)
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    cuda = torch.device(device).type == "cuda"
    if cuda:
        torch.cuda.reset_peak_memory_stats(device)
    conditions = conditions_for(pack, cfg["version"])
    g, _ = build(cfg, conditions)
    g.to(device)
    ema = ema_model(g)
    optimizer = torch.optim.AdamW(g.net.parameters(), lr=cfg["lr"], betas=(.9, .99), weight_decay=.01)
    scaler = torch.cuda.amp.GradScaler(enabled=cuda)
    run_dir = Path(output)/f"{arm}_seed{seed}"
    run_dir.mkdir()
    save_json(run_dir/"conditions.json", conditions.metadata())
    rows_of = conditions.lookup
    signal = pack["signal"][conditions.ids]
    phase, usable = real_scaffolds(signal, conditions.raw[:, 0], conditions.known[:, 0] > 0)
    domain_of = pack["domain"][conditions.ids]
    scaffold_share = {d: float(usable[domain_of == d].mean()) for d in conditions.domains}
    band = torch.tensor(view_mask(VIEW, signal.shape[-1]+2*FINISH_PAD))
    slow = slow_wrist_bank(signal, phase, usable, conditions.raw[:, 0], domain_of == "wrist", band) \
        if cfg["wrist_slow"] else None
    slow_info = None if slow is None else dict(copies=int(len(slow[2])), sources=sorted({int(i) for i in slow[3]}),
                                                 target_bpm=sorted({float(t) for t in slow[2]}))
    save_json(run_dir/"scaffolds.json", dict(usable_share=scaffold_share, windows=int(len(usable)), wrist_slow=slow_info))
    signal = torch.tensor(signal[:, None], device=device)
    phase, usable = torch.tensor(phase, device=device), torch.tensor(usable, device=device)
    bank = torch.tensor(conditions.bank, device=device)
    wrist = torch.tensor(domain_of == "wrist", device=device)
    if slow is not None:
        rows_of_slow = conditions.bank[slow[3]].copy()
        rows_of_slow[:, -3] = (slow[2]-conditions.center[0])/conditions.scale[0]
        slow = tuple(torch.tensor(v, device=device) for v in (slow[0], slow[1], rows_of_slow.astype(np.float32)))
    ids, weights = balanced_pool(pack, "train")
    best, best_step, history = float("inf"), 0, []
    stability = dict(updates=steps, nonfinite_losses=0, max_grad_norm=0., clipped=0)
    snapshots = Snapshots(conditions, cfg, device, run_dir/"snapshots.npz")
    start = time.monotonic()
    for step in range(1, steps+1):
        g.train()
        for group in optimizer.param_groups:
            group["lr"] = learning_rate(cfg, step-1, steps)*min(1., step/WARMUP)
        rows = torch.tensor([rows_of[int(i)] for i in rng.choice(ids, batch, p=weights)], device=device)
        optimizer.zero_grad(set_to_none=True)
        x, ph, cond = signal[rows], phase[rows], bank[rows]
        if slow is not None:
            x, ph, cond = swap_slow(x, ph, cond, usable[rows] & wrist[rows], cfg["wrist_slow"], *slow)
        with torch.autocast("cuda", enabled=cuda):
            loss = flow_loss(g.net, x, ph, usable[rows], cond, deriv=cfg["deriv"],
                             t_dist=cfg["t_dist"], spectral=cfg["spectral"], spectral_stop=cfg["spectral_stop"],
                             input_noise=cfg["input_noise"])
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
        snapshots.maybe(step, steps, ema)
        if (step >= min(2*interval, steps) and step % interval == 0) or step == steps:
            ema.eval()
            run = sampler(ema, cfg, device)
            real_score = evaluator.s_real(run, conditions, seed+10000)
            ctrl = control.controllability(run, conditions, CONTROL_N)
            value = real_score["S_real"]+.5*ctrl["C"]
            row = dict(step=step, loss=float(loss.detach()), checkpoint_score=value, S_real=real_score["S_real"],
                       rho=real_score["rho"], C=ctrl["C"],
                       control={k: ctrl[k] for k in ("mae_in", "mae_ext", "spearman", "auc_irr", "lock_rate")},
                       pools={n: {k: v[k] for k in ("Q", "total_mmd", "precision", "recall")}
                              for n, v in real_score["pools"].items()},
                       seconds=time.monotonic()-start)
            history.append(row)
            if value < best:
                best, best_step = value, step
                torch.save(dict(generator=ema.state_dict(), arm=arm, seed=seed, step=step, checkpoint_score=value,
                                config=cfg), run_dir/"best.pt")
            save_json(run_dir/"history.json", history)
            print(arm, seed, json.dumps({k: row[k] for k in ("step", "checkpoint_score", "S_real", "C", "rho")}),
                  flush=True)
    torch.save(dict(generator=g.state_dict(), ema=ema.state_dict(), arm=arm, seed=seed, step=steps),
               run_dir/"last_training_state.pt")
    result = dict(arm=arm, seed=seed, best_step=best_step, checkpoint_score=best, config=cfg,
                  training_seconds=time.monotonic()-start, generator_parameters=sum(p.numel() for p in g.parameters()),
                  training_device=str(device), worker_pid=os.getpid(), stability=stability, scaffolds=scaffold_share,
                  peak_cuda_bytes=torch.cuda.max_memory_allocated(device) if cuda else 0)
    # The pilot scores every sampler on the same weights; the final scores the arm's own (frozen) sampler.
    variants = [v for v in (frozen or {}).get("samplers", []) if base_of(v) == base_of(arm)] or [arm]
    scored = {}
    for variant in variants:
        scored[variant] = score_arm(variant, seed, pack, evaluator, run_dir, device, None, steps)
        save_json(run_dir/"sampler_scores.json", scored)
    own = scored.get(arm) or min(scored.values(), key=lambda r: r["S_arm"])
    result.update(own, samplers={v: dict(S_arm=r["S_arm"], S_real=r["S_real_fresh"], C=r["C_fresh"],
                                         auc=r["c2st_derivative_auc"], eligible=r["eligible"], gates=r["gates"],
                                         latency=r["latency"], wrist_Q=r["prompted_validation"]["pools"]["wrist"]["Q"])
                                  for v, r in scored.items()})
    save_json(run_dir/"training_result.json", result)
    return result


def resume_row(arm, seed, pack, evaluator, run_dir, device, steps):
    """Score a trained run whose worker died before scoring: best checkpoint from its history, same score_arm.
    Training counters (clipping, non-finite losses) lived in the dead worker and are not recovered."""
    history = json.loads((run_dir/"history.json").read_text())
    best = min(history, key=lambda h: h["checkpoint_score"])
    conditions = conditions_for(pack, config(arm)["version"])
    model, _ = build(config(arm), conditions)
    scaffolds = json.loads((run_dir/"scaffolds.json").read_text())["usable_share"]
    result = dict(arm=arm, seed=seed, best_step=best["step"], checkpoint_score=best["checkpoint_score"], config=config(arm),
                  training_seconds=history[-1]["seconds"], generator_parameters=sum(p.numel() for p in model.parameters()),
                  training_device="cuda (final kernel)", scaffolds=scaffolds, resumed_scoring_device=str(device),
                  stability=dict(updates=steps, note="worker terminated while scoring; counters not recovered"))
    scored = score_arm(arm, seed, pack, evaluator, run_dir, device, None, steps)
    save_json(run_dir/"sampler_scores.json", {arm: scored})
    result.update(scored, samplers={arm: dict(S_arm=scored["S_arm"], S_real=scored["S_real_fresh"], C=scored["C_fresh"],
                                              auc=scored["c2st_derivative_auc"], eligible=scored["eligible"],
                                              gates=scored["gates"], latency=scored["latency"],
                                              wrist_Q=scored["prompted_validation"]["pools"]["wrist"]["Q"])})
    save_json(run_dir/"training_result.json", result)
    return result


def resume_final(a, output, pack):
    """Rebuild the final's benchmark from a run that trained every seed but died while scoring some of them."""
    import shutil
    source = next(Path(a.resume_from).rglob("FROZEN_ROUND10.json")).parent
    shutil.copy(source/"FROZEN_ROUND10.json", output/"FROZEN_ROUND10.json")
    shutil.copytree(source/"benchmark", output/"benchmark")
    frozen = json.loads((output/"FROZEN_ROUND10.json").read_text())
    arm = frozen["arm"]
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    from ml.kaggle_multidomain.experiment_v3 import PromptedEvaluator
    evaluator = PromptedEvaluator(development, a.eval_samples)
    device = "cpu" if a.allow_cpu else "cuda:0"
    rows, started = [], time.monotonic()
    for seed in frozen["seeds"]:
        run_dir = output/"benchmark"/f"{arm}_seed{seed}"
        done = run_dir/"training_result.json"
        rows.append(json.loads(done.read_text()) if done.exists() else
                    resume_row(arm, seed, development, evaluator, run_dir, device, frozen["steps"]))
        print("SCORED", arm, seed, round(rows[-1]["S_arm"], 4), flush=True)
    save_json(output/"benchmark"/"training_execution.json", dict(
        wall_seconds=time.monotonic()-started, resumed_from=str(source), steps=frozen["steps"], runs=rows,
        note="seeds without training_result.json were scored here, one at a time, after the final's worker pool died"))
    return arm, frozen["incumbent"], rows


def select_pilot(rows, go=None):
    """Lowest S_arm among eligible (arm, sampler) pairs of the seed-42 pilot; validation-derived fields only.
    With go limits only pairs within them can win, and go_final says whether any did (else no 3-seed final)."""
    candidates = [dict(arm=r["arm"], sampler=v, **s) for r in rows for v, s in r["samplers"].items()]
    eligible = [c for c in candidates if c["eligible"] and (go is None or (
        c["wrist_Q"] <= go["wrist_Q"] and c["S_arm"] <= go["S_arm"]))]
    winner = min(eligible, key=lambda c: c["S_arm"]) if eligible else None
    reason = "argmin S_arm over eligible (arm, sampler) pairs, seed 42"+(f" within {go}" if go else "")
    result = dict(winner=winner and winner["sampler"], base=winner and winner["arm"], candidates=candidates,
                  reason=reason if winner else "no eligible pair"+(f" within {go}" if go else ""),
                  criterion_sha256=CRITERION_SHA256)
    return dict(result, go_limits=go, go_final=winner is not None) if go else result


def final_devices(seeds, allow_cpu=False):
    """One worker per GPU, at most two; parallel() gives worker i the seeds i, i+2, ... so a third seed waits for
    the first worker. Three concurrent workers (two on one GPU) lost the round-10 pool while scoring."""
    return ["cpu"] if allow_cpu else ["cuda:0", "cuda:1"][:len(seeds)]


def incumbent_scores(root):
    """The shipped round-9 arm: per-seed S_arm, S_real and validation wrist Q from its own outputs."""
    from ml.kaggle_multidomain.experiment_v5 import scores
    path = next(p for p in Path(root).rglob("DECISION_ROUND5.json")
                if json.loads(p.read_text()).get("arm") == INCUMBENT_ARM)
    if not json.loads(path.read_text())["ship"]:
        raise ValueError("Round 9 did not ship; name the shipped incumbent explicitly")
    return dict(scores(path.parent/"benchmark"/"training_execution.json", INCUMBENT_ARM), name="round9_"+INCUMBENT_ARM)


def rule_text(arm, incumbent):
    base = base_of(arm)
    cfg = config(arm)
    finish = (f", stopped at t={cfg['t_end']:g} and finished with the data-view filter on a reflection-padded window"
              if cfg["finish_filter"] else "")
    return (f"PhysioFlow round-10 rule (validation only; locked criterion sha256 {CRITERION_SHA256}).\n"
            f"Arm {arm} = {DESCRIPTION[base]}; sampler {cfg['sample_steps']} Heun steps, guidance {cfg['guidance']:g}{finish}; "
            "chosen by the seed-42 pilot (validation S_arm).\n"
            "Gates: the round-3 gates (finite, no flat output, rho in [0.75, 1.25], TorchScript trace) with the flow "
            f"latency limit: median one-thread CPU time per 30 s window < {cfg['latency_limit_ms']:g} ms (Kaggle host).\n"
            f"Incumbent: {incumbent['name']} (app model), S_arm {incumbent['S_arm']}, S_real {incumbent['S_real_fresh']}, "
            f"validation wrist Q {incumbent['wrist_Q']}.\n"
            "PhysioFlow replaces it as the app's conditioned generator only if every seed passes the gates, its mean "
            "S_arm beats the incumbent's by more than the pooled seed SD of S_arm, its mean S_real is at most the "
            "incumbent's + 0.05, and its mean validation wrist Q is at most the incumbent's mean + the pooled seed SD "
            "of wrist Q (the round-9 wrist gain is kept); the shipped seed is its lowest-S_arm seed. Otherwise the "
            "incumbent stays. The GXU test is scored only after this decision is saved.")


def decide(rows, arm, incumbent):
    from ml.kaggle_multidomain.experiment_v5 import decide as decide_s_arm, pool_q
    result = decide_s_arm(rows, arm, incumbent)
    mine = [r for r in rows if r["arm"] == arm]
    own, theirs = stat([pool_q(r, "wrist") for r in mine]), stat(incumbent["wrist_Q"])
    pooled = math.sqrt(((own["sd"] or 0)**2+(theirs["sd"] or 0)**2)/2)
    wrist_ok = own["mean"] <= theirs["mean"]+pooled
    return dict(result, ship=bool(result["ship"] and wrist_ok), wrist_Q=own, incumbent_wrist_Q=theirs,
                wrist_pooled_sd=pooled, wrist_non_inferior=wrist_ok)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stage", choices=("pilot", "final"), required=True)
    parser.add_argument("--pilot-root", help="Directory holding PILOT_SELECTION_FLOW.json (final)")
    parser.add_argument("--incumbent-root", help="Directory holding the round-9 outputs (final)")
    parser.add_argument("--arms", nargs="+", default=list(FLOW_BASES), choices=list(FLOW_BASES))
    parser.add_argument("--resume-from", help="Final: a final run that trained every seed but died while scoring")
    parser.add_argument("--arm", help="Final: the sampler arm chosen across pilot loops (validation S_arm); "
                                      "default: the mounted pilot's winner")
    parser.add_argument("--samplers", nargs="+", help="Pilot sampler arms (default: every FLOW_SAMPLERS one)")
    parser.add_argument("--go", nargs="?", const="loop5", choices=tuple(GO),
                        help="Pilot: apply that loop's go limits (wrist Q, S_arm; bare --go = loop 5) to the winner; "
                             "final: refuse a pilot that did not pass them")
    parser.add_argument("--steps", type=int, default=12000)
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 2026])
    parser.add_argument("--batch", type=int, default=128)
    parser.add_argument("--interval", type=int, default=1500)
    parser.add_argument("--eval-samples", type=int, default=256)
    parser.add_argument("--bootstrap", type=int, default=200)
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and (len(names) != 2 or any("T4" not in name for name in names)):
        raise RuntimeError(f"Two T4 GPUs required, allocated {names}")
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    seal, sealed_count = sealed_subjects(pack)
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    save_json(output/"configuration.json", dict(args=vars(a), python=platform.python_version(), torch=torch.__version__,
              allocated_gpus=names, cpu_count=os.cpu_count(), data_sha256=manifest["windows_sha256"], view=VIEW,
              criterion_sha256=CRITERION_SHA256, gxu_test_subject_sha256=seal, gxu_test_subjects=sealed_count))
    if a.stage == "pilot":
        # One arm per GPU, concurrently; each worker scores its own arm's samplers on the same weights.
        jobs = [(arm, 42) for arm in a.arms]
        devices = ["cpu"] if a.allow_cpu else ["cuda:0", "cuda:1"][:len(jobs)]
        samplers = a.samplers or [s for arm in a.arms for s in sampler_arms(arm)]
        rows = parallel(jobs, devices, a.input_root, output/"pilot", a.steps, a.batch, a.interval, a.eval_samples,
                        dict(samplers=samplers), 2)
        selection = select_pilot(rows, GO[a.go] if a.go else None)
        save_json(output/"PILOT_SELECTION_FLOW.json", selection)
        save_json(output/"COMPLETE.json", dict(status="pilot_complete", winner=selection["winner"],
                  data_sha256=manifest["windows_sha256"], wall_seconds=time.monotonic()-started))
        print("PILOT COMPLETE", selection["winner"], flush=True)
        return
    if a.resume_from:
        arm, incumbent, rows = resume_final(a, output, pack)
        return finish_final(a, output, pack, manifest, arm, incumbent, rows, started)
    pilot = json.loads(next(Path(a.pilot_root).rglob("PILOT_SELECTION_FLOW.json")).read_text())
    if pilot["criterion_sha256"] != CRITERION_SHA256 or not (pilot["winner"] or a.arm):
        raise ValueError("Pilot used a different criterion or found no eligible PhysioFlow sampler")
    if a.go and not pilot.get("go_final"):
        raise ValueError("The pilot did not pass its go limits; no 3-seed final")
    arm = a.arm or pilot["winner"]
    if a.arm and a.arm not in {c["sampler"] for c in pilot["candidates"]}:
        pilot = dict(pilot, note=f"final arm {a.arm} chosen across pilot loops on validation S_arm; this mounted "
                                 "pilot is the latest loop")
    incumbent = incumbent_scores(a.incumbent_root)
    rule = rule_text(arm, incumbent)
    save_json(output/"FROZEN_ROUND10.json", dict(rule=rule, rule_sha256=hashlib.sha256(rule.encode()).hexdigest(),
              arm=arm, config=config(arm), incumbent=incumbent, seeds=a.seeds, steps=a.steps, batch=a.batch,
              data_sha256=manifest["windows_sha256"], gxu_test_subject_sha256=seal, pilot=pilot))
    devices = final_devices(a.seeds, a.allow_cpu)
    rows = parallel([(arm, seed) for seed in a.seeds], devices, a.input_root, output/"benchmark", a.steps, a.batch,
                    a.interval, a.eval_samples, dict(samplers=[arm]), 2)
    return finish_final(a, output, pack, manifest, arm, incumbent, rows, started)


def finish_final(a, output, pack, manifest, arm, incumbent, rows, started):
    devices = ["cpu"] if a.allow_cpu else ["cuda:0"]
    decision = decide(rows, arm, incumbent)
    save_json(output/"DECISION_ROUND10.json", decision)
    print("DECISION", arm, "ship", decision["ship"], flush=True)
    from ml.kaggle_multidomain.evaluate_v3 import evaluate_frozen
    from ml.kaggle_multidomain.report_v3 import figures
    results = evaluate_frozen(rows, pack, output/"benchmark", dict(arms=[arm], aliases={}), devices[0], a.bootstrap,
                              a.eval_samples)
    references = json.loads((output/"benchmark"/"references.json").read_text())
    summary = summarize(results)
    save_json(output/"summary.json", dict(arms=summary, decision=decision, references=references))
    figures(output, results, summary, references)
    s = summary[arm]
    (output/"REPORT_ROUND10.md").write_text("\n".join([
        f"# PhysioFlow round 10: {arm}", "",
        f"Thay model trong app: **{decision['ship']}** so với {incumbent['name']} (S_arm {fmt(decision['incumbent_S_arm'])}); "
        f"chênh {decision['gap']:.3f}, SD gộp {decision['pooled_sd']:.3f}; Q cổ tay {fmt(decision['wrist_Q'])} so với "
        f"{fmt(decision['incumbent_wrist_Q'])}.", "",
        f"S_arm {fmt(s['S_arm'])}, S_real {fmt(s['S_real'])}, C {fmt(s['C'])}, C2ST đạo hàm {fmt(s['c2st_derivative'])}, "
        f"C2ST raw {fmt(s['c2st_raw'])}, GXU test Q {fmt(s['gxu_test_Q'])} (test đã mở ở round 3; chỉ báo cáo).", "",
        "![Control](control_and_fresh_test.png)", "![Waveforms](waveforms_gxu.png)"])+"\n")
    save_json(output/"COMPLETE.json", dict(status="complete", arm=arm, ship=decision["ship"],
              data_sha256=manifest["windows_sha256"], wall_seconds=time.monotonic()-started, deployment="research_only"))
    print("COMPLETE", arm, flush=True)


if __name__ == "__main__":
    main()
