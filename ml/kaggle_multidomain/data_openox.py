"""Local pack ppg_openox_red_v1: paired (infrared, red) windows from the OpenOximetry Repository 1.1.1 discrete PPG files.

OpenOximetry (Fong et al., PhysioNet openox-repo 1.1.1, restricted access under the PhysioNet Restricted Health Data
Use Agreement 1.5.0) is used on this machine only: the pack is written below ml/runs (outside git) and is never
uploaded. Its people are new to the PhysioFlow-2 work, so they can serve as the fresh validation people that RULE_12
requires for any further change.

Each `<encounter_id>_ppg` record (86 Hz, unscaled, unfiltered; not time-synchronised with the other waveforms) holds
either IR/RED counts or `IR Signal`/`Red Signal` with drive, DC and modulation channels. The signal channels are used
in every format and processed exactly as PTT in data_dual: v3 view of the sign-corrected, mean-removed record, 30 s
windows, R = (ptp(AC_red)/DC_red)/(ptp(AC_ir)/DC_ir) with the raw window mean as DC, red = R*(red_view - mean). The
records carry no ECG, so polarity is fixed per record from the pulse shape (the systolic upstroke is steeper than the
diastolic decline); a record with an ambiguous shape is skipped. A window keeps its red only if R is in R_RANGE and the
infrared and red views correlate (QUALITY_CORR), which rejects detached or dead channels. People are split 70/15/15
by patient_id (encounter.csv) with OPENOX_SPLIT_SEED. R is a device optical ratio, not an SpO2 label; the
desaturation protocol (SaO2 70-100 %) widens its range compared with FINGER and PTT.

    PPG_DRY_RUN=1 .venv/bin/python -m ml.kaggle_multidomain.data_openox \
        --root ~/datasets/openox/physionet.org/files/openox-repo/1.1.1 --output ml/runs/openox-red-v1
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

from ml.kaggle_lsm.train_lsm import FS, LENGTH, save_json
from ml.kaggle_multidomain.data import digest, split_patients
from ml.kaggle_multidomain.data_dual import R_RANGE, red_relative, view, window_ratio
from ml.kaggle_multidomain.data_gxu import EDGE_EXCESS_MAX, edge_excess
from ml.kaggle_multidomain.data_more import finite_windows
from ml.kaggle_multidomain.flow import window_peaks

PROTOCOL = "ppg_openox_red_v1"
VERSION = "1.1.1"
DOMAIN = "openox"
OPENOX_FS = 86
OPENOX_SPLIT_SEED = 20261022
CHANNELS = (("IR", "RED"), ("IR Signal", "Red Signal"))
QUALITY_CORR = .8              # infrared/red view correlation below this: detached or dead channel
POLARITY_MIN = 1.25            # steep-side / shallow-side slope ratio needed to fix the polarity
MAX_WINDOWS_PER_RECORD = 40    # evenly spaced, so long desaturation records do not dominate


def checksums(root):
    return {line.split()[1]: line.split()[0] for line in (Path(root)/"SHA256SUMS.txt").read_text().splitlines()
            if line.strip()}


def verify(root, relative, sums):
    if digest(Path(root)/relative) != sums.get(relative):
        raise ValueError(f"OpenOximetry checksum mismatch: {relative}")


def encounter_patients(root):
    with open(Path(root)/"encounter.csv", newline="") as f:
        return {row["encounter_id"]: row["patient_id"] for row in csv.DictReader(f)}


def polarity(ir, fs):
    """+1 or -1 so that sign*(ir - mean) has the steep systolic upstroke; None if the shape is ambiguous."""
    sos = butter(2, (.5, 8.), "bandpass", fs=fs, output="sos")
    slope = np.diff(sosfiltfilt(sos, ir-np.mean(ir)))
    up, down = np.percentile(slope, 99), -np.percentile(slope, 1)
    if min(up, down) <= 0:
        return None
    ratio = up/down
    return 1 if ratio >= POLARITY_MIN else -1 if 1/ratio >= POLARITY_MIN else None


def spaced(items, limit=MAX_WINDOWS_PER_RECORD):
    if len(items) <= limit:
        return items
    return [items[i] for i in np.unique(np.linspace(0, len(items)-1, limit).round().astype(int))]


def record_rows(record, patient, stats):
    names = record.sig_name
    pair = next((p for p in CHANNELS if p[0] in names and p[1] in names), None)
    if pair is None:
        stats["records_without_signal_channels"] += 1
        return []
    if int(round(record.fs)) != OPENOX_FS:
        stats["records_unexpected_fs"] += 1
        return []
    ir, red = (record.p_signal[:, names.index(c)].astype(np.float64) for c in pair)
    if not (np.isfinite(ir).all() and np.isfinite(red).all()) or len(ir) < 30*OPENOX_FS or np.ptp(ir) <= 0:
        stats["records_nonfinite_or_short"] += 1
        return []
    sign = polarity(ir, OPENOX_FS)
    if sign is None:
        stats["records_polarity_ambiguous"] += 1
        return []
    stats[f"records_format_{len(names)}ch"] += 1
    ir_view, red_view = view(sign*(ir-ir.mean()), OPENOX_FS), view(sign*(red-red.mean()), OPENOX_FS)
    ir_clips, bad = finite_windows(sign*(ir-ir.mean()), OPENOX_FS, "v3")
    red_clips = dict(finite_windows(sign*(red-red.mean()), OPENOX_FS, "v3")[0])
    stats.update({"openox:"+k: v for k, v in bad.items()})
    rows = []
    for start, wave in spaced(ir_clips):
        ratio, pi = window_ratio(ir_view, red_view, ir, red, OPENOX_FS, start) if start in red_clips else (np.nan, np.nan)
        corr = float(np.corrcoef(ir_view[start:start+LENGTH], red_view[start:start+LENGTH])[0, 1]) \
            if start in red_clips else np.nan
        known = bool(np.isfinite(ratio) and R_RANGE[0] <= ratio <= R_RANGE[1] and np.isfinite(corr)
                     and corr >= QUALITY_CORR)
        if window_peaks(wave) is None:
            stats["windows_without_peaks"] += 1
            continue
        stats["windows_red" if known else "windows_no_red"] += 1
        rows.append(dict(signal=wave.astype(np.float32), subject="openox:"+patient, domain=DOMAIN,
                         record="openox:"+record.record_name, start=int(start), channels=len(names),
                         red=red_relative(red_clips[start], ratio) if known else np.zeros(LENGTH, np.float32),
                         red_known=known, ratio_r=ratio if known else np.nan, pi_ir=pi if known else np.nan,
                         ir_red_corr=corr))
    return rows


def build(root, output):
    import wfdb
    root, output = Path(root).expanduser(), Path(output)
    sums = checksums(root)
    for name in ("encounter.csv", "RECORDS"):
        verify(root, name, sums)
    patients = encounter_patients(root)
    records = [r for r in (root/"RECORDS").read_text().split() if r.endswith("_ppg")]
    stats, rows = Counter(listed_ppg_records=len(records)), []
    for relative in records:
        if not all((root/f"{relative}{s}").exists() for s in (".hea", ".dat")):
            stats["records_not_downloaded"] += 1
            continue
        for suffix in (".hea", ".dat"):
            verify(root, relative+suffix, sums)
        encounter = Path(relative).name[:-len("_ppg")]
        if encounter not in patients:
            stats["records_without_encounter"] += 1
            continue
        rows.extend(record_rows(wfdb.rdrecord(str(root/relative)), patients[encounter], stats))
    if not rows:
        raise ValueError("No OpenOximetry windows")
    quality = edge_excess(np.stack([r["signal"] for r in rows])) <= EDGE_EXCESS_MAX
    stats["windows_edge_rejected"] = int((~quality).sum())
    rows = [r for r, q in zip(rows, quality) if q]
    assignment = split_patients([r["subject"] for r in rows], seed=OPENOX_SPLIT_SEED)
    out = {k: np.asarray([r[k] for r in rows]) for k in rows[0]}
    out["split"] = np.asarray([assignment[s] for s in out["subject"]])
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output/"windows.npz", **out)
    content = hashlib.sha256()
    for key in ("signal", "red", "red_known", "ratio_r", "subject", "split"):
        content.update(np.ascontiguousarray(out[key]).tobytes())
    counts = {s: dict(windows=int((out["split"] == s).sum()), people=len(set(out["subject"][out["split"] == s])),
                      red=int(((out["split"] == s) & out["red_known"]).sum())) for s in ("train", "validation", "test")}
    r = out["ratio_r"][out["red_known"]]
    save_json(output/"manifest.json", dict(
        protocol=PROTOCOL, source=f"https://physionet.org/content/openox-repo/{VERSION}/", version=VERSION,
        access="PhysioNet Restricted Health Data Use Agreement 1.5.0; local use only, never uploaded",
        windows_sha256=digest(output/"windows.npz"), content_sha256=content.hexdigest(), view="v3", fs_hz=FS,
        seconds=LENGTH//FS, domain=DOMAIN, split_seed=OPENOX_SPLIT_SEED, counts=counts,
        ratio_r=dict(median=float(np.median(r)), p5=float(np.percentile(r, 5)), p95=float(np.percentile(r, 95))),
        quality=dict(corr_min=QUALITY_CORR, r_range=list(R_RANGE), polarity_min=POLARITY_MIN,
                     max_windows_per_record=MAX_WINDOWS_PER_RECORD, edge_excess_max=EDGE_EXCESS_MAX),
        stats=dict(stats),
        limitations=["R is a device optical ratio; it is not an SpO2 label (PPG files are not time-synchronised "
                     "with the blood-gas or reference oximeter data)",
                     "polarity fixed from the pulse shape (no ECG); ambiguous records skipped",
                     "lab protocol at rest: no walking or running motion"]))
    return out


def load_openox(root):
    paths = [p for p in Path(root).rglob("windows.npz") if (p.parent/"manifest.json").exists()
             and json.loads((p.parent/"manifest.json").read_text()).get("protocol") == PROTOCOL]
    if len(paths) != 1:
        raise ValueError(f"Expected one {PROTOCOL} pack, found {len(paths)}")
    manifest = json.loads((paths[0].parent/"manifest.json").read_text())
    if digest(paths[0]) != manifest["windows_sha256"]:
        raise ValueError(f"{PROTOCOL} checksum mismatch")
    with np.load(paths[0], allow_pickle=False) as source:
        return {k: source[k] for k in source.files}, manifest


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    a = parser.parse_args(argv)
    out = build(a.root, a.output)
    print(json.dumps(json.loads((Path(a.output)/"manifest.json").read_text())["counts"]), len(out["signal"]))


if __name__ == "__main__":
    main()
