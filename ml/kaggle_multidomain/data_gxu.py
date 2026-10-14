"""Add the GXU finger ECG + dual-wavelength PPG set as a new subject-split domain.

Mendeley Data 10.17632/pz2zzr8vhm.1 (CC BY 4.0): 148 subjects x 3 states, 250 Hz raw ADC
columns ECG_I, PPG_RED (660 nm), PPG_IR (940 nm). Raw photodiode PPG falls when blood volume
rises, so the shared view negates it; every record is checked against its own ECG R-peaks.
The PhysioMix v1 pack, splits and holdouts are kept byte-for-byte; GXU test subjects are new.
"""
from collections import Counter
import io
import json
from pathlib import Path
import re
import zipfile

import numpy as np
from scipy.signal import butter, find_peaks, sosfiltfilt

from ml.kaggle_lsm.train_lsm import FS, LENGTH, save_json
from ml.kaggle_multidomain.data import digest, download, split_patients, validate_pack
from ml.kaggle_multidomain.data_more import digest_row, finite_windows, load_input as load_v1

PROTOCOL = "ppg_physiomix_v2"
V1_SHA256 = "af3c3a0ff5bd8dc41a56172ad104349db469c87bd8edae3ade7eda88e05405e0"
GXU_URL = ("https://data.mendeley.com/public-files/datasets/pz2zzr8vhm/files/"
           "01fe8a7c-175b-4a54-b5f0-4633ba63bb3d/file_downloaded")
GXU_SHA256 = "6a98ba2e702a6ab2eb98944f856abff644491442c4c5bb006df09a54fc1e4dfd"
GXU_FS = 250
STATES = {"1": "gxu_rest", "2": "gxu_post_exercise_a", "3": "gxu_post_exercise_b"}
# Wrist activities keep codes 0-3; GXU states extend the same optional label.
STATE_CODES = {"1": 4, "2": 5, "3": 6}
NAME = re.compile(r"Raw_data/(\d{3})_([123])\.csv$")
# v1 windows were resampled with zero padding while carrying raw DC; the record-start transient
# then dominates per-window min-max (94% of proxy-rate<40 windows start at sample 0).
EDGE_EXCESS_MAX = .5
EDGE = 2*FS


def edge_excess(x):
    """Excursion of the first/last 2 s beyond the middle 1-99% range, in middle-range units."""
    x = np.atleast_2d(x)
    middle = x[:, 3*FS:-3*FS]
    lo, hi = np.quantile(middle, .01, axis=1), np.quantile(middle, .99, axis=1)
    edge = np.concatenate((x[:, :EDGE], x[:, -EDGE:]), 1)
    return np.maximum(edge.max(1)-hi, lo-edge.min(1))/np.maximum(hi-lo, 1e-6)


def read_record(raw_bytes):
    """Parse one raw CSV; malformed rows become NaN and are excluded as gaps, never filled."""
    text = raw_bytes.decode("utf-8-sig", errors="strict")
    header, _, body = text.partition("\n")
    columns = [c.strip() for c in header.split(",")]
    if columns[:3] != ["ECG_I", "PPG_RED", "PPG_IR"]:
        raise ValueError(f"Unexpected GXU header: {header[:80]!r}")
    rate = re.search(r"'Hz'\s*:\s*(\d+)", header)
    if rate is None or int(rate.group(1)) != GXU_FS:
        raise ValueError("GXU sampling rate must be declared as 250 Hz")
    values = np.genfromtxt(io.StringIO(body), delimiter=",", usecols=(0, 1, 2),
                           invalid_raise=False, dtype=np.float64)
    values = np.atleast_2d(values)
    if values.shape[1] != 3 or len(values) < 30*GXU_FS:
        raise ValueError("GXU record shorter than one 30 s window")
    return values[:, 0], values[:, 1], values[:, 2]


def r_peaks(ecg, fs=GXU_FS):
    finite = np.isfinite(ecg)
    if finite.mean() < .99:
        return np.array([], dtype=int)
    x = sosfiltfilt(butter(3, [5, 30], "bandpass", fs=fs, output="sos"), np.where(finite, ecg, np.nanmedian(ecg)))
    x = x if abs(np.quantile(x, .999)) >= abs(np.quantile(x, .001)) else -x
    peaks, _ = find_peaks(x, distance=round(.33*fs), height=.5*np.quantile(x, .98))
    return peaks


def polarity_lag(ppg, peaks, fs=GXU_FS):
    """Delay of the R-locked mean maximum of the NEGATED 0.5-8 Hz PPG; None if unverifiable."""
    if len(peaks) < 20 or not np.isfinite(ppg).all():
        return None
    x = -sosfiltfilt(butter(3, [.5, 8], "bandpass", fs=fs, output="sos"), ppg)
    span = round(.8*fs)
    beats = np.array([x[p:p+span] for p in peaks[1:-1] if p+span <= len(x)])
    return float(np.argmax(beats.mean(0))/fs) if len(beats) >= 20 else None


def reference_rate(peaks, fs, start):
    """ECG median-IBI rate inside one 40 Hz window; ancillary context, not conditioning truth."""
    times = np.asarray(peaks)/fs
    chosen = times[(times >= start/FS) & (times < start/FS+LENGTH/FS)]
    return float(60/np.median(np.diff(chosen))) if len(chosen) >= 3 else float("nan")


def gxu_records(archive):
    """Yield (subject, state, name, bytes) from the verified archive in a stable order."""
    with zipfile.ZipFile(archive) as zf:
        names = sorted(n for n in zf.namelist() if NAME.search(n))
        if len(names) != 444:
            raise ValueError(f"Expected 444 GXU raw records, found {len(names)}")
        for name in names:
            subject, state = NAME.search(name).groups()
            yield subject, state, name, zf.read(name)


def prepare(input_root, cache, output, archive=None, view="v1", base_sha=V1_SHA256, protocol=PROTOCOL):
    pack, v1 = load_v1(input_root)
    if v1["windows_sha256"] != base_sha or v1.get("view", "v1") != view:
        raise ValueError("Use the verified PhysioMix base pack for this view")
    cache, output = Path(cache), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    archive = Path(archive) if archive else download(GXU_URL, cache/"gxu.zip", "sha256", GXU_SHA256)
    if digest(archive) != GXU_SHA256:
        raise ValueError("GXU archive checksum mismatch")
    keys = ("signal", "subject", "domain", "split", "record", "start")
    rows = list(zip(*(pack[k] for k in keys)))
    activity, rhythm = list(pack["activity_label"]), list(pack["rhythm_label"])
    reference = list(pack["reference_hr_bpm"])
    fingerprints = {digest_row(row[0]) for row in rows}
    subjects = sorted({"gxu:"+s for s, *_ in _names(archive)})
    assignment = split_patients(subjects, seed=20261011)
    rejected, lags, red_rows = Counter(), [], []
    for subject, state, name, raw_bytes in gxu_records(archive):
        try:
            ecg, red, ir = read_record(raw_bytes)
        except ValueError as error:
            rejected["gxu:unparseable:"+str(error)[:40]] += 1
            continue
        peaks = r_peaks(ecg)
        lag = polarity_lag(ir, peaks)
        lags.append(lag)
        # Systolic arrival 0.1-0.6 s after R confirms the negated orientation for this record.
        if lag is None or not .1 <= lag <= .6:
            rejected["gxu:polarity_unverified" if lag is None else "gxu:polarity_inconsistent"] += 1
            continue
        # Remove raw ADC DC before resampling so zero padding cannot create an edge step.
        ir_clips, bad = finite_windows(-(ir-np.nanmean(ir)), GXU_FS, view)
        red_clips = dict(finite_windows(-(red-np.nanmean(red)), GXU_FS, view)[0])
        rejected.update({"gxu:"+k: v for k, v in bad.items()})
        sid = "gxu:"+subject
        for start, wave in ir_clips:
            fingerprint = digest_row(wave)
            if fingerprint in fingerprints:
                rejected["gxu:duplicate"] += 1
                continue
            fingerprints.add(fingerprint)
            rows.append((wave, sid, "gxu_finger", assignment[sid], f"gxu:{subject}_{state}", start))
            activity.append(STATE_CODES[state])
            rhythm.append(-1)
            reference.append(reference_rate(peaks, GXU_FS, start))
            red_rows.append((len(rows)-1, red_clips.get(start)))
    extended = {key: np.asarray(value) for key, value in zip(keys, zip(*rows))}
    extended.update(activity_label=np.asarray(activity, dtype=np.int8),
                    rhythm_label=np.asarray(rhythm, dtype=np.int8),
                    reference_hr_bpm=np.asarray(reference, dtype=np.float32))
    # One label-free rule for every domain and split, fixed before any v2 model is trained.
    excess = edge_excess(extended["signal"])
    keep = excess <= EDGE_EXCESS_MAX
    quality_rejected = {f"{d}:{s}": int(((extended["domain"] == d) & (extended["split"] == s) & ~keep).sum())
                        for d in sorted(set(extended["domain"])) for s in ("train", "validation", "test", "external")}
    original_rows = np.flatnonzero(keep)
    extended = {key: value[keep] for key, value in extended.items()}
    remap = {old: new for new, old in enumerate(original_rows)}
    red_rows = [(remap[i], w) for i, w in red_rows if i in remap]
    validate_pack(extended)
    np.savez_compressed(output/"windows.npz", **extended)
    paired = [(i, w) for i, w in red_rows if w is not None]
    np.savez_compressed(output/"gxu_red_windows.npz", row=np.asarray([i for i, _ in paired]),
                        red=np.asarray([w for _, w in paired], dtype=np.float32))
    counts = {domain: {split: dict(windows=int(((extended["domain"] == domain) & (extended["split"] == split)).sum()),
                                  source_groups=len(set(extended["subject"][(extended["domain"] == domain) & (extended["split"] == split)])))
                       for split in ("train", "validation", "test", "external")}
              for domain in sorted(set(extended["domain"]))}
    measurable = [x for x in lags if x is not None]
    verified = [x for x in measurable if .1 <= x <= .6]
    manifest = dict(protocol=protocol, windows_sha256=digest(output/"windows.npz"), view=view,
                    red_windows_sha256=digest(output/"gxu_red_windows.npz"),
                    base_manifest=v1, base_windows_sha256=base_sha, fs_hz=FS, seconds=30,
                    sources=dict(gxu=dict(doi="10.17632/pz2zzr8vhm.1", license="CC BY 4.0",
                                          url=GXU_URL, sha256=GXU_SHA256, raw_fs_hz=GXU_FS,
                                          citation="Li S. et al., A dataset of simultaneous collected ECG and PPG signals, "
                                                   "Mendeley Data v1 (2026); Data 11(7):155",
                                          channel="PPG_IR 940 nm negated; PPG_RED stored separately, not trained")),
                    counts=counts, gxu_subject_assignment=assignment, rejected=dict(rejected),
                    edge_quality_rule=dict(max_edge_excess=EDGE_EXCESS_MAX, edge_seconds=EDGE/FS,
                                           rejected_by_domain_split={k: v for k, v in quality_rejected.items() if v}),
                    gxu_polarity=dict(checked=len(lags), measurable=len(measurable), consistent=len(verified),
                                      median_r_to_peak_s=float(np.median(verified)) if verified else None),
                    label_schema=dict(v1["label_schema"], activity_label={**v1["label_schema"]["activity_label"],
                                      **{str(code): STATES[s] for s, code in STATE_CODES.items()}},
                                      reference_hr_bpm="ECG R-peak median IBI; Wrist, CapnoBase and GXU; NaN otherwise"),
                    limitations=v1["limitations"]+[
                        "GXU: 148 apparently healthy adults, one handheld finger-contact device; not a patient cohort",
                        "GXU states 2/3 follow treadmill exercise per the data descriptor; intensities not verified here",
                        "GXU raw IR is negated by device physics and accepted only when its R-locked maximum lags 0.1-0.6 s",
                        "Windows whose first/last 2 s exceed the middle range by >50% are dropped in every split (v1 record-start transient)",
                        "GXU test subjects are the only fresh holdout; every v1 test/external split is now exploratory",
                        "RED windows are stored for future paired work; models still learn one normalized shape"])
    save_json(output/"manifest.json", manifest)
    print("PREPARED", json.dumps(counts), json.dumps(manifest["gxu_polarity"]), flush=True)
    return extended, manifest


def _names(archive):
    with zipfile.ZipFile(archive) as zf:
        return [NAME.search(n).groups() for n in zf.namelist() if NAME.search(n)]


def load_input(root, protocol=PROTOCOL):
    """Load the single verified pack of this protocol below root. ppg_physiomix_v3d is derived in memory from the
    verified v3g pack (fresh_galaxy.daily_wrist), not stored."""
    if protocol == "ppg_physiomix_v3d":
        from ml.kaggle_multidomain.fresh_galaxy import daily_wrist
        return daily_wrist(*load_input(root, "ppg_physiomix_v3g"))
    paths = [p for p in Path(root).rglob("windows.npz") if (p.parent/"manifest.json").exists()
             and json.loads((p.parent/"manifest.json").read_text()).get("protocol") == protocol]
    if len(paths) != 1:
        raise ValueError(f"Expected one {protocol} pack, found {len(paths)}")
    manifest = json.loads((paths[0].parent/"manifest.json").read_text())
    if digest(paths[0]) != manifest["windows_sha256"]:
        raise ValueError("PhysioMix v2 data checksum mismatch")
    with np.load(paths[0], allow_pickle=False) as source:
        pack = {k: source[k] for k in source.files}
    validate_pack(pack)
    for key in ("rhythm_label", "activity_label", "reference_hr_bpm"):
        if len(pack[key]) != len(pack["signal"]):
            raise ValueError(f"Metadata length mismatch: {key}")
    if np.any((pack["domain"] == "capnobase") & (pack["split"] != "external")):
        raise ValueError("CapnoBase must stay external-only")
    return pack, manifest
