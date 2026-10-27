"""P5 round: PhysioGAN-R (a GAN trained from scratch on the R records, physiogan_r) against the R1 family, aiming at
the real-vs-real strict-judge level (AUC near 0.5; the real_other_people null sits at ~0.45).

Why: P4 moved the wrong way (strict AUC 0.73 -> 0.97): its 4-step student was pulled to a frozen flow teacher, and its
checkpoints were chosen on S_real + 0.5C, not realism. P5 keeps the strict judge as it is and changes the generator:
- G4_physiogan_r (seeds 42/123/2026): one-pass generator of the 40 s record ending in the v3 band-pass applied once
  (flow_r.RView), relativistic pairing loss with R1/R2 penalties, the judge's views as the critic, conditioned on
  domain and record context only (heart rate / SpO2 set aside), checkpoint on a selection C2ST of training people;
- the R1 fallback, all from the P1 ship seed (sha256 frozen): r1_s16 (as shipped), r1_s32 and r1_s64 (same weights,
  more Heun steps; the P4 diagnosis measured 0.90 / 0.82 / 0.75 at 4 / 8 / 16 steps) and r1f_s64 (R1 trained further
  with its own flow loss, checkpoint on S_real alone, experiment_v3 R1F_flowr_ft, judged at 64 steps).
A copy gate guards the way a generator can pass a C2ST without generalising: replaying training windows.
Two kernels (P5 v2): the train stage trains, runs the copy check and the direct waveform comparison
(waveform_compare: PREVIEW_P5.json, figures, samples) and stops; the user and the agent review it; only then does the
judge stage (mounting the train stage's output) run the judges. Every source, the real_other_people null and the r_pipeline null are judged by the strict judge from scratch, on the
validation people for the decision and once on the test people after DECISION_P5.json.
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
from ml.kaggle_multidomain.experiment_strict import indistinguishable, judge_family, mean_auc, spread

JUDGE = "strict"
GAN = "G4_physiogan_r"
R1F, R1F_SEED = "R1F_flowr_ft", 42
R1_SOURCES = {"r1_s16": ("r1", 16), "r1_s32": ("r1", 32), "r1_s64": ("r1", 64), "r1f_s64": ("r1f", 64)}
INCUMBENT = "r1_s16"
VALID_RANGE = (.40, .60)
TARGET = .55
COPY_LIMIT, COPY_PER_DOMAIN, COPY_SEED = .05, 128, 20261027
KERNEL_HOURS, PREVIEW_RESERVE_HOURS = 12., 1.5
RULE = ("P5 round rule, fixed before training; validation people only. Goal: strict-judge AUC near the real-vs-real "
        "level; target AUC <= 0.55. Sources judged by the strict judge (judge seeds 0-2 + offset): real_other_people, "
        "r_pipeline, r1_s16 (the P1 ship seed, sha256 in FROZEN_P5.json, 16 Heun steps), r1_s32 and r1_s64 (same "
        "weights, 32 / 64 steps), r1f_s64 (that R1 trained further with its own flow loss, checkpoint on S_real alone, "
        "64 steps) and G4_physiogan_r seeds 42/123/2026 (PhysioGAN-R: one-pass GAN generator of the R record through "
        "the record-context v3 view, relativistic pairing loss with R1/R2 penalties, the judge's views plus the 7-14 Hz "
        "band as critic at half the generator's learning rate behind adaptive augmentation (ADA, r_t target 0.6), "
        "domain and record context only, checkpoint on a selection C2ST of training people). The strict judge is "
        "not changed. The judge stage runs after a review of the train stage's direct waveform comparison. "
        "Validity: the "
        "real_other_people and r_pipeline mean AUC both lie in [0.40, 0.60]; otherwise no claim. Copy gate: a source "
        "passes if at most 5% of its windows (128 per domain, prompted by training windows) lie closer (RMS, v3 view) "
        "to a training window of their domain than that domain's 1st percentile of training windows' distance to "
        "their nearest training window of another record. R1 fallback: best_r1 is r1_s16 unless the copy-passing "
        "variant with the lowest AUC is below it by more than max(0.02, the larger judge-seed SD of the two). "
        "PhysioGAN-R is kept if the round is valid, every seed passes the copy gate and its mean AUC over seeds is below "
        "best_r1's by more than max(0.02, seed SD); its ship seed is the copy-passing seed with the lowest AUC. "
        "Otherwise the kept model is best_r1. Target met if the kept model's AUC (PhysioGAN-R: mean over seeds) <= 0.55. "
        "Heart-rate / SpO2 control is not part of this round (C not measured). The test people are judged once, after "
        "DECISION_P5.json. indistinguishable = 100(1-|2AUC-1|).")


def rule_sha256():
    return hashlib.sha256(RULE.encode()).hexdigest()


def gan_names(seeds):
    return [f"{GAN}_seed{s}" for s in seeds]


# ---------------------------------------------------------------- training
def device_jobs(device, jobs, input_root, output, job_hours, deadline, steps, interval, n, teacher_root):
    """Jobs in turn on one device, each with its own job_hours, none past the kernel's deadline."""
    from ml.kaggle_multidomain import experiment_v3, physiogan_r
    rows = []
    for arm, seed in jobs:
        stop = min(time.time()+3600*job_hours, deadline)
        if arm == GAN:
            rows.append(physiogan_r.train(seed, input_root, output, device, stop))
        else:
            rows += experiment_v3.worker(device, [(arm, seed)], input_root, output, steps, 32, interval, n, None, 2,
                                         stop, [input_root, teacher_root])
    return rows


def plan(seeds, devices):
    """GPU 0: PhysioGAN-R seeds 0 and 2; GPU 1: PhysioGAN-R seed 1, then R1F (each job about the same hours)."""
    jobs = [(GAN, s) for s in seeds]+[(R1F, R1F_SEED)]
    if devices == ["cpu"]:
        return {"cpu": jobs}
    return {d: jobs[i::len(devices)] for i, d in enumerate(devices)}


def train_all(seeds, devices, input_root, output, job_hours, deadline, steps, interval, n, teacher_root):
    args = (input_root, output, job_hours, deadline, steps, interval, n, teacher_root)
    work = plan(seeds, devices)
    if devices == ["cpu"]:
        rows = device_jobs("cpu", work["cpu"], *args)
    else:
        rows = []
        with ProcessPoolExecutor(len(devices), mp_context=multiprocessing.get_context("spawn")) as pool:
            futures = [pool.submit(device_jobs, d, jobs, *args) for d, jobs in work.items()]
            for future in as_completed(futures):
                rows.extend(future.result())
                save_json(Path(output)/"training_progress.json", rows)
    done = sorted((r["arm"], r["seed"]) for r in rows)
    if done != sorted(j for jobs in work.values() for j in jobs):
        raise RuntimeError(f"Missing or duplicate training runs: {done}")
    return rows


# ---------------------------------------------------------------- sources
def r1_sources(teacher_root, run_dir, bank, device):
    """{r1_*: generate} on the P1 ship seed's weights and the R1F run's best checkpoint, at each source's steps."""
    from ml.kaggle_multidomain.experiment_v3 import config, load_best
    from ml.kaggle_multidomain.flow_r import FlowGeneratorR, teacher_state_r
    teacher = teacher_state_r([teacher_root])
    c = bank.conditions
    r1 = FlowGeneratorR(c.bank.shape[1], c.center, c.scale, len(c.domains), teacher["contexts"], teacher["cdf"],
                        width=config("R1_flowr")["width"])
    r1.flow.net.load_state_dict(teacher["net"])
    weights = dict(r1=r1.eval(), r1f=load_best(R1F, Path(run_dir), c, None, "cpu")[0].eval())

    def make(which, steps):
        model = weights[which]

        @torch.no_grad()
        def generate(ids, conditions, seed):
            model.flow.sample_steps = steps
            model.to(device)
            z = torch.randn(len(ids), LENGTH, generator=torch.Generator().manual_seed(seed))
            rows = torch.as_tensor(np.asarray(conditions.for_ids(ids), np.float32))
            out = [model(a.to(device), b.to(device)).cpu() for a, b in zip(z.split(64), rows.split(64))]
            return torch.cat(out).numpy()[:, 0].astype(np.float32)
        return generate
    return {name: make(*spec) for name, spec in R1_SOURCES.items()}, weights


def copy_check(pack, bank, sources, seed=COPY_SEED):
    """(COPY_P5.json, {source: (windows, domains)}): every source's copy rate on windows prompted by training windows
    (COPY_PER_DOMAIN per domain), and the validation people's real windows as the reference (a real held-out set
    copies nothing). The windows are the preview's samples."""
    from ml.kaggle_multidomain.physiogan_r import copy_rate
    rng = np.random.default_rng(seed)
    train = np.flatnonzero((pack["split"] == "train") & np.isin(pack["domain"], sj.DOMAINS))
    held = np.flatnonzero((pack["split"] == "validation") & np.isin(pack["domain"], sj.DOMAINS))
    ids = sj.sample(pack, train, COPY_PER_DOMAIN, rng)
    reference = sj.sample(pack, held, COPY_PER_DOMAIN, rng, replace=False)
    base = (pack["signal"][train], pack["domain"][train], pack["record"][train])
    out = dict(limit=COPY_LIMIT, per_domain=COPY_PER_DOMAIN,
               validation_people=copy_rate(pack["signal"][reference], pack["domain"][reference], *base))
    windows = {}
    for g, (name, generate) in enumerate(sources.items()):
        windows[name] = (generate(ids, bank, seed+g), pack["domain"][ids])
        out[name] = copy_rate(*windows[name], *base)
        out[name]["passed"] = bool(out[name]["rate"] <= COPY_LIMIT)
        print("copy", name, f"{out[name]['rate']:.3f}", flush=True)
    return out, windows


# ---------------------------------------------------------------- decision
def seed_sd(rows, name):
    return spread([r["auc"] for r in rows if r["judge"] == JUDGE and r["source"] == name])


def decide(val, copies, seeds):
    names = gan_names(seeds)
    auc = {n: mean_auc(val, JUDGE, n) for n in [*R1_SOURCES, *names, "real_other_people", "r_pipeline"]}
    valid = dict(null=bool(VALID_RANGE[0] <= auc["real_other_people"] <= VALID_RANGE[1]),
                 pipeline=bool(VALID_RANGE[0] <= auc["r_pipeline"] <= VALID_RANGE[1]))
    passed = {n: copies[n]["passed"] for n in [*R1_SOURCES, *names]}
    best_r1 = INCUMBENT
    variants = [n for n in R1_SOURCES if n != INCUMBENT and passed[n]]
    if variants:
        challenger = min(variants, key=auc.get)
        margin = max(.02, seed_sd(val, challenger), seed_sd(val, INCUMBENT))
        if auc[challenger] < auc[INCUMBENT]-margin:
            best_r1 = challenger
    gan = float(np.mean([auc[n] for n in names]))
    gan_margin = max(.02, spread([auc[n] for n in names]))
    checks = dict(valid=all(valid.values()), copy_gate=all(passed[n] for n in names),
                  auc_gain=gan < auc[best_r1]-gan_margin)
    shippable = [s for s in seeds if passed[f"{GAN}_seed{s}"]]
    keep_gan = all(checks.values())
    kept = GAN if keep_gan else best_r1
    kept_auc = gan if keep_gan else auc[best_r1]
    return dict(judge=JUDGE, rule_sha256=rule_sha256(), auc=auc, auc_sd={n: seed_sd(val, n) for n in auc},
                validity=valid, copy_passed=passed, best_r1=best_r1, physiogan_mean_auc=gan,
                physiogan_margin=gan_margin, checks=checks, kept=kept, kept_auc=kept_auc,
                ship_seed=min(shippable, key=lambda s: auc[f"{GAN}_seed{s}"]) if keep_gan else None,
                target=TARGET, target_met=bool(all(valid.values()) and kept_auc <= TARGET),
                gap_to_null=kept_auc-auc["real_other_people"])


def ship(decision, output, run_dir, weights, bank):
    """ship/: the kept model's file and SHIP.json (what it is, its steps or seed, its sha256)."""
    folder = Path(output)/"ship"
    folder.mkdir()
    if decision["kept"] == GAN:
        name = f"physiogan_r_seed{decision['ship_seed']}.pt"
        shutil.copy2(Path(run_dir)/f"{GAN}_seed{decision['ship_seed']}"/"best.pt", folder/name)
        info = dict(kind="physiogan_r_state_dict", seed=decision["ship_seed"])
    else:
        which, steps = R1_SOURCES[decision["kept"]]
        model = weights[which].cpu()
        model.flow.sample_steps = steps
        c = bank.conditions
        rows = torch.as_tensor(c.for_ids(c.ids[:2]))
        name = "physioflow_r_generator.ts"
        model.export(torch.randn(2, LENGTH), rows).save(str(folder/name))
        info = dict(kind="physioflow_r_torchscript", weights=which, sample_steps=steps)
    info.update(source=decision["kept"], file=name, sha256=hashlib.sha256((folder/name).read_bytes()).hexdigest(),
                deployment="research_only")
    save_json(folder/"SHIP.json", info)
    return info


def frozen_round(input_root):
    """The P5 train stage's output under input_root (its FROZEN_P5.json), checked against this rule."""
    paths = sorted(Path(input_root).rglob("FROZEN_P5.json"))
    if len(paths) != 1:
        raise ValueError(f"Expected one FROZEN_P5.json, found {len(paths)}")
    frozen = json.loads(paths[0].read_text())
    if frozen["rule_sha256"] != rule_sha256():
        raise ValueError("The train stage froze another P5 rule")
    if not (paths[0].parent/"PREVIEW_P5.json").exists():
        raise ValueError("The train stage did not finish its preview")
    return paths[0].parent, frozen


def preview(output, pack, bank, sources, run_dir):
    """Before any judge: the copy check and the direct waveform comparison (waveform_compare) of every source
    against the validation people's real windows, with training people's real windows as the real-vs-real row."""
    from ml.kaggle_multidomain import waveform_compare
    copies, windows = copy_check(pack, bank, {k: v for k, v in sources.items() if k != "r_pipeline"})
    save_json(output/"COPY_P5.json", copies)
    rng = np.random.default_rng(COPY_SEED+1)
    train = np.flatnonzero((pack["split"] == "train") & np.isin(pack["domain"], sj.DOMAINS))
    held = np.flatnonzero((pack["split"] == "validation") & np.isin(pack["domain"], sj.DOMAINS))
    target = sj.sample(pack, held, COPY_PER_DOMAIN, rng, replace=False)
    reference = sj.sample(pack, train, COPY_PER_DOMAIN, rng, replace=False)
    nearest = {n: float(np.median([v["median"] for v in c["per_domain"].values()])) for n, c in copies.items()
               if n in windows}
    result = waveform_compare.report(output/"preview", windows, pack["signal"][target], pack["domain"][target],
                                     pack["signal"][reference], pack["domain"][reference], nearest)
    balance = {}
    for path in sorted(Path(run_dir).glob(f"{GAN}_seed*/balance.json")):
        trace = json.loads(path.read_text())
        balance[path.parent.name] = dict(last=trace[-1] if trace else None, steps=len(trace))
    out = dict(rule_sha256=rule_sha256(), summary=result["summary"], copy={n: c["rate"] for n, c in copies.items()
                                                                           if n in windows},
               balance=balance, figures=result["figures"], note="descriptive; the judge stage runs only after review")
    save_json(output/"PREVIEW_P5.json", out)
    return out


def sources_for(round_dir, r, pack, bank, seeds, device):
    from ml.kaggle_multidomain import physiogan_r
    from ml.kaggle_multidomain.flow_r import r_pipeline_source
    run_dir = Path(round_dir)/"benchmark"
    r1, weights = r1_sources(Path(round_dir)/"teacher", run_dir/f"{R1F}_seed{R1F_SEED}", bank, device)
    sources = {"r_pipeline": r_pipeline_source(r, pack), **r1}
    sources.update({f"{GAN}_seed{s}": physiogan_r.generator(run_dir/f"{GAN}_seed{s}", device) for s in seeds})
    return sources, weights


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True,
                        help="v3 pack, R pack and the P1 round's output (train); also the train stage's output (judge)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--stage", choices=("train", "judge"), required=True)
    parser.add_argument("--steps", type=int, default=6000, help="R1F training steps")
    parser.add_argument("--job-hours", type=float, default=4.5, help="Training time of each job")
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 2026])
    parser.add_argument("--judge-seeds", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--interval", type=int, default=500)
    parser.add_argument("--eval-samples", type=int, default=256)
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    from ml.kaggle_multidomain import physiogan_r
    from ml.kaggle_multidomain.data_gxu import load_input
    from ml.kaggle_multidomain.data_r import load_r
    from ml.kaggle_multidomain.experiment_p4 import resolve_teacher
    from ml.kaggle_multidomain.experiment_v3 import ARMS, PROTOCOL, check_pack, conditions_for
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and len(names) != 2:
        raise RuntimeError(f"Two GPUs required, allocated {names}")
    devices = ["cpu"] if a.allow_cpu else ["cuda:0", "cuda:1"]
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started, kernel_start = time.monotonic(), time.time()
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    r, r_manifest = load_r(a.input_root, manifest)
    save_json(output/"configuration.json", dict(args=vars(a), python=platform.python_version(), torch=torch.__version__,
                                                allocated_gpus=names, cpu_count=os.cpu_count()))
    view = {k: v[pack["split"] != "external"] for k, v in pack.items()}
    keep = np.flatnonzero(np.isin(view["split"], ["train", "validation"]))
    bank = sj.ConditionsView(conditions_for({k: v[keep] for k, v in view.items()}, "v2"), keep)
    if a.stage == "train":
        teacher = resolve_teacher(a.input_root, output/"teacher")
        save_json(output/"FROZEN_P5.json", dict(
            rule=RULE, rule_sha256=rule_sha256(), judge=JUDGE, judge_spec=sj.JUDGES[JUDGE], seeds=a.seeds,
            judge_seeds=a.judge_seeds,
            physiogan=dict(config=physiogan_r.CONFIG, critic=physiogan_r.CRITIC, train=physiogan_r.TRAIN,
                           select=physiogan_r.SELECT, select_sizes=physiogan_r.SELECT_SIZES,
                           ada=dict(target=physiogan_r.ADA_TARGET, images=physiogan_r.ADA_IMAGES,
                                    max=physiogan_r.ADA_MAX)),
            r1f=dict(arm=ARMS[R1F], seed=R1F_SEED, steps=a.steps), r1_sources=R1_SOURCES, job_hours=a.job_hours,
            teacher=teacher, data_sha256=manifest["windows_sha256"], r_sha256=r_manifest["windows_sha256"]))
        print("TEACHER", json.dumps({k: teacher[k] for k in ("seed", "sha256", "p1_winner")}), flush=True)
        deadline = kernel_start+3600*(KERNEL_HOURS-PREVIEW_RESERVE_HOURS)
        (output/"benchmark").mkdir()
        training = train_all(a.seeds, devices, a.input_root, output/"benchmark", a.job_hours, deadline, a.steps,
                             a.interval, a.eval_samples, str(output/"teacher"))
        save_json(output/"training_execution.json", training)
        print("TRAINING DONE", f"{time.monotonic()-started:.0f}s", flush=True)
        sources, _ = sources_for(output, r, view, bank, a.seeds, devices[0])
        result = preview(output, view, bank, sources, output/"benchmark")
        print("PREVIEW", json.dumps(dict(copy=result["copy"], balance=result["balance"])), flush=True)
        save_json(output/"COMPLETE.json", dict(status="train_complete", next="review, then the judge stage",
                                               wall_seconds=time.monotonic()-started, deployment="research_only"))
        print("COMPLETE", flush=True)
        return result

    round_dir, frozen = frozen_round(a.input_root)
    if frozen["data_sha256"] != manifest["windows_sha256"] or frozen["r_sha256"] != r_manifest["windows_sha256"]:
        raise ValueError("The judge stage's packs differ from the train stage's")
    seeds = frozen["seeds"]
    for name in ("FROZEN_P5.json", "COPY_P5.json", "PREVIEW_P5.json"):
        shutil.copy2(round_dir/name, output/name)
    copies = json.loads((round_dir/"COPY_P5.json").read_text())
    sources, weights = sources_for(round_dir, r, view, bank, seeds, devices[0])
    val = judge_family(view, bank, sources, "validation", sj.DOMAINS, [JUDGE], frozen["judge_seeds"], devices,
                       output/"validation")
    decision = decide(val, copies, seeds)
    save_json(output/"DECISION_P5.json", decision)
    print("DECISION", json.dumps({k: decision[k] for k in ("kept", "kept_auc", "target_met", "checks", "best_r1")}),
          flush=True)
    test = judge_family(view, bank, sources, "test", sj.DOMAINS, [JUDGE], frozen["judge_seeds"], devices,
                        output/"test")
    shipped = ship(decision, output, round_dir/"benchmark", weights, bank)
    test_auc = {n: mean_auc(test, JUDGE, n) for n in [*sources, "real_other_people"]}
    kept_test = float(np.mean([test_auc[n] for n in gan_names(seeds)])) if decision["kept"] == GAN \
        else test_auc[decision["kept"]]
    summary = dict(judge=JUDGE, teacher=frozen["teacher"], decision=decision, ship=shipped,
                   validation=indistinguishable(val, JUDGE), test=indistinguishable(test, JUDGE), test_auc=test_auc,
                   kept_test_auc=kept_test, target_met_test=bool(kept_test <= TARGET),
                   copy={k: v["rate"] for k, v in copies.items() if isinstance(v, dict) and "rate" in v},
                   wall_seconds=time.monotonic()-started)
    save_json(output/"summary.json", summary)
    save_json(output/"COMPLETE.json", dict(status="complete", kept=decision["kept"], target_met=decision["target_met"],
                                           target_met_test=summary["target_met_test"],
                                           wall_seconds=time.monotonic()-started, deployment="research_only"))
    print("COMPLETE", flush=True)
    return summary


if __name__ == "__main__":
    main()
