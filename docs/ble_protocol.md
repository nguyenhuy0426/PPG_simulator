# BLE Remote-Control Protocol (Android ↔ PPG Simulator) — v2

FROZEN contract between this app (`comm/ble_server.py`, `bless` peripheral) and
the Android controller app `com.medical.simulator` (`ble/RpiBleManager.java`,
Nordic BLE library). Do not change either side without updating the other.

v2 additions (Pi side, backwards-compatible for parameter-only clients):
explicit **run/record** control, programmatic CSV **playback** (`pb`), the
control-state fields in the status frame, per-key command isolation, the
PI-while-locked translation, and the grace-window echo rule. The
implicit "first command auto-starts the simulation" behavior is REMOVED —
press RUN.

## GATT layout

| Role | UUID | Properties | Direction | Cadence |
|---|---|---|---|---|
| Service | `12345678-1234-5678-1234-56789abcdef0` | — | — | — |
| Command | `12345678-1234-5678-1234-56789abcdef1` | write, write-without-response | App → Pi | on user input (250 ms debounce) |
| Waveform | `12345678-1234-5678-1234-56789abcdef2` | notify | Pi → App | ~50 Hz (env `PPG_BLE_WAVEFORM_RATE`) |
| Status | `12345678-1234-5678-1234-56789abcdef3` | read + notify | Pi → App | ~5 Hz (env `PPG_BLE_STATUS_RATE`) |

Advertised local name: **`MedicalSimulatorRPi`**. The Android app requests
MTU 256; a status JSON measures ~200–207 bytes in normal operation and has a
**worst case of 247 bytes** even with every amplitude at its 4-digit maximum,
`"android"` origin and a 9-digit `seq` — because `pb_file` is truncated to
14 characters (`PB_FILE_MAX_CHARS`). Notifications cap at MTU−3, so the
client's negotiated MTU must be **≥ 250** (the Android app requests 256).
The waveform payload (≤ 8 bytes) is truncated-safe at default MTU 23.

## Command (WRITE, app → Pi)

UTF-8 JSON. All keys optional — **delta merge**, only present keys are applied.
Parameter values are clamped to `models/limits.py` (AC/DC amplitude:
**0–1500 mV**). Each key is applied inside its own guard: a value that raises
is logged and skipped, and **every other key of the same command still
applies**.

```json
{"hr":75,"spo2":98,"rr":16,"pi":2.50,"noise":0.10,"condition":0,
 "ac_ir_mv":45.0,"ac_red_mv":45.0,"dc_ir_mv":1500.0,"dc_red_mv":1500.0,
 "run":true,"record":false,"record_file":"data_1.csv","origin":"android"}
```

| Key | Meaning | Range |
|---|---|---|
| `hr` | heart rate setpoint | 10–300 BPM |
| `spo2` | SpO₂ target | 0–100 % |
| `rr` | respiration rate | 1–150 BrPM |
| `pi` | perfusion index | 0.01–30 % (see PI/lock note) |
| `noise` | artefact level | 0–1 |
| `condition` | condition mode index | 0–5 (Normal … Vasodilation) |
| `ac_ir_mv` / `ac_red_mv` | explicit AC amplitude | 0–1500 mV (`ac_red_mv` explicit uncouples RED from SpO₂) |
| `dc_ir_mv` / `dc_red_mv` | DC baseline | 0–1500 mV |
| `run` | **v2** start/stop the simulation (current condition) | `true` / `false`; also accepts `1`/`0`/`"true"`/`"false"`. Idempotent. |
| `record` | **v2** start/stop CSV recording (engine-owned sink → `dataset/`) | `true` / `false`. Requires `run:true` first; needs no GUI. Idempotent. |
| `record_file` | **v2** shared recording basename | Short bare `.csv` name. Both sides use it for the synchronized recording session. |
| `pb` | **v2** drive the Pi's recordings playback | `"start"` \| `"stop"` \| `"pause"` \| `"resume"` |
| `pb_file` | **v2** recording to play (with `pb:"start"`) | bare file name in `dataset/`; `.csv` appended if omitted; directory components are stripped; missing file → logged, no crash |
| `origin` | informational | ignored by the Pi |
| `seq` | informational | ignored by the Pi |

Notes:

- **PI while AC+DC are both locked** (set on the Pi's Signal setup tab):
  `engine.update_perfusion_index` would be a no-op, so the Pi *translates*
  `{"pi":P}` into `AC_ir = P/100 × DC_ir` and writes AC directly. The phone's
  intent lands on the device, and the next status frame echoes the resulting
  `pi`/`ac_ir_mv`.
- An unknown `pb` action is logged and ignored; `pb` commands are queued on
  the engine and applied by the GUI thread (typically within ~40 ms). In
  headless mode there is no playback UI, so a queued `pb` request is simply
  never serviced.
- Malformed JSON is logged and dropped (never crashes). Commands never
  auto-start the simulation (v2); the phone's RUN button is the trigger.

### Command examples (v2)

```json
{"run":true}
{"hr":90,"pi":4.0}
{"record":true}
{"pb":"start","pb_file":"data_1.csv"}
{"pb":"pause"}
{"pb":"resume"}
{"pb":"stop"}
{"run":false}
```

Parameter commands are delta-merged; omitted keys keep their current values.
When a packet contains both `pi` and explicit AC/DC fields (as a full phone
snapshot does), the explicit AC/DC values are authoritative and `pi` is
recomputed from `AC_IR / DC_IR * 100`. A packet containing `pi` without an
explicit AC IR value derives AC from PI; a packet containing only DC derives AC
from the current PI. This prevents a stale PI field from overwriting a slider
value in the same packet.

### Applied echo

`handle_command` returns the applied map (clamped values / resulting state);
`"run"` and `"record"` report the **post-command engine state**, so an
idempotent repeat (e.g. `{"record":true}` while already recording) confirms
`true` without restarting anything. On a Pi with log DEBUG at
`/tmp/ppg_simulator.log` these appear as `[BLE] Command applied: …`.

## Waveform (NOTIFY, Pi → App)

UTF-8 text `"%.2f"` of the **display IR signal in millivolts** (DC + AC +
noise, the same value that drives the DAC display path), e.g. `"1520.43"`.
The waveform keeps broadcasting the engine's last ring value while the
simulation is stopped — on a fresh dry-run that is the seeded DAC center
(≈ 1640 mV), not `"0.00"`. Clients must use the status frame's `running`
field as the authoritative stopped indicator, not the waveform text.

## Status (NOTIFY/READ, Pi → App)

UTF-8 JSON, ~5 Hz:

```json
{"hr":75.0,"spo2":98.0,"rr":16.0,"pi":3.0,"noise":0.0,"condition":0,
 "ac_ir_mv":45.0,"ac_red_mv":21.6,"dc_ir_mv":1500.0,"dc_red_mv":1500.0,
 "running":true,"recording":false,"pb":0,"origin":"rpi","seq":42}
```

While playback is active (`pb > 0`) the frame additionally carries
`"pb_file"` (truncated to 14 chars):

```json
{…,"running":true,"recording":false,"pb":1,"origin":"rpi","seq":88,
  "pb_file":"data_1.csv"}
```

> **Note:** `pb_file` is truncated to 14 chars, so cross-device playback
> mirroring is reliable only for short Pi-side names (`data_N.csv`). Phone-side
> `ppg_<timestamp>.csv` recordings exceed the limit and never name-match on
> the Pi: the Pi-only file must already exist in `dataset/`, otherwise the
> peer just shows the remote label.

| Key | Meaning |
|---|---|
| `running` | simulation producing output (`true` even while the engine thread is idle-parked; matches the Pi Run/Stop button) |
| `recording` | engine is capturing CSV rows to a `dataset/` file |
| `record_file` | shared basename while `recording` is true; omitted otherwise |
| `pb` | playback state: `0` inactive, `1` playing, `2` paused |
| `pb_file` | name of the loaded clip — present **only** when `pb > 0` |

Derived (None) AC setpoints are reported as their **nominal** values
(`AC_IR = PI/100 × DC_IR`; RED via the SpO₂ ratio-of-ratios) so phone sliders
always show what the generator outputs.

### Echo / sync rule (both sides must agree)

- `origin:"android"` — appears **only within a 1-second grace window**
  after a command applied from a Bluetooth write (`ANDROID_GRACE_S`). The
  phone updates its metric cards but **not** its sliders, so its own
  250 ms-debounced bursts are never fought.
- `origin:"rpi"` — every other status tick, without exception: after the
  grace window expires, and always for changes made locally on the Pi (GUI,
  engine, `PPG_BLE_CMD_FILE`). The status frame is the **source of truth**;
  the phone updates sliders **and** cards (skipping any slider the user is
  dragging) and therefore always converges on actual Pi state within
  ~1 s + one status interval.
- `seq` increments on every status broadcast.

`ac_ir_mv` / `ac_red_mv` / `dc_ir_mv` / `dc_red_mv` are echoed back with the
applied (clamped / re-derived) values so both UIs converge on the same
numbers.

## Running

```bash
# One-time (laptop or Pi):
.venv/bin/python -m pip install -r requirements/ble.txt

# GUI + BLE remote control:
PPG_DRY_RUN=1 .venv/bin/python main.py --dry-run --ble
# or on hardware:
.venv/bin/python main.py --ble

# Headless (no GUI) — for automated/CI testing:
PPG_DRY_RUN=1 .venv/bin/python main.py --dry-run --ble-only
```

`--ble-only` auto-starts the simulation and runs until Ctrl+C; config is saved
on exit. In GUI mode nothing starts implicitly — the phone must send
`{"run":true}` (or press the Pi Run button). When `--ble-only` runs headless,
phone-driven `record` still writes CSV files (the engine owns the recording
sink and pumps model ticks at 4 Hz without any Tk involvement).

## Troubleshooting

- **Phone cannot find the device** — check the adapter supports the peripheral
  role: `bluetoothctl show` → `Roles:` must list `peripheral`; while
  advertising, `ActiveInstances` must be ≥ 1.
- **Connects but no waveform** — the simulation is stopped by design; press
  Run in the GUI or send `{"run":true}` from the phone.
- **Single-adapter laptops cannot scan their own advertisement** — use the
  phone (or a second adapter) as the central.
- **Permission errors on D-Bus** — no root required; ensure the user session
  can reach the system bus and BlueZ is running (`systemctl status bluetooth`).
- Sliders fighting each other — both sides implement the echo rule above;
  verify `origin`/`seq` in the logs (`/tmp/ppg_simulator.log`, `[BLE]` lines).
  A per-key rejection now logs `[BLE] Command key '<name>' failed` with a
  traceback but never kills the rest of the command.
