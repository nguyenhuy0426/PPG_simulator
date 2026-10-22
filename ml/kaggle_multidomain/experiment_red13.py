"""Round 13: the red head (red_head.py) judged on fresh validation people from OpenOximetry. Laptop CPU only.

RULE_12 stopped PhysioFlow-2 tuning on the v4 validation people. Round 13 changes the question: the infrared generator
stays as shipped (PhysioMix R9, PhysioFlow F6) and only the red channel is generated, as R x (infrared + residual).
Training uses the v4 training windows with red (FINGER, PTT) and the OpenOximetry training people; the decision reads
the OpenOximetry validation people only (never seen in any round); the OpenOximetry test people are not opened.
OpenOximetry stays on this machine (PhysioNet Restricted Health Data Use Agreement 1.5.0).

    PPG_DRY_RUN=1 .venv/bin/python -m ml.kaggle_multidomain.experiment_red13 --pack ml/runs/physioflow2-data-v4 \
        --openox ml/runs/openox-red-v1 --output ml/runs/red13-v1
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import LENGTH, save_json
from ml.kaggle_multidomain.data_dual import load_dual
from ml.kaggle_multidomain.data_openox import DOMAIN as OPENOX, load_openox
from ml.kaggle_multidomain.experiment_dual import pair_c2st
from ml.kaggle_multidomain.red_head import HEAD_DOMAINS, residual_score, residual_target
from ml.kaggle_multidomain.red_head_train import RECIPE, candidates, red_rows, train_head

DOMAINS = HEAD_DOMAINS+(OPENOX,)
ROUND13 = dict(steps=6000, seeds=(42, 123, 2026), probe_seeds=(0, 1, 2), probe_train_n=512)
LIMITS13 = dict(score_ratio=.8, ptp_error=1e-3, latency_ms=1000.)
RULE_13 = (
    "Round 13 (red head), fixed before any OpenOximetry validation window is scored. Infrared generators unchanged. "
    "Red head: residual flow (red_head.py, 2.8 M parameters, 8 Heun steps) trained with RECIPE for 6000 steps at seeds "
    "42, 123 and 2026 on the v4 training windows with red (gxu_finger, ptt_sit, ptt_walk, ptt_run) plus the "
    "OpenOximetry training people (data_openox, split seed 20261022). Scored on the OpenOximetry validation people "
    "with their real infrared: residual score (median residual SD and 4-band power, |log10| ratios; 0 = real) and a "
    "probe C2ST on (standardised infrared, residual) trained on training-people windows (3 probe seeds). Baselines: "
    "coloured residual with the OpenOximetry training spectrum, and the infrared copy (the app today). D3 (the red head "
    "replaces the infrared copy as the app's red channel): every seed finite with |ptp(red) - R| <= 1e-3, TorchScript "
    "agreement and single-thread laptop latency < 1000 ms; seed-mean residual score <= 0.8 x the coloured baseline's; "
    "seed-mean probe AUC + 2 x seed SD < the coloured baseline's probe AUC. Shipped seed: lowest residual score. "
    "OpenOximetry test people are not used. Laptop CPU; the Raspberry Pi is not measured.")


def combined(v4, openox):
    """v4 training windows with red in HEAD_DOMAINS plus every OpenOximetry window, with the fields the head uses."""
    keep = (v4["split"] == "train") & v4["red_known"] & np.isin(v4["domain"], HEAD_DOMAINS)
    out = {}
    for key in ("signal", "red", "red_known", "ratio_r", "domain", "split", "subject"):
        a, b = v4[key][keep], openox[key]
        out[key] = np.concatenate((a.astype(str), b.astype(str))) if a.dtype.kind in "US" else np.concatenate((a, b))
    return out


def probe_auc(pack, ids_train, red_train, ids_valid, red_valid, seed):
    """C2ST on (standardised infrared, residual y): real windows against the candidate's, on held-out people."""
    def stack(ids, red):
        ir = pack["signal"][ids].astype(np.float64)
        y, _, valid = residual_target(ir, red.astype(np.float64))
        x = (ir-ir.mean(-1, keepdims=True))/ir.std(-1, keepdims=True)
        return np.stack((x, y), 1)[valid].astype(np.float32)
    real_t, real_v = stack(ids_train, pack["red"][ids_train]), stack(ids_valid, pack["red"][ids_valid])
    return float(pair_c2st(real_t, stack(ids_train, red_train), real_v, stack(ids_valid, red_valid), "cpu", seed=seed))


def export_check(head, conditions, pack, ids):
    traced = torch.jit.trace(head.eval(), example_inputs(conditions, pack, ids[:2]), check_trace=False)
    for n in (1, 3):
        args = example_inputs(conditions, pack, ids[:n])
        with torch.no_grad():
            torch.testing.assert_close(traced(*args), head(*args))
    threads = torch.get_num_threads()
    torch.set_num_threads(1)
    args = example_inputs(conditions, pack, ids[:1])
    with torch.no_grad():
        traced(*args)
        times = []
        for _ in range(5):
            start = time.perf_counter()
            traced(*args)
            times.append(1000*(time.perf_counter()-start))
    torch.set_num_threads(threads)
    return traced, float(np.median(times))


def example_inputs(conditions, pack, ids):
    ratio = pack["ratio_r"][ids].astype(np.float32)
    return (torch.randn(len(ids), LENGTH, generator=torch.Generator().manual_seed(7)),
            torch.tensor(pack["signal"][ids].astype(np.float32)), torch.tensor(conditions.rows(pack["domain"][ids], ratio)),
            torch.tensor(ratio))


def decide(rows):
    head = np.array([r["head"]["score"] for r in rows])
    coloured = np.array([r["coloured"]["score"] for r in rows])
    auc_head = np.array([np.mean(r["head"]["probe_auc"]) for r in rows])
    auc_coloured = float(np.mean([np.mean(r["coloured"]["probe_auc"]) for r in rows]))
    checks = dict(every_seed_valid=all(r["gates"]["ok"] for r in rows),
                  score_vs_coloured=bool(head.mean() <= LIMITS13["score_ratio"]*coloured.mean()),
                  probe_vs_coloured=bool(auc_head.mean()+2*auc_head.std(ddof=1) < auc_coloured))
    ship = min(rows, key=lambda r: r["head"]["score"])["seed"]
    return dict(D3=all(checks.values()), checks=checks, ship_seed=ship,
                residual_score=dict(head=head.tolist(), coloured=coloured.tolist(),
                                    copy=[r["copy"]["score"] for r in rows]),
                probe_auc=dict(head=auc_head.tolist(), coloured=auc_coloured,
                               copy=float(np.mean([np.mean(r["copy"]["probe_auc"]) for r in rows]))))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True)
    parser.add_argument("--openox", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--steps", type=int, default=ROUND13["steps"])
    parser.add_argument("--smoke", action="store_true", help="Few steps, one seed; no decision value")
    a = parser.parse_args(argv)
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=False)
    save_json(out/"RULE_13.json", dict(rule=RULE_13, recipe=RECIPE, round=ROUND13, limits=LIMITS13))
    v4, v4_manifest = load_dual(a.pack)
    ox, ox_manifest = load_openox(a.openox)
    pack = combined(v4, ox)
    train_ids, train_y = red_rows(pack, "train", DOMAINS)
    valid_ids, valid_y = red_rows(pack, "validation", (OPENOX,))
    ox_train = red_rows(pack, "train", (OPENOX,))[0]
    probe_train = np.random.default_rng(8101).choice(ox_train, min(ROUND13["probe_train_n"], len(ox_train)), replace=False)
    seeds, steps = (ROUND13["seeds"][:1], 50) if a.smoke else (ROUND13["seeds"], a.steps)
    rows = []
    for seed in seeds:
        run = out/f"seed{seed}"
        run.mkdir()
        start = time.monotonic()
        head, conditions, history = train_head(pack, train_ids, train_y, seed, steps, a.threads,
                                               log=lambda m, s=seed: print(s, m, flush=True))
        torch.save(dict(head=head.state_dict(), conditions=conditions.metadata(), recipe=RECIPE, steps=steps,
                        seed=seed), run/"red_head.pt")
        held = candidates(head, conditions, pack, valid_ids, seed+1, (OPENOX,))
        fitted = candidates(head, conditions, pack, probe_train, seed+2, (OPENOX,))
        row = dict(seed=seed, steps=steps, history=history, training_seconds=time.monotonic()-start)
        ir = pack["signal"][valid_ids].astype(np.float64)
        for name, red in held.items():
            y, _, valid = residual_target(ir, red.astype(np.float64))
            total, per = residual_score(y[valid], valid_y, pack["domain"][valid_ids][valid], pack["domain"][valid_ids])
            row[name] = dict(score=total, datasets=per,
                             ptp_error_max=float(np.max(np.abs(np.ptp(red, -1)-pack["ratio_r"][valid_ids]))),
                             probe_auc=[probe_auc(pack, probe_train, fitted[name], valid_ids, red, s)
                                        for s in ROUND13["probe_seeds"]])
        try:
            traced, latency = export_check(head, conditions, pack, valid_ids)
            traced.save(str(run/"red_head_cpu.ts"))
            trace_ok = True
        except (RuntimeError, AssertionError) as error:
            latency, trace_ok = None, False
            row["trace_error"] = str(error)[:300]
        finite = bool(np.isfinite(held["head"]).all())
        row["gates"] = dict(finite=finite, ptp_ok=row["head"]["ptp_error_max"] <= LIMITS13["ptp_error"],
                            trace_ok=trace_ok, latency_ms=latency,
                            latency_ok=bool(latency is not None and latency < LIMITS13["latency_ms"]))
        row["gates"]["ok"] = all(row["gates"][k] for k in ("finite", "ptp_ok", "trace_ok", "latency_ok"))
        save_json(run/"result.json", row)
        print(seed, json.dumps({k: (row[k]["score"], np.mean(row[k]["probe_auc"])) for k in held}), flush=True)
        rows.append(row)
    decision = dict(rule=RULE_13, smoke=a.smoke, v4_windows_sha256=v4_manifest["windows_sha256"],
                    openox_windows_sha256=ox_manifest["windows_sha256"], training_windows=int(len(train_ids)),
                    validation_windows=int(len(valid_ids)),
                    validation_people=int(len(set(pack["subject"][valid_ids]))), rows=rows,
                    scope="Laptop CPU; OpenOximetry validation people; test people not opened; Pi not measured")
    if not a.smoke and len(rows) > 1:
        decision.update(decide(rows))
    save_json(out/"DECISION_13.json", decision)
    print(json.dumps({k: decision.get(k) for k in ("D3", "checks", "residual_score", "probe_auc")}, indent=1))


if __name__ == "__main__":
    main()
