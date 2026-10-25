"""PhysioFlow-R pack (P1): the v3 pack's non-external windows in the resample-only domain, with 5 s of context.

Why: every generator so far was trained on v3 windows (0.5-8 Hz Butterworth, sosfiltfilt) and has to reach the view's
stop band (12-20 Hz at ~1e-9 of the window power) by itself; PhysioFlow leaves white 12-20 Hz error 1.5e3-2.5e4 times
the real level and the strict judge separates it there alone. Here the target is the record before the view's
band-pass (record mean removed, resample_poly padtype=line, view.resample_only), so a model can end with the view's
own band-pass applied once, as the real windows had it.

Rows follow the v3 pack's (record, start) exactly: each record is rebuilt from the raw cache with the v3 builders'
own steps (data.windows for the .mat sources, data_more.finite_windows spans for wrist and GXU, GXU negated about its
nanmean) and every rebuilt v3 window must equal the pack's to 1e-6 after min-max, else the build stops. The 40 s
context is wave[start-200 : start+1400] clipped to the record (PERform Large records are 32 s: no left context,
80 samples right); missing context is reflection-padded and its real extent stored in `context` (left, right).
Amplitude is the resampled raw unit (not normalised). External domains (CapnoBase, PTT) are not included.
"""
import argparse
from collections import Counter
from fractions import Fraction
import json
from pathlib import Path

import numpy as np

from ml.kaggle_lsm.train_lsm import FS, LENGTH, normalize, save_json
from ml.kaggle_multidomain.data import digest
from ml.kaggle_multidomain.view import resample_only, view_filter

PROTOCOL = "ppg_physioflow_r1"
BASE_PROTOCOL = "ppg_physiomix_v3"
CONTEXT = 5*FS
R_LENGTH = LENGTH+2*CONTEXT
MATCH_TOL = 1e-6
MAT_FILES = dict(bidmc="bidmc_data.mat", perform_af="mimic_perform_af_data.mat",
                 perform_non_af="mimic_perform_non_af_data.mat",
                 perform_large_train="mimic_perform_large_train_a_data.mat",
                 perform_large_test="mimic_perform_large_test_a_data.mat")


def spans(raw, fs, finite_only):
    """[(offset at FS, resampled-only wave, v3 wave)] for the stretches the v3 builders windowed."""
    raw = np.asarray(raw, np.float64).reshape(-1)
    ratio = Fraction(FS/float(fs)).limit_denominator(10000)
    if not finite_only:
        pieces = [(0, raw)] if np.isfinite(raw).all() else []
    else:
        finite = np.isfinite(raw)
        edges = np.diff(np.r_[False, finite, False].astype(np.int8))
        pieces = [(round(a*FS/fs), raw[a:b]) for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))
                  if (b-a)/fs >= 30]
    out = []
    for offset, piece in pieces:
        wave = resample_only(piece, ratio.numerator, ratio.denominator)
        out.append((offset, wave, view_filter(wave)))
    return out


def mat_records(cache, wanted):
    from scipy.io import loadmat
    for source, name in MAT_FILES.items():
        indices = sorted(int(r.split(":")[1]) for r in wanted if r.startswith(source+":"))
        if not indices:
            continue
        rows = loadmat(Path(cache)/name, simplify_cells=True)["data"]
        rows = [rows] if isinstance(rows, dict) else list(rows)
        for i in indices:
            yield f"{source}:{i}", spans(rows[i]["ppg"]["v"], float(rows[i]["ppg"]["fs"]), False)


def wrist_records(cache, wanted):
    import wfdb
    for name in sorted(wanted):
        rec = wfdb.rdrecord(str(Path(cache)/"wrist"/name), channel_names=["wrist_ppg"])
        yield name, spans(rec.p_signal[:, 0], rec.fs, True)


def gxu_spans(archive, wanted):
    from ml.kaggle_multidomain.data_gxu import GXU_FS, gxu_records, read_record
    for subject, state, _, raw_bytes in gxu_records(archive):
        record = f"gxu:{subject}_{state}"
        if record in wanted:
            ir = read_record(raw_bytes)[2]
            yield record, spans(-(ir-np.nanmean(ir)), GXU_FS, True)


def cut(wave, start):
    """(context window of R_LENGTH, (left, right) real context) around wave[start:start+LENGTH]."""
    left, right = min(CONTEXT, start), min(CONTEXT, len(wave)-start-LENGTH)
    piece = wave[start-left:start+LENGTH+right]
    return np.pad(piece, (CONTEXT-left, CONTEXT-right), mode="reflect"), (left, right)


def build(pack, cache, archive):
    rows = np.flatnonzero(pack["split"] != "external")
    records = {}
    for j in rows:
        records.setdefault(str(pack["record"][j]), []).append(int(j))
    mats = {r for r in records if r.split(":")[0] in MAT_FILES}
    wrist = {r for r in records if str(pack["domain"][records[r][0]]) == "wrist"}
    gxu = {r for r in records if r.startswith("gxu:")}
    if mats | wrist | gxu != set(records):
        raise ValueError(f"Records without a raw source: {sorted(set(records)-mats-wrist-gxu)[:5]}")
    signal = np.zeros((len(pack["signal"]), R_LENGTH), np.float32)
    context = np.full((len(pack["signal"]), 2), -1, np.int16)
    worst, stats = 0., Counter()
    for source in (mat_records(cache, mats), wrist_records(cache, wrist), gxu_spans(archive, gxu)):
        for record, pieces in source:
            for j in records[record]:
                start = int(pack["start"][j])
                found = [(o, r, v) for o, r, v in pieces if o <= start and start+LENGTH <= o+len(r)]
                if len(found) != 1:
                    raise ValueError(f"{record}@{start}: {len(found)} spans hold this window")
                offset, wave_r, wave_v3 = found[0]
                local = start-offset
                error = float(np.abs(normalize(wave_v3[local:local+LENGTH])-pack["signal"][j]).max())
                if error > MATCH_TOL:
                    raise ValueError(f"{record}@{start}: rebuilt v3 window differs from the pack by {error:.2e}")
                worst = max(worst, error)
                signal[j], context[j] = cut(wave_r, local)
                stats[str(pack["domain"][j])] += 1
            print("rebuilt", record, len(records[record]), flush=True)
    if (context[rows] < 0).any():
        raise ValueError("Some windows were not rebuilt")
    return (dict(index=rows, record=pack["record"][rows], start=pack["start"][rows], signal=signal[rows],
                 context=context[rows]), dict(max_v3_error=worst, windows=dict(stats)))


def load_r(root, base_manifest):
    """The verified R pack below root that was built from this v3 pack: index (into that pack), record, start,
    signal and context."""
    paths = [p for p in Path(root).rglob("r_windows.npz") if (p.parent/"manifest.json").exists()
             and json.loads((p.parent/"manifest.json").read_text()).get("protocol") == PROTOCOL]
    if len(paths) != 1:
        raise ValueError(f"Expected one {PROTOCOL} pack, found {len(paths)}")
    manifest = json.loads((paths[0].parent/"manifest.json").read_text())
    if digest(paths[0]) != manifest["windows_sha256"]:
        raise ValueError("R pack checksum mismatch")
    if manifest["base_windows_sha256"] != base_manifest["windows_sha256"]:
        raise ValueError("R pack was built from another v3 pack")
    with np.load(paths[0], allow_pickle=False) as source:
        return {k: source[k] for k in source.files}, manifest


def rows_for(r, pack, ids):
    """R pack rows of pack rows ids, matched on (record, start), so any subset of the v3 pack can be used."""
    at = {(str(a), int(b)): i for i, (a, b) in enumerate(zip(r["record"], r["start"]))}
    try:
        return np.array([at[str(pack["record"][j]), int(pack["start"][j])] for j in ids], dtype=np.int64)
    except KeyError as error:
        raise ValueError(f"No R window for {error.args[0]}") from None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, help="the verified v3 pack")
    parser.add_argument("--cache", required=True, help="raw .mat files and wrist/ (data.prepare's cache)")
    parser.add_argument("--gxu", required=True, help="the GXU archive (data_gxu.GXU_SHA256)")
    parser.add_argument("--output", required=True)
    a = parser.parse_args(argv)
    from ml.kaggle_multidomain.data_gxu import GXU_SHA256, load_input
    if digest(a.gxu) != GXU_SHA256:
        raise ValueError("GXU archive checksum mismatch")
    pack, base = load_input(a.input_root, BASE_PROTOCOL)
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=False)
    r, stats = build(pack, a.cache, a.gxu)
    np.savez_compressed(output/"r_windows.npz", **r)
    manifest = dict(protocol=PROTOCOL, base_protocol=BASE_PROTOCOL, base_windows_sha256=base["windows_sha256"],
                    fs_hz=FS, seconds=R_LENGTH/FS, context_samples=CONTEXT,
                    preprocessing="record mean removed; resample_poly padtype=line (the v3 view before its band-pass); "
                                  "40 s context around each v3 window, reflection-padded where the record ends",
                    domains=sorted({str(d) for d in pack["domain"][r["index"]]}), **stats,
                    context_share={k: float(np.mean((r["context"] == (CONTEXT, CONTEXT)).all(1)[
                        pack["domain"][r["index"]] == k])) for k in sorted(stats["windows"])},
                    windows_sha256=digest(output/"r_windows.npz"))
    save_json(output/"manifest.json", manifest)
    print(json.dumps({k: manifest[k] for k in ("max_v3_error", "windows", "context_share")}), flush=True)


if __name__ == "__main__":
    main()
