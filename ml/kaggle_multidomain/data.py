"""Pinned public PPG sources, conservative patient splits, and shared 40 Hz view."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np
from scipy.io import loadmat

from ml.kaggle_lsm.train_lsm import DATA_URL, MAT_HASH, FS, LENGTH, normalize, save_json
from ml.kaggle_multidomain.view import describe as describe_view, resample_filter

ZENODO = "https://zenodo.org/records/15906524/files/"
PTT = "https://physionet.org/files/pulse-transit-time-ppg/1.0.0/"
SOURCES = {
    "bidmc": (DATA_URL, "sha256", MAT_HASH),
    "perform_large_train": (ZENODO+"mimic_perform_large_train_a_data.mat", "md5", "98a930bc5b764cad520a38f8ef2efba6"),
    "perform_large_test": (ZENODO+"mimic_perform_large_test_a_data.mat", "md5", "f75a87885ae1dffc0a33d3ce6446abeb"),
    "perform_af": (ZENODO+"mimic_perform_af_data.mat", "md5", "38adc07e4420226a0edfe9769a23284f"),
    "perform_non_af": (ZENODO+"mimic_perform_non_af_data.mat", "md5", "d1c4f93442a3b4c9cb95718ca0a57013"),
}


def digest(path, algorithm="sha256"):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, algorithm).hexdigest()


def download(url, path, algorithm, expected):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and digest(path, algorithm) == expected:
        return path
    part = path.with_suffix(path.suffix+".partial")
    subprocess.run(["curl", "-fLsS", "--retry", "4", "--retry-all-errors", "--connect-timeout", "30",
                    "--max-time", "1800", "--continue-at", "-", url, "-o", str(part)], check=True)
    if digest(part, algorithm) != expected:
        raise ValueError(f"Checksum mismatch: {path.name}")
    part.replace(path)
    return path


def patient_id(fix, bidmc=False, aliases=None):
    fix = fix.get("mimic_details", fix)
    key = "id" if bidmc else "subj_id"
    raw = str(fix[key])
    if not re.fullmatch(r"[sp]?\d+", raw):
        raise ValueError(f"Unsupported patient ID format: {raw}")
    if not bidmc and raw.isdigit() and len(raw) == 7:
        # Unmatched waveform IDs cannot be asserted to be unique clinical patients.
        return (aliases or {}).get(raw, "mimic-record:"+raw)
    # Conservatively treat matching numeric patient IDs across MIMIC releases as one person.
    return "mimic:"+str(int(raw.lstrip("sp")))


def record_aliases(records):
    aliases = {}
    for rec in records:
        subject = patient_id(rec["fix"])
        for name in np.atleast_1d(rec["fix"]["files"]):
            base = str(name).split("_")[0]
            if not re.fullmatch(r"\d{7}", base):
                raise ValueError(f"Unrecognized waveform record: {name}")
            if base in aliases and aliases[base] != subject:
                raise ValueError("Conflicting waveform-to-patient mapping")
            aliases[base] = subject
    return aliases


def split_patients(patients, seed=20261009):
    patients = np.array(sorted(set(patients)))
    if len(patients) < 6:
        raise ValueError("At least six patients required for a three-way split")
    patients = np.random.default_rng(seed).permutation(patients)
    n = max(2, round(.15*len(patients)))
    return {str(p): split for split, group in zip(("test", "validation", "train"),
            (patients[:n], patients[n:2*n], patients[2*n:])) for p in group}


def windows(raw, fs, view="v1"):
    raw = np.asarray(raw, dtype=np.float64).reshape(-1)
    if not np.isfinite(fs) or fs < 2*5 or fs > 10000:
        raise ValueError("Invalid sampling frequency")
    if not np.isfinite(raw).all() or len(raw)/fs < 30 or np.ptp(raw) < 1e-8:
        return [], Counter(invalid_record=1)
    ratio = Fraction(FS/float(fs)).limit_denominator(10000)
    wave = resample_filter(raw, ratio.numerator, ratio.denominator, view)
    result, rejected = [], Counter()
    for start in range(0, len(wave)-LENGTH+1, LENGTH):
        raw_segment = raw[round(start*fs/FS):round((start+LENGTH)*fs/FS)]
        if (np.ptp(raw_segment) < 1e-8 or
                max(np.mean(raw_segment == raw_segment.min()), np.mean(raw_segment == raw_segment.max())) > .05):
            rejected["flat_or_clipped"] += 1
            continue
        try:
            result.append((start, normalize(wave[start:start+LENGTH])))
        except ValueError:
            rejected["invalid_window"] += 1
    return result, rejected


def validate_pack(pack):
    x = pack["signal"]
    if x.ndim != 2 or x.shape[1] != LENGTH or not np.isfinite(x).all() or x.min() < 0 or x.max() > 1:
        raise ValueError("Invalid signal pack")
    if np.any(np.ptp(x, axis=1) < 1e-6):
        raise ValueError("Flat signal in pack")
    for key in ("subject", "domain", "split", "record", "start"):
        if len(pack[key]) != len(x):
            raise ValueError(f"Metadata length mismatch: {key}")
    allowed = {"train", "validation", "test", "external"}
    if not set(pack["split"]).issubset(allowed):
        raise ValueError("Unknown split")
    groups = {s: set(pack["subject"][pack["split"] == s]) for s in allowed}
    for a in allowed:
        for b in allowed-{a}:
            if groups[a] & groups[b]:
                raise ValueError("Patient leakage between splits")
    hashes = [hashlib.sha256(np.round(row, 5).tobytes()).hexdigest() for row in x]
    if len(set(hashes)) != len(hashes):
        raise ValueError("Duplicate normalized waveforms")


def balanced_pool(pack, split, domains=None):
    mask = pack["split"] == split
    if domains is not None:
        mask &= np.isin(pack["domain"], domains)
    present = np.unique(pack["domain"][mask])
    if not len(present):
        raise ValueError(f"Empty selection: {split}, {domains}")
    ids = np.flatnonzero(mask)
    weights = np.zeros(len(pack["signal"]), dtype=np.float64)
    for domain in present:
        dm = mask & (pack["domain"] == domain)
        subjects = np.unique(pack["subject"][dm])
        for subject in subjects:
            pm = dm & (pack["subject"] == subject)
            weights[pm] = 1/(len(present)*len(subjects)*pm.sum())
    return ids, weights[ids]/weights[ids].sum()


def balanced_indices(pack, split, rng, n, domains=None):
    ids, weights = balanced_pool(pack, split, domains)
    return rng.choice(ids, n, p=weights)


def prepare(cache, output, include_ptt=True, view="v1"):
    cache, output = Path(cache), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    records, licenses, sources = {}, {}, {}
    for domain, (url, algorithm, expected) in SOURCES.items():
        path = download(url, cache/url.rsplit("/", 1)[1], algorithm, expected)
        mat = loadmat(path, simplify_cells=True)
        rows = mat["data"]
        records[domain] = [rows] if isinstance(rows, dict) else list(rows)
        licenses[domain] = str(mat.get("license", "BIDMC: ODC-By-1.0; Pimentel et al."))
        sources[domain] = dict(url=url, sha256=digest(path), records=len(records[domain]))
        print("loaded", domain, len(records[domain]), flush=True)
    aliases = record_aliases(records["perform_af"]+records["perform_non_af"])
    frozen = json.loads(Path(__file__).with_name("bidmc_split.json").read_text())
    assignment = {patient_id({"id": p}, True): split for split, patients in frozen.items() for p in patients}
    bidmc_patients = set(assignment)
    official_test = {patient_id(r["fix"], aliases=aliases) for r in records["perform_large_test"]}-bidmc_patients
    assignment.update({p: "test" for p in official_test})
    for domain in ("perform_af", "perform_non_af"):
        ids = {patient_id(r["fix"]) for r in records[domain]}-set(assignment)
        assignment.update(split_patients(ids))
    large_ids = {patient_id(r["fix"], aliases=aliases) for r in records["perform_large_train"]}-set(assignment)
    assignment.update(split_patients(large_ids))
    rows, seen, rejected = [], set(), Counter()

    def append(raw, fs, subject, domain, split, record):
        accepted, bad = windows(raw, fs, view)
        rejected.update({domain+":"+k: v for k, v in bad.items()})
        for start, wave in accepted:
            fingerprint = hashlib.sha256(np.round(wave, 5).tobytes()).hexdigest()
            if fingerprint in seen:
                rejected[domain+":duplicate"] += 1
                continue
            seen.add(fingerprint)
            rows.append((wave, subject, domain, split, record, start))

    for source in ("bidmc", "perform_af", "perform_non_af", "perform_large_train", "perform_large_test"):
        for i, rec in enumerate(records[source]):
            p = patient_id(rec["fix"], source == "bidmc", aliases)
            if source != "bidmc" and p in bidmc_patients:
                rejected[source+":possible_bidmc_patient_overlap"] += 1
                continue
            domain = "perform_large" if source.startswith("perform_large") else source
            append(rec["ppg"]["v"], float(rec["ppg"]["fs"]), p, domain, assignment[p], f"{source}:{i}")

    if include_ptt:
        import wfdb
        import urllib.request
        hashes_text = urllib.request.urlopen(PTT+"SHA256SUMS.txt", timeout=60).read().decode()
        hashes = {line.split()[1]: line.split()[0] for line in hashes_text.splitlines()}
        # All 22 participants, all three activities, pleth_1 only; no wavelength assertion.
        names = [f"s{i}_{activity}" for i in range(1, 23) for activity in ("sit", "walk", "run")]
        def get_record(name):
            for suffix in (".hea", ".dat"):
                download(PTT+name+suffix, cache/"ptt"/(name+suffix), "sha256", hashes[name+suffix])
            record = wfdb.rdrecord(str(cache/"ptt"/name), channel_names=["pleth_1"])
            return name, record.p_signal[:, 0], record.fs
        with ThreadPoolExecutor(max_workers=4) as pool:
            for name, raw, fs in pool.map(get_record, names):
                subject, activity = name.split("_")
                append(raw, fs, "ptt:"+subject, "ptt_"+activity, "external", name)
        licenses["ptt"] = urllib.request.urlopen(PTT+"LICENSE.txt", timeout=60).read().decode()
        sources["ptt"] = dict(url=PTT, channel="pleth_1", records=len(names),
                              file_sha256={name+ext: hashes[name+ext] for name in names for ext in (".hea", ".dat")})
    keys = ("signal", "subject", "domain", "split", "record", "start")
    pack = {k: np.asarray(v) for k, v in zip(keys, zip(*rows))}
    validate_pack(pack)
    counts = {d: {s: dict(windows=int(((pack["domain"] == d) & (pack["split"] == s)).sum()),
                          patients=len(set(pack["subject"][(pack["domain"] == d) & (pack["split"] == s)])))
                   for s in ("train", "validation", "test", "external")} for d in sorted(set(pack["domain"]))}
    manifest = dict(protocol="ppg_multidomain_v1", fs_hz=FS, seconds=30, sources=sources,
                    preprocessing=describe_view(view), view=view,
                    counts=counts, rejected=dict(rejected), patients=assignment, licenses=licenses,
                    waveform_patient_aliases=aliases,
                    unresolved_waveform_groups=sum(p.startswith("mimic-record:") for p in assignment),
                    limitations=["MIMIC release identity crosswalk unavailable: conservatively exclude numeric BIDMC matches; exact waveform dedup is not proof against all overlap",
                                 "PERform Large unmatched 7-digit IDs are waveform groups, not verified unique clinical patients; known AF record aliases are joined before splitting",
                                 "BIDMC test previously inspected; exploratory. PTT is independent and never used for selection",
                                 "Filtering suppresses motion/high-frequency morphology; benchmark concerns this common filtered view",
                                 "No absolute AC/DC, SpO2 calibration, or paired IR/RED learned; unconditional generators",
                                 "Basic finite/flat/clipping screening only; no clinical signal-quality certification"])
    np.savez_compressed(output/"windows.npz", **pack)
    manifest["windows_sha256"] = digest(output/"windows.npz")
    save_json(output/"manifest.json", manifest)
    print(json.dumps(counts, indent=2), flush=True)
    return pack, manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--no-ptt", action="store_true", help="Preparation smoke check only; not a cross-domain benchmark")
    args = parser.parse_args()
    prepare(args.cache, args.output, not args.no_ptt)
