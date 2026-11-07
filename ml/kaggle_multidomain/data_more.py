"""Extend the frozen pack; CapnoBase is reserved entirely for new external evaluation."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import numpy as np

from ml.kaggle_lsm.train_lsm import FS, save_json
from ml.kaggle_multidomain.data import digest, download, split_patients, validate_pack, windows
from ml.kaggle_multidomain.train import load_input as load_base

PROTOCOL = "ppg_physiomix_v1"
BASE_SHA256 = "7c8f8bbb2b60db0605cc40d4d7c56efa92acab3b82bee78ae1faeca7f22aade8"
ACTIVITIES = ("walk", "run", "low_resistance_bike", "high_resistance_bike")


def finite_windows(raw, fs, view="v1"):
    """Never interpolate missing physiological samples or filter across a recording gap."""
    if not np.isfinite(fs) or fs < 10 or fs > 10000:
        raise ValueError("Invalid sampling frequency")
    raw = np.asarray(raw).reshape(-1)
    finite = np.isfinite(raw)
    edges = np.diff(np.r_[False, finite, False].astype(np.int8))
    result, rejected = [], Counter(nonfinite_samples_excluded=int((~finite).sum()))
    for first, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        if (end-first)/fs < 30:
            rejected["short_finite_spans"] += 1
            continue
        clips, bad = windows(raw[first:end], fs, view)
        rejected.update(bad)
        result.extend((round(first*FS/fs)+start, wave) for start, wave in clips)
    return result, rejected


def load_input(root):
    paths = [p for p in Path(root).rglob("windows.npz") if (p.parent/"manifest.json").exists()
             and json.loads((p.parent/"manifest.json").read_text()).get("protocol") == PROTOCOL]
    if len(paths) != 1:
        raise ValueError(f"Expected one PhysioMix pack, found {len(paths)}")
    manifest = json.loads((paths[0].parent/"manifest.json").read_text())
    if digest(paths[0]) != manifest["windows_sha256"]:
        raise ValueError("PhysioMix data checksum mismatch")
    with np.load(paths[0], allow_pickle=False) as source:
        pack = {k: source[k] for k in source.files}
    validate_pack(pack)
    for key in ("rhythm_label", "activity_label", "reference_hr_bpm"):
        if len(pack[key]) != len(pack["signal"]):
            raise ValueError(f"Metadata length mismatch: {key}")
    if np.any((pack["domain"] == "capnobase") & (pack["split"] != "external")):
        raise ValueError("CapnoBase must stay external-only")
    return pack, manifest


def reference_rate(peaks, fs, start):
    peaks = np.asarray(peaks).reshape(-1)/fs
    selected = peaks[(peaks >= start/FS) & (peaks < start/FS+30)]
    return float(60/np.median(np.diff(selected))) if len(selected) >= 2 else float("nan")


def prepare(input_root, cache, output, view="v1", base_sha=BASE_SHA256):
    import h5py
    import wfdb

    pack, base = load_base(input_root)
    if base["windows_sha256"] != base_sha or base.get("view", "v1") != view:
        raise ValueError("Use the verified frozen base dataset for this view")
    cache, output = Path(cache), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    keys = ("signal", "subject", "domain", "split", "record", "start")
    rows = list(zip(*(pack[k] for k in keys)))
    activity = [-1]*len(rows)
    reference_hr = [float("nan")]*len(rows)
    fingerprints = {digest_row(row[0]) for row in rows}
    rejected = Counter()
    here = Path(__file__).parent
    wrist = json.loads((here/"wrist_sources.json").read_text())
    capno = json.loads((here/"capnobase_sources.json").read_text())
    subjects = ["wrist:"+name.split("_")[0] for name in wrist["records"]]
    assignment = split_patients(subjects, seed=20261010)
    checksums = {}

    def append(raw, fs, subject, domain, split, record, peaks, code=-1):
        clips, bad = finite_windows(raw, fs, view)
        rejected.update({domain+":"+key: count for key, count in bad.items()})
        for start, wave in clips:
            fingerprint = digest_row(wave)
            if fingerprint in fingerprints:
                rejected[domain+":duplicate"] += 1
                continue
            fingerprints.add(fingerprint)
            rows.append((wave, subject, domain, split, record, start))
            activity.append(code)
            reference_hr.append(reference_rate(peaks, fs, start))

    def wrist_record(name):
        for ext in (".hea", ".dat", ".atr"):
            path = download(wrist["mirror"]+name+ext, cache/"wrist"/(name+ext),
                            "sha256", wrist["sha256"][name+ext])
        rec = wfdb.rdrecord(str(path.with_suffix("")), channel_names=["wrist_ppg"])
        peaks = wfdb.rdann(str(path.with_suffix("")), "atr").sample
        return name, rec.p_signal[:, 0], rec.fs, peaks

    with ThreadPoolExecutor(max_workers=4) as pool:
        for name, raw, fs, peaks in pool.map(wrist_record, wrist["records"]):
            subject = "wrist:"+name.split("_")[0]
            append(raw, fs, subject, "wrist", assignment[subject], name, peaks,
                   ACTIVITIES.index(name.split("_", 1)[1]))
            checksums.update({"wrist/"+name+ext: wrist["sha256"][name+ext] for ext in (".hea", ".dat", ".atr")})
    print("WRIST prepared", len(rows)-len(pack["signal"]), flush=True)

    def capno_record(item):
        path = download("https://borealisdata.ca/api/access/datafile/"+str(item["id"]),
                        cache/"capnobase"/item["name"], "md5", item["md5"])
        with h5py.File(path) as mat:
            raw = mat["signal/pleth/y"][()].reshape(-1)
            fs = float(mat["param/samplingrate/pleth"][()].item())
            ecg_fs = float(mat["param/samplingrate/ecg"][()].item())
            if ecg_fs != fs:
                raise ValueError("CapnoBase ECG/PPG time base mismatch")
            peaks = mat["labels/ecg/peak/x"][()].reshape(-1)-1  # MATLAB sample indices.
        return item["name"], raw, fs, peaks, digest(path)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for name, raw, fs, peaks, checksum in pool.map(capno_record, capno["files"]):
            append(raw, fs, "capnobase-case:"+name.split("_")[0], "capnobase", "external", name, peaks)
            checksums["capnobase/"+name] = checksum
    extended = {key: np.asarray(value) for key, value in zip(keys, zip(*rows))}
    extended.update(activity_label=np.asarray(activity, dtype=np.int8),
                    rhythm_label=np.where(extended["domain"] == "perform_af", 1,
                                          np.where(extended["domain"] == "perform_non_af", 0, -1)).astype(np.int8),
                    reference_hr_bpm=np.asarray(reference_hr, dtype=np.float32))
    validate_pack(extended)
    counts = {domain: {split: dict(windows=int(((extended["domain"] == domain) & (extended["split"] == split)).sum()),
                                  source_groups=len(set(extended["subject"][(extended["domain"] == domain) & (extended["split"] == split)])))
                       for split in ("train", "validation", "test", "external")}
              for domain in sorted(set(extended["domain"]))}
    np.savez_compressed(output/"windows.npz", **extended)
    manifest = dict(protocol=PROTOCOL, windows_sha256=digest(output/"windows.npz"), view=view,
                    base_manifest=base, base_windows_sha256=base_sha, fs_hz=FS, seconds=30,
                    sources=dict(wrist=wrist, capnobase=capno), source_sha256=checksums,
                    counts=counts, wrist_subject_assignment=assignment, rejected=dict(rejected),
                    label_schema=dict(domain="9 source/activity domains; 5 training domains",
                                      rhythm_label="-1 unknown, 0 non-AF cohort, 1 AF cohort; not universal beat labels",
                                      activity_label=dict(enumerate(ACTIVITIES)),
                                      reference_hr_bpm="ECG R-peak median IBI; only Wrist and CapnoBase; NaN otherwise"),
                    limitations=base["limitations"]+[
                        "CapnoBase kept external-only following author recommendation; cases are grouping units",
                        "Wrist has only 8 participants; 4 train, 2 validation, 2 test; limited population coverage",
                        "ECG rate is stored for context, not a PPG signal-quality certificate or HR conditioning ground truth",
                        "Wrist NaN padding/missing samples excluded as finite spans; no interpolation across gaps",
                        "Wrist view uses nominal WFDB 256Hz indexing; auxiliary second-of-minute timestamps wrap and jitter; no absolute clock calibration claim",
                        "Old test/PTT previously viewed; secondary exploratory results only",
                        "Fresh Wrist test and entire CapnoBase must remain unseen until all validation choices are frozen"])
    save_json(output/"manifest.json", manifest)
    print("PREPARED", json.dumps(counts), flush=True)
    return extended, manifest


def digest_row(wave):
    import hashlib
    return hashlib.sha256(np.round(wave, 5).tobytes()).hexdigest()
