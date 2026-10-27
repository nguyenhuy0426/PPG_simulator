"""PPG-physiGPT pretraining shards: 30 s PLETH windows at 40 Hz from the MIMIC-III Waveform Database v1.0.

GPT-PPG (Chen et al. 2025) pretrained on >200 million 30 s strips at 40 Hz from UCSF ICU monitoring held under a data
use agreement; that data is not public. The open substitute with the same kind of signal is the MIMIC-III Waveform
Database (PhysioNet, Open Data Commons Open Database License v1.0, 125 Hz, 8/10-bit PLETH, adult ICU records).

Bandwidth decides the scale, so only the bytes of the chosen windows are fetched (HTTP Range on the multiplexed
.dat files, formats 80 and 16): per record, blocks of BLOCK_WINDOWS consecutive 30 s windows from its PLETH segments,
at most `cap` windows, chosen deterministically from the record name. Records are taken in a fixed hashed order of
RECORDS-adults; a shard is the half-open record range [start, stop) of that order, so shards never share a record and
continual pretraining adds shards with new records. About 2% of records (by name hash) are held out for validation.

Each window: no invalid sample (format 80: no run of byte 0 of 1 s or more), not flat, at most 5% of samples at the block's min or max (the pack rule in
ml/kaggle_multidomain/data.py), then the project's v3 view (record mean removed, resample_poly to 40 Hz with linear
edge padding, 0.5-8 Hz zero-phase Butterworth over the whole block plus a margin) and per-window min-max, stored as
uint16. GPT-PPG did not band-pass; the v3 view is the one the strict judge compares, so the pretrained model and the
project's fine-tuning share it. The autocorrelation peak and its rate are stored for later filtering, not used here.

Records the project's MIMIC PERFORM sets were cut from (their 7-digit waveform names) are excluded so pretraining
never sees the people the strict judge validates or tests on. BIDMC comes from MIMIC-II with names that cannot be
mapped to these records; that overlap risk stays, and the copy gate of a judge round is what guards against it.
Engineering data for signal-shape modelling; not clinical labels.
"""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

import numpy as np
from scipy.signal import butter, resample_poly, sosfiltfilt

from ml.kaggle_lsm.train_lsm import FS, LENGTH, save_json

BASE = "https://physionet.org/files/mimic3wdb/1.0/"
LICENSE = "MIMIC-III Waveform Database v1.0, PhysioNet, Open Data Commons Open Database License v1.0"
PROTOCOL = "ppg_physigpt_mimic3_v1"
SRC_FS = 125
UP, DOWN = 8, 25                      # 125 Hz -> 40 Hz
WINDOW = LENGTH*SRC_FS//FS            # 3750 source frames per 30 s window
BLOCK_WINDOWS = 10                    # one Range request covers 5 min
MARGIN = 2*SRC_FS                     # source frames fetched on each side so the filter's edges fall outside
ORDER_SALT = "physigpt-order-v1"
VALID_PERCENT = 2
FORMATS = {"80": (1, np.uint8), "16": (2, np.dtype("<i2"))}
INVALID = {"80": 0, "16": -32768}     # raw byte 0 is sample -128, WFDB's invalid value for format 80
# 8-bit PLETH also rails at byte 0 on troughs, so in format 80 only a run of 1 s or more counts as a dropout; shorter
# runs are the window minimum and fall under the 5% clipping rule.
DROPOUT_RUN = SRC_FS
CLIP_LIMIT = .05
CHUNK = 65536
SOS = butter(4, [.5, 8.], "bandpass", fs=FS, output="sos")
RATE_LAGS = (int(.3*FS), int(2.*FS))  # 30-200 bpm


def record_order(names):
    return sorted(names, key=lambda n: hashlib.sha256((ORDER_SALT+n).encode()).hexdigest())


def is_validation(name):
    return int(hashlib.sha256(("physigpt-split-v1"+name).encode()).hexdigest()[:8], 16) % 100 < VALID_PERCENT


def record_number(name):
    match = re.fullmatch(r"3\d/(\d{7})/?", name)
    if not match:
        raise ValueError(f"Unrecognized MIMIC-III record: {name}")
    return match.group(1)


def parse_header(text):
    """WFDB header -> dict(name, nsig, fs, frames, segments=[(name, frames)] | None, signals=[dict])."""
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    head = lines[0].split()
    name, nsig = head[0], int(head[1])
    fs = float(head[2].split("/")[0]) if len(head) > 2 else 250.
    frames = int(head[3]) if len(head) > 3 else 0
    if "/" in name:
        segments = [(part.split()[0], int(part.split()[1])) for part in lines[1:1+int(name.split("/")[1])]]
        return dict(name=name.split("/")[0], nsig=nsig, fs=fs, frames=frames, segments=segments, signals=[])
    signals = []
    for line in lines[1:1+nsig]:
        part = line.split()
        signals.append(dict(file=part[0], format=part[1], description=" ".join(part[8:]) if len(part) > 8 else ""))
    return dict(name=name, nsig=nsig, fs=fs, frames=frames, segments=None, signals=signals)


def pleth_layout(header):
    """(column, format) of the PLETH signal in a single-file segment, or None (no PLETH / unsupported layout)."""
    signals = header["signals"]
    names = [s["description"] for s in signals]
    if "PLETH" not in names or header["fs"] != SRC_FS:
        return None
    if len({s["file"] for s in signals}) != 1 or len({s["format"] for s in signals}) != 1:
        return None
    fmt = signals[0]["format"]
    return (names.index("PLETH"), fmt) if fmt in FORMATS else None


def blocks_of(frames):
    """(start frame, windows) blocks covering a segment of `frames` source frames."""
    windows = frames//WINDOW
    return [(b*WINDOW, min(BLOCK_WINDOWS, windows-b)) for b in range(0, windows, BLOCK_WINDOWS)]


def http_fetch(url, byte_range=None, retries=4, timeout=60):
    request = urllib.request.Request(url, headers={"User-Agent": "ppg-physigpt-research/1"})
    if byte_range:
        request.add_header("Range", f"bytes={byte_range[0]}-{byte_range[1]-1}")
    for attempt in range(retries+1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read()
            if byte_range and len(data) != byte_range[1]-byte_range[0]:
                raise OSError(f"short range read {len(data)} of {byte_range[1]-byte_range[0]}")
            return data
        except urllib.error.HTTPError as error:
            if error.code == 404 or attempt == retries:
                raise
        except OSError:
            if attempt == retries:
                raise
        time.sleep(min(30, 2**attempt))


def rate_features(x):
    """Autocorrelation peak in the 30-200 bpm lag range and its rate (bpm) per window."""
    centered = x-x.mean(1, keepdims=True)
    spectrum = np.fft.rfft(centered, 2*LENGTH, axis=1)
    acf = np.fft.irfft(np.abs(spectrum)**2, axis=1)[:, :LENGTH]
    acf = acf/np.maximum(acf[:, :1], 1e-12)
    lo, hi = RATE_LAGS
    lag = lo+acf[:, lo:hi].argmax(1)
    return acf[np.arange(len(x)), lag], 60*FS/lag


def invalid_mask(raw, fmt):
    bad = raw == INVALID[fmt]
    if fmt != "80" or not bad.any():
        return bad
    edges = np.flatnonzero(np.diff(np.r_[0, bad.astype(np.int8), 0]))
    mask = np.zeros_like(bad)
    for lo, hi in zip(edges[::2], edges[1::2]):
        if hi-lo >= DROPOUT_RUN:
            mask[lo:hi] = True
    return mask


def block_windows(raw, fmt, has_margin):
    """Valid min-max v3 windows of one fetched block. raw: PLETH ADC counts incl. margins."""
    left, right = has_margin
    core = raw[left:len(raw)-right]
    n = len(core)//WINDOW
    bad = invalid_mask(raw, fmt)
    keep, reason = [], {}
    clean = raw.astype(np.float64)
    if bad.any():
        good = np.flatnonzero(~bad)
        if len(good) < 2:
            return np.zeros((0, LENGTH), np.float32), [], {"invalid": n}
        clean[bad] = np.interp(np.flatnonzero(bad), good, clean[good])  # filter input only; such windows are dropped
    wave = sosfiltfilt(SOS, resample_poly(clean-clean.mean(), UP, DOWN, padtype="line"))
    offset = left*FS//SRC_FS
    out = []
    for w in range(n):
        source = slice(left+w*WINDOW, left+(w+1)*WINDOW)
        segment = raw[source]
        if bad[source].any():
            reason["invalid"] = reason.get("invalid", 0)+1
            continue
        if np.ptp(segment) < 4 or max(np.mean(segment == segment.min()), np.mean(segment == segment.max())) > CLIP_LIMIT:
            reason["flat_or_clipped"] = reason.get("flat_or_clipped", 0)+1
            continue
        x = wave[offset+w*LENGTH:offset+(w+1)*LENGTH]
        span = np.ptp(x)
        if len(x) != LENGTH or not np.isfinite(x).all() or span < 1e-8:
            reason["invalid_window"] = reason.get("invalid_window", 0)+1
            continue
        out.append((x-x.min())/span)
        keep.append(w)
    return (np.asarray(out, np.float32).reshape(-1, LENGTH), keep, reason)


def process_record(name, cap, fetch=http_fetch, base=BASE):
    """All accepted windows of one record: (signal float32 [n, LENGTH], rows of (segment, start frame), counts)."""
    rec = record_number(name)
    root = base+name.rstrip("/")+"/"
    master = parse_header(fetch(root+rec+".hea").decode())
    counts = {"segments_pleth": 0}
    segments = master["segments"] if master["segments"] is not None else [(master["name"], master["frames"])]
    rng = np.random.default_rng(int(hashlib.sha256(("physigpt-blocks-v1"+rec).encode()).hexdigest()[:8], 16))
    candidates = [(seg, frames) for seg, frames in segments if seg != "~" and not seg.endswith("_layout")
                  and frames >= WINDOW]
    pool = []
    for i in rng.permutation(len(candidates)):
        seg, frames = candidates[i]
        header = master if master["segments"] is None else parse_header(fetch(root+seg+".hea").decode())
        layout = pleth_layout(header)
        if layout is None:
            counts["segments_skipped"] = counts.get("segments_skipped", 0)+1
            continue
        counts["segments_pleth"] += 1
        pool += [(seg, header, layout, start, n) for start, n in blocks_of(header["frames"])]
        if sum(b[-1] for b in pool) >= 3*cap:
            break
    order = rng.permutation(len(pool))
    chosen, total = [], 0
    for i in order:
        if total >= cap:
            break
        take = min(pool[i][-1], cap-total)
        chosen.append(pool[i][:-1]+(take,))
        total += take
    signals, rows = [], []
    for seg, header, (column, fmt), start, n in sorted(chosen, key=lambda b: (b[0], b[3])):
        width, dtype = FORMATS[fmt]
        left = min(MARGIN, start)
        right = min(MARGIN, header["frames"]-(start+n*WINDOW))
        lo, hi = start-left, start+n*WINDOW+right
        data = fetch(root+header["signals"][0]["file"], (lo*header["nsig"]*width, hi*header["nsig"]*width))
        raw = np.frombuffer(data, dtype=dtype).reshape(-1, header["nsig"])[:, column].astype(np.int32)
        x, keep, reason = block_windows(raw, fmt, (left, right))
        for key, value in reason.items():
            counts[key] = counts.get(key, 0)+value
        signals.append(x)
        rows.append([(seg, start+w*WINDOW) for w in keep])
    signal = np.concatenate(signals) if signals else np.zeros((0, LENGTH), np.float32)
    counts["windows"] = len(signal)
    return signal, [r for block in rows for r in block], counts


def perform_record_names(fix):
    """7-digit waveform record names of one PERFORM record: the AF/non-AF sets keep a segment list in `files`
    (subj_id is a pNNNNNN clinical ID), the Large sets keep `mimic_details` with one `file` and a 7-digit rec_id."""
    fix = fix.get("mimic_details", fix)
    names = set()
    for key in ("files", "file", "rec_id", "subj_id"):
        for value in np.atleast_1d(fix.get(key, [])):
            base = str(value).split("_")[0]
            if re.fullmatch(r"\d{7}", base):
                names.add(base)
    return names


def perform_exclusions(cache):
    """7-digit MIMIC-III waveform record names behind the project's MIMIC PERFORM sets (data.SOURCES)."""
    from scipy.io import loadmat
    from ml.kaggle_multidomain.data import SOURCES, download
    names = set()
    for domain, (url, algorithm, expected) in SOURCES.items():
        if not domain.startswith("perform"):
            continue
        path = download(url, Path(cache)/url.rsplit("/", 1)[1], algorithm, expected)
        rows = loadmat(path, simplify_cells=True)["data"]
        for rec in [rows] if isinstance(rows, dict) else rows:
            names.update(perform_record_names(rec["fix"]))
        print("perform exclusions after", domain, len(names), flush=True)
    return sorted(names)


class ShardWriter:
    """Chunked uint16 windows (chunk_XXXX_signal.npy, memory-mappable) and their per-window metadata."""

    def __init__(self, output):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.buffer, self.meta, self.chunks, self.windows = [], [], [], 0

    def add(self, signal, record, rows, valid, acf, rate):
        self.buffer.append(np.round(np.clip(signal, 0, 1)*65535).astype(np.uint16))
        self.meta += [(int(record), int(rows[i][1]), int(valid), float(acf[i]), float(rate[i])) for i in range(len(rows))]
        if sum(len(b) for b in self.buffer) >= CHUNK:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        signal = np.concatenate(self.buffer)
        meta = np.array(self.meta, dtype=[("record", "<i4"), ("start", "<i4"), ("valid", "u1"), ("acf", "<f2"),
                                          ("rate", "<f2")])
        stem = f"chunk_{len(self.chunks):04d}"
        np.save(self.output/f"{stem}_signal.npy", signal)
        np.save(self.output/f"{stem}_meta.npy", meta)
        self.chunks.append(dict(stem=stem, windows=len(signal), valid=int(meta["valid"].sum()),
                                sha256=hashlib.sha256(signal.tobytes()).hexdigest()))
        self.windows += len(signal)
        self.buffer, self.meta = [], []


def build_shard(output, start, stop, cap, target, hours, workers=16, records=None, exclude=(), fetch=http_fetch,
                base=BASE):
    begin = time.time()
    if records is None:
        records = [line.strip() for line in fetch(base+"RECORDS-adults").decode().splitlines() if line.strip()]
    order = record_order(records)
    stop = min(stop, len(order))
    excluded = set(exclude)
    writer, done, failed, totals = ShardWriter(output), [], {}, {}
    pending, cursor, downloaded = {}, start, 0

    def submit(pool):
        nonlocal cursor
        while cursor < stop and len(pending) < 2*workers:
            name = order[cursor]
            cursor += 1
            if record_number(name) in excluded:
                totals["excluded_records"] = totals.get("excluded_records", 0)+1
                continue
            pending[pool.submit(process_record, name, cap, fetch, base)] = name

    with ThreadPoolExecutor(workers) as pool:
        submit(pool)
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                name = pending.pop(future)
                try:
                    signal, rows, counts = future.result()
                except Exception as error:  # a record that keeps failing is logged and skipped, never retried silently
                    failed[name] = f"{type(error).__name__}: {error}"[:200]
                    continue
                for key, value in counts.items():
                    totals[key] = totals.get(key, 0)+value
                done.append(name)
                if len(signal):
                    acf, rate = rate_features(signal)
                    writer.add(signal, record_number(name), rows, is_validation(name), acf, rate)
                    downloaded += len(signal)
            elapsed = (time.time()-begin)/3600
            if writer.windows+sum(len(b) for b in writer.buffer) >= target or elapsed >= hours:
                stop = cursor  # submit nothing more; in-flight records finish
            if len(done) % 200 == 0 and finished:
                print(f"records {len(done)} windows {writer.windows+sum(len(b) for b in writer.buffer)} "
                      f"failed {len(failed)} hours {elapsed:.2f}", flush=True)
            submit(pool)
    writer.flush()
    manifest = dict(protocol=PROTOCOL, license=LICENSE, source=BASE, fs=FS, length=LENGTH, src_fs=SRC_FS,
                    view="v3: record-block mean removed, resample_poly 8/25 padtype=line, Butterworth 4 0.5-8 Hz "
                         "sosfiltfilt over the block, per-window minmax, uint16",
                    order_salt=ORDER_SALT, valid_percent=VALID_PERCENT, cap_per_record=cap, block_windows=BLOCK_WINDOWS,
                    record_range=[start, cursor], next_record=cursor, records_total=len(order), records_done=len(done),
                    records_failed=failed, excluded=sorted(excluded), counts=totals, windows=writer.windows,
                    chunks=writer.chunks, hours=round((time.time()-begin)/3600, 3),
                    windows_per_hour=round(writer.windows/max((time.time()-begin)/3600, 1e-9)))
    save_json(Path(output)/"manifest.json", manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--stop", type=int, default=10**9)
    parser.add_argument("--cap", type=int, default=300, help="windows per record")
    parser.add_argument("--target", type=int, default=5_000_000)
    parser.add_argument("--hours", type=float, default=10.5)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--cache", default="/tmp/perform")
    args = parser.parse_args(argv)
    exclude = perform_exclusions(args.cache)
    manifest = build_shard(args.output, args.start, args.stop, args.cap, args.target, args.hours, args.workers,
                           exclude=exclude)
    print(json.dumps({k: manifest[k] for k in ("record_range", "windows", "hours", "windows_per_hour",
                                               "records_done")}), flush=True)


if __name__ == "__main__":
    main()
