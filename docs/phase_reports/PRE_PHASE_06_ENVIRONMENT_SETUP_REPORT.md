# Pre-Phase-6 Environment Setup Report — Raspberry Pi 4 Python Environment

**Date:** 2026-07-12
**Scope:** Prepare the Python runtime environment for the PPG Simulator *before* Phase 6.
**Explicitly NOT done:** Phase 6 not started. No change to the Phase 1–5 signal-processing,
TX, RX, calibration, DAC, or ADC architecture. Only two new scripts and this report were added.

**Deliverables created (additive only):**
- `scripts/setup_rpi_venv.sh` — recommended isolated-venv installer.
- `scripts/install_rpi_system_packages.sh` — fallback system-Python installer (`--break-system-packages`).
- `docs/phase_reports/PRE_PHASE_06_ENVIRONMENT_SETUP_REPORT.md` — this report.

---

## 0. Honest execution constraint (read first)

This session ran on the **development laptop `huynn-lap` (x86_64, Ubuntu 24.04)**, **not** the
Raspberry Pi 4. No Grove Base HAT, MCP4725 DACs, or OPT101s are attached, and the Pi is not
reachable from this session. Consequently:

- Every **hardware-dependent** verification (grove.adc install/introspection, Blinka
  `board`/`busio`/MCP4725 import, `i2cdetect -y 1`) is honestly reported **NOT RUN / BLOCKED**.
- Every **host-portable** verification (CustomTkinter import, full project import graph in
  dry-run, script syntax, venv health logic) was **actually run** and its real output recorded.
- **No hardware-validation result is fabricated anywhere in this report.** This mirrors the
  Phase 5 report's constraint (see `PHASE_05_COMPLETION_REPORT.md` §1).

The scripts are written so the operator runs them **on the Pi**, where the currently-BLOCKED
checks execute for real.

---

## 1. Environment (measured on this host)

| Item | Value | How obtained |
|------|-------|--------------|
| OS | Ubuntu 24.04.4 LTS (Noble) | `cat /etc/os-release` |
| Kernel | `Linux 6.17.0-35-generic` | `uname -a` |
| Architecture | `x86_64` (**not** aarch64/armv7l → not a Pi) | `uname -m` |
| Board | *(no `/proc/device-tree/model` Raspberry-Pi match)* | device-tree probe |
| Python | `Python 3.12.3` | `python3 --version` |
| `python3` on PATH | `/home/huynn/final_project/PPG_simulator_raspi/.venv/bin/python3` | `which python3` |
| pip | `pip 24.0` (in `.venv`) | `python3 -m pip --version` |
| venv path (target) | `/home/huynn/final_project/PPG_simulator_raspi/.venv` | per task spec |

---

## 2. Source-of-truth: what the ACTIVE runtime path actually imports

Traced from `main.py` outward (not from `requirements.txt`, which is stale — see §7):

```
main.py
 ├─ config, config_store, comm.logger            (stdlib only)
 ├─ core.signal_engine ─ models.ppg_model, calibration, core.state_machine,
 │                        core.csv_logger, hw.dac_manager
 ├─ hw.opt101_rx        (stdlib + config; grove.adc imported LAZILY in begin())
 └─ ui.ctk_app ─ customtkinter, tkinter,
                 ui.frames.{pathology,calibration,playback}_frame (all customtkinter)
```

**Active third-party dependencies (the only ones the running app needs):**

| Package | Imported by | When |
|---------|-------------|------|
| `customtkinter` (+ `tkinter`, `darkdetect`) | `ui.ctk_app`, `ui/frames/*` | at import (UI) |
| `grove.py` → `grove.adc` | `hw/opt101_rx.py` | **lazy**, inside `begin()` when not dry-run |
| `smbus2` | transitive of `grove.adc` (grove.i2c) | with grove |
| `RPi.GPIO` | transitive of `grove.adc` (grove.i2c reads `RPI_REVISION`) | with grove |
| `adafruit-blinka` (`board`, `busio`) | `hw/dac_manager.py` | **lazy**, inside `begin()` when not dry-run |
| `adafruit-circuitpython-mcp4725` | `hw/dac_manager.py` | **lazy**, inside `begin()` |

**Deliberately NOT installed** (present in `requirements.txt` but NOT in the active CustomTkinter
runtime path — installing them would violate "only required packages"):

| Package | Why excluded (evidence) |
|---------|-------------------------|
| `pygame` | Only `ui/sliders.py` imports it — a dead pygame-UI module not reached from `main.py` (the live UI is CustomTkinter; `ui/pygame_display.py` source no longer exists, only a stale `.pyc`). `grep -rn "import numpy\|import pygame"` finds no active importer. |
| `numpy` | **Not imported anywhere** in the project (`grep` for `numpy` across all active source → 0 hits). |
| `bless` (BLE) | Only `comm/ble_server.py` imports it; that module is not referenced by the active path (`grep` for `ble_server`/`bless` outside itself → 0 hits). |
| `lgpio` | Only `hw/button_handler.py` (not in active path). |

Because all hardware imports are **lazy** (inside `begin()`), the entire project import graph
loads with **no hardware libraries present** in dry-run — this is what makes the host-side
verification below meaningful.

---

## 3. apt packages (minimal, evidence-based)

Both scripts install exactly this set:

```
python3-venv python3-dev build-essential python3-tk i2c-tools
```

| Package | Justification |
|---------|---------------|
| `python3-venv` | create the `.venv` (setup script only) |
| `python3-dev` + `build-essential` | compile the `RPi.GPIO` C extension and native Blinka deps |
| `python3-tk` | Tk backend required by CustomTkinter (`ui.ctk_app` → `import tkinter`) |
| `i2c-tools` | provides `i2cdetect` for the `0x04/0x60/0x61` bus-scan verification |

**apt commands actually RUN on this host: NONE.** Installing system packages on the dev laptop
was deliberately avoided. On this host `dpkg-query` shows `python3-venv`, `python3-dev`,
`build-essential`, `python3-tk` already installed and `i2c-tools` **not-installed**.

The **exact command the scripts will run on the Pi** (only for missing packages):

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev build-essential python3-tk i2c-tools
```

---

## 4. pip commands (exact, as embedded in the scripts)

**pip install commands actually RUN on this host: NONE** (no packages were installed or
upgraded; only the pre-existing `customtkinter` was imported for verification).

**Recommended path — `scripts/setup_rpi_venv.sh` (inside the venv, no `--break-system-packages`):**

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install customtkinter                       # host-portable
# Pi only (gated on Raspberry-Pi detection):
python -m pip install \
    "RPi.GPIO>=0.7.0" \
    "smbus2" \
    "grove.py" \
    "adafruit-blinka>=8.0.0" \
    "adafruit-circuitpython-mcp4725>=1.4.0"
```

**Fallback path — `scripts/install_rpi_system_packages.sh` (system Python, `--break-system-packages`
LAST on every command, run as normal user → `~/.local`, no `sudo pip`):**

```bash
python3 -m pip install --upgrade pip setuptools wheel --break-system-packages
python3 -m pip install customtkinter --break-system-packages
python3 -m pip install "RPi.GPIO>=0.7.0" --break-system-packages
python3 -m pip install "smbus2" --break-system-packages
python3 -m pip install "grove.py" --break-system-packages
python3 -m pip install "adafruit-blinka>=8.0.0" --break-system-packages
python3 -m pip install "adafruit-circuitpython-mcp4725>=1.4.0" --break-system-packages
```

**Version-pin rationale:** floors (`>=`) mirror the project's existing `requirements.txt` where
one is specified (`RPi.GPIO>=0.7.0`, `adafruit-blinka>=8.0.0`,
`adafruit-circuitpython-mcp4725>=1.4.0`). `grove.py`, `smbus2`, and `customtkinter` are left
**unpinned** — no verified compatibility evidence exists to justify a hard pin (blind pinning
avoided per instruction). The Phase 5 audit inspected `grove.py` **0.6**; if a specific grove
version must be reproduced, pin `grove.py==0.6` after confirming it on the Pi.

---

## 5. Installed package versions (current `.venv`, measured)

`python -m pip list` in `/home/huynn/final_project/PPG_simulator_raspi/.venv`:

```
customtkinter 5.2.2
darkdetect    0.8.0
packaging     26.2
pip           24.0
```

None of the hardware packages (`grove.py`, `smbus2`, `RPi.GPIO`, `adafruit-blinka`,
`adafruit-circuitpython-mcp4725`) are installed in any interpreter reachable from this host.
The setup script installs them on the Pi.

---

## 6. grove.adc API findings — SOURCE-AUDIT ONLY (on-Pi confirmation BLOCKED)

The mandated `python3 -c "import grove.adc, inspect; print(inspect.getsourcefile(grove.adc))"`
**cannot run here** (grove not installed; not on Pi). Result on this host:

```
$ .venv/bin/python -c "import grove.adc, inspect; print(inspect.getsourcefile(grove.adc))"
ModuleNotFoundError: No module named 'grove'          # NOT RUN / BLOCKED (no Pi, grove absent)
```

**Best available evidence** = the Phase 5 audit of the official **`grove.py` 0.6** package
(`grove/adc.py`, `grove/i2c.py`) from PyPI — real published, version-pinned code, not memory.
Reproduced here for the operator to diff against the *installed* grove on the Pi:

| API item | Value **[VERIFIED-CODE, grove.py 0.6 — CONFIRM ON PI]** |
|----------|--------------------------------------------------------|
| Class name | `ADC` (in `grove.adc`) |
| Constructor | `ADC(address=0x04)` |
| Default I2C address | `0x04` (matches user-verified Grove ADC MCU) |
| `read_raw(channel)` | reads register `0x10 + channel`, returns `int` (12-bit code, 0..4095) |
| `read_voltage(channel)` | reads `0x20 + channel`, returns input mV (`int`) — **not used** by RX |
| `read(channel)` | reads `0x30 + channel`, returns ratio % — not used |
| Channel numbering | channel index → register `0x10+ch`; so `A0`=ch 0 (IR), `A2`=ch 2 (Red) |
| Return type/units | `int`; raw = 12-bit ADC code (authoritative stored value in RX) |
| Transaction pattern | `bus.write_byte(addr, reg)` then `bus.read_word_data(addr, reg)` |
| Bus backend | `grove.i2c.Bus` = singleton `smbus2.SMBus`; selects bus via `RPi.GPIO.RPI_REVISION` |
| **Exception behavior** | `read_register()` catches `IOError`/`OSError`, prints a hint, then **`sys.exit(2)`** |
| Still calls `sys.exit(2)`? | **Yes in 0.6** — RX (`hw/opt101_rx.py`) already catches `SystemExit`. **Re-confirm on the installed version.** |

`scripts/setup_rpi_venv.sh` runs an **introspection block on the Pi** that prints the installed
`grove.adc` source path, `inspect.signature(ADC.__init__)`, the available methods, the default
address, and whether the source still contains `sys.exit` — so the table above is *verified against
the actual install*, not assumed. If the installed version differs (class/method names or the
`sys.exit` behavior), the RX error handling in `hw/opt101_rx.py` must be re-checked before trusting
RX data (per Phase 5 §1 handoff).

---

## 7. requirements.txt is STALE (documented, left unmodified)

`requirements.txt` predates the CustomTkinter UI and the Phase 5 grove RX. It is **not** the
install source of truth; the scripts are. Discrepancies (not changed — out of scope, and it is a
Phase 1–5 artifact):

- **Lists but unused:** `pygame>=2.5.0`, `numpy>=1.24.0`, `bless>=0.2.6` (see §2).
- **Missing but required:** `grove.py`, `smbus2` (grove RX dependencies), `customtkinter`.
- **Comments** still describe a `venv/` + pygame workflow and a `sudo bash` grove install.

Recommendation for Phase 6+ (not done here): regenerate `requirements.txt` from the active graph,
or point contributors at `scripts/setup_rpi_venv.sh`.

---

## 8. Pre-existing venvs are RELOCATED copies (real finding)

Both bundled venvs were created on **other machines/paths** and copied into this repo, so their
internal absolute paths are wrong:

| venv | `pyvenv.cfg command =` (origin) | `bin/pip` shebang | Status |
|------|----------------------------------|-------------------|--------|
| `.venv/` | `/home/halovie/Documents/KLTN/BioSignalSimulatorPro/.venv` | `#!/home/halovie/.../python3` (**does not exist here**) | `bin/pip` console script **broken**; `bin/activate` exports a foreign `VIRTUAL_ENV` |
| `venv/` | `/home/huynn/final_project/BioSignalSimulatorPro/PPG_simulator_raspi/venv` | foreign | stale duplicate |

`.venv/bin/python` still works (pyvenv.cfg `home=/usr/bin`, `executable=/usr/bin/python3.12` both
exist here) and `python -m pip` resolves `sys.prefix` correctly to the project `.venv`, which is why
imports pass. But relying on the copied venv is fragile (broken `pip` script, wrong activate path).

**Fix applied in the script:** `setup_rpi_venv.sh` includes `venv_is_healthy()` which verifies
`sys.prefix == $VENV_DIR` **and** that `bin/pip`'s shebang points inside `$VENV_DIR`; a relocated
venv is rebuilt with `python3 -m venv --clear`. Unit-tested against the current `.venv`:

```
verdict: RELOCATED/UNHEALTHY (would rebuild) — correct
```

The duplicate `venv/` directory is left untouched (not the target path; removing it is a separate
cleanup decision, not part of this task).

---

## 9. Verification matrix (every step)

| # | Verification step | Result | Evidence |
|---|-------------------|--------|----------|
| 1 | OS / architecture / kernel | **PASS** | Ubuntu 24.04.4, x86_64, 6.17.0-35 (§1) |
| 2 | Python version present | **PASS** | 3.12.3 |
| 3 | pip present | **PASS** | pip 24.0 |
| 4 | Script syntax (`bash -n`) — both scripts | **PASS** | both "syntax OK" |
| 5 | `venv_is_healthy()` detects relocated `.venv` | **PASS** | "RELOCATED/UNHEALTHY (would rebuild)" |
| 6 | Script venv-activate + verify mechanics (isolated run) | **PASS** | `RESULT PASS=2 FAIL=0` |
| 7 | `import customtkinter` | **PASS** | `CustomTkinter import OK 5.2.2` |
| 8 | `import tkinter` (CustomTkinter backend) | **PASS** | `tkinter OK 8.6` |
| 9 | Full project import graph (dry-run, hardware lazy) | **PASS** | `PROJECT CORE IMPORTS OK` |
| 10 | apt install of required packages | **NOT RUN** | intentionally not modifying dev host; command in §3 for the Pi |
| 11 | pip install of runtime packages | **NOT RUN** | no installs performed on dev host; commands in §4 for the Pi |
| 12 | `import grove.adc` + source path | **BLOCKED** | grove not installed; not on Pi (§6) |
| 13 | grove.adc constructor/methods/address/units | **BLOCKED (source-audit provided)** | grove.py 0.6 audit in §6; on-Pi introspection embedded in script |
| 14 | grove.adc still `sys.exit(2)` on I2C fault? | **BLOCKED (0.6 = yes; confirm on Pi)** | §6; RX already contains `SystemExit` |
| 15 | `import board, busio, adafruit_mcp4725` | **BLOCKED** | `ModuleNotFoundError: No module named 'board'`; not on Pi |
| 16 | `i2cdetect -y 1` → 0x04, 0x60, 0x61 | **NOT RUN / BLOCKED** | `i2cdetect` not installed; no Grove HAT; the `/dev/i2c-*` here are laptop HDMI/DDC buses, not the HAT |

**Summary:** host-portable PASS = 9/9. Hardware-dependent steps = NOT RUN / BLOCKED (no Pi),
0 fabricated results, 0 FAIL.

---

## 10. Remaining incompatibilities / unknowns (verify on the Pi)

1. **`RPi.GPIO` on Raspberry Pi OS Bookworm** — classic `RPi.GPIO` can fail on the Bookworm
   kernel; the drop-in replacement is the `rpi-lgpio` shim (provides an `RPi.GPIO` module). Because
   `grove.i2c` only reads the module-level constant `GPIO.RPI_REVISION`, the pip wheel is *usually*
   sufficient, but this must be confirmed by verification step 12/13 on the Pi. If `import grove.adc`
   fails on `RPi.GPIO`, install `rpi-lgpio` (and remove classic `RPi.GPIO`) in the venv.
2. **I2C must be enabled + user in `i2c` group** — `i2cdetect -y 1` needs `dtparam=i2c_arm=on`
   (`sudo raspi-config nonint do_i2c 0`, then reboot) and the runtime user in the `i2c` group
   (`sudo usermod -aG i2c <user>`). The script **checks and advises** (non-fatal); it does not
   auto-edit boot config or group membership (no silent privileged changes; no `chmod 777`, no
   run-as-root).
3. **Venv vs kernel GPIO/I2C access** — the isolated venv approach installs `RPi.GPIO`/`grove.py`
   into `.venv`. If venv-local hardware access misbehaves on the target image, the documented
   fallback is `scripts/install_rpi_system_packages.sh` (system interpreter).
4. **grove installed version may differ from 0.6** — re-run the §6 introspection on the Pi and diff.
5. **Actual I2C bus clock unknown** (Phase 5 §5) — affects RX timing inferences, not environment
   setup; out of scope here.
6. **OPT101 electrical unknowns carried from Phase 5 §9** (supply rail / 3.3 V input range,
   optical crosstalk) — hardware-bring-up items, not environment-setup items; unchanged and
   unresolved.

---

## 11. Commands actually run this session (host-portable, real output)

```
uname -a                       → Linux huynn-lap 6.17.0-35-generic x86_64
cat /etc/os-release            → Ubuntu 24.04.4 LTS
python3 --version              → Python 3.12.3
python3 -m pip --version       → pip 24.0 (.venv)
.venv/bin/python -m pip list   → customtkinter 5.2.2 / darkdetect 0.8.0 / packaging 26.2 / pip 24.0
import customtkinter           → OK 5.2.2                            [PASS]
import tkinter                 → OK 8.6                              [PASS]
project core imports (dry-run) → PROJECT CORE IMPORTS OK             [PASS]
import grove.adc               → ModuleNotFoundError                 [BLOCKED — no Pi]
import board,busio,mcp4725     → ModuleNotFoundError: 'board'        [BLOCKED — no Pi]
which i2cdetect                → not installed                       [NOT RUN]
bash -n scripts/*.sh           → syntax OK (both)                    [PASS]
venv_is_healthy(.venv)         → RELOCATED/UNHEALTHY (rebuild)       [PASS]
```

---

## 12. Operator runbook (on the Raspberry Pi 4)

```bash
cd /home/huynn/final_project/PPG_simulator_raspi
./scripts/setup_rpi_venv.sh                 # recommended (isolated .venv)
# ...or, only if the venv path is unworkable:
# ./scripts/install_rpi_system_packages.sh  # fallback (system python, --break-system-packages)

# then, manually confirm the shared bus:
i2cdetect -y 1                              # expect: 0x04 (Grove ADC), 0x60 (IR DAC), 0x61 (Red DAC)
source .venv/bin/activate
python3 -c "import grove.adc, inspect; print(inspect.getsourcefile(grove.adc))"
python3 -c "import board, busio, adafruit_mcp4725; print('MCP4725 imports OK')"
python3 -c "import customtkinter; print('CustomTkinter import OK')"
```

**STOP — Phase 6 not started.** Environment scripts and verification are prepared; the
hardware-dependent checks must be executed on the Pi and their real results appended before
any Phase 6 work begins.
