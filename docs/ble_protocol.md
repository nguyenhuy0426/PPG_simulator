# BLE Remote-Control Protocol (Android ↔ PPG Simulator)

FROZEN contract between this app (`comm/ble_server.py`, `bless` peripheral) and
the Android controller app `com.medical.simulator` (`ble/RpiBleManager.java`,
Nordic BLE library). Do not change either side without updating the other.

## GATT layout

| Role | UUID | Properties | Direction | Cadence |
|---|---|---|---|---|
| Service | `12345678-1234-5678-1234-56789abcdef0` | — | — | — |
| Command | `12345678-1234-5678-1234-56789abcdef1` | write, write-without-response | App → Pi | on user input (250 ms debounce) |
| Waveform | `12345678-1234-5678-1234-56789abcdef2` | notify | Pi → App | ~50 Hz (env `PPG_BLE_WAVEFORM_RATE`) |
| Status | `12345678-1234-5678-1234-56789abcdef3` | read + notify | Pi → App | ~5 Hz (env `PPG_BLE_STATUS_RATE`) |

Advertised local name: **`MedicalSimulatorRPi`**. The Android app requests
MTU 256; the status JSON stays ≤ ~180 bytes so it also fits MTU 247 (and can be
truncated-safe at default MTU 23 for waveform-only links: floats are ≤ 8 bytes).

## Command (WRITE, app → Pi)

UTF-8 JSON. All keys optional — **delta merge**, only present keys are applied.
Values are clamped to `models/limits.py` (AC/DC amplitude: **0–1500 mV**).

```json
{"hr":75,"spo2":98,"rr":16,"pi":2.50,"noise":0.10,"condition":0,
 "ac_ir_mv":45.0,"ac_red_mv":45.0,"dc_ir_mv":1500.0,"dc_red_mv":1500.0,
 "origin":"android"}
```

| Key | Meaning | Range |
|---|---|---|
| `hr` | heart rate setpoint | 10–300 BPM |
| `spo2` | SpO₂ target | 0–100 % |
| `rr` | respiration rate | 1–150 BrPM |
| `pi` | perfusion index | 0.01–30 % |
| `noise` | artefact level | 0–1 |
| `condition` | condition mode index | 0–5 (Normal … Vasodilation) |
| `ac_ir_mv` / `ac_red_mv` | explicit AC amplitude | 0–1500 mV (`ac_red_mv` explicit uncouples RED from SpO₂) |
| `dc_ir_mv` / `dc_red_mv` | DC baseline | 0–1500 mV |
| `origin` | informational, always `"android"` | — |

Unknown keys are ignored; malformed JSON is logged and dropped (never crashes).

## Waveform (NOTIFY, Pi → App)

UTF-8 text `"%.2f"` of the **display IR signal in millivolts** (DC + AC +
noise, the same value that drives the DAC display path), e.g. `"1520.43"`.
While the simulation is stopped the payload is `"0.00"`.

## Status (NOTIFY/READ, Pi → App)

UTF-8 JSON, ~5 Hz:

```json
{"hr":75.0,"spo2":98.0,"rr":16.0,"pi":3.0,"noise":0.0,"condition":0,
 "ac_ir_mv":45.0,"ac_red_mv":59.4,"dc_ir_mv":1500.0,"dc_red_mv":1500.0,
 "origin":"rpi","seq":42}
```

Derived (None) AC setpoints are reported as their **nominal** values
(`AC_IR = PI/100 × DC_IR`; RED via the SpO₂ ratio-of-ratios) so phone sliders
always show what the generator outputs.

### Echo / sync rule (both sides must agree)

- `origin:"android"` — the change came from an app command; the phone updates
  its metric cards but **not** its sliders (avoids feedback jitter).
- `origin:"rpi"` — the change came from the Pi GUI/engine; the phone updates
  sliders **and** cards (skipping any slider the user is dragging).
- `seq` increments on every status broadcast.

`ac_ir_mv` / `ac_red_mv` / `dc_ir_mv` / `dc_red_mv` are echoed back with the
applied (clamped) values so both UIs converge on the same numbers.

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
on exit. In GUI mode the engine auto-starts once when the phone sends its first
command while stopped, so the phone immediately sees a waveform.

## Troubleshooting

- **Phone cannot find the device** — check the adapter supports the peripheral
  role: `bluetoothctl show` → `Roles:` must list `peripheral`; while
  advertising, `ActiveInstances` must be ≥ 1.
- **Connects but no waveform** — the simulation is stopped; press Run in the
  GUI or send any command from the phone (auto-start).
- **Single-adapter laptops cannot scan their own advertisement** — use the
  phone (or a second adapter) as the central.
- **Permission errors on D-Bus** — no root required; ensure the user session
  can reach the system bus and BlueZ is running (`systemctl status bluetooth`).
- Sliders fighting each other — both sides implement the echo rule above;
  verify `origin`/`seq` in the logs (`/tmp/ppg_simulator.log`, `[BLE]` lines).
