"""P4 diagnosis (judge only): is G3's validation AUC (~0.97 vs its teacher's 0.726) from the 4-step sampler or from the
adversarial fine-tuning?

The same PhysioFlow-R sampler (flow_r.FlowGeneratorR, Heun with a final Euler step, the record-context view) runs the
P1 ship seed's weights (the P4 teacher) at 16, 8 and 4 steps and the fine-tuned G3 seed 42 weights at 4 (as P4 judged
it) and 16 steps. Sources, judge kind, judge seeds and sets are the P4 round's validation ones, so r1_s16 and g3_s4
reproduce P4's r1_teacher and G3_flowgan_r_seed42. Validation people only: the test people were judged once per round
and are not used. No training, no ship, no claim about the app models.
Engineering evaluation of normalised 30 s PPG shape; not clinical validation, not measured on the Pi/DAC/OPT101.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import time

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import LENGTH, save_json
from ml.kaggle_multidomain import strict_judge as sj
from ml.kaggle_multidomain.experiment_strict import indistinguishable, judge_family, mean_auc, spread

JUDGE = "strict"
G3_ARM, G3_SEED = "G3_flowgan_r", 42
SOURCES = {"r1_s16": ("r1", 16), "r1_s8": ("r1", 8), "r1_s4": ("r1", 4), "g3_s4": ("g3", 4), "g3_s16": ("g3", 16)}
RULE = ("P4 diagnosis rule, fixed before judging; validation people, P4's strict judge, seeds 0-2 + offset. "
        "step_effect = AUC(r1_s4) - AUC(r1_s16); gan_effect = AUC(g3_s4) - AUC(r1_s4); gan_effect_16 = AUC(g3_s16) - "
        "AUC(r1_s16). An effect is real if it exceeds max(0.02, the larger judge-seed SD of its two sources). "
        "Reproduction: r1_s16 and g3_s4 within 0.03 of P4's r1_teacher and G3_flowgan_r_seed42 validation AUC, else "
        "the comparison is not trusted. Valid only if the real_other_people null lies in [0.40, 0.60].")


def rule_sha256():
    return hashlib.sha256(RULE.encode()).hexdigest()


def find_one(root, pattern):
    paths = sorted(Path(root).rglob(pattern))
    if len(paths) != 1:
        raise ValueError(f"Expected one {pattern} under {root}, found {len(paths)}")
    return paths[0]


def generators(p4_round, bank, device):
    """{source: generate(ids, conditions, seed)} on one PhysioFlow-R sampler; weights from the P4 round's output."""
    from ml.kaggle_multidomain.experiment_v3 import config, load_best
    from ml.kaggle_multidomain.flow_r import FlowGeneratorR, TEACHER_R_FILE, teacher_state_r
    teacher = teacher_state_r([Path(p4_round)/"teacher"])
    frozen = json.loads((Path(p4_round)/"FROZEN_P4.json").read_text())
    if teacher["sha256"] != frozen["teacher"]["sha256"]:
        raise ValueError(f"{TEACHER_R_FILE} is not the teacher P4 froze")
    c = bank.conditions
    # The teacher's U-Net has the student's width (P4 loads one into the other).
    r1 = FlowGeneratorR(c.bank.shape[1], c.center, c.scale, len(c.domains), teacher["contexts"], teacher["cdf"],
                        width=config(G3_ARM)["width"])
    r1.flow.net.load_state_dict(teacher["net"])
    g3 = load_best(G3_ARM, Path(p4_round)/"benchmark"/f"{G3_ARM}_seed{G3_SEED}", c, None, "cpu")[0].gen
    weights = dict(r1=r1.eval(), g3=g3.eval())

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
    return {name: make(*spec) for name, spec in SOURCES.items()}, teacher["sha256"]


def effect(rows, a, b):
    """AUC(a) - AUC(b) and whether it exceeds max(0.02, the larger judge-seed SD)."""
    sd = max(spread([r["auc"] for r in rows if r["judge"] == JUDGE and r["source"] == n]) for n in (a, b))
    value = mean_auc(rows, JUDGE, a)-mean_auc(rows, JUDGE, b)
    return dict(value=value, threshold=max(.02, sd), real=bool(abs(value) > max(.02, sd)))


def diagnose(rows, p4_decision):
    auc = {n: mean_auc(rows, JUDGE, n) for n in [*SOURCES, "real_other_people"]}
    reproduced = dict(r1_s16=abs(auc["r1_s16"]-p4_decision["references"]["r1_teacher"]) <= .03,
                      g3_s4=abs(auc["g3_s4"]-p4_decision["auc_by_seed"][str(G3_SEED)]) <= .03)
    return dict(rule_sha256=rule_sha256(), judge=JUDGE, auc=auc,
                null_valid=bool(.40 <= auc["real_other_people"] <= .60), reproduced=reproduced,
                step_effect=effect(rows, "r1_s4", "r1_s16"), gan_effect=effect(rows, "g3_s4", "r1_s4"),
                gan_effect_16=effect(rows, "g3_s16", "r1_s16"))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="v3 pack, app model files and the P4 round's output")
    parser.add_argument("--output", required=True)
    parser.add_argument("--judge-seeds", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--allow-cpu", action="store_true")
    a = parser.parse_args(argv)
    from ml.kaggle_multidomain.data_gxu import load_input
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
    p4_round = find_one(a.input_root, "DECISION_P4.json").parent
    pack = {k: v[pack["split"] != "external"] for k, v in pack.items()}
    keep = np.flatnonzero(np.isin(pack["split"], ["train", "validation"]))
    bank = sj.ConditionsView(conditions_for({k: v[keep] for k, v in pack.items()}, "v2"), keep)
    sources, teacher_sha = generators(p4_round, bank, devices[0])
    save_json(output/"FROZEN_DIAG.json", dict(rule=RULE, rule_sha256=rule_sha256(), judge=JUDGE,
                                              judge_spec=sj.JUDGES[JUDGE], judge_seeds=a.judge_seeds,
                                              sources=SOURCES, g3_seed=G3_SEED, teacher_sha256=teacher_sha,
                                              data_sha256=manifest["windows_sha256"]))
    save_json(output/"configuration.json", dict(args=vars(a), python=platform.python_version(), torch=torch.__version__,
                                                allocated_gpus=names, cpu_count=os.cpu_count()))
    val = judge_family(pack, bank, sources, "validation", sj.DOMAINS, [JUDGE], a.judge_seeds, devices,
                       output/"validation")
    result = diagnose(val, json.loads((p4_round/"DECISION_P4.json").read_text()))
    result.update(validation=indistinguishable(val, JUDGE), wall_seconds=time.monotonic()-started)
    save_json(output/"DIAGNOSIS_P4.json", result)
    print("DIAGNOSIS", json.dumps({k: result[k] for k in ("auc", "reproduced", "step_effect", "gan_effect",
                                                          "gan_effect_16")}), flush=True)
    save_json(output/"COMPLETE.json", dict(status="complete", wall_seconds=time.monotonic()-started,
                                           deployment="research_only"))
    print("COMPLETE", flush=True)
    return result


if __name__ == "__main__":
    main()
