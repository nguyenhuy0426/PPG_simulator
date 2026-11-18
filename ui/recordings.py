"""CSV reader for timestamped TX recordings and explicit legacy playback."""
import csv
import math
from pathlib import Path
from config import DAC_FULLSCALE_V, DAC_MAX_VALUE

LEGACY_RATE_HZ = 50.0
MAX_ROWS = 1_000_000
# Recordings saved before the record-pump fix (2026-11-18) can hold a few rows written out of order: two threads
# drained the engine buffer and wrote their batches interleaved. Such rows are put back in time order when they
# are few and only slightly early; anything more is a damaged file and is refused.
MAX_REORDERED_FRACTION = 0.01
MAX_REORDER_S = 0.5


def load_recording(path):
    rows = []
    timing = "Recorded model timestamps"
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"IR_Raw", "RED_Raw", "HR_BPM", "SpO2_%", "RR_BPM", "PI_%", "Condition"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Unsupported CSV: expected a PPG TX recording with IR_Raw / RED_Raw columns")
        timestamped = "Time_s" in reader.fieldnames
        if not timestamped: timing = "Legacy file: timing unavailable; playback assumes 50 Hz"
        latest, previous, early, worst = None, None, 0, 0.0
        for i, row in enumerate(reader):
            if i >= MAX_ROWS: raise ValueError("Recording exceeds 1,000,000 rows")
            try:
                ir, red = float(row["IR_Raw"]), float(row["RED_Raw"])
                if not all(math.isfinite(x) and 0 <= x <= 4095 for x in (ir, red)):
                    raise ValueError("DAC code outside 0…4095")
                stamp = float(row["Time_s"]) if timestamped else i / LEGACY_RATE_HZ
                if not math.isfinite(stamp) or stamp < 0:
                    raise ValueError("timestamps must be finite and strictly increasing")
                numeric = [float(row[k]) for k in ("HR_BPM", "SpO2_%", "RR_BPM", "PI_%")]
                if not all(math.isfinite(x) for x in numeric): raise ValueError("invalid parameter")
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid CSV row {i + 2}: {exc}") from exc
            if previous is not None and stamp <= previous:
                early += 1                               # a break in time order (one batch written into another)
            if latest is not None and stamp <= latest:
                worst = max(worst, latest - stamp)
            latest = stamp if latest is None else max(latest, stamp)
            previous = stamp
            rows.append((stamp, ir, red, (*numeric, row["Condition"])))
    if not rows: raise ValueError("Recording contains no data rows")
    if early:
        if early > MAX_REORDERED_FRACTION * len(rows) or worst > MAX_REORDER_S:
            raise ValueError(f"Invalid CSV: time goes back at {early} rows (up to {worst:.2f} s); "
                             "timestamps must be finite and strictly increasing")
        rows.sort(key=lambda r: r[0])
        if any(a[0] == b[0] for a, b in zip(rows, rows[1:])):
            raise ValueError("Invalid CSV: two rows share a timestamp; timestamps must be finite and strictly increasing")
        timing += f"; rows out of order at {early} places were put back in time order"
    first = rows[0][0]
    samples = [(t - first, ir / DAC_MAX_VALUE * DAC_FULLSCALE_V, red / DAC_MAX_VALUE * DAC_FULLSCALE_V)
               for t, ir, red, _ in rows]
    parameters = [p for *_, p in rows]
    return samples, parameters, timing
