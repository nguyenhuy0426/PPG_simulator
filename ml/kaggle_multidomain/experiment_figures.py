"""Figure kernel for docs/model-report/gan-report.html: per-window strict-judge scores (Fig. 6b, AUC by artifact
group) and the judges' weights (Fig. 2c, where the judge looks).

For each chosen source of a finished round (the flow-GAN round, and the strict round when mounted), the validation
judge sets are rebuilt exactly as that round built them (strict_judge.build_sets with experiment_strict.SET_SEEDS, the
round's generator order, so the same windows, prompts and generator noise; sources not re-judged are stubbed, which
leaves every other draw unchanged), and the strict judge is retrained with the round's first validation judge seed
(0 + JUDGE_SEED_OFFSETS). Saved per source: the eval logits of both sides, their domains and artifact shares
(artifact_sqi, a heuristic SQI), the judge's AUC next to the round's judges.json AUC for the same seed (GPU training is
not bit-reproducible, so they agree only approximately), and the fp16 judge state. No waveform is written: the eval
windows are rebuilt from the pack and the generators where needed (scripts/build_gan_report.py).
Engineering evaluation of normalised 30 s PPG shape; not clinical validation.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import multiprocessing
from pathlib import Path
import time

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import LENGTH, save_json
from ml.kaggle_multidomain import strict_judge as sj

SPLIT, JUDGE = "validation", "strict"
NULL = "real_other_people"


def round_order(kind, slot, seeds):
    """Generator names in the order the round passed them to build_sets (their index sets the noise seeds)."""
    from ml.kaggle_multidomain import experiment_flowgan as ef
    from ml.kaggle_multidomain.experiment_strict import LSM_ARMS, PHYSIOMIX_ARMS
    if kind == "flowgan":
        return [f"{slot}_app", "physioflow_app", "physioflow_sensor"]+[f"{ef.ARMS[slot]}_seed{s}" for s in seeds]
    if slot == "physiomix":
        return ["physiomix_app", "physioflow_app", "physioflow_sensor"]+[f"{a}_seed{s}" for a in PHYSIOMIX_ARMS
                                                                          for s in seeds]
    return ["lsm_app"]+[f"{a}_seed{s}" for a in LSM_ARMS for s in seeds]


def chosen(kind, decision, seeds):
    """{slot: sources to re-judge}: the flow-GAN round's references, app model, ship seed and null control; the
    strict round's best arm (its ship seed)."""
    from ml.kaggle_multidomain import experiment_flowgan as ef
    if kind == "flowgan":
        out = {}
        for slot in ef.ARMS:
            seed = decision[slot]["ship_seed"] if decision[slot]["ship_seed"] is not None else seeds[0]
            refs = ["physioflow_app", "physioflow_sensor"] if slot == "physiomix" else ["physioflow_app"]
            out[slot] = [f"{slot}_app", *refs, f"{ef.ARMS[slot]}_seed{seed}", NULL]
        return out
    pm = decision["physiomix"]
    arm = pm["winner"] or min(pm["arms"], key=lambda a: pm["arms"][a]["mean_auc"])
    lsm = decision["lsm"]
    best = lsm["winner"] or lsm["candidate"]
    return {"physiomix": [f"{arm}_seed{pm['arms'][arm]['ship_seed']}"],
            "lsm": [f"{best}_seed{lsm['arms'][best]['ship_seed']}"]}


def stub(ids, conditions, seed):
    return np.zeros((len(ids), LENGTH), np.float32)


def resolve(name, roots, apps, bank, device):
    """The generate() of one source, found under roots as the round found it."""
    from ml.kaggle_multidomain.experiment_strict import checkpoint_generator, sensor_finished, unconditional_generator
    if name in apps:
        return apps[name]
    if name == "physioflow_sensor":
        return sensor_finished(apps["physioflow_app"])
    arm, seed = name.rsplit("_seed", 1)
    if arm.startswith("lsm_"):
        return unconditional_generator(first(roots, f"lsm/{name}/generator_cpu.ts"))
    best = first(roots, f"benchmark/{name}/best.pt")
    return checkpoint_generator(best.parent, arm, bank, device)


def first(roots, pattern):
    """The single match of pattern under the roots (two would mean an ambiguous source)."""
    hits = sorted(p for root in roots for p in Path(root).rglob(pattern))
    if len(hits) != 1:
        raise FileNotFoundError(f"{pattern}: {len(hits)} matches under {list(map(str, roots))}")
    return hits[0]


def eval_only(generate):
    """Stub the train and inner calls of build_sets (it draws train, inner, eval in that order): eval windows only."""
    calls = []

    def wrapped(ids, conditions, seed):
        calls.append(seed)
        return generate(ids, conditions, seed) if len(calls) % 3 == 0 else stub(ids, conditions, seed)
    return wrapped


def build(pack, bank, kind, slot, wanted, seeds, roots, apps, device, only_eval=False):
    """build_sets for one round and slot with every unwanted source stubbed (only_eval: their train/inner too)."""
    from ml.kaggle_multidomain.experiment_strict import LSM_DOMAIN, SET_SEEDS
    names = round_order(kind, slot, seeds)
    missing = [n for n in wanted if n != NULL and n not in names]
    if missing:
        raise ValueError(f"{kind}/{slot}: {missing} were not judged in that round")
    generators = {n: resolve(n, roots, apps, bank, device) if n in wanted else stub for n in names}
    if only_eval:
        generators = {n: eval_only(g) if n in wanted else g for n, g in generators.items()}
    domains = sj.DOMAINS if slot == "physiomix" else (LSM_DOMAIN,)
    arrays, info = sj.build_sets(pack, bank, generators, SPLIT, seed=SET_SEEDS[SPLIT], domains=domains,
                                 controls=(NULL,), eval_prompts="control_eval")
    return {k: v for k, v in arrays.items() if k.startswith("real_") or any(k.startswith(f"{n}_") for n in wanted)}, info


def official_auc(roots, kind, slot, name, seed):
    marker = "DECISION_FLOWGAN.json" if kind == "flowgan" else "DECISION_STRICT.json"
    folder = first(roots, marker).parent
    rows = json.loads((folder/SPLIT/slot/"judges.json").read_text())
    hits = [r["auc"] for r in rows if r["judge"] == JUDGE and r["source"] == name and r["seed"] == seed]
    return hits[0] if hits else None


def judge_job(device, data_path, name, seed, out_file):
    from ml.kaggle_multidomain import artifact_sqi
    torch.set_num_threads(2)
    if device.startswith("cuda"):
        torch.cuda.set_device(device)
    with np.load(data_path, allow_pickle=False) as source:
        data = {k: source[k] for k in source.files}
    started = time.monotonic()
    model, history = sj.fit(JUDGE, data["real_train"], data[f"{name}_train"], data["real_inner"],
                            data[f"{name}_inner"], device, seed)
    result, (a, b) = sj.judge_scores(model, JUDGE, data["real_eval"], data["real_eval_domain"], data[f"{name}_eval"],
                                     data[f"{name}_eval_domain"], torch.device(device))
    np.savez(out_file, logits_real=a.astype(np.float32), logits_fake=b.astype(np.float32),
             domain_real=data["real_eval_domain"], domain_fake=data[f"{name}_eval_domain"],
             sqi_real=artifact_sqi.artifact_fraction(data["real_eval"]).astype(np.float32),
             sqi_fake=artifact_sqi.artifact_fraction(data[f"{name}_eval"]).astype(np.float32))
    torch.save({k: v.half() for k, v in model.state_dict().items()}, Path(out_file).with_suffix(".pt"))
    return dict(source=name, seed=seed, auc=result["auc"], per_domain=result["per_domain"], history=history,
                seconds=time.monotonic()-started)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="v3 pack, app models and the finished rounds' outputs")
    parser.add_argument("--output", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 2026])
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    from ml.kaggle_multidomain.data_gxu import load_input
    from ml.kaggle_multidomain.experiment_strict import JUDGE_SEED_OFFSETS, app_sources
    from ml.kaggle_multidomain.experiment_v3 import PROTOCOL, check_pack, conditions_for
    names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    if not a.allow_cpu and len(names) != 2:
        raise RuntimeError(f"Two GPUs required, allocated {names}")
    devices = ["cpu"] if a.allow_cpu else ["cuda:0", "cuda:1"]
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    pack, manifest = load_input(a.input_root, PROTOCOL)
    check_pack(pack, manifest, a.allow_cpu)
    pack = {k: v[pack["split"] != "external"] for k, v in pack.items()}
    keep = np.flatnonzero(np.isin(pack["split"], ["train", "validation"]))
    bank = sj.ConditionsView(conditions_for({k: v[keep] for k, v in pack.items()}, "v2"), keep)
    root = Path(a.input_root)
    roots = [root]
    bundle = next(p.parent for p in root.rglob("manifest.json") if (p.parent/"physiomix_generator.ts").exists())
    apps = app_sources(bundle, bank, devices[0])
    seed = JUDGE_SEED_OFFSETS[SPLIT]
    rounds = {k: m for k, m in (("flowgan", "DECISION_FLOWGAN.json"), ("strict", "DECISION_STRICT.json"))
              if list(root.rglob(m))}
    if not rounds:
        raise FileNotFoundError("No finished round (DECISION_*.json) under the input root")
    jobs, index = [], []
    for kind, marker in rounds.items():
        decision = json.loads(first(roots, marker).read_text())
        for slot, wanted in chosen(kind, decision, a.seeds).items():
            arrays, info = build(pack, bank, kind, slot, wanted, a.seeds, roots, apps, devices[0])
            data_path = Path("/tmp" if devices != ["cpu"] else output)/f"figures_{kind}_{slot}.npz"
            np.savez(data_path, **arrays)
            for name in wanted:
                file = output/f"{kind}_{slot}_{name}.npz"
                jobs.append((data_path, name, file))
                index.append(dict(round=kind, slot=slot, source=name, seed=seed, file=file.name, seeds=a.seeds,
                                  official_auc=official_auc(roots, kind, slot, name, seed), counts=info["counts"]))
            print("SETS", kind, slot, wanted, f"{time.monotonic()-started:.0f}s", flush=True)
    rows = {}
    if devices == ["cpu"]:
        for data_path, name, file in jobs:
            rows[file.name] = judge_job("cpu", data_path, name, seed, file)
    else:
        with ProcessPoolExecutor(len(devices), mp_context=multiprocessing.get_context("spawn")) as pool:
            futures = {pool.submit(judge_job, devices[i % len(devices)], d, n, seed, f): f.name
                       for i, (d, n, f) in enumerate(jobs)}
            for future in as_completed(futures):
                rows[futures[future]] = future.result()
                print("JUDGED", futures[future], f"auc {rows[futures[future]]['auc']:.4f}", flush=True)
    for entry in index:
        entry.update(rows[entry["file"]])
    save_json(output/"index.json", index)
    save_json(output/"COMPLETE.json", dict(status="complete", judged=len(index), wall_seconds=time.monotonic()-started))
    print("COMPLETE", flush=True)
    return index


if __name__ == "__main__":
    main()
