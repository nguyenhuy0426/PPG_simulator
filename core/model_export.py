"""CSV output of a Model page window (ui/frames/neural_frame.py) for the Recordings list and for the phone.

Two forms:
  - recording_csv(): the Recordings format (ui/recordings.py): the DAC codes the window sends to the LEDs at its
    native rate, so it lists, plays to the LEDs and uploads like a Classic recording. HR is the window's HR
    (requested or measured) when it has one; SpO2, RR and PI are left blank: a generated window has none.
  - waveform_csv(): time_s, ir_v, red_v, the same columns as the Pi's own Export CSV.

transfer_parts() cuts a text into UI parts small enough for the BLE link (comm/ble_remote.UI_PART_MAX_BYTES)
so the phone can rebuild the file and save it where the user picks.
"""
import json
import re
from pathlib import Path

from calibration import dac_voltage_to_code

RECORDING_HEADER = "IR_Raw,RED_Raw,HR_BPM,SpO2_%,RR_BPM,PI_%,Condition,Time_s,Source\n"
NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


def window_hr(preview):
    """The window's HR in bpm (measured beats the requested one), or None."""
    info = getattr(preview, "provenance", None) or {}
    hr = info.get("hr_measured_bpm", getattr(preview, "hr_target", None))
    return float(hr) if isinstance(hr, (int, float)) and hr > 0 else None


def recording_csv(clip, preview, mode):
    hr = window_hr(preview)
    seed = getattr(preview, "seed", None)
    source = f"Model window {mode}" + (f" seed {seed}" if seed is not None else "")
    rows = [RECORDING_HEADER]
    for t, ir_v, red_v in clip.samples:
        rows.append(f"{dac_voltage_to_code(ir_v)},{dac_voltage_to_code(red_v)},"
                    f"{'' if hr is None else f'{hr:.1f}'},,,,{mode},{t:.6f},{source}\n")
    return "".join(rows)


def waveform_csv(clip):
    return "time_s,ir_v,red_v\n" + "".join(f"{t:.4f},{ir:.5f},{red:.5f}\n" for t, ir, red in clip.samples)


def file_stem(mode, preview, profile=""):
    seed = getattr(preview, "seed", None)
    stem = f"{mode}_{seed}" if seed is not None else f"{mode}_{profile}"
    return NAME_RE.sub("-", stem).strip("-") or "model"


def save_recording(folder, stem, text):
    """Write text as folder/<stem>.csv, or <stem>_2.csv ... when taken; returns the path."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f"{stem}.csv", 2
    while path.exists():
        path, n = folder / f"{stem}_{n}.csv", n + 1
    tmp = path.with_suffix(".csv.part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)          # the sync scan and the list never see a half-written file
    return path


def _size(fields):
    return len(json.dumps(fields, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def transfer_parts(text, ident, name, key="nnx", limit=240):
    """[(part name, fields)]: {"k", "id", "c", "m", "d"} chunks of text (whole lines), chunk 0 also "n" (file name).

    Each part encodes to at most `limit` bytes, so fit_part never shortens one."""
    lines = text.splitlines(keepends=True)
    chunks, current = [], ""
    def size(d):     # the file name rides on chunk 0 only; 99999 stands in for any index or count
        return _size({"k": key, "id": ident, "c": 99999, "m": 99999, "d": d, **({} if chunks else {"n": name})})

    for line in lines:
        if current and size(current + line) > limit:
            chunks.append(current)
            current = ""
        current += line
        if size(current) > limit:
            raise ValueError("a CSV line does not fit one part")
    if current or not chunks:
        chunks.append(current)
    parts = []
    for i, chunk in enumerate(chunks):
        fields = {"k": key, "id": ident, "c": i, "m": len(chunks), "d": chunk}
        if i == 0:
            fields["n"] = name
        parts.append((f"{key}{i}", fields))
    return parts
