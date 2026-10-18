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

The application imports neither `RPi.GPIO` nor `lgpio` itself, but Adafruit
Blinka needs `RPi.GPIO` on the Pi 4: in adafruit-blinka 9.2.0, the `import board` in
[hw/dac_manager.py](../../hw/dac_manager.py) reaches `from RPi import GPIO`, and
without a provider `DACManager.begin()` returns `False`. On Ubuntu 24.04 the
right way to satisfy that import is the **`rpi-lgpio` shim**, which presents the
`RPi.GPIO` API on top of the `lgpio` character-device backend that this kernel
actually exposes. It pulls `lgpio` as a dependency.

**Never install both `RPi.GPIO` and `rpi-lgpio` in the same environment.**
`requirements/rpi.txt` installs only `rpi-lgpio`, and both
`scripts/setup_rpi_ubuntu24.sh` and `scripts/verify_rpi_env.py` fail loudly if
they ever find the pair.

### The MM32 at 0x08 needs no adaptation

The official `grove/adc.py` declares `def __init__(self, address = 0x04)` — the
address is a **constructor keyword**, and `0x04` is only its default.
[hw/opt101_rx.py:172](../../hw/opt101_rx.py#L172) already passes
`ADC(address=GROVE_ADC_ADDR)` with `GROVE_ADC_ADDR = 0x08`
([config.py:63](../../config.py#L63)), and `grove.i2c.Bus(bus=1)` already defaults
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
[docs/hardware/design-audit/03_LED_DRIVER_ARCHITECTURE.md](../hardware/design-audit/03_LED_DRIVER_ARCHITECTURE.md)
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

## 11. Start automatically with the desktop session

For a standalone bench, install the **systemd user service** `ppg-simulator.service`.
It starts the simulator when your desktop session starts and restarts it after a
crash. It runs `.venv/bin/python main.py` as your normal user under
`systemctl --user`, so it gets your `i2c` group and your display. It never runs
as root.

```bash
cd ~/final_project/PPG_simulator_raspi
./scripts/install_user_service.sh --now
```

[scripts/install_user_service.sh](../../scripts/install_user_service.sh) fills
this checkout's path into
[packaging/linux/ppg-simulator.service.in](../../packaging/linux/ppg-simulator.service.in),
checks it with `systemd-analyze --user verify`, installs it as
`~/.config/systemd/user/ppg-simulator.service` and enables it. Run it as your
user, without `sudo`. Without `--now`, the service first starts at your next
login. `--now` starts it in the running session, after stopping any copy started
from the desktop icon with `SIGTERM`, which parks the DACs. Two copies would
fight over I2C and BLE. If `scripts/deploy_and_run.sh` started the app under its
transient unit, the installer always stops that copy and starts the installed
unit in its place, because systemd cannot enable a unit name while a transient
unit holds it.

### Why a user service

- In the Ubuntu 24.04 GNOME session (Wayland or Xorg), the session exports
  `DISPLAY`, `WAYLAND_DISPLAY` and `XAUTHORITY` into the systemd user manager.
  Every user service inherits them (`systemctl --user show-environment`).
- `graphical-session.target` is reached only after GNOME Shell has started:
  `gnome-session.target` is ordered after the Shell, before
  `graphical-session.target`, and binds it. The unit is `WantedBy=`, `After=`
  and `PartOf=graphical-session.target`, the pattern Ubuntu's own
  `xdg-desktop-portal-gnome.service` uses. It therefore starts once the display
  exists. At logout GNOME starts `gnome-session-shutdown.target`, which
  conflicts with `graphical-session.target`. That stop reaches the service
  through `PartOf=`, ordered before GNOME Shell stops.
- `scripts/deploy_and_run.sh` has already run the app on this Pi as a
  (transient) user unit, with the display and the Grove ADC working
  ([docs/rx-monitor-2026-10-01.md](../rx-monitor-2026-10-01.md)).
- An XDG autostart entry (`~/.config/autostart/`) would also start the app, but
  nothing would restart it after a crash.

The ordering, the inherited display, the restart and the start limit below were
checked on an Ubuntu 24.04.5 GNOME 46 (Wayland) laptop with systemd 255, using
`main.py --dry-run --no-ble`. They have **not yet been checked on the Pi**.

### What the unit does

| Situation | Behaviour |
|---|---|
| Desktop session starts | Started. The unit refuses to start outside a desktop session (`Requisite=graphical-session.target`) |
| Crash: non-zero exit, or killed by a signal | Restarted after 5 s (`Restart=on-failure`, `RestartSec=5`) |
| Crash loop | At most 5 starts in 5 minutes. After that the unit stays `failed` until `systemctl --user reset-failed ppg-simulator`, or until someone taps the desktop icon |
| Window closed, or `SIGTERM`/`SIGINT` sent to the app | Clean exit with status 0: not restarted |
| `systemctl --user stop`, logout | `SIGTERM` runs main.py's window-close path. It stops the output and parks both DACs at 0 V first, then stops the Neural worker, BLE and RX and saves the config. Its own timeouts add up to 18 s; `SIGKILL` comes only after 30 s (`TimeoutStopSec=30`) |
| Reboot, power-off | Ubuntu caps this at 5 s; see the end of this section |

The app's console output goes to the user journal
(`journalctl --user -u ppg-simulator -f`). The DEBUG log stays in
`/tmp/ppg_simulator.log`.

### Starting after a reboot needs automatic login

A user service runs only inside your session. After a reboot it therefore starts
only when someone logs in on the Pi screen. For a standalone bench, enable GDM
automatic login for this user: **Settings → System → Users → Unlock → Automatic
Login**, or set these lines in the `[daemon]` section of `/etc/gdm3/custom.conf`:

```ini
[daemon]
AutomaticLoginEnable=true
AutomaticLogin=<your user name>
```

The installer only reads this file, and prints a note when automatic login is
off. It never edits the file.

Automatic login gives anyone at the touch panel your desktop session, including
your files and SSH keys. Use it only on a bench you control. It also leaves the
login keyring locked, so store Wi‑Fi passwords for all users; otherwise GNOME
asks for the keyring password on the panel.

Optional, to keep the panel readable:

```bash
gsettings set org.gnome.desktop.session idle-delay 0               # never blank the screen
gsettings set org.gnome.desktop.screensaver lock-enabled false     # no lock screen asking for your password
```

### Everyday commands

```bash
systemctl --user status ppg-simulator           # running? how many restarts?
journalctl --user -u ppg-simulator -f           # live log
systemctl --user restart ppg-simulator          # apply new code copied by hand
systemctl --user stop ppg-simulator             # stop until the next login (DACs parked)
systemctl --user disable --now ppg-simulator    # stop, and do not start at login
./scripts/install_user_service.sh --uninstall   # stop, disable and remove the unit
```

- **Desktop icon:** with the service installed, the icon starts the service
  instead of a second copy, after clearing a `failed` state. While the service
  runs, the icon only reports "already running". The launcher with arguments
  (`scripts/launch_ppg_simulator.sh --no-ble`) still runs a diagnostic copy
  directly, but not while the service runs.
- **`scripts/deploy_and_run.sh`:** restarts the installed unit, which has the
  same name, instead of starting its transient one.
- **After moving the checkout, or after changing the unit template,** run the
  installer again (with `--now` to apply it at once). The unit stores the
  checkout's absolute path, and a deploy does not refresh it.

### Reboot and power-off: Ubuntu's 5 s cap

Ubuntu's `systemd` package ships
`/usr/lib/systemd/system/user@.service.d/timeout.conf` with `TimeoutStopSec=5`.
During a shutdown or reboot, all of your user services together get 5 s before
`SIGKILL`, whatever the unit's own 30 s says. main.py parks the DACs at the start
of its shutdown, so the outputs should reach 0 V within that time. BLE and RX
teardown may be cut short, though. For the full shutdown, stop the app first:

```bash
systemctl --user stop ppg-simulator && sudo reboot
```

The file was found on the Ubuntu 24.04 laptop this was written on. Check the Pi
with `systemctl cat user@$(id -u).service`.

### Still to check on the Pi

- The service starts at login, and with automatic login after a reboot, in the
  Pi's own GNOME session (Wayland or Xorg)
- The DACs, the Grove ADC and BLE work from the service
  (`journalctl --user -u ppg-simulator`)
- Both DAC outputs measure 0 V after `systemctl --user stop`, logout, reboot and
  power-off (multimeter on the MCP4725 outputs)
- How long the `SIGTERM` shutdown takes with BLE running. The laptop dry run
  without BLE took 0.12 s
- A crash on the Pi is restarted, and the start limit stops a crash loop

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
| `ppg-simulator.service` is `failed` with "Start request repeated too quickly" | five crashes in five minutes. Read `journalctl --user -u ppg-simulator -b`, fix the cause, then run `systemctl --user reset-failed ppg-simulator` and start it, or tap the desktop icon (§11) |
| The service log shows `Permission denied` on `/dev/i2c-1`, but a terminal does not | the systemd user manager started before you joined `i2c`; it survives a logout while an SSH session stays open. `systemd-run --user --wait --pipe id -nG` shows the groups a service gets. Reboot to fix it |
| "A dependency job for ppg-simulator.service failed" | no desktop session is running for this user. The service runs only inside one: log in on the Pi screen, or enable automatic login (§11) |
| The app does not come back after a reboot | automatic login is off (§11), or the unit is not enabled: `systemctl --user is-enabled ppg-simulator` |

---

## Related files

| File | Purpose |
|---|---|
| [scripts/setup_rpi_ubuntu24.sh](../../scripts/setup_rpi_ubuntu24.sh) | this guide, automated |
| [scripts/verify_rpi_env.py](../../scripts/verify_rpi_env.py) | read-only Pi environment check |
| [scripts/install_user_service.sh](../../scripts/install_user_service.sh) | installs, starts or removes the autostart user service (§11) |
| [packaging/linux/ppg-simulator.service.in](../../packaging/linux/ppg-simulator.service.in) | the systemd user unit it installs |
| [scripts/setup_laptop_venv.sh](../../scripts/setup_laptop_venv.sh) | laptop environment (no hardware) |
| [scripts/verify_laptop_env.py](../../scripts/verify_laptop_env.py) | read-only laptop check |
| [requirements/base.txt](../../requirements/base.txt) | host-portable runtime deps |
| [requirements/rpi.txt](../../requirements/rpi.txt) | Pi-only hardware deps, with reasons |
| [config.py](../../config.py) | addresses, channels, references, `DRY_RUN` |
| [docs/hardware/design-audit/03_LED_DRIVER_ARCHITECTURE.md](../hardware/design-audit/03_LED_DRIVER_ARCHITECTURE.md) | the 5 V driver design hypothesis |

**Never copy `.venv` between the laptop and the Pi.** The wheels are
architecture-specific and the `bin/` shebangs hardcode absolute paths. Each
machine builds its own; `.venv/` is in `.gitignore`.
