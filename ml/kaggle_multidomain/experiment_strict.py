"""Strict round: the app's two GANs retrained against stronger critics and judged by the strict judge.

PhysioMix (conditional, six domains): the shipped round-9 recipe (L3_rel_beat_lr_crop_r1w_motion_dom: same data,
seeds, learning-rate schedule, gates and checkpoint rule) with the critic replaced by strict_judge.StrictCritic, alone
and with the quiet generator revision (physio.PhysioMixR quiet/sensor: a low-passed trunk noise channel and an explicit
measurement-noise term). LSM-GAN (unconditional, BIDMC): the
author topology retrained on the v3 view with its released objective (lsm_author_v3) and LSM-GAN-S
(ml.kaggle_lsm.lsm_strict). Every model, the app's included, is scored by the judge kind chosen in the strict-judge
kernel (SELECTION_JUDGE.json, validation people), retrained from scratch against each source. RULE is saved before
training; the test people are judged only after DECISION_STRICT.json is saved, with fresh windows, prompts, generator
noise and judge seeds. The judges' real class comes from training people (every generator trained on all of them);
the judges are scored on validation or test people. The GAN critics and the evaluation judge share the three views but
never weights: each judge is trained after the generator is frozen.
Stages: train_physiomix and train_lsm (one Kaggle kernel each, T4x2), then judge (a third kernel mounting both
outputs); all runs every stage in one process (tests, CPU).
Engineering evaluation of normalised 30 s PPG shape; not clinical validation, not measured on the Pi/DAC/OPT101.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import shutil
import time

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import LENGTH, save_json
from ml.kaggle_multidomain import strict_judge as sj

INCUMBENT_ARM = "L3_rel_beat_lr_crop_r1w_motion_dom"
PHYSIOMIX_ARMS = (f"{INCUMBENT_ARM}_strict", f"{INCUMBENT_ARM}_strict_quiet")
LSM_ARMS = ("lsm_author_v3", "lsm_strict")
LSM_DOMAIN = "bidmc"
STAGES = ("all", "train_physiomix", "train_lsm", "judge")
# build_sets draw (strict_judge seed 0 was the selection kernel's) and judge-seed offsets per split.
SET_SEEDS, JUDGE_SEED_OFFSETS = dict(validation=1, test=2), dict(validation=10, test=20)
NULL_RANGE = (.4, .6)
# Diagnostic only (no decision): the app's PhysioFlow as shipped, and with white noise of this level (on its [0, 1]
# window) added before the reflection-padded data-view filter. The strict judge separated it only in 8-20 Hz (band-stop
# AUC 0.502); the level matches real training windows' 8-20 Hz power within 0.2 dB (training windows only).
FLOW_SENSOR_SIGMA = .03
# Round 9 (the shipped PhysioMix) per-seed validation scores at its chosen checkpoints, seeds 42/123/2026
# (ml/runs/physiomix9-motion-dom-result-v1/physiomix9/benchmark/training_execution.json).
INCUMBENT = dict(seeds=[42, 123, 2026], S_real=[0.3367, 0.3349, 0.3597], C=[0.0469, 0.0314, 0.0584])
RULE = ("Strict round rule, fixed before training (validation people only). PhysioMix arms train for the given steps or "
        "until the training deadline, whichever comes first. Score: pooled AUC of the selected strict judge between real "
        "windows of unseen validation people and the source's windows (eval fakes prompted with labels of training people "
        "the judge never saw), averaged over 3 judge seeds; lower is better; indistinguishable = 100(1-|2 mean AUC-1|). "
        "A family's comparison is valid only if its null control (real windows of other training people) has mean AUC in "
        "[0.40, 0.60]; otherwise that family ships nothing. PhysioMix: an arm ships only if every seed passes the "
        "round-3 gates, its mean AUC over the training seeds is below the app model's by more than max(0.02, the "
        "training-seed SD), its mean S_real is at most round 9's mean + 0.05 and its mean C at most round 9's mean + 0.05; "
        "among shipping arms the lowest mean AUC wins; the shipped seed is its lowest-AUC eligible seed. LSM-GAN (BIDMC "
        "only): the arm with the lower mean AUC is the candidate; it replaces the app's LSM-GAN only if its mean AUC is "
        "below the app model's by more than max(0.02, its training-seed SD); the shipped seed is its lowest-AUC seed. "
        "Test people are scored only after this decision is saved, with fresh windows, prompts, generator noise and "
        "judge seeds.")


def rule_sha256():
    return hashlib.sha256(RULE.encode()).hexdigest()


# ---------------------------------------------------------------- training
def lsm_job(device, arm, seed, input_root, output, lsm_steps):
    from ml.kaggle_lsm.lsm_multiset import train_gan
    from ml.kaggle_lsm.lsm_strict import train_strict
    from ml.kaggle_multidomain.data_gxu import load_input
    from ml.kaggle_multidomain.experiment_v3 import PROTOCOL
    pack, _ = load_input(input_root, PROTOCOL)
    rows = lambda split: pack["signal"][(pack["split"] == split) & (pack["domain"] == LSM_DOMAIN)]
    started = time.monotonic()
    if arm == "lsm_author_v3":
        g, history, best = train_gan(rows("train"), rows("validation"), "lsm_repo_corrected", "steps", seed, device)
    else:
        g, history, best = train_strict(rows("train"), rows("validation"), seed, device, dict(steps=lsm_steps))
    run_dir = Path(output)/"lsm"/f"{arm}_seed{seed}"
    run_dir.mkdir(parents=True)
    z = torch.randn(3, LENGTH, generator=torch.Generator().manual_seed(seed))
    traced = torch.jit.trace(g, z[:2])
    torch.testing.assert_close(traced(z), g(z))
    traced.save(str(run_dir/"generator_cpu.ts"))
    save_json(run_dir/"history.json", history)
    return dict(family="lsm", arm=arm, seed=seed, best_step=best["step"], selection=best["selection"],
                generator_parameters=sum(p.numel() for p in g.parameters()), training_seconds=time.monotonic()-started,
                training_device=device, generator=f"lsm/{arm}_seed{seed}/generator_cpu.ts")


def device_worker(device, jobs, input_root, output, steps, lsm_steps, interval, n, threads, deadline):
    from ml.kaggle_multidomain import experiment_v3
    torch.set_num_threads(threads)
    rows = []
    for family, arm, seed in jobs:
        if family == "physiomix":
            rows += [dict(r, family="physiomix") for r in experiment_v3.worker(
                device, [(arm, seed)], input_root, Path(output)/"benchmark", steps, 32, interval, n, None, threads,
                deadline)]
        else:
            rows.append(lsm_job(device, arm, seed, input_root, output, lsm_steps))
        print("TRAINED", family, arm, seed, flush=True)
    return rows


def training_jobs(stage, seeds):
    physiomix = [("physiomix", arm, s) for arm in PHYSIOMIX_ARMS for s in seeds]
    lsm = [("lsm", arm, s) for arm in LSM_ARMS for s in seeds]
    return dict(all=physiomix+lsm, train_physiomix=physiomix, train_lsm=lsm, judge=[])[stage]


def groups(jobs, devices):
    """(device, jobs) per worker process: one process per PhysioMix run, alternating GPUs; the LSM runs (short) split
    into one sequential process per GPU."""
    if devices == ["cpu"]:
        return [("cpu", jobs)] if jobs else []
    physiomix = [j for j in jobs if j[0] == "physiomix"]
    lsm = [j for j in jobs if j[0] == "lsm"]
    out = [(devices[i % len(devices)], [job]) for i, job in enumerate(physiomix)]
    return out+[(d, lsm[i::len(devices)]) for i, d in enumerate(devices) if lsm[i::len(devices)]]


def train_all(jobs, devices, input_root, output, steps, lsm_steps, interval, n, deadline):
    work = groups(jobs, devices)
    # Kaggle's T4x2 machine has 4 CPU cores.
    threads = 1 if len(work) > 2 else 2
    if devices == ["cpu"]:
        return device_worker("cpu", work[0][1], input_root, output, steps, lsm_steps, interval, n, threads, deadline) \
            if work else []
    rows = []
    with ProcessPoolExecutor(len(work), mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(device_worker, d, jobs, input_root, output, steps, lsm_steps, interval, n, threads,
                               deadline) for d, jobs in work]
        for future in as_completed(futures):
            rows.extend(future.result())
            save_json(Path(output)/"training_progress.json", rows)
    return rows


# A training stage's frozen values that the judge stage must share.
SHARED = ("steps", "lsm_steps", "hours", "seeds", "physiomix_arms", "lsm_arms", "data_sha256")


def collect_training(root, expected=None):
    """Training rows of every training stage below root, with their run folders resolved; each stage must have frozen
    this RULE, finished (COMPLETE.json) and, given expected (the judge stage's frozen values), share its SHARED values."""
    rows = []
    for path in sorted(Path(root).rglob("training_execution.json")):
        frozen = path.parent/"FROZEN_STRICT.json"
        if not frozen.exists():
            continue
        frozen = json.loads(frozen.read_text())
        if frozen["rule_sha256"] != rule_sha256():
            raise ValueError(f"{path.parent}: trained under a different strict rule")
        if expected is not None:
            differ = [k for k in SHARED if frozen.get(k) != expected[k]]
            if differ:
                raise ValueError(f"{path.parent}: training {differ} differ from this stage's")
        complete = path.parent/"COMPLETE.json"
        if frozen.get("stage") != "all" and not (complete.exists() and json.loads(complete.read_text())["status"] == "complete"):
            raise ValueError(f"{path.parent}: training stage did not complete")
        for r in json.loads(path.read_text()):
            location = (path.parent/"benchmark"/f"{r['arm']}_seed{r['seed']}" if r["family"] == "physiomix"
                        else path.parent/r["generator"])
            rows.append(dict(r, location=str(location)))
    keys = [(r["family"], r["arm"], r["seed"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate training runs below the input root")
    return rows


# ---------------------------------------------------------------- sources
def app_sources(bundle, bank, device):
    """The app's TorchScript files (physiomix_app, lsm_app, and physioflow_app when the bundle has it), checked against
    the manifest's sha256 and condition schema."""
    bundle = Path(bundle)
    manifest = json.loads((bundle/"manifest.json").read_text())
    conditional = [s for s in ("physiomix", "physioflow") if f"{s}_generator" in manifest["models"]]
    for slot in conditional:
        meta = manifest[slot]
        if meta["domains"] != bank.domains or not np.allclose(meta["center"], bank.center, rtol=1e-5) \
                or not np.allclose(meta["scale"], bank.scale, rtol=1e-5):
            raise ValueError(f"{slot}: app condition schema differs from the v3 pack's")
    for slot in conditional+["lsm"]:
        entry = manifest["models"][f"{slot}_generator"]
        if hashlib.sha256((bundle/entry["file"]).read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"{slot}_generator checksum mismatch")
    out = {f"{s}_app": sj.torchscript_generator(bundle/manifest["models"][f"{s}_generator"]["file"], device,
                                                len(bank.domains)+5) for s in conditional}
    # The app emits the LSM-GAN's raw output (core/neural_preview.py); it is judged as emitted, like the candidates.
    out["lsm_app"] = unconditional_generator(bundle/manifest["models"]["lsm_generator"]["file"])
    return out


def sensor_finished(generate, sigma=FLOW_SENSOR_SIGMA):
    """generate's windows plus white noise of level sigma, through the reflection-padded data-view filter, renormalised."""
    from ml.kaggle_multidomain.flow import FINISH_PAD, finish
    from ml.kaggle_multidomain.physio import view_mask
    band = torch.tensor(view_mask("v3", LENGTH+2*FINISH_PAD))

    def wrapped(ids, conditions, seed):
        x = torch.from_numpy(generate(ids, conditions, seed))[:, None]
        noise = torch.randn(x.shape, generator=torch.Generator().manual_seed(seed+7))
        return sj.normalise(finish(x+sigma*noise, band)[:, 0].numpy())
    return wrapped


def checkpoint_generator(run_dir, arm, bank, device):
    from ml.kaggle_multidomain.experiment_v3 import load_best, sampler
    model, cfg = load_best(arm, Path(run_dir), bank.conditions, None, device)
    run = sampler(model, cfg, device)

    def generate(ids, conditions, seed):
        z = torch.randn(len(ids), LENGTH, generator=torch.Generator().manual_seed(seed))
        return run(z, conditions.for_ids(ids)).astype(np.float32)
    return generate


def unconditional_generator(path):
    model = torch.jit.load(str(path), map_location="cpu").eval()

    def generate(ids, conditions, seed):
        z = torch.randn(len(ids), LENGTH, generator=torch.Generator().manual_seed(seed))
        with torch.inference_mode():
            return torch.cat([model(part) for part in z.split(256)])[:, 0].numpy().astype(np.float32)
    return generate


def judge_family(pack, bank, generators, split, domains, kinds, seeds, devices, folder):
    folder.mkdir(parents=True)
    arrays, info = sj.build_sets(pack, bank, generators, split, seed=SET_SEEDS[split], domains=domains,
                                 controls=("real_other_people",), eval_prompts="control_eval")
    save_json(folder/"sets.json", dict(counts=info["counts"], people={k: len(v) for k, v in info["people"].items()},
                                       set_seed=SET_SEEDS[split]))
    path = Path("/tmp" if Path("/tmp").exists() and devices != ["cpu"] else folder)/f"strict_{folder.name}.npz"
    np.savez(path, **arrays)
    jobs = [(kind, name, s+JUDGE_SEED_OFFSETS[split]) for s in seeds for kind in kinds
            for name in [*generators, "real_other_people"]]
    jobs.sort(key=lambda j: j[0] == "probe")
    rows = sj.run_jobs(jobs, devices, path, folder, bands=False)
    path.unlink()
    save_json(folder/"judges.json", rows)
    return rows


# ---------------------------------------------------------------- decision
def mean_auc(rows, judge, name):
    values = [r["auc"] for r in rows if r["judge"] == judge and r["source"] == name]
    if not values:
        raise ValueError(f"No {judge} rows for {name}")
    return float(np.mean(values))


def spread(values):
    return float(np.std(values, ddof=1)) if len(values) > 1 else 0.


def null_control(rows, judge):
    value = mean_auc(rows, judge, "real_other_people")
    return dict(auc=value, valid=bool(NULL_RANGE[0] <= value <= NULL_RANGE[1]))


def decide(physiomix_val, lsm_val, training, judge, seeds):
    physiomix_app = mean_auc(physiomix_val, judge, "physiomix_app")
    arms = {}
    for arm in PHYSIOMIX_ARMS:
        mine = sorted((r for r in training if r["family"] == "physiomix" and r["arm"] == arm), key=lambda r: r["seed"])
        auc = {r["seed"]: mean_auc(physiomix_val, judge, f"{arm}_seed{r['seed']}") for r in mine}
        values = list(auc.values())
        margin = max(.02, spread(values))
        s_real, c = float(np.mean([r["S_real_fresh"] for r in mine])), float(np.mean([r["C_fresh"] for r in mine]))
        eligible = bool(mine) and all(r["eligible"] for r in mine)
        checks = dict(eligible=eligible, auc_gain=physiomix_app-float(np.mean(values)) > margin,
                      s_real_ok=s_real <= float(np.mean(INCUMBENT["S_real"]))+.05,
                      c_ok=c <= float(np.mean(INCUMBENT["C"]))+.05)
        ships = [r["seed"] for r in mine if r["eligible"]]
        arms[arm] = dict(auc_by_seed=auc, mean_auc=float(np.mean(values)), margin=margin, S_real=s_real, C=c,
                         checks=checks, ship=all(checks.values()),
                         ship_seed=min(ships, key=lambda s: auc[s]) if ships else None)
    null = null_control(physiomix_val, judge)
    shipping = [a for a in arms if arms[a]["ship"]] if null["valid"] else []
    physiomix = dict(app_auc=physiomix_app, null_control=null, arms=arms,
                     winner=min(shipping, key=lambda a: arms[a]["mean_auc"]) if shipping else None)
    lsm_app = mean_auc(lsm_val, judge, "lsm_app")
    candidates = {}
    for arm in LSM_ARMS:
        auc = {s: mean_auc(lsm_val, judge, f"{arm}_seed{s}") for s in seeds}
        candidates[arm] = dict(auc_by_seed=auc, mean_auc=float(np.mean(list(auc.values()))),
                               margin=max(.02, spread(list(auc.values()))), ship_seed=min(auc, key=auc.get))
    best = min(candidates, key=lambda a: candidates[a]["mean_auc"])
    null = null_control(lsm_val, judge)
    gain = lsm_app-candidates[best]["mean_auc"] > candidates[best]["margin"]
    lsm = dict(app_auc=lsm_app, null_control=null, arms=candidates, candidate=best,
               winner=best if gain and null["valid"] else None)
    return dict(judge=judge, rule_sha256=rule_sha256(), physiomix=physiomix, lsm=lsm)


def indistinguishable(rows, judge):
    names = sorted({r["source"] for r in rows if r["judge"] == judge})
    return {n: dict(auc=mean_auc(rows, judge, n), auc_sd=spread([r["auc"] for r in rows if r["judge"] == judge
                                                                  and r["source"] == n]),
                    indistinguishable=100*(1-abs(2*mean_auc(rows, judge, n)-1))) for n in names}


# ---------------------------------------------------------------- main
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True,
                        help="v3 pack, app model files, SELECTION_JUDGE.json and (judge stage) the training outputs")
    parser.add_argument("--output", required=True)
    parser.add_argument("--stage", choices=STAGES, default="all")
    parser.add_argument("--judge", help="Judge kind; default: SELECTION_JUDGE.json's best below --input-root")
    parser.add_argument("--steps", type=int, default=20000)
    parser.add_argument("--lsm-steps", type=int, default=8000)
    parser.add_argument("--hours", type=float, default=10.,
                        help="Training deadline after the stage starts (Kaggle stops a session at 12 h)")
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 2026])
    parser.add_argument("--judge-seeds", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--interval", type=int, default=500)
    parser.add_argument("--eval-samples", type=int, default=256)
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    from ml.kaggle_multidomain.data_gxu import load_input
    from ml.kaggle_multidomain.experiment_v3 import PROTOCOL, check_pack, conditions_for
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and len(names) != 2:
        raise RuntimeError(f"Two GPUs required, allocated {names}")
    devices = ["cpu"] if a.allow_cpu else ["cuda:0", "cuda:1"]
    judge = a.judge
    if judge is None:
        selection = json.loads(next(Path(a.input_root).rglob("SELECTION_JUDGE.json")).read_text())
        judge = selection["best"]
    if judge not in sj.JUDGES:
        raise ValueError(f"Unknown judge {judge}")
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started, deadline = time.monotonic(), time.time()+3600*a.hours
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    frozen = dict(rule=RULE, rule_sha256=rule_sha256(), stage=a.stage, judge=judge, judge_spec=sj.JUDGES[judge],
                  physiomix_arms=list(PHYSIOMIX_ARMS), lsm_arms=list(LSM_ARMS), incumbent=INCUMBENT, seeds=a.seeds,
                  judge_seeds=a.judge_seeds, set_seeds=SET_SEEDS, judge_seed_offsets=JUDGE_SEED_OFFSETS, steps=a.steps,
                  lsm_steps=a.lsm_steps, hours=a.hours, data_sha256=manifest["windows_sha256"])
    save_json(output/"FROZEN_STRICT.json", frozen)
    save_json(output/"configuration.json", dict(args=vars(a), python=platform.python_version(), torch=torch.__version__,
              allocated_gpus=names, cpu_count=os.cpu_count()))
    jobs = training_jobs(a.stage, a.seeds)
    if jobs:
        if any(j[0] == "physiomix" for j in jobs):
            (output/"benchmark").mkdir()
        training = train_all(jobs, devices, a.input_root, output, a.steps, a.lsm_steps, a.interval, a.eval_samples,
                             deadline)
        save_json(output/"training_execution.json", training)
        print("TRAINING DONE", a.stage, f"{time.monotonic()-started:.0f}s", flush=True)
    if a.stage not in ("all", "judge"):
        save_json(output/"COMPLETE.json", dict(status="complete", stage=a.stage, wall_seconds=time.monotonic()-started))
        return None

    training = collect_training(output if a.stage == "all" else a.input_root, frozen)
    expected = {(f, arm, s) for f, arm, s in training_jobs("all", a.seeds)}
    if {(r["family"], r["arm"], r["seed"]) for r in training} != expected:
        raise ValueError("Training outputs do not match the frozen arms and seeds")
    pack = {k: v[pack["split"] != "external"] for k, v in pack.items()}
    keep = np.flatnonzero(np.isin(pack["split"], ["train", "validation"]))
    bank = sj.ConditionsView(conditions_for({k: v[keep] for k, v in pack.items()}, "v2"), keep)
    bundle = next(p.parent for p in Path(a.input_root).rglob("manifest.json") if (p.parent/"physiomix_generator.ts").exists())
    apps = app_sources(bundle, bank, devices[0])
    physiomix_app, lsm_app = apps["physiomix_app"], apps["lsm_app"]
    diagnostics = {}
    if "physioflow_app" in apps:
        diagnostics = dict(physioflow_app=apps["physioflow_app"], physioflow_sensor=sensor_finished(apps["physioflow_app"]))
    where = {(r["family"], r["arm"], r["seed"]): Path(r["location"]) for r in training}

    def physiomix_sources(arms, seeds, extra=None):
        out = dict(physiomix_app=physiomix_app, **(extra or {}))
        out.update({f"{arm}_seed{s}": checkpoint_generator(where[("physiomix", arm, s)], arm, bank, devices[0])
                    for arm in arms for s in seeds})
        return out

    def lsm_sources(arms, seeds):
        out = dict(lsm_app=lsm_app)
        out.update({f"{arm}_seed{s}": unconditional_generator(where[("lsm", arm, s)]) for arm in arms for s in seeds})
        return out

    kinds = [judge]+(["probe"] if judge != "probe" else [])
    val = output/"validation"
    physiomix_val = judge_family(pack, bank, physiomix_sources(PHYSIOMIX_ARMS, a.seeds, diagnostics), "validation",
                                 sj.DOMAINS, kinds, a.judge_seeds, devices, val/"physiomix")
    lsm_val = judge_family(pack, bank, lsm_sources(LSM_ARMS, a.seeds), "validation", (LSM_DOMAIN,), kinds,
                           a.judge_seeds, devices, val/"lsm")
    decision = decide(physiomix_val, lsm_val, training, judge, a.seeds)
    save_json(output/"DECISION_STRICT.json", decision)
    print("DECISION", json.dumps(dict(physiomix=decision["physiomix"]["winner"], lsm=decision["lsm"]["winner"])), flush=True)

    # Test people, opened once: the app models and every seed of each family's best arm.
    best_physiomix = decision["physiomix"]["winner"] or min(decision["physiomix"]["arms"],
                                                            key=lambda arm: decision["physiomix"]["arms"][arm]["mean_auc"])
    test = output/"test"
    physiomix_test = judge_family(pack, bank, physiomix_sources([best_physiomix], a.seeds), "test", sj.DOMAINS, kinds,
                                  a.judge_seeds, devices, test/"physiomix")
    lsm_test = judge_family(pack, bank, lsm_sources([decision["lsm"]["candidate"]], a.seeds), "test", (LSM_DOMAIN,),
                            kinds, a.judge_seeds, devices, test/"lsm")
    ship = output/"ship"
    ship.mkdir()
    if decision["physiomix"]["winner"]:
        arm = decision["physiomix"]["winner"]
        seed = decision["physiomix"]["arms"][arm]["ship_seed"]
        shutil.copy2(where[("physiomix", arm, seed)]/"generator_cpu.ts", ship/"physiomix_generator.ts")
    if decision["lsm"]["winner"]:
        arm = decision["lsm"]["winner"]
        shutil.copy2(where[("lsm", arm, decision["lsm"]["arms"][arm]["ship_seed"])], ship/"lsm_generator.ts")
    summary = dict(judge=judge, decision=decision,
                   validation={k: {"physiomix": indistinguishable(physiomix_val, k), "lsm": indistinguishable(lsm_val, k)}
                               for k in kinds},
                   test={k: {"physiomix": indistinguishable(physiomix_test, k), "lsm": indistinguishable(lsm_test, k)}
                         for k in kinds},
                   wall_seconds=time.monotonic()-started)
    save_json(output/"summary.json", summary)
    save_json(output/"COMPLETE.json", dict(status="complete", stage=a.stage, physiomix=decision["physiomix"]["winner"],
              lsm=decision["lsm"]["winner"], wall_seconds=time.monotonic()-started, deployment="research_only"))
    print("COMPLETE", flush=True)
    return summary


if __name__ == "__main__":
    main()
