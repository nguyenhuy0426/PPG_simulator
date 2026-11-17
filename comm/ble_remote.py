"""BLE protocol v3: remote pages for the Android controller (pure helpers, no BlueZ, no Tk).

v3 lets the phone drive every page of the Pi app, not only the Monitor setpoints. The page logic stays in the
Pi frames; the phone sends page commands and shows what the Pi reports:

    STREAM  ...def4  Pi -> app  notify, ~10 Hz: "T<ir>,<red>;...|R<ir>,<red>;..." in mV, about 50 Hz per side.
                     T = what the Pi's TX plot of the active page shows (the DAC command, or the recording being
                     replayed on the Recordings page); R = the OPT101 receiver lanes A4 (IR) and A0 (RED), raw.
                     A side without data is sent empty ("T|R1.2,3.4"); nothing is ever invented.
    UI      ...def5  Pi -> app  notify + read: one JSON "part" per notification, {"k": <part>, ...}, each at most
                     UI_PART_MAX_BYTES so it fits a 256-byte MTU. Parts are built on the Tk thread for the page
                     on screen (key "page" says which) and re-sent in rotation, changed parts first.

Commands (on the v1 command characteristic ...def1, next to the v2 keys) are queued for the Tk thread:
    {"view": "monitor"|"calibration"|"recordings"|"neural"}   show that page on the Pi
    {"beep": bool}  {"gauss": true}                             Monitor: pulse tone, 3-Gaussian waveform
    {"cal": {"f","ir","red","sw","tol": number, "run": bool, "spo2": true}}
    {"nn": {"mode": str, "prof": str, "hr","lo","hi","dc","ac","seek": number, "gen": true, "play": bool}}
    {"rec": {"sel": "<file>.csv"}}                               load a recording (play/pause/stop stay on "pb")
See docs/ble_protocol.md, "Protocol v3".
"""
import json

STREAM_UUID = "12345678-1234-5678-1234-56789abcdef4"
UI_UUID = "12345678-1234-5678-1234-56789abcdef5"

# A notification carries at most MTU - 3 bytes. The Android app asks for MTU 517 but a central may settle lower;
# 240 bytes keeps every frame whole down to the MTU 256 the v2 status frame already requires.
UI_PART_MAX_BYTES = 240
STREAM_MAX_BYTES = 240
STREAM_RATE_HZ = 10.0
STREAM_STEP_S = 0.02            # ~50 Hz per side on the phone: the Pi TX plot and the RX lanes at half rate
STREAM_BACKLOG = 100            # samples per side kept for a slow link (2 s); older ones are dropped
UI_SEND_INTERVAL_S = 0.05       # one changed part per 50 ms
UI_ROTATE_INTERVAL_S = 0.25     # otherwise one part re-sent every 250 ms
UI_PUBLISH_INTERVAL_S = 0.25    # how often the Tk thread rebuilds the parts

VIEWS = {"monitor": "Pathology", "calibration": "Calibration", "recordings": "Playback", "neural": "Neural"}
FRAME_VIEWS = {frame: view for view, frame in VIEWS.items()}
REMOTE_KEYS = ("view", "beep", "gauss", "cal", "nn", "rec")


def remote_request(obj):
    """The v3 page keys of a decoded command, validated just enough to queue: {} when there are none.

    Values are re-checked (and clamped by the page widgets) on the Tk thread; this only drops shapes the pages
    cannot use, so a malformed key never reaches them.
    """
    out = {}
    if not isinstance(obj, dict):
        return out
    view = obj.get("view")
    if isinstance(view, str) and view in VIEWS:
        out["view"] = view
    if "beep" in obj and isinstance(obj["beep"], (bool, int)):
        out["beep"] = bool(obj["beep"])
    if obj.get("gauss") is True:
        out["gauss"] = True
    for key in ("cal", "nn", "rec"):
        if isinstance(obj.get(key), dict) and obj[key]:
            out[key] = dict(obj[key])
    return out


def number(value, default=None):
    """float(value) for JSON numbers only; bools and text give `default`."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    return value if value == value and abs(value) != float("inf") else default


def _encoded(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def fit_part(name, fields, limit=UI_PART_MAX_BYTES):
    """One UI part as UTF-8 JSON of at most `limit` bytes.

    Strings (also inside lists) are shortened, the longest first, with an ellipsis, until the part fits; a part
    that still does not fit has its longest list cut. Numbers and keys are never altered.
    """
    obj = {"k": name, **fields}
    data = _encoded(obj)
    while len(data) > limit:
        holder, key, longest = None, None, ""
        for k, v in obj.items():
            if k != "k" and isinstance(v, str) and len(v) > len(longest):
                holder, key, longest = obj, k, v
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    if isinstance(item, str) and len(item) > len(longest):
                        holder, key, longest = v, i, item
        if holder is not None and len(longest) > 8:
            cut = max(8, len(longest) - max(4, (len(data) - limit) + 1))
            holder[key] = longest[:cut - 1].rstrip() + "…"
        else:
            lists = [(k, v) for k, v in obj.items() if isinstance(v, list) and v]
            if not lists:
                break
            k, v = max(lists, key=lambda kv: len(_encoded(kv[1])))
            obj[k] = v[:-1]
        data = _encoded(obj)
    return data


def pack_stream(tx, rx, limit=STREAM_MAX_BYTES):
    """One stream frame from the oldest queued samples: (bytes, tx_used, rx_used).

    tx and rx are sequences of "ir,red" strings; as many of each as fit in `limit` are taken, alternating so
    neither side starves.
    """
    out_tx, out_rx = [], []
    size = 3                       # "T" + "|R"
    i = j = 0
    while i < len(tx) or j < len(rx):
        progressed = False
        if i < len(tx) and size + len(tx[i]) + 1 <= limit:
            out_tx.append(tx[i])
            size += len(tx[i]) + 1
            i += 1
            progressed = True
        if j < len(rx) and size + len(rx[j]) + 1 <= limit:
            out_rx.append(rx[j])
            size += len(rx[j]) + 1
            j += 1
            progressed = True
        if not progressed:
            break
    frame = "T" + ";".join(out_tx) + "|R" + ";".join(out_rx)
    return frame.encode("ascii"), i, j


def pair(ir_mv, red_mv):
    """"ir,red" with one decimal; an unknown lane is left empty."""
    def one(value):
        return "" if value is None else f"{value:.1f}"
    return f"{one(ir_mv)},{one(red_mv)}"


def decimate(rows, last_t, step=STREAM_STEP_S):
    """Rows (t, ...) at least `step` after last_t, one per `step`: (kept rows, new last_t).

    last_t None starts afresh with its last half second. A history whose newest time is well before last_t was restarted (the engine
    stamps a new run from 0), so it is read from its start again.
    """
    if rows and last_t is not None and rows[-1][0] < last_t - 1.0:
        last_t = None
    if rows and last_t is None:          # (re)start: the last half second, not the whole history
        last_t = rows[-1][0] - 0.5 - step
    kept = []
    for row in rows:
        if last_t is not None and row[0] < last_t + step * 0.999:
            continue
        kept.append(row)
        last_t = row[0]
    return kept, last_t


def preview_parts(series, key="pv", points=160, chunk=40):
    """A plotted window (lanes of (t, mV)) as compact parts the phone stitches together.

    Each lane is resampled to `points` values on 0-999 between its own min and max, sent in chunks of `chunk`:
    {"k": "pv", "id": <window id>, "l": lane, "n": lanes, "c": chunk index, "m": chunks, "lo": mV, "hi": mV,
     "t": seconds shown, "v": [...]}. The id changes whenever the window does, so the phone drops stale chunks.
    """
    lanes = [lane for lane in series if lane]
    if not lanes:
        return [(f"{key}0", {"k": key, "id": 0, "l": 0, "n": 0, "c": 0, "m": 0, "v": []})]
    ident = hash(tuple((round(lane[0][0], 3), round(lane[-1][0], 3), len(lane),
                        round(sum(v for _t, v in lane), 1)) for lane in lanes)) & 0x7FFFFFFF
    parts = []
    for li, lane in enumerate(lanes):
        t0, t1 = lane[0][0], lane[-1][0]
        values = [v for _t, v in lane]
        lo, hi = min(values), max(values)
        span = (hi - lo) or 1.0
        picked = []
        for p in range(points):
            target = t0 + (t1 - t0) * p / (points - 1) if points > 1 else t0
            idx = min(len(lane) - 1, max(0, round((target - t0) / ((t1 - t0) or 1) * (len(lane) - 1))))
            picked.append(int(round((lane[idx][1] - lo) / span * 999)))
        chunks = [picked[c:c + chunk] for c in range(0, len(picked), chunk)]
        for ci, values_chunk in enumerate(chunks):
            parts.append((f"{key}{li}.{ci}", {"k": key, "id": ident, "l": li, "n": len(lanes), "c": ci, "m": len(chunks),
                                               "lo": round(lo, 1), "hi": round(hi, 1), "t": round(t1 - t0, 2),
                                               "v": values_chunk}))
    return parts
