"""CSV reader for timestamped TX recordings and explicit legacy playback."""
import csv
import math
from pathlib import Path
from config import DAC_FULLSCALE_V, DAC_MAX_VALUE

LEGACY_RATE_HZ = 50.0
MAX_ROWS = 1_000_000


def load_recording(path):
    samples, parameters = [], []
    timing = "Recorded model timestamps"
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"IR_Raw", "RED_Raw", "HR_BPM", "SpO2_%", "RR_BPM", "PI_%", "Condition"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Unsupported CSV: expected a PPG TX recording with IR_Raw / RED_Raw columns")
        timestamped = "Time_s" in reader.fieldnames
        if not timestamped: timing = "Legacy file: timing unavailable; playback assumes 50 Hz"
        first = None
        previous = None
        for i, row in enumerate(reader):
            if i >= MAX_ROWS: raise ValueError("Recording exceeds 1,000,000 rows")
            try:
                ir, red = float(row["IR_Raw"]), float(row["RED_Raw"])
                if not all(math.isfinite(x) and 0 <= x <= 4095 for x in (ir, red)):
                    raise ValueError("DAC code outside 0…4095")
                stamp = float(row["Time_s"]) if timestamped else i / LEGACY_RATE_HZ
                if not math.isfinite(stamp) or stamp < 0 or (previous is not None and stamp <= previous):
                    raise ValueError("timestamps must be finite and strictly increasing")
                previous = stamp
                if first is None: first = stamp
                numeric = [float(row[k]) for k in ("HR_BPM", "SpO2_%", "RR_BPM", "PI_%")]
                if not all(math.isfinite(x) for x in numeric): raise ValueError("invalid parameter")
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid CSV row {i + 2}: {exc}") from exc
            samples.append((stamp-first, ir / DAC_MAX_VALUE * DAC_FULLSCALE_V, red / DAC_MAX_VALUE * DAC_FULLSCALE_V))
            parameters.append((*numeric, row["Condition"]))
    if not samples: raise ValueError("Recording contains no data rows")
    return samples, parameters, timing
