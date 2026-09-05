# Raspberry Pi 4 — Ubuntu 24.04 LTS setup guide

Bring-up guide for the PPG simulator on a **Raspberry Pi 4** running
**Ubuntu 24.04 LTS (aarch64)**.

**Status of this document:** the software steps are testable and reproducible.
The hardware statements it points to (LED current, op-amp compliance, optical
behaviour) are **design hypotheses, not measurements** — see
[§10](#10-what-is-still-unverified).

> This guide is for **Ubuntu 24.04**. Use
> [scripts/setup_rpi_ubuntu.sh](../../scripts/setup_rpi_ubuntu.sh); legacy
> Raspberry Pi OS installers were removed because they assumed the wrong Grove
> ADC address and GPIO backend for this hardware.

---

## Hardware this guide assumes

| Item | Value |
|---|---|
| Board | 1 × Raspberry Pi 4 |
| HAT | 1 × Grove Base HAT, common ground verified |
| ADC | Grove Base HAT **MM32**, I2C **0x08**, 12-bit, Vref **3.28 V** |
| DAC — IR | MCP4725, I2C **0x60**, full scale **3.28 V** |
| DAC — Red | MCP4725, I2C **0x61**, full scale **3.28 V** |
| Op-amp | LM358P (classic PDIP), supply **5.00 V** |
| Photodiode | OPT101, supply **3.28 V** |
| RX — IR | OPT101 → ADC channel **A0** |
| RX — Red | OPT101 → ADC channel **A2** |
| A1 | unused |
| Optics | two **completely isolated** Red and IR compartments |

These match [config.py](../../config.py) exactly; step 6 re-checks that
programmatically.

---

## The one-command path

If you want the whole thing and are willing to read what it asks:

```bash
cd ~/final_project/PPG_simulator_raspi
./scripts/setup_rpi_ubuntu24.sh --enable-i2c
```

Run it **as your normal user, not with sudo.** It calls `sudo` only for `apt`
and for the two system changes it prompts about first (the boot config edit and
the `i2c` group membership). It never writes a DAC value, never toggles a GPIO,
never probes the bus and never reboots.

The rest of this document is the same work done step by step, so you can see and
check each part.

---

## 1. Confirm Ubuntu 24.04 and aarch64

```bash
cat /etc/os-release
uname -m
cat /proc/device-tree/model
```

Expected:

```
PRETTY_NAME="Ubuntu 24.04 LTS"
VERSION_ID="24.04"
aarch64
Raspberry Pi 4 Model B Rev 1.x
```

If `uname -m` reports `armv7l`, a 32-bit image was flashed. Stop here and
reflash: the aarch64 wheels in [requirements/rpi.txt](../../requirements/rpi.txt)
will not install on a 32-bit userland.

---

## 2. Enable I2C in `/boot/firmware/config.txt`

On Ubuntu for the Pi, the boot configuration lives at **`/boot/firmware/config.txt`**
(not `/boot/config.txt`, which is the older Raspberry Pi OS path). There is no
`raspi-config` on a stock Ubuntu install, so edit the file:

```bash
sudo cp -a /boot/firmware/config.txt /boot/firmware/config.txt.bak
sudo nano /boot/firmware/config.txt
```

Ensure this line is present, in the `[all]` section (or at the end of the file):

```
dtparam=i2c_arm=on
```

Optional, only if you later need a bus speed other than the 100 kHz default:

```
dtparam=i2c_arm_baudrate=100000
```

Leave the default unless you have a measured reason to change it. Faster clocks
make marginal wiring and long Grove cables fail in ways that look like software
bugs.

---

## 3. Reboot and verify `/dev/i2c-1`

The device-tree parameter is read at boot. Nothing appears until you reboot.

```bash
sudo reboot
```

After it comes back:

```bash
ls -l /dev/i2c-*
```

Expected:

```
crw-rw---- 1 root i2c 89, 1 ... /dev/i2c-1
```

`/dev/i2c-1` is the bus the Grove Base HAT sits on (GPIO2 = SDA, GPIO3 = SCL).
If it is missing, step 2 did not take effect — re-check the exact spelling of
`dtparam=i2c_arm=on` and that you edited `/boot/firmware/config.txt`.

You may also see `/dev/i2c-0` or higher-numbered buses (HDMI DDC, camera). Ignore
them; this project uses bus 1 only.

---

## 4. Configure user permissions — without `chmod 777`

Notice the mode above: `crw-rw----`, owner `root`, group `i2c`. Your user needs
to be **in that group**. That is the whole fix:

```bash
sudo usermod -aG i2c "$USER"
```

Then **log out and log back in.** Group membership is established at login;
`usermod` does not change your current session. Verify:

```bash
id -nG        # 'i2c' must appear
```

**Do not run `sudo chmod 777 /dev/i2c-1`.** It grants every process on the
system — including anything you install later — unrestricted raw access to the
bus, it does not survive a reboot (udev recreates the node), and it hides the
real problem instead of fixing it. Group membership is persistent, scoped to
your user, and is what the device node was designed for.

For the same reason, do not run the application with `sudo`. Nothing in this
project needs root.

---

## 5. Create and activate the virtual environment

Ubuntu 24.04 marks its system Python as **externally managed** (PEP 668), so
`pip install` into it is blocked — correctly. Everything goes into a project-local
venv.

```bash
cd ~/final_project/PPG_simulator_raspi

sudo apt update
sudo apt install -y python3-venv python3-dev python3-pip python3-tk \
                    build-essential git i2c-tools

python3 -m venv --system-site-packages .venv
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements/rpi.txt

# grove.py, from the official Seeed Studio source repository:
python -m pip install --no-deps "git+https://github.com/Seeed-Studio/grove.py.git"
```

### Why each apt package

| Package | Reason |
|---|---|
| `python3-venv` | Ubuntu ships `venv` separately; without it `python3 -m venv` fails |
| `python3-dev` | headers, for any dependency lacking an aarch64 wheel |
| `python3-pip` | bootstraps pip inside the venv |
| `python3-tk` | the stdlib `tkinter`, required by `customtkinter` ([ui/ctk_app.py](../../ui/ctk_app.py)). **An OS package, not a pip package** |
| `build-essential` | C toolchain for the same source-build case |
| `git` | pip installs grove.py from a git repository |
| `i2c-tools` | provides `i2cdetect`, used in step 7 |

### Why `--system-site-packages`

It lets the venv see any vendor-supplied Python package already installed
system-wide (a distro `python3-gpiod`, a BSP module) that pip cannot reproduce on
aarch64. Project dependencies are still installed **into** the venv and shadow
anything inherited, so the dependency list stays explicit.

### Why `--no-deps` for grove.py — this one matters

grove.py's `setup.py` inspects `/proc/cpuinfo` and, when it sees a Raspberry Pi,
**appends `RPi.GPIO` and `rpi_ws281x` to `install_requires`**. Letting pip resolve
those would install the classic `RPi.GPIO` into an environment that already has
`rpi-lgpio`. Both provide the module name `RPi.GPIO`; installing both leaves which
one wins to installation order. `rpi_ws281x` is a NeoPixel driver this project
never uses. The only grove.py dependency on this project's code path is `smbus2`,
already pinned in [requirements/rpi.txt](../../requirements/rpi.txt).

### GPIO backend: `rpi-lgpio`, not `RPi.GPIO`

[hw/button_handler.py](../../hw/button_handler.py) tries `import RPi.GPIO` first
and falls back to `import lgpio`. On Ubuntu 24.04 the right way to satisfy the
first import is the **`rpi-lgpio` shim**, which presents the `RPi.GPIO` API on top
of the `lgpio` character-device backend that this kernel actually exposes. It
pulls `lgpio` as a dependency, so the fallback path works too.

**Never install both `RPi.GPIO` and `rpi-lgpio` in the same environment.**
`requirements/rpi.txt` installs only `rpi-lgpio`, and both
`scripts/setup_rpi_ubuntu24.sh` and `scripts/verify_rpi_env.py` fail loudly if
they ever find the pair.

### The MM32 at 0x08 needs no adaptation

The official `grove/adc.py` declares `def __init__(self, address = 0x04)` — the
address is a **constructor keyword**, and `0x04` is only its default.
[hw/opt101_rx.py:161](../../hw/opt101_rx.py#L161) already passes
`ADC(address=GROVE_ADC_ADDR)` with `GROVE_ADC_ADDR = 0x08`
([config.py:60](../../config.py#L60)), and `grove.i2c.Bus(bus=1)` already defaults
to `/dev/i2c-1`. **No installed file is patched, and none needs to be.** Step 6
re-checks this by introspecting the actually-installed class rather than trusting
this paragraph.

---

## 6. Run the environment verification

```bash
.venv/bin/python scripts/verify_rpi_env.py
```

It is **read-only**: it writes no DAC value, toggles no GPIO, and does not even
transact on the I2C bus. It reports `PASS` / `FAIL` / `SKIP` for:

- Linux, aarch64, Ubuntu 24.04, and the Pi model when readable
- running inside the project's own `.venv`
- `/dev/i2c-1` exists, **and your user can read/write it**
- `smbus2`, `board`, `busio`, `adafruit_mcp4725` import
- `grove.adc` imports and its `ADC` accepts an `address` argument
- `grove.i2c.Bus` defaults to bus 1
- a GPIO backend imports (`RPi.GPIO` shim and/or `lgpio`), and that
  `RPi.GPIO` + `rpi-lgpio` are **not** both installed
- `config.py` holds `0x08`, `0x60`, `0x61`, `DAC_FULLSCALE_V = 3.28`,
  `ADC_VOLTAGE_REF = 3.28`, `ADC_MAX_VALUE = 4095`, IR = A0, Red = A2
- `config.DRY_RUN` is `False` (i.e. `PPG_DRY_RUN` is not left set)

Exit status is 0 when nothing failed. `SKIP` never fails the run.

Also run the test suite on the Pi — it is hardware-independent, so it should give
the same result as on the laptop:

```bash
PPG_DRY_RUN=1 .venv/bin/python -m unittest \
    tests.test_calibration tests.test_phase3_acdc tests.test_phase4_dac \
    tests.test_phase5_rx tests.test_led_driver_dac \
    tests.test_led_driver_compliance tests.test_led_driver_power \
    tests.test_led_driver_error_budget
```

---

## 7. Scan the bus with `i2cdetect`

```bash
i2cdetect -y 1
```

No `sudo` — if you need it, step 4 is incomplete.

`i2cdetect` is not run automatically by any script here. Address scanning means
writing to every address on the bus, which can disturb a device mid-conversion;
that is a decision for you to make with the hardware in front of you, not
something a setup script should do behind your back.

---

## 8. Expected addresses

```
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         08 -- -- -- -- -- -- --
...
60: 60 61 -- -- -- -- -- -- -- -- -- -- -- -- -- --
70: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
```

| Address | Device |
|---|---|
| `0x08` | Grove Base HAT MM32 ADC |
| `0x60` | MCP4725 — **IR** |
| `0x61` | MCP4725 — **Red** |

Reading the result:

- **A device is missing** → check the Grove cable seating, the 3.28 V supply to
  that device, and common ground. A missing DAC is usually power or wiring, not
  software.
- **Both DACs at the same address** → the A0 address pin of one MCP4725 is not
  strapped. Two devices answering one address collide and neither is usable.
- **`UU` instead of an address** → a kernel driver has claimed it. Not expected
  here.
- **Extra addresses** → other HAT peripherals. Harmless if you are not using
  them.

---

## 9. An ACK does not prove analog or optical operation

**This is the most important sentence in this guide.**

A device appearing in `i2cdetect` proves exactly one thing: a chip pulled SDA low
in response to one address byte. That is a digital handshake on two wires.

It does **not** prove any of the following:

- that the MCP4725 output pin produces the expected voltage for a given code;
- that the ÷2 attenuator ratio is what the design assumes;
- that the LM358P is inside its input common-mode range or has output headroom;
- that any current flows through either LED, or how much;
- that the sense resistors are the assumed 100 Ω / 82 Ω, or within tolerance;
- that the 2SC1815 is in its active region rather than saturated or cut off;
- that either OPT101 receives light, or produces a signal above its noise floor;
- that the Red and IR optical compartments are actually isolated from each other
  or from ambient light;
- that the AC/DC ratio, perfusion index or R value computed downstream mean
  anything physical.

Every one of those requires **physical measurement** — a multimeter for DC
operating points, an oscilloscope for waveform, timing and loop stability. Until
those measurements exist, the 5 V driver design in
[led_driver/](../../led_driver/) and
[docs/superpowers/ppg_design_audit/03_LED_DRIVER_ARCHITECTURE.md](../superpowers/ppg_design_audit/03_LED_DRIVER_ARCHITECTURE.md)
is a **calculated hypothesis**, and the 261 passing tests are evidence about
*arithmetic*, not about *hardware*.

---

## 10. What is still unverified

Completing every step above gets you a working **software** environment on the
Pi. The following remain open and must be measured on the bench:

**Electrical**
- MCP4725 output voltage vs. code, at both 0x60 and 0x61
- The divider's actual ratio and its resistors' real tolerance
- LM358P input common-mode headroom at the top of the command range
- Emitter/sense voltage and the resulting LED current at code 0 and code 4095
- Sense-resistor, transistor and LED dissipation at full scale
- Total 5 V rail current against the calculated 37.60 mA budget

**Oscilloscope**
- Loop stability and whether the `C2` compensation footprint needs a part at all
  — it is currently **DNP / MEASUREMENT-REQUIRED**
- The `R_BE` choice between 10 kΩ, 100 kΩ and DNP, including low-current
  distortion and turn-off behaviour — **not finalised, do not populate on a guess**
- Actual TX/RX sample timing, jitter and clock drift under Linux, and whether the
  1 kHz component aliases into the 0.5–4 Hz heart-rate band

**I2C**
- Bus behaviour with all three devices active at the intended sample rate
- Error, retry and timeout behaviour under load

**Optical**
- OPT101 response with the LEDs driven
- Real optical isolation between the Red and IR compartments
- Signal-to-noise ratio, saturation, and ambient-light rejection

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `/dev/i2c-1` missing after reboot | `dtparam=i2c_arm=on` not in `/boot/firmware/config.txt`, or edited `/boot/config.txt` by mistake (step 2) |
| `Permission denied: /dev/i2c-1` | not in the `i2c` group, or you have not logged out and back in since `usermod` (step 4). **Do not `chmod 777`** |
| `error: externally-managed-environment` | you are pip-installing outside the venv. `source .venv/bin/activate` first (step 5) |
| `ModuleNotFoundError: No module named 'tkinter'` | `python3-tk` is an OS package: `sudo apt install python3-tk` |
| `ModuleNotFoundError: No module named 'grove'` | the `--no-deps` git install in step 5 did not run |
| `RPi.GPIO` behaving oddly | both `RPi.GPIO` and `rpi-lgpio` are installed. `pip uninstall RPi.GPIO` |
| Venv interpreter will not start | the `.venv` was copied from the x86_64 laptop. Delete it and re-run `./scripts/setup_rpi_ubuntu24.sh --recreate` |
| `i2cdetect` shows nothing | power and ground before software. Check the HAT seating and the 3.28 V rail |

---

## Related files

| File | Purpose |
|---|---|
| [scripts/setup_rpi_ubuntu24.sh](../../scripts/setup_rpi_ubuntu24.sh) | this guide, automated |
| [scripts/verify_rpi_env.py](../../scripts/verify_rpi_env.py) | read-only Pi environment check |
| [scripts/setup_laptop_venv.sh](../../scripts/setup_laptop_venv.sh) | laptop environment (no hardware) |
| [scripts/verify_laptop_env.py](../../scripts/verify_laptop_env.py) | read-only laptop check |
| [requirements/base.txt](../../requirements/base.txt) | host-portable runtime deps |
| [requirements/rpi.txt](../../requirements/rpi.txt) | Pi-only hardware deps, with reasons |
| [config.py](../../config.py) | addresses, channels, references, `DRY_RUN` |
| [docs/superpowers/ppg_design_audit/03_LED_DRIVER_ARCHITECTURE.md](../superpowers/ppg_design_audit/03_LED_DRIVER_ARCHITECTURE.md) | the 5 V driver design hypothesis |

**Never copy `.venv` between the laptop and the Pi.** The wheels are
architecture-specific and the `bin/` shebangs hardcode absolute paths. Each
machine builds its own; `.venv/` is in `.gitignore`.
