#!/usr/bin/env python3
"""Figures, LaTeX tables and an evidence extract for docs/paper/main.tex.

Table values are read from the evidence files in SOURCES: the JSON records of the Kaggle runs,
committed under docs/paper/evidence/ as copies of their ml/runs originals (ml/runs stays local, see
.gitignore), the decision records committed under docs/, and the data pack, which only exists under
ml/runs. Nothing is typed by hand. Two items are new measurements on the machine that runs this
script: the single-thread CPU latency of the generators shipped in assets/neural and the
commanded-versus-measured rate curves of Fig. 5.

    PPG_DRY_RUN=1 .venv/bin/python docs/paper/make_figures.py            # everything
    PPG_DRY_RUN=1 .venv/bin/python docs/paper/make_figures.py --no-measure  # reuse data/measured.json
"""
import argparse
import hashlib
import json
import math
import platform
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PAPER = ROOT/"docs"/"paper"
FIG, TAB, DATA = PAPER/"figures", PAPER/"tables", PAPER/"data"
RUNS = ROOT/"ml"/"runs"
EVIDENCE = PAPER/"evidence"
HW = ROOT/"docs"/"hardware-validation"/"2026-09-30"


def run_file(relative):
    """A Kaggle run record: the committed copy under docs/paper/evidence, else the local ml/runs file."""
    committed = EVIDENCE/relative
    return committed if committed.exists() else RUNS/relative


SOURCES = {
    "pack": RUNS/"physio3-data-v1/physio3_data/windows.npz",
    "pack_verification": run_file("physio3-data-v1/VERIFICATION.json"),
    "r9_summary": run_file("physiomix9-motion-dom-result-v1/physiomix9/summary.json"),
    "r9_decision": ROOT/"docs/physiomix-v3/rules/DECISION_ROUND9.json",
    "r10_decision": ROOT/"docs/physioflow/rules/DECISION_ROUND10.json",
    "r10_gxu_test": ROOT/"docs/physioflow/rules/GXU_TEST_ROUND10.json",
    "l6_decision": run_file("physioflow10e-final-result-v1/physioflow10/DECISION_ROUND10.json"),
    "realism": run_file("realism-v1/realism_round10.json"),
    "realism_lsm_narrow": run_file("realism-v1/realism_lsm_narrow.json"),
    "fresh_galaxy": run_file("fresh-galaxy-result-v1/fresh_galaxy.json"),
    "judges": run_file("judges-c-v1/judges_c.json"),
    "step_b": run_file("galaxy-b-pilot-result-v1/galaxy_b/DECISION_GALAXY_B.json"),
    "step_d": run_file("galaxy-d-pilot-result-v1/daily_d/DECISION_D_PILOT.json"),
    "step_d_test": run_file("galaxy-d-pilot-result-v1/daily_d/TEST_REPORT_D_PILOT.json"),
    "step_e": run_file("galaxy-e-result-v1/step_e/DECISION_E.json"),
    "step_e_test": run_file("galaxy-e-result-v1/step_e/TEST_REPORT_E.json"),
    "pi_headless_before": HW/"initial/summary.json",
    "pi_headless_after": HW/"timing-fixed/summary.json",
    "pi_gui_1k": HW/"gui-bench-before.json",
    "pi_gui_1k_light": HW/"gui-bench-throttled.json",
    "pi_gui_500": HW/"gui-bench.json",
    "pi_arm": HW/"arm-inference.json",
    "pi_loopback": HW/"timing-fixed/correlation.json",
    "manifest": ROOT/"assets/neural/manifest.json",
    # New laptop analyses (docs/paper/analysis/*.py)
    "realism_ci": DATA/"realism_ci.json",
    "downstream": DATA/"downstream.json",
}
SEED_METRICS = {
    "physioflow": "physioflow10c-resume-local-v1/physioflow10/benchmark/F6_flow_flag_deriv_unif_s16_w1_seed{}/metrics.json",
    "physioflow_sb": "physioflow10e-final-result-v1/physioflow10/benchmark/F10_flow_unif_stop01_s16_w1_seed{}/metrics.json",
}
SEEDS = (42, 123, 2026)
USED = {}

# Dataset keys in the code -> names used in the paper.
DOMAINS = ("gxu_finger", "perform_large", "bidmc", "perform_af", "perform_non_af", "wrist")
NAME = {"gxu_finger": "FINGER", "perform_large": "MIMIC-L", "bidmc": "BIDMC", "perform_af": "MIMIC-AF",
        "perform_non_af": "MIMIC-nonAF", "wrist": "WRIST-EX"}
SOURCE_NAME = {"real_other_people": "Real (other subjects)", "round9": "PhysioMix", "physiomix": "PhysioMix",
               "physioflow": "PhysioFlow", "lsm_gan": "LSM-GAN", "gaussian_shaper": "Gaussian",
               "physiomix_g": "PhysioMix-G", "physioflow_g": "PhysioFlow-G",
               "physiomix_d_seed42": "PhysioMix-D", "physioflow_d_seed42": "PhysioFlow-D"}
# Okabe-Ito colours; one per source across every figure.
COLOR = {"Real (other subjects)": "#000000", "PhysioMix": "#0072B2", "PhysioFlow": "#D55E00",
         "LSM-GAN": "#009E73", "Gaussian": "#999999", "PhysioMix-G": "#56B4E9", "PhysioFlow-G": "#E69F00",
         "PhysioMix-D": "#56B4E9", "PhysioFlow-D": "#E69F00", "PhysioFlow-E": "#CC79A7"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load(key, path=None):
    path = Path(path or SOURCES[key])
    USED[str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)] = sha256(path)
    return json.loads(path.read_text())


def mean_sd(values):
    values = np.asarray([v for v in values if v is not None], dtype=float)
    return dict(mean=float(values.mean()), sd=float(values.std(ddof=1)) if len(values) > 1 else 0., n=len(values))


# --------------------------------------------------------------------------------------------- evidence

def pack_counts():
    path = SOURCES["pack"]
    USED[str(path.relative_to(ROOT))] = sha256(path)
    with np.load(path, allow_pickle=False) as z:
        domain, split, subject = z["domain"], z["split"], z["subject"]
    counts = {}
    for d in DOMAINS:
        counts[d] = {}
        for s in ("train", "validation", "test"):
            m = (domain == d) & (split == s)
            counts[d][s] = dict(windows=int(m.sum()), subjects=int(len(set(subject[m].tolist()))))
    return counts


def seed_metrics(key):
    rows = []
    for seed in SEEDS:
        m = load(key, run_file(SEED_METRICS[key].format(seed)))
        rows.append(dict(seed=seed, S_arm=m["S_arm"], S_real=m["S_real_fresh"], C=m["C_fresh"],
                         auc=m["c2st_derivative_auc"], best_step=m["best_step"],
                         params=m["generator_parameters"], train_s=m["training_seconds"],
                         updates=m["stability"]["updates"], **{k: m["control"][k] for k in (
                             "mae_in", "mae_ext", "spearman", "auc_irr", "lock_rate", "irr_cv_at_sigma_0_2")}))
    return rows


def evidence():
    E = {"datasets": pack_counts(), "pack": load("pack_verification")}
    r9s, r9d = load("r9_summary"), load("r9_decision")
    arm = r9s["arms"]["L3_rel_beat_lr_crop_r1w_motion_dom"]
    E["physiomix"] = dict(S_arm=r9d["S_arm"], S_real=r9d["S_real"], C=arm["C"], auc=arm["c2st_derivative"],
                          wrist_Q=r9d["target_Q"], control=arm["control"], gxu_test_Q=arm["gxu_test_Q"],
                          params=arm["generator_parameters"], ship_seed=r9d["ship_seed"],
                          incumbent=dict(S_arm=r9d["incumbent_S_arm"], wrist_Q=r9d["incumbent_target_Q"]),
                          decision=dict(gap=r9d["gap"], pooled_sd=r9d["pooled_sd"], target_gap=r9d["target_gap"],
                                        target_pooled_sd=r9d["target_pooled_sd"], ship=r9d["ship"]))
    for key, decision in (("physioflow", "r10_decision"), ("physioflow_sb", "l6_decision")):
        rows, d = seed_metrics(key), load(decision)
        E[key] = dict(per_seed=rows, decision={k: d[k] for k in (
            "ship", "gap", "pooled_sd", "S_arm", "S_real", "wrist_Q", "incumbent_wrist_Q", "wrist_pooled_sd",
            "wrist_non_inferior", "non_inferior", "eligible")},
                      control={k: mean_sd([r[k] for r in rows]) for k in (
                          "mae_in", "mae_ext", "spearman", "auc_irr", "lock_rate", "irr_cv_at_sigma_0_2")},
                      C=mean_sd([r["C"] for r in rows]), auc=mean_sd([r["auc"] for r in rows]))
    E["physioflow"]["gxu_test"] = load("r10_gxu_test")
    E["realism"] = load("realism")
    E["fresh_galaxy"] = load("fresh_galaxy")
    E["judges"] = load("judges")
    E["step_b"], E["step_d"], E["step_d_test"] = load("step_b"), load("step_d"), load("step_d_test")
    E["step_e"], E["step_e_test"] = load("step_e"), load("step_e_test")
    E["pi"] = {k: load(k) for k in ("pi_headless_before", "pi_headless_after", "pi_gui_1k", "pi_gui_1k_light",
                                    "pi_gui_500", "pi_arm", "pi_loopback")}
    E["manifest"] = load("manifest")
    E["realism_ci"], E["downstream"] = load("realism_ci"), load("downstream")
    return E


# ----------------------------------------------------------------------------------- new measurements

def generators():
    from core.neural_preview import LSMSequenceGenerator, PhysioMixGenerator
    return {"PhysioMix": PhysioMixGenerator(slot="physiomix"), "PhysioFlow": PhysioMixGenerator(slot="physioflow"),
            "LSM-GAN": LSMSequenceGenerator()}


def measure(repeats=7):
    """Single-thread CPU latency per 30 s strip and commanded-vs-measured rate on this machine."""
    import torch
    from ml.kaggle_multidomain.labels import beat_stats
    torch.set_num_threads(1)
    gens = generators()
    out = dict(machine=dict(cpu=_cpu_name(), python=platform.python_version(), torch=torch.__version__,
                            threads=1), latency_ms={}, rate={},
               params={name: int(sum(t.numel() for t in g.model.parameters())) for name, g in gens.items()})
    for name, g in gens.items():
        z = torch.randn(1, 1200, generator=torch.Generator().manual_seed(0))
        with torch.inference_mode():
            run = (lambda: g.model(z)) if name == "LSM-GAN" else (
                lambda: g.model(z, torch.tensor([g.condition("gxu_finger", 75.)])))
            run()
            times = []
            for _ in range(repeats):
                t0 = time.perf_counter()
                run()
                times.append(1000*(time.perf_counter()-t0))
        out["latency_ms"][name] = dict(median=float(np.median(times)), min=float(np.min(times)),
                                       max=float(np.max(times)), repeats=repeats)
    grid = np.arange(40., 181., 10.)
    torch.set_num_threads(4)
    for name in ("PhysioMix", "PhysioFlow"):
        g = gens[name]
        out["rate"][name] = {}
        for domain in DOMAINS:
            medians, lo, hi = [], [], []
            for rate in grid:
                z = torch.randn(8, 1200, generator=torch.Generator().manual_seed(4242+int(rate)))
                c = torch.tensor([g.condition(domain, float(rate), .02)]*8)
                with torch.inference_mode():
                    y = g.model(z, c)[:, 0].numpy()
                hr = beat_stats(y)[:, 0]
                hr = hr[np.isfinite(hr)]
                medians.append(float(np.median(hr)) if len(hr) else None)
                lo.append(float(np.percentile(hr, 25)) if len(hr) else None)
                hi.append(float(np.percentile(hr, 75)) if len(hr) else None)
            out["rate"][name][domain] = dict(grid=grid.tolist(), median=medians, q25=lo, q75=hi)
    return out


def _cpu_name():
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


# ---------------------------------------------------------------------------------------------- tables

def f(x, d=3):
    return "--" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{d}f}"


def pm(stat, d=3):
    return f"{stat['mean']:.{d}f} $\\pm$ {stat['sd']:.{d}f}"


def thou(n):
    return f"{int(n):,}".replace(",", "{,}")


def write(name, body):
    (TAB/name).write_text(body.strip()+"\n")


def tables(E, M):
    # Table: datasets and subject-disjoint splits.
    meta = {"gxu_finger": ("Li et al. \\cite{li2026data}", "Finger, handheld device; healthy adults at rest and seated after exercise", "250"),
            "perform_large": ("MIMIC PERform \\cite{charlton2022beats}", "ICU pulse oximeter; critically ill adults (MIMIC-III)", "125"),
            "bidmc": ("BIDMC \\cite{pimentel2017rr}", "ICU pulse oximeter; critically ill adults", "125"),
            "perform_af": ("MIMIC PERform \\cite{charlton2022beats}", "ICU pulse oximeter; atrial fibrillation", "125"),
            "perform_non_af": ("MIMIC PERform \\cite{charlton2022beats}", "ICU pulse oximeter; sinus-rhythm controls", "125"),
            "wrist": ("Jarchi and Casson \\cite{jarchi2017wrist}", "Wrist, research device; healthy adults walking, running and cycling", "256")}
    rows = []
    for d in DOMAINS:
        c = E["datasets"][d]
        cells = " & ".join(f"{c[s]['subjects']} / {thou(c[s]['windows'])}" for s in ("train", "validation", "test"))
        rows.append(f"{NAME[d]} & {meta[d][0]} & {meta[d][1]} & {meta[d][2]} & {cells} \\\\")
    write("datasets.tex", "\n".join(rows))

    # Table: development outcome of the shipped models (3 seeds each, validation only).
    pmx, pfl, psb = E["physiomix"], E["physioflow"], E["physioflow_sb"]
    def dev_row(label, S_arm, S_real, C, auc, wq, ctrl):
        return (f"{label} & {pm(S_arm)} & {pm(S_real)} & {pm(C)} & {pm(auc)} & {pm(wq)} & "
                f"{ctrl['mae_in']['mean']:.2f} & {ctrl['mae_ext']['mean']:.2f} & {ctrl['spearman']['mean']:.3f} & "
                f"{ctrl['auc_irr']['mean']:.3f} & {ctrl['irr_cv_at_sigma_0_2']['mean']:.3f} \\\\")
    write("development.tex", "\n".join([
        dev_row("PhysioMix", pmx["S_arm"], pmx["S_real"], pmx["C"], pmx["auc"], pmx["wrist_Q"], pmx["control"]),
        dev_row("PhysioFlow", pfl["decision"]["S_arm"], pfl["decision"]["S_real"], pfl["C"], pfl["auc"],
                pfl["decision"]["wrist_Q"], pfl["control"]),
        dev_row("PhysioFlow-SB", psb["decision"]["S_arm"], psb["decision"]["S_real"], psb["C"], psb["auc"],
                psb["decision"]["wrist_Q"], psb["control"])]))

    # Table: realism on subjects never used for training.
    R = E["realism"]["realism"]
    order = (("round9", "PhysioMix"), ("physioflow", "PhysioFlow"), ("lsm_gan", "LSM-GAN"),
             ("gaussian_shaper", "Gaussian"), ("real_other_people", "Real (other subjects)"))
    rows = []
    for d in DOMAINS:
        r = R[d]
        cells = []
        for key, _ in order:
            v = r[key]
            cells.append(f"{100*v['fidelity']:.0f} / {100*v['coverage']:.0f} / {100*v['indistinguishable']:.0f}")
        rows.append(f"{NAME[d]} & {r['people']} & " + " & ".join(cells) + " \\\\")
    write("realism.tex", "\n".join(rows))
    CI = E["realism_ci"]["datasets"]
    rows = []
    for d in DOMAINS:
        cells = []
        for key, _ in order:
            v = CI[d][key]
            lo, hi = v["ci95"]["indistinguishable"]
            cells.append(f"{v['indistinguishable']:.0f} [{lo:.0f}, {hi:.0f}]")
        rows.append(f"{NAME[d]} & {CI[d]['people']} & " + " & ".join(cells) + " \\\\")
    write("realism_ci.tex", "\n".join(rows))

    # Table: published beat detectors on real and generated strips (within 5 bpm of the reference, %).
    DS = E["downstream"]
    rows = []
    for context, entry in DS["contexts"].items():
        for i, det in enumerate(("Elgendi", "MSPTD", "MSPTDfast")):
            cells = []
            for src in ("Real", "PhysioMix", "PhysioFlow", "Gaussian"):
                v = entry["sources"][src][det]
                lo, hi = v["within_5bpm_ci95"]
                cells.append(f"{100*v['within_5bpm']:.0f} [{100*lo:.0f}, {100*hi:.0f}]")
            head = (f"\\multirow{{3}}{{*}}{{\\shortstack[l]{{{context}\\\\ {entry['people']} / {entry['windows']}}}}}"
                    if i == 0 else "")
            rows.append(f"{head} & {det} & " + " & ".join(cells) + " \\\\")
        rows.append("\\addlinespace")
    rows.append("\\midrule")
    agree = DS["agreement"]
    rows.append("\\multicolumn{3}{l}{Mean $|$generated $-$ real$|$ (points)} & " + " & ".join(
        f"{agree[s]['mean_abs_gap_pp']:.1f}" for s in ("PhysioMix", "PhysioFlow", "Gaussian")) + " \\\\")
    write("detectors.tex", "\n".join(rows))

    # Table: condition following and memorisation screening.
    cf = E["realism"]["condition_following"]
    mem = E["realism"]["memorization"]
    rows = []
    for key, label in (("real_unseen", "Real, unseen"), ("round9", "PhysioMix"), ("physioflow", "PhysioFlow"),
                       ("lsm_gan", "LSM-GAN"), ("gaussian_shaper", "Gaussian")):
        c = cf[key]
        swap = "--" if "swap_following" not in c else f"{100*c['swap_following']:.0f}"
        wrist_ok = 100*c["accuracy"]["wrist_exercise"]
        mkey = "real_unseen" if key == "real_unseen" else key
        med = " & ".join(f"{mem[d][mkey]['median']:.2f}" for d in DOMAINS)
        rows.append(f"{label} & {100*c['balanced_accuracy']:.0f} & {wrist_ok:.0f} & {swap} & {med} \\\\")
    write("following.tex", "\n".join(rows))

    # Tables: everyday wrist PPG (GalaxyPPG). (a) fresh test of models trained without it, all 24 participants;
    # (b) retraining steps scored on the 12 held-out participants, each next to the references of the same run.
    fg = E["fresh_galaxy"]["summary"]
    def cell(s, key, d=1, scale=1.):
        return f"{scale*s[key]['mean']:.{d}f}"
    rows = []
    for key, label in (("real_other_people", "Real (other subjects)"), ("physiomix", "PhysioMix"),
                       ("physioflow", "PhysioFlow"), ("lsm_gan", "LSM-GAN"), ("gaussian_shaper", "Gaussian")):
        v = fg[key]
        rows.append(f"{label} & {v['indistinguishable']['mean']:.1f} $\\pm$ {v['indistinguishable']['sd']:.1f} & "
                    f"{cell(v, 'fidelity', 0, 100)} & {cell(v, 'coverage', 0, 100)} & {cell(v, 'Q', 2)} & "
                    f"{cell(v, 'rate_error_median_bpm')} & {cell(v, 'rate_within_5bpm', 0, 100)} \\\\")
    write("wrist_fresh.tex", "\n".join(rows))
    T = E["step_e_test"]["summary"]
    seeds = [T[f"physioflow_e_seed{s}"] for s in SEEDS]
    pooled = {k: dict(mean=float(np.mean([v[k]["mean"] for v in seeds])), sd=float(np.mean([v[k]["sd"] for v in seeds])),
                      seed_sd=float(np.std([v[k]["mean"] for v in seeds], ddof=1)))
              for k in ("indistinguishable", "Q", "rate_error_median_bpm", "rate_within_5bpm")}
    runs = (("B", E["step_b"]["summary"], (("physiomix_g", "PhysioMix-G"), ("physioflow_g", "PhysioFlow-G"))),
            ("D", E["step_d_test"]["summary"], (("physiomix_d_seed42", "PhysioMix-D"), ("physioflow_d_seed42", "PhysioFlow-D"))),
            ("E", dict(T, physioflow_e=pooled), (("physioflow_e", "PhysioFlow-E (3 seeds)"),)))
    rows = []
    for step, S, models in runs:
        for key, label in models:
            v = S[key]
            rows.append(f"{step} & {label} & {v['indistinguishable']['mean']:.1f} $\\pm$ {v['indistinguishable']['sd']:.1f} & "
                        f"{S['physiomix']['indistinguishable']['mean']:.1f} & {S['real_other_people']['indistinguishable']['mean']:.1f} & "
                        f"{cell(v, 'Q', 2)} & {cell(S['physiomix'], 'Q', 2)} & {cell(v, 'rate_error_median_bpm')} & "
                        f"{cell(v, 'rate_within_5bpm', 0, 100)} \\\\")
    write("wrist_retrain.tex", "\n".join(rows))

    # Table: decisions taken under rules fixed before training or scoring.
    r9, r10, l6 = E["physiomix"], E["physioflow"]["decision"], E["physioflow_sb"]["decision"]
    fd = E["fresh_galaxy"]["decision"]
    B, D, Ed = E["step_b"]["candidates"], E["step_d"]["candidates"], E["step_e"]
    old_b = E["step_b"]["old_validation"]
    rows = [
        f"R9 & PhysioMix R9 vs.\\ R7 & Validation & wrist $Q$ {r9['wrist_Q']['mean']:.3f} vs.\\ {r9['incumbent']['wrist_Q']['mean']:.3f} "
        f"(gap {r9['decision']['target_gap']:.3f} $>$ {r9['decision']['target_pooled_sd']:.3f}); $S_\\mathrm{{arm}}$ {r9['S_arm']['mean']:.3f} "
        f"$\\le$ {r9['incumbent']['S_arm']['mean']:.3f} + {r9['decision']['pooled_sd']:.3f} & Deployed (seed {r9['ship_seed']}) \\\\",
        f"R10 & PhysioFlow vs.\\ PhysioMix R9 & Validation & $S_\\mathrm{{arm}}$ gap {r10['gap']:.3f} $>$ {r10['pooled_sd']:.3f}; wrist $Q$ "
        f"{r10['wrist_Q']['mean']:.3f} $>$ {r10['incumbent_wrist_Q']['mean']:.3f} + {r10['wrist_pooled_sd']:.3f} & Not deployed; research mode \\\\",
        f"R10-SB & PhysioFlow-SB vs.\\ PhysioMix R9 & Validation & $S_\\mathrm{{arm}}$ gap {l6['gap']:.3f} $>$ {l6['pooled_sd']:.3f}; wrist $Q$ "
        f"{l6['wrist_Q']['mean']:.3f} $>$ {l6['incumbent_wrist_Q']['mean']+l6['wrist_pooled_sd']:.3f} & Not deployed \\\\",
        f"A & PhysioFlow vs.\\ PhysioMix & GalaxyPPG, 24 subjects & indistinguishable gap ${fd['gap']:.2f}$ $<$ {fd['margin']:.2f}; "
        f"$Q$ worse by more than 0.05 & PhysioMix kept \\\\",
        f"B & PhysioFlow-G, PhysioMix-G & GalaxyPPG, 12 held-out subjects; validation & PhysioFlow-G gap {B['physioflow_g']['gap']:.1f} $>$ "
        f"{B['physioflow_g']['margin']:.1f} but wrist $Q$ {old_b['physioflow_g']['wrist_Q']:.3f} $>$ 0.587; PhysioMix-G gap "
        f"{B['physiomix_g']['gap']:.1f} $<$ {B['physiomix_g']['margin']:.1f} & No final run \\\\",
        f"D & PhysioFlow-D, PhysioMix-D & 4 everyday-wrist validation subjects; validation & PhysioFlow-D gap {D['physioflow_d']['gap']:.1f} $<$ "
        f"{D['physioflow_d']['margin']:.1f}; PhysioMix-D gap {D['physiomix_d']['gap']:.1f} $<$ {D['physiomix_d']['margin']:.1f} & No final run \\\\",
        f"E & PhysioFlow-E, 3 seeds & 6 everyday-wrist validation subjects; validation & gap {Ed['gap']:.1f} $<$ {Ed['margin']:.1f}; "
        f"$Q$, rate and validation guards met & PhysioMix kept \\\\"]
    write("decisions.tex", "\n".join(rows))

    # Table: Raspberry Pi real-time output counters.
    P = E["pi"]
    def pi_row(label, rate, key):
        e = P[key]["engine"]
        dac = P[key].get("dac_errors") or [P[key].get("dac_write_errors_ir", 0), P[key].get("dac_write_errors_red", 0)]
        return (f"{label} & {rate} & {thou(e['samples_generated'])} & {e['overruns']} & {e['dropped_samples']} & "
                f"{e['underruns']} & {sum(dac)} \\\\")
    write("pi_timing.tex", "\n".join([
        pi_row("Headless, fixed sleep (initial)", "1000", "pi_headless_before"),
        pi_row("Headless, deadline sleep", "1000", "pi_headless_after"),
        pi_row("GUI + BLE + RX", "1000", "pi_gui_1k"),
        pi_row("GUI + BLE + RX, lighter redraw", "1000", "pi_gui_1k_light"),
        pi_row("GUI + BLE + RX, lighter redraw", "500", "pi_gui_500")]))

    # Table: generator footprint (latency measured here, single thread).
    lat = M["latency_ms"]
    man = E["manifest"]
    write("generators.tex", "\n".join([
        f"PhysioMix & {thou(E['physiomix']['params'])} & GAN, constructed rhythm & {lat['PhysioMix']['median']:.1f} \\\\",
        f"PhysioFlow & {thou(E['physioflow']['per_seed'][0]['params'])} & Rectified flow, 16 Heun steps & {lat['PhysioFlow']['median']:.0f} \\\\",
        f"LSM-GAN & {thou(M['params']['LSM-GAN'])} & GAN, unconditional & {lat['LSM-GAN']['median']:.1f} \\\\"]))
    return dict(wrist_e_test=pooled)


# --------------------------------------------------------------------------------------------- figures

def style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7, "axes.titlesize": 7.2, "axes.labelsize": 7,
                         "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "legend.fontsize": 6.2, "axes.linewidth": .6,
                         "xtick.major.width": .6, "ytick.major.width": .6, "lines.linewidth": .9,
                         "pdf.fonttype": 42, "ps.fonttype": 42, "savefig.dpi": 300, "figure.dpi": 150,
                         "axes.spines.top": False, "axes.spines.right": False})
    return plt


def save(fig, name):
    # No creation date in the PDF, so rerunning the script on unchanged evidence leaves the files unchanged.
    fig.savefig(FIG/f"{name}.pdf", bbox_inches="tight", pad_inches=.02, metadata={"CreationDate": None})
    fig.savefig(FIG/f"{name}.png", bbox_inches="tight", pad_inches=.02, dpi=200)


W = 5.4          # text width of the elsarticle preprint layout (390 pt); figures are drawn at print size
BOXFS = 5.9


def box(ax, xy, wh, text, fc="#FFFFFF", ec="#333333", fs=BOXFS, weight="normal",
        style="round,pad=0.003,rounding_size=0.008", lw=.6, color="#000000"):
    from matplotlib.patches import FancyBboxPatch
    x, y = xy
    w, h = wh
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=style, fc=fc, ec=ec, lw=lw, transform=ax.transAxes))
    ax.text(x+w/2, y+h/2, text, ha="center", va="center", fontsize=fs, weight=weight, transform=ax.transAxes,
            linespacing=1.18, color=color)


def arrow(ax, a, b, both=False, color="#333333", lw=.7, style="-|>", connection="arc3"):
    from matplotlib.patches import FancyArrowPatch
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=("<|-|>" if both else style), mutation_scale=5.5, lw=lw,
                                 color=color, transform=ax.transAxes, connectionstyle=connection,
                                 shrinkA=0, shrinkB=0))


def fig_system(plt):
    fig = plt.figure(figsize=(W, 3.75))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    soft, engine = "#EEF4FA", "#DCE9F6"
    box(ax, (.008, .04), (.425, .935), "", fc="#F7F7F7", ec="#777777", style="round,pad=0.003,rounding_size=0.015")
    ax.text(.2205, .945, "Raspberry Pi 4 (arm64 Linux, Python 3.12)", ha="center", fontsize=6.2, weight="bold",
            transform=ax.transAxes)
    box(ax, (.022, .79), (.193, .115), "Touch UI\n1024 × 600, EN/VI", fc=soft)
    box(ax, (.228, .79), (.193, .115), "BLE GATT server\n50 Hz stream", fc=soft)
    box(ax, (.022, .515), (.399, .22),
        "Signal engine thread\nmodel 100 Hz → interpolation → ring buffer\n"
        "→ DAC writer, 500 Hz, deadline pacing\nboth DACs at 0 V (LEDs off) when idle", fc=engine)
    box(ax, (.022, .275), (.193, .185), "Generator process\nTorchScript, CPU\n30 s strips, 40 Hz", fc="#FBE9DD")
    box(ax, (.228, .275), (.193, .185), "RX thread\nA0 (IR), A2 (red)\n100 Hz, explicit\nstatus flags", fc=soft)
    box(ax, (.022, .07), (.399, .15), "CSV recording and playback, atomic\nconfiguration, dry run without hardware", fc=soft)
    arrow(ax, (.118, .46), (.118, .515))
    arrow(ax, (.118, .79), (.118, .735), both=True)
    arrow(ax, (.324, .79), (.324, .735), both=True)
    ax.plot([.452, .452], [.2, .76], color="#444444", lw=1.6, transform=ax.transAxes, solid_capstyle="butt")
    ax.text(.457, .19, "I$^2$C bus", fontsize=5.9, transform=ax.transAxes, va="top")
    arrow(ax, (.421, .615), (.452, .615))
    arrow(ax, (.452, .37), (.421, .37))
    box(ax, (.475, .62), (.15, .11), "MCP4725, 0x60\nIR command")
    box(ax, (.475, .475), (.15, .11), "MCP4725, 0x61\nred command")
    box(ax, (.475, .245), (.15, .15), "Grove HAT ADC\nMM32, 0x08\n12 bit, 0–3.3 V")
    arrow(ax, (.452, .675), (.475, .675))
    arrow(ax, (.452, .53), (.475, .53))
    arrow(ax, (.475, .32), (.452, .32))
    box(ax, (.475, .835), (.15, .11), "Android app\n(BLE central)", fc=soft)
    arrow(ax, (.421, .85), (.475, .89), both=True)
    box(ax, (.65, .43), (.165, .33),
        "LED driver (×2)\n10 kΩ/10 kΩ divider\nLM358 + 2N4401\ncurrent sink\nR$_s$ = 100 Ω\n"
        "$I_E \\approx V_\\mathrm{DAC}/(2R_s)$", fc="#FFF6E5")
    arrow(ax, (.625, .675), (.65, .675))
    arrow(ax, (.625, .53), (.65, .53))
    box(ax, (.835, .17), (.158, .76), "", fc="#2F2F2F", ec="#2F2F2F", style="round,pad=0.003,rounding_size=0.015")
    ax.text(.914, .895, "Dark chamber", color="w", ha="center", fontsize=6, weight="bold", transform=ax.transAxes)
    box(ax, (.846, .67), (.136, .19), "Red LED\n620–625 nm\nIR LED\n875 nm", fc="#F4D2D2")
    box(ax, (.846, .49), (.136, .12), "Aperture\n2, 5, 16 mm", fc="#DDDDDD")
    box(ax, (.846, .2), (.136, .23), "OPT101\nreceiver\n1 MΩ TIA\nRC 1 kΩ, 1 µF", fc="#D9EAD3")
    arrow(ax, (.815, .6), (.846, .74))
    for a, b in (((.914, .67), (.914, .61)), ((.914, .49), (.914, .43))):
        arrow(ax, a, b, color="#FFFFFF")
    arrow(ax, (.846, .31), (.625, .31))
    ax.text(.735, .275, "A0, A2", fontsize=5.9, ha="center", transform=ax.transAxes)
    save(fig, "fig1_system")
    plt.close(fig)


def fig_hardware(plt):
    from PIL import Image
    paths = [ROOT/"hardware/led_ir_driver/reports/pcb_top.png",
             ROOT/"hardware/opt101_receiver_kicad/opt101_receiver/reports/pcb_top.png",
             ROOT/"docs/ui/touch-output/physiomix-en-pi-panel-1024.png"]
    for p in paths:
        USED[str(p.relative_to(ROOT))] = sha256(p)
    crops = [(195, 250, 1372, 925), (195, 415, 1372, 762), None]
    fig = plt.figure(figsize=(W, 2.05))
    axes = [fig.add_axes([0, .55, .33, .43]), fig.add_axes([0, .1, .33, .28]), fig.add_axes([.35, .1, .65, .88])]
    labels = ["(a) LED driver, 70 × 40 mm", "(b) OPT101 receiver, 70 × 20 mm",
              "(c) Generator page, laptop dry run, 1024 × 600"]
    for p, crop, ax, lab in zip(paths, crops, axes, labels):
        im = Image.open(p).convert("RGB")
        if crop:
            im = im.crop(crop)
        ax.imshow(im)
        ax.set_axis_off()
        ax.text(.5, -.04, lab, transform=ax.transAxes, ha="center", va="top", fontsize=6.2)
    save(fig, "fig2_hardware_ui")
    plt.close(fig)


def fig_architecture(plt):
    fig = plt.figure(figsize=(W, 4.45))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    shared, gan, flow, grey = "#E8F1E4", "#E3EEF8", "#FBE9DD", "#F2F2F2"
    box(ax, (.08, .885), (.84, .1), "Inputs: noise $z \\in \\mathbb{R}^{1200}$; condition $c$ = dataset one-hot (6),\n"
        "label-known flags (2), standardised rate, inter-beat-interval CV, signal SD", fc="#FFFFFF")
    box(ax, (.08, .755), (.84, .1), "Rhythm scaffold (both models): log-normal inter-beat intervals, mean 60/rate\n"
        "and log-scale SD $\\sigma_\\tau$ from $c$, drawn from $z$ → beat phase $\\phi(t)$ over 30 s", fc=shared)
    arrow(ax, (.5, .885), (.5, .855))
    arrow(ax, (.3, .755), (.255, .712))
    arrow(ax, (.7, .755), (.745, .712))
    ax.text(.255, .672, "(a) PhysioMix: conditional GAN", ha="center", va="bottom", fontsize=6.5, weight="bold",
            transform=ax.transAxes)
    ax.text(.745, .672, "(b) PhysioFlow: rectified flow", ha="center", va="bottom", fontsize=6.5,
            weight="bold", transform=ax.transAxes)
    texts_a = ("Trunk: parallel Conv1d (k = 5, 21, 61) on $z$\nand [sin $\\phi$, cos $\\phi$, sin 2$\\phi$, sin 3$\\phi$];\n"
               "8 dilated residual blocks (d = 1 ... 128),\nFiLM from MLP($z_{1:8}$, $c$)",
               "Pulse head at 1 s knots: 6 harmonic weights\nand phases, baseline, gain; systole fixed,\n"
               "diastole absorbs IBI changes; beat gain\n$(\\tau_{k-1}f)^{\\beta}$; residual $0.15\\tanh\\zeta$; motion $m(t)$",
               "0.5–8 Hz band limit on a padded window,\ncentre crop, min–max → 1200 samples",
               "Critic: 3 scales, spectral norm, input\n$[x, 10\\Delta x, 20\\Delta^2 x]$, projection on $c$; hinge\n"
               "loss, lazy R1 (weight 0.1), spectral/ACF loss, EMA")
    texts_b = ("1-D U-Net, 5 levels (1200 → 75 samples),\nattention at 150 and 75 samples, FiLM\n"
               "from flow-time and condition embeddings;\ninput $[x_s$, sin $\\phi$, cos $\\phi$, flag$]$",
               "Training: $x_s=(1-s)\\,x_0+s\\,\\varepsilon$, $s\\sim U(0,1)$,\ntarget $\\varepsilon-x_0$; MSE plus\n"
               "$(1-s)^2$-weighted first-difference loss;\n10% condition, 15% scaffold dropout",
               "16 Heun steps from $s$ = 1 to 0 (31 network\ncalls), min–max → 1200 samples",
               "No critic and no output filter; scaffold\nsupplied only when the condition marks\nthe rate as known")
    heights, ys = (.15, .15, .085, .125), (.515, .34, .23, .045)
    for (x, fc), texts in zip(((.02, gan), (.51, flow)), (texts_a, texts_b)):
        for i, (text, h, y) in enumerate(zip(texts, heights, ys)):
            last = i == len(texts)-1
            box(ax, (x, y), (.47, h), text, fc=grey if last else fc, ec="#888888" if last else "#333333")
        cx = x+.235
        arrow(ax, (cx, .515), (cx, .49))
        arrow(ax, (cx, .34), (cx, .315))
    ax.plot([.02, .98], [.197, .197], color="#BBBBBB", lw=.6, ls=":", transform=ax.transAxes)
    save(fig, "fig3_generators")
    plt.close(fig)


def fig_waveforms(plt, E):
    """10 s excerpts: one test-split window per dataset and generator outputs prompted at its rate."""
    import torch
    from ml.kaggle_multidomain.labels import beat_stats
    gens = generators()
    with np.load(SOURCES["pack"], allow_pickle=False) as z:
        signal, domain, split, ref = z["signal"], z["domain"], z["split"], z["reference_hr_bpm"]
    rng = np.random.default_rng(20261018)
    shown = ("gxu_finger", "perform_large", "perform_af", "wrist")
    fig, axes = plt.subplots(len(shown), 4, figsize=(W, 3.9), sharex=True)
    t = np.arange(400)/40
    prompts = {}
    for i, d in enumerate(shown):
        ids = np.flatnonzero((domain == d) & (split == "test"))
        k = rng.choice(ids)
        row = signal[k]
        # Exercise wrist PPG is motion-dominated; its ECG reference rate is the honest prompt there.
        rate, source = (float(ref[k]), "ECG") if d == "wrist" and np.isfinite(ref[k]) else (float(beat_stats(row[None])[0, 0]), "PPG")
        rate = float(np.clip(rate, 40, 180))
        default_cv = gens["PhysioMix"].meta["domain_defaults"][d][0]
        prompts[d] = dict(rate=rate, rate_source=source, irregularity=default_cv)
        series = [("Real (test subject)", row)]
        for name in ("PhysioMix", "PhysioFlow"):
            g = gens[name]
            zz = torch.randn(1, 1200, generator=torch.Generator().manual_seed(7))
            with torch.inference_mode():
                series.append((name, g.model(zz, torch.tensor([g.condition(d, rate, default_cv)]))[0, 0].numpy()))
        with torch.inference_mode():
            lsm = gens["LSM-GAN"].model(torch.randn(1, 1200, generator=torch.Generator().manual_seed(7+i)))[0, 0].numpy()
        series.append(("LSM-GAN", lsm))
        for j, (name, y) in enumerate(series):
            ax = axes[i, j]
            ax.plot(t, y[400:800], color=COLOR.get(name, "#000000"), lw=.75)
            ax.set_ylim(-.05, 1.05)
            ax.set_yticks([0, 1] if j == 0 else [])
            ax.set_xticks([0, 5, 10])
            if i == 0:
                ax.set_title(name if name != "LSM-GAN" else "LSM-GAN (no condition)", fontsize=7.5)
            if j == 0:
                ax.set_ylabel(f"{NAME[d]}\n{rate:.0f} bpm ({source})", fontsize=6.8)
            else:
                ax.spines["left"].set_visible(False)
    for ax in axes[-1]:
        ax.set_xlabel("Time (s)")
    fig.tight_layout(pad=.3, w_pad=.6, h_pad=.3)
    save(fig, "fig4_waveforms")
    plt.close(fig)
    return prompts


def fig_rate(plt, M):
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.45), sharey=True)
    marks = dict(zip(DOMAINS, ("o", "s", "^", "D", "v", "P")))
    for ax, name in zip(axes, ("PhysioMix", "PhysioFlow")):
        ax.plot([40, 180], [40, 180], color="#BBBBBB", lw=.8, ls="--", zorder=0)
        ax.axvspan(60, 140, color="#F2F2F2", zorder=-1)
        for d in DOMAINS:
            r = M["rate"][name][d]
            g = np.asarray(r["grid"])
            med = np.asarray([np.nan if v is None else v for v in r["median"]])
            lo = np.asarray([np.nan if v is None else v for v in r["q25"]])
            hi = np.asarray([np.nan if v is None else v for v in r["q75"]])
            ax.errorbar(g, med, yerr=[med-lo, hi-med], fmt=marks[d], ms=2.6, lw=.6, capsize=0, label=NAME[d],
                        mfc="none", mew=.7)
        ax.set_title(name)
        ax.set_xlabel("Commanded rate (bpm)")
        ax.set_xlim(35, 185)
        ax.set_ylim(35, 185)
    axes[0].set_ylabel("Measured rate (bpm)")
    axes[1].legend(ncol=2, frameon=False, loc="upper left", handletextpad=.3, columnspacing=.8)
    fig.tight_layout(pad=.3)
    save(fig, "fig5_rate_control")
    plt.close(fig)


def fig_realism(plt, E):
    R = E["realism"]["realism"]
    srcs = (("round9", "PhysioMix"), ("physioflow", "PhysioFlow"), ("lsm_gan", "LSM-GAN"),
            ("gaussian_shaper", "Gaussian"), ("real_other_people", "Real (other subjects)"))
    fig, axes = plt.subplots(1, 3, figsize=(W, 2.7), sharey=True)
    x = np.arange(len(DOMAINS))
    w = .16
    CI = E["realism_ci"]["datasets"]
    for ax, metric, ci_key, title in zip(axes, ("fidelity", "coverage", "indistinguishable"),
                                         ("precision", "recall", "indistinguishable"),
                                         ("(a) Precision", "(b) Recall", "(c) Indistinguishable")):
        for k, (key, label) in enumerate(srcs):
            vals = np.array([100*R[d][key][metric] for d in DOMAINS])
            lo = np.array([CI[d][key]["ci95"][ci_key][0] for d in DOMAINS])
            hi = np.array([CI[d][key]["ci95"][ci_key][1] for d in DOMAINS])
            ax.bar(x+(k-2)*w, vals, w, color=COLOR[label], label=label, lw=0,
                   yerr=[np.clip(vals-lo, 0, None), np.clip(hi-vals, 0, None)],
                   error_kw=dict(lw=.45, capsize=0, ecolor="#444444"))
        ax.set_xticks(x)
        ax.set_xticklabels([NAME[d] for d in DOMAINS], rotation=40, ha="right")
        ax.set_title(title)
        ax.set_ylim(0, 100)
        ax.grid(axis="y", color="#E5E5E5", lw=.5)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("Percent")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, ncol=5, frameon=False, loc="upper center", bbox_to_anchor=(.5, 1.0),
               handlelength=1.1, columnspacing=1.2)
    fig.tight_layout(pad=.3, rect=(0, 0, 1, .9))
    save(fig, "fig6_realism")
    plt.close(fig)


def fig_wrist(plt, E, pooled_e):
    from scipy.stats import spearmanr
    fg, J, B = E["fresh_galaxy"]["summary"], E["judges"], E["step_b"]["summary"]
    D = E["step_d_test"]["summary"]
    rows = [("Real (other subjects)", fg["real_other_people"]["indistinguishable"]), ("PhysioMix", fg["physiomix"]["indistinguishable"]),
            ("PhysioFlow", fg["physioflow"]["indistinguishable"]), ("LSM-GAN", fg["lsm_gan"]["indistinguishable"]),
            ("Gaussian", fg["gaussian_shaper"]["indistinguishable"]), ("PhysioMix-G", B["physiomix_g"]["indistinguishable"]),
            ("PhysioFlow-G", B["physioflow_g"]["indistinguishable"]), ("PhysioMix-D", D["physiomix_d_seed42"]["indistinguishable"]),
            ("PhysioFlow-D", D["physioflow_d_seed42"]["indistinguishable"]), ("PhysioFlow-E", pooled_e["indistinguishable"])]
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.75), gridspec_kw=dict(width_ratios=[1.25, 1]))
    ax = axes[0]
    y = np.arange(len(rows))[::-1]
    for yy, (label, s) in zip(y, rows):
        ax.barh(yy, s["mean"], xerr=s["sd"], color=COLOR.get(label, "#666666"), height=.62, error_kw=dict(lw=.6),
                hatch="////" if label.endswith(("-G", "-D", "-E")) else None, ec="white", lw=0)
        right = s["mean"]+s["sd"]
        if right > 90:
            ax.text(s["mean"]-2, yy, f"{s['mean']:.1f}", va="center", ha="right", fontsize=6.3, color="white")
        else:
            ax.text(right+1.5, yy, f"{s['mean']:.1f}", va="center", fontsize=6.3)
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows])
    ax.axhline(4.5, color="#999999", lw=.6, ls=":")
    ax.text(103, 4.75, "24 participants,\nno GalaxyPPG in training", fontsize=5.6, ha="right", va="bottom", color="#555555")
    ax.text(103, 4.25, "12 held-out participants,\nGalaxyPPG in training", fontsize=5.6, ha="right", va="top", color="#555555")
    ax.set_xlim(0, 105)
    ax.set_xlabel("Indistinguishable (%)")
    ax.set_title("(a) Everyday wrist PPG")
    ax = axes[1]
    pts = []
    for setname, summ in [("WRIST-DAILY", J["galaxy_test"]["summary"])]+[(NAME[k], v["summary"]) for k, v in J["v3_unseen"].items()]:
        for src, v in summ.items():
            if src == "real_other_people":
                continue
            pts.append((setname, SOURCE_NAME.get(src, src), v["cnn"]["mean"], v["papagei"]["indistinguishable"]["mean"]))
    rho = spearmanr([p[2] for p in pts], [p[3] for p in pts]).statistic
    markers = {"WRIST-DAILY": "o", "FINGER": "s", "MIMIC-L": "^", "BIDMC": "D", "WRIST-EX": "v"}
    for s, label, a, b in pts:
        ax.scatter(a, b, s=14, marker=markers[s], color=COLOR.get(label, "#666666"), lw=.4, ec="white")
    ax.plot([0, 100], [0, 100], color="#BBBBBB", lw=.7, ls="--", zorder=0)
    ax.set_xlim(-3, 100)
    ax.set_ylim(-3, 100)
    ax.set_xlabel("Derivative CNN (%)")
    ax.set_ylabel("PaPaGei-S (%)")
    ax.set_title("(b) Agreement of two judges")
    ax.text(97, -1, f"Spearman $\\rho$ = {rho:.2f}", fontsize=6.6, ha="right", va="bottom")
    fig.tight_layout(pad=.3, w_pad=1.)
    save(fig, "fig7_wrist_judges")
    plt.close(fig)
    return float(rho), len(pts)


# ------------------------------------------------------------------------------------------------ main

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--no-measure", action="store_true", help="reuse data/measured.json")
    args = parser.parse_args()
    for d in (FIG, TAB, DATA):
        d.mkdir(parents=True, exist_ok=True)
    E = evidence()
    measured_path = DATA/"measured.json"
    if args.no_measure:
        M = json.loads(measured_path.read_text())
    else:
        M = measure()
        measured_path.write_text(json.dumps(M, indent=1))
    extra = tables(E, M)
    plt = style()
    fig_system(plt)
    fig_hardware(plt)
    fig_architecture(plt)
    prompts = fig_waveforms(plt, E)
    fig_rate(plt, M)
    fig_realism(plt, E)
    rho, pairs = fig_wrist(plt, E, extra["wrist_e_test"])
    J = E["judges"]["galaxy_test"]["summary"]
    lsm_narrow = load("realism_lsm_narrow")["realism"]["bidmc"]["lsm_gan"]
    text_numbers = dict(
        band_limited_galaxy={k: {b: round(x["mean"], 1) for b, x in J[k]["cnn_by_band"].items()}
                             for k in ("real_other_people", "physiomix", "physioflow", "physioflow_g")},
        lsm_bidmc_own_band={k: round(100*lsm_narrow[k], 1) for k in ("fidelity", "coverage", "indistinguishable")},
        step_e_real_per_halving=[round(h["real_other_people"]["indistinguishable"], 1)
                                 for h in E["step_e"]["daily_validation_per_halving"]],
        rate_fresh={name: dict(max_abs_median_error=round(max(abs(m-g) for d in M["rate"][name].values()
                                                              for g, m in zip(d["grid"], d["median"]) if m is not None), 2))
                    for name in ("PhysioMix", "PhysioFlow")})
    summary = dict(sources=USED, judges_spearman=rho, judges_pairs=pairs, measured=M, fig4_prompts=prompts,
                   text_numbers=text_numbers,
                   step_e_test_pooled=extra["wrist_e_test"])
    (DATA/"evidence_index.json").write_text(json.dumps(summary, indent=1, sort_keys=True))
    print(json.dumps({"figures": sorted(p.name for p in FIG.glob("*.pdf")),
                      "tables": sorted(p.name for p in TAB.glob("*.tex")), "judges_spearman": round(rho, 3),
                      "latency_ms": {k: round(v["median"], 1) for k, v in M["latency_ms"].items()}}, indent=1))


if __name__ == "__main__":
    main()
