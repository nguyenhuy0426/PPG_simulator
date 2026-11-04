"""Round 11 data pack ppg_physioflow2_v4: the v3e pack plus a paired red channel where the data have one.

The infrared channel stays exactly the v3 view (record mean removed, 40 Hz, zero-phase 0.5-8 Hz Butterworth, per-window
min-max), so every earlier criterion still applies to it. Red is stored relative to infrared: for a window with
ratio of ratios R = (ptp(AC_red)/DC_red) / (ptp(AC_ir)/DC_ir), computed on the same view of the raw record with the
raw window mean as DC, red = R * (red_view - mean(red_view)), where red_view is the red window in the v3 view. Then
ptp(red) = R and ptp(infrared) = 1, so a generator that learns (infrared, red) learns the red shape and the ratio of
ratios together. R is an optical ratio of the recording device, not an SpO2 value.

Red is available for:
- FINGER (Li et al., PPG_RED 660 nm / PPG_IR 940 nm, 250 Hz): the v3g red windows (gxu_red_windows.npz), with R from
  the raw archive; each re-derived infrared window must match the pack row (correlation > 0.99) before it is used.
- PTT (Mehrgardt et al., PhysioNet pulse-transit-time-ppg 1.0.0, MAX30101, 500 Hz), rebuilt here from the raw records,
  distal phalanx only: infrared = pleth_2, red = pleth_1. The README's methods text and channel list disagree on this
  mapping; on the 19 sitting records available when this was written the median R of pleth_1/pleth_2 was 0.42 with
  every record below 0.6, whereas the reversed mapping would give R > 1, incompatible with the SpO2 of 96-99% in the
  record headers (engineering inference, not confirmed by the dataset authors). PTT becomes three training contexts
  (ptt_sit, ptt_walk, ptt_run) with subject-disjoint splits. The v3 PTT windows (pleth_1 read as if it were the
  infrared channel, external split, never used for selection) are removed.

Every other dataset has red_known = False. Deterministic; the manifest records every digest.
"""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np

from ml.kaggle_lsm.train_lsm import FS, LENGTH, save_json
from ml.kaggle_multidomain.data import digest, split_patients
from ml.kaggle_multidomain.data_gxu import (GXU_FS, NAME, edge_excess, EDGE_EXCESS_MAX, load_input, polarity_lag,
                                            r_peaks, read_record, reference_rate)
from ml.kaggle_multidomain.data_more import finite_windows
from ml.kaggle_multidomain.view import resample_filter

PROTOCOL = "ppg_physioflow2_v4"
BASE_PROTOCOL = "ppg_physiomix_v3e"
PTT_VERSION = "1.0.0"
PTT_FS = 500
PTT_ACTIVITIES = {"sit": 7, "walk": 8, "run": 9}
PTT_CHANNELS = dict(infrared="pleth_2", red="pleth_1", site="distal phalanx")
PTT_SPLIT_SEED = 20261021
ALIGN_MIN = .99           # correlation of a re-derived infrared window with the pack row
R_RANGE = (.05, 3.)       # outside this the ratio is treated as a failed measurement (red_known = False)


def view(raw, fs):
    ratio = Fraction(FS/float(fs)).limit_denominator(10000)
    return resample_filter(np.asarray(raw, np.float64), ratio.numerator, ratio.denominator, "v3")


def window_ratio(ir_view, red_view, ir_raw, red_raw, fs, start):
    """(R, PI_ir in %) of one 40 Hz window from whole-record views and raw samples; NaN if undefined."""
    sl = slice(start, start+LENGTH)
    raw = slice(round(start*fs/FS), round((start+LENGTH)*fs/FS))
    dc_ir, dc_red = np.nanmean(ir_raw[raw]), np.nanmean(red_raw[raw])
    if not (np.isfinite(dc_ir) and np.isfinite(dc_red)) or dc_ir <= 0 or dc_red <= 0:
        return np.nan, np.nan
    a_ir, a_red = np.ptp(ir_view[sl])/dc_ir, np.ptp(red_view[sl])/dc_red
    return (float(a_red/a_ir) if a_ir > 0 else np.nan), float(100*a_ir)


def red_relative(red_window, ratio):
    return (ratio*(red_window-red_window.mean())).astype(np.float32)


def finger_red(pack, base_rows, v3g_root, archive, stats):
    """Fill red, R and PI for FINGER rows from the v3g red windows and the raw GXU archive."""
    paired = np.load(Path(v3g_root)/"gxu_red_windows.npz", allow_pickle=False)
    red_of = {int(r): w for r, w in zip(paired["row"], paired["red"])}
    by_record = {}
    for new, old in enumerate(base_rows):
        if pack["domain"][new] == "gxu_finger":
            by_record.setdefault(str(pack["record"][new]), []).append((int(old), new))
    with zipfile.ZipFile(archive) as z:
        files = {f"gxu:{m.group(1)}_{m.group(2)}": n for n in z.namelist() if (m := NAME.search(n))}
        for record, rows in sorted(by_record.items()):
            name = files.get(record)
            if name is None:
                stats["finger_missing_record"] += len(rows)
                continue
            ecg, red, ir = read_record(z.read(name))
            if not (np.isfinite(red).all() and np.isfinite(ir).all()):
                stats["finger_nonfinite_record"] += len(rows)
                continue
            ir_view, red_view = view(-(ir-ir.mean()), GXU_FS), view(-(red-red.mean()), GXU_FS)
            for old, new in rows:
                start = int(pack["start"][new])
                w = ir_view[start:start+LENGTH]
                if len(w) < LENGTH or old not in red_of:
                    stats["finger_no_red_window"] += 1
                    continue
                if np.corrcoef(w, pack["signal"][new])[0, 1] < ALIGN_MIN:
                    stats["finger_misaligned"] += 1
                    continue
                ratio, pi = window_ratio(ir_view, red_view, ir, red, GXU_FS, start)
                if not R_RANGE[0] <= ratio <= R_RANGE[1]:
                    stats["finger_ratio_out_of_range"] += 1
                    continue
                pack["red"][new] = red_relative(red_of[old], ratio)
                pack["red_known"][new], pack["ratio_r"][new], pack["pi_ir"][new] = True, ratio, pi
                stats["finger_red"] += 1


def ptt_rows(ptt_dir, stats):
    """New PTT windows: infrared signal in the v3 view, relative red, R, PI and the ECG reference rate."""
    import wfdb
    subjects = [f"ptt:s{s}" for s in range(1, 23)]
    assignment = split_patients(subjects, seed=PTT_SPLIT_SEED)
    out = {k: [] for k in ("signal", "subject", "domain", "split", "record", "start", "activity_label",
                           "rhythm_label", "reference_hr_bpm", "red", "red_known", "ratio_r", "pi_ir")}
    for s in range(1, 23):
        for activity, code in PTT_ACTIVITIES.items():
            name = f"s{s}_{activity}"
            record = wfdb.rdrecord(str(Path(ptt_dir)/name))
            if int(record.fs) != PTT_FS:
                raise ValueError(f"{name}: unexpected sampling rate {record.fs}")
            channel = {n: record.p_signal[:, i] for i, n in enumerate(record.sig_name)}
            ecg, ir, red = channel["ecg"], channel[PTT_CHANNELS["infrared"]], channel[PTT_CHANNELS["red"]]
            peaks = r_peaks(ecg, PTT_FS)
            lag = polarity_lag(ir, peaks, PTT_FS)
            if lag is None or not .1 <= lag <= .6:
                stats["ptt_polarity_unverified" if lag is None else "ptt_polarity_inconsistent"] += 1
                continue
            ir_clips, bad = finite_windows(-(ir-np.nanmean(ir)), PTT_FS, "v3")
            red_clips = dict(finite_windows(-(red-np.nanmean(red)), PTT_FS, "v3")[0])
            stats.update({"ptt:"+k: v for k, v in bad.items()})
            finite = np.isfinite(ir).all() and np.isfinite(red).all()
            ir_view = view(-(ir-ir.mean()), PTT_FS) if finite else None
            red_view = view(-(red-red.mean()), PTT_FS) if finite else None
            subject = f"ptt:s{s}"
            for start, wave in ir_clips:
                ratio, pi = (window_ratio(ir_view, red_view, ir, red, PTT_FS, start) if finite and start in red_clips
                             else (np.nan, np.nan))
                known = bool(np.isfinite(ratio) and R_RANGE[0] <= ratio <= R_RANGE[1])
                out["signal"].append(wave.astype(np.float32))
                out["subject"].append(subject)
                out["domain"].append("ptt_"+activity)
                out["split"].append(assignment[subject])
                out["record"].append("ptt:"+name)
                out["start"].append(start)
                out["activity_label"].append(code)
                out["rhythm_label"].append(-1)
                out["reference_hr_bpm"].append(reference_rate(peaks, PTT_FS, start))
                out["red"].append(red_relative(red_clips[start], ratio) if known else np.zeros(LENGTH, np.float32))
                out["red_known"].append(known)
                out["ratio_r"].append(ratio if known else np.nan)
                out["pi_ir"].append(pi if known else np.nan)
                stats["ptt_windows"] += 1
                stats["ptt_red" if known else "ptt_no_red"] += 1
    return out, assignment


def build(v3g_root, archive, ptt_dir, output):
    pack, manifest = load_input(v3g_root, BASE_PROTOCOL)
    keep = ~np.char.startswith(pack["domain"].astype(str), "ptt_")
    base_rows = np.flatnonzero(keep)
    pack = {k: v[keep] for k, v in pack.items()}
    n = len(pack["signal"])
    pack.update(red=np.zeros((n, LENGTH), np.float32), red_known=np.zeros(n, bool),
                ratio_r=np.full(n, np.nan, np.float32), pi_ir=np.full(n, np.nan, np.float32))
    stats = Counter(removed_v3_ptt_windows=int((~keep).sum()))
    finger_red(pack, base_rows, v3g_root, archive, stats)
    new, assignment = ptt_rows(ptt_dir, stats)
    new = {k: np.asarray(v) for k, v in new.items()}
    quality = edge_excess(new["signal"]) <= EDGE_EXCESS_MAX
    stats["ptt_edge_rejected"] = int((~quality).sum())
    new = {k: v[quality] for k, v in new.items()}
    out = {}
    for key in pack:
        a, b = pack[key], new[key]
        out[key] = (np.concatenate((a.astype(str), b.astype(str))) if a.dtype.kind in "US" or b.dtype.kind in "US"
                    else np.concatenate((a, b.astype(a.dtype))))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output/"windows.npz", **out)
    content = hashlib.sha256()
    for key in ("signal", "red", "red_known", "ratio_r", "subject", "domain", "split"):
        content.update(np.ascontiguousarray(out[key]).tobytes())
    domains = sorted(set(out["domain"]))
    counts = {d: {s: dict(windows=int(((out["domain"] == d) & (out["split"] == s)).sum()),
                          subjects=len(set(out["subject"][(out["domain"] == d) & (out["split"] == s)])),
                          red=int(((out["domain"] == d) & (out["split"] == s) & out["red_known"]).sum()))
                  for s in ("train", "validation", "test", "external")} for d in domains}
    ratios = {}
    for d in sorted(set(out["domain"][out["red_known"]])):
        r = out["ratio_r"][(out["domain"] == d) & out["red_known"]]
        ratios[d] = dict(median=float(np.median(r)), p5=float(np.percentile(r, 5)), p95=float(np.percentile(r, 95)))
    save_json(output/"manifest.json", dict(
        protocol=PROTOCOL, base_protocol=BASE_PROTOCOL, base_windows_sha256=manifest["windows_sha256"],
        base_content_sha256=manifest.get("content_sha256"), windows_sha256=digest(output/"windows.npz"),
        content_sha256=content.hexdigest(), view="v3", fs_hz=FS, seconds=LENGTH//FS,
        red_representation="red = R*(red_view - mean); ptp(red) = R; infrared = v3 view with ptp 1",
        ratio_definition="R = (ptp(AC_red)/DC_red)/(ptp(AC_ir)/DC_ir) on the v3 view of the raw record; DC = raw window mean",
        ptt=dict(source=f"https://physionet.org/files/pulse-transit-time-ppg/{PTT_VERSION}/", channels=PTT_CHANNELS,
                 channel_evidence="median R(pleth_1/pleth_2) 0.42 on 19 sitting records, all < 0.6; header SpO2 96-99%",
                 split_seed=PTT_SPLIT_SEED, assignment=assignment, activity_codes=PTT_ACTIVITIES),
        gxu_archive_sha256=digest(archive), counts=counts, ratio_r=ratios, stats=dict(stats),
        limitations=["R is a device optical ratio from healthy subjects (SpO2 about 96-99%); it is not an SpO2 label",
                     "red exists for FINGER and PTT only; other datasets train the infrared channel alone",
                     "PTT red/infrared mapping inferred from the ratio of ratios, not confirmed by the authors"]))
    return out


def load_dual(root):
    """Load and verify the single ppg_physioflow2_v4 pack below root."""
    paths = [p for p in Path(root).rglob("windows.npz") if (p.parent/"manifest.json").exists()
             and json.loads((p.parent/"manifest.json").read_text()).get("protocol") == PROTOCOL]
    if len(paths) != 1:
        raise ValueError(f"Expected one {PROTOCOL} pack, found {len(paths)}")
    manifest = json.loads((paths[0].parent/"manifest.json").read_text())
    if digest(paths[0]) != manifest["windows_sha256"]:
        raise ValueError(f"{PROTOCOL} checksum mismatch")
    with np.load(paths[0], allow_pickle=False) as source:
        pack = {k: source[k] for k in source.files}
    if not (pack["signal"].min() >= 0 and pack["signal"].max() <= 1 and np.isfinite(pack["red"]).all()):
        raise ValueError(f"Invalid {PROTOCOL} signals")
    return pack, manifest


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--v3g", required=True, help="Directory holding the verified v3g pack and gxu_red_windows.npz")
    parser.add_argument("--gxu-archive", required=True)
    parser.add_argument("--ptt", required=True, help="Directory holding the PTT 1.0.0 WFDB records")
    parser.add_argument("--output", required=True)
    a = parser.parse_args(argv)
    out = build(a.v3g, a.gxu_archive, a.ptt, a.output)
    print(json.dumps(json.loads((Path(a.output)/"manifest.json").read_text())["stats"], indent=1))
    print(len(out["signal"]), "windows")


if __name__ == "__main__":
    main()
