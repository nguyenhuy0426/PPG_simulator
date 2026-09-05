#!/usr/bin/env python3
"""
scripts/verify_rpi_env.py — READ-ONLY check of the Raspberry Pi 4 environment.

Run on the Pi, inside the Pi's own .venv:

    .venv/bin/python scripts/verify_rpi_env.py

WHAT THIS SCRIPT DOES NOT DO
----------------------------
It is strictly read-only with respect to hardware:

  * It NEVER writes a DAC value. No MCP4725 write, no `dac.value = ...`,
    no raw I2C write of any kind.
  * It NEVER toggles a GPIO. It does not call setup(), output(), or claim any
    line on any gpiochip.
  * It does not even probe the I2C bus. Probing means transacting on the bus,
    which can disturb a device mid-conversion. Address discovery is left to
    `i2cdetect -y 1`, which you run yourself (see step 7 of
    docs/setup/RASPBERRY_PI_4_UBUNTU_24_04.md or
    docs/setup/RASPBERRY_PI_4_UBUNTU_26_04_SSH.md).

It inspects: the OS, the machine, /dev/i2c-1's presence and YOUR permission on
it, whether the required Python modules import, whether the installed grove.py
accepts a non-default I2C address, and whether config.py holds the addresses
this build expects.

Exit status: 0 if no check FAILED, 1 otherwise. SKIP never fails the run.

WHAT A PASS HERE MEANS
----------------------
Only that the software environment is correct and the bus is reachable. It is
NOT electrical, analog or optical validation. Even a later `i2cdetect` ACK at
0x08 / 0x60 / 0x61 proves only that a chip pulled SDA low for one address byte.
It says nothing about DAC output voltage, op-amp compliance, LED current,
photodiode response or optical isolation between the Red and IR compartments.
Those need a multimeter and an oscilloscope on the real board.
"""

import importlib
import inspect
import os
import platform
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

I2C_DEV = Path("/dev/i2c-1")
SUPPORTED_UBUNTU_LTS = {"24.04", "26.04"}

# The addresses this build is wired for. Cross-checked against config.py.
EXPECTED_ADDRESSES = {
    0x08: "Grove Base HAT MM32 ADC (12-bit, Vref 3.28 V)",
    0x60: "MCP4725 DAC — IR channel",
    0x61: "MCP4725 DAC — Red channel",
}

_RESULTS = []
_GREEN, _RED, _YELLOW, _CYAN, _OFF = (
    "\033[1;32m", "\033[1;31m", "\033[1;33m", "\033[1;36m", "\033[0m")


def _supports_colour() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _paint(colour: str, text: str) -> str:
    return f"{colour}{text}{_OFF}" if _supports_colour() else text


def section(title: str) -> None:
    print(f"\n{_paint(_CYAN, '==> ' + title)}")


def record(status: str, label: str, detail: str = "") -> None:
    colour = {"PASS": _GREEN, "FAIL": _RED, "SKIP": _YELLOW}[status]
    print(f"  [{_paint(colour, status)}] {label}")
    if detail:
        for line in detail.splitlines():
            print(f"        {line}")
    _RESULTS.append((status, label, detail))


def _try_import(name: str):
    """Import a module, returning (module_or_None, exception_or_None)."""
    try:
        return importlib.import_module(name), None
    except Exception as exc:                      # noqa: BLE001 - report anything
        return None, exc


# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------

def check_platform() -> None:
    section("Platform")

    if platform.system() == "Linux":
        record("PASS", "operating system is Linux")
    else:
        record("FAIL", f"operating system is {platform.system()}, expected Linux")

    machine = platform.machine()
    if machine == "aarch64":
        record("PASS", "architecture is aarch64 (64-bit ARM)")
    elif machine in ("armv7l", "armv6l"):
        record("FAIL", f"architecture is {machine} — this is a 32-bit userland",
               "Ubuntu for the Pi 4 is 64-bit. A 32-bit userland means the\n"
               "wrong image was flashed, and aarch64 wheels will not install.")
    else:
        record("FAIL", f"architecture is {machine}, expected aarch64",
               "This script is meant to run ON the Raspberry Pi 4, not on the laptop.")

    # /etc/os-release is the authoritative distro identity.
    os_release = Path("/etc/os-release")
    if os_release.is_file():
        fields = {}
        for line in os_release.read_text().splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                fields[key] = value.strip('"')
        pretty = fields.get("PRETTY_NAME", "unknown")
        if (fields.get("ID") == "ubuntu"
                and fields.get("VERSION_ID") in SUPPORTED_UBUNTU_LTS):
            record("PASS", f"distribution: {pretty}")
        else:
            record("SKIP", f"distribution: {pretty}",
                   "This setup supports Ubuntu 24.04 and 26.04 LTS. Another distro\n"
                   "may work but the apt package names and /boot/firmware/config.txt\n"
                   "path in the guide are Ubuntu-specific.")
    else:
        record("SKIP", "/etc/os-release not readable")

    model_file = Path("/proc/device-tree/model")
    if model_file.is_file():
        try:
            model = model_file.read_bytes().decode("utf-8", "replace").rstrip("\x00").strip()
        except OSError as exc:
            record("SKIP", "could not read /proc/device-tree/model", str(exc))
            return
        if "Raspberry Pi 4" in model:
            record("PASS", f"board: {model}")
        elif "Raspberry Pi" in model:
            record("SKIP", f"board: {model}",
                   "Not a Pi 4. The Grove Base HAT pinout and the I2C bus number\n"
                   "may differ. Verify before trusting anything below.")
        else:
            record("FAIL", f"board: {model} — not a Raspberry Pi")
    else:
        record("SKIP", "/proc/device-tree/model absent — board model unknown",
               "Normal on a non-Pi machine, or in a container.")


# ---------------------------------------------------------------------------
# I2C bus
# ---------------------------------------------------------------------------

def check_i2c_device() -> None:
    section("I2C bus (existence and permissions only — no bus traffic)")

    if not I2C_DEV.exists():
        record("FAIL", f"{I2C_DEV} does not exist",
               "The I2C controller is not enabled. Add this line to\n"
               "/boot/firmware/config.txt and reboot:\n"
               "    dtparam=i2c_arm=on\n"
               "See the Ubuntu setup guide under docs/setup/ steps 2-3.")
        return
    record("PASS", f"{I2C_DEV} exists")

    if os.access(I2C_DEV, os.R_OK | os.W_OK):
        record("PASS", f"current user can read and write {I2C_DEV}")
    else:
        record("FAIL", f"current user CANNOT read/write {I2C_DEV}",
               "Add yourself to the i2c group — do NOT chmod 777 the device:\n"
               "    sudo usermod -aG i2c $USER\n"
               "then log out and back in (group membership is set at login).")

    # Report group ownership so a wrong-group situation is visible.
    try:
        st = I2C_DEV.stat()
        import grp
        group = grp.getgrgid(st.st_gid).gr_name
        print(f"        node: mode {oct(st.st_mode & 0o777)}, group '{group}'")
        try:
            in_group = st.st_gid in os.getgroups()
        except OSError:
            in_group = False
        if in_group:
            print(f"        you are a member of group '{group}'")
        else:
            print(f"        you are NOT a member of group '{group}' in this session")
    except (OSError, KeyError):
        pass


# ---------------------------------------------------------------------------
# Python packages
# ---------------------------------------------------------------------------

def check_venv() -> None:
    section("Interpreter")
    v = sys.version_info
    record("PASS" if v[:2] >= (3, 9) else "FAIL",
           f"Python {v.major}.{v.minor}.{v.micro}", sys.executable)

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    expected = PROJECT_ROOT / ".venv"
    if in_venv and Path(sys.prefix).resolve() == expected.resolve():
        record("PASS", "running inside the project's own .venv", str(expected))
    elif in_venv:
        record("SKIP", "running inside a venv other than the project's",
               f"sys.prefix = {sys.prefix}")
    else:
        record("FAIL", "not running inside a virtual environment",
               "Ubuntu marks its system Python as externally-managed\n"
               "(PEP 668); installing into it with pip is both blocked and wrong.\n"
               "Run:  .venv/bin/python scripts/verify_rpi_env.py")


def check_gui_modules() -> None:
    section("GUI modules (imports only — no window is created)")

    tkinter, exc = _try_import("tkinter")
    if tkinter is not None:
        record("PASS", "import tkinter",
               f"Tk {getattr(tkinter, 'TkVersion', 'unknown')}")
    else:
        record("FAIL", "import tkinter", f"{exc!r}\n"
               "Tkinter is an Ubuntu package, not a pip package. Install it with:\n"
               "    sudo apt install -y python3-tk")

    customtkinter, exc = _try_import("customtkinter")
    if customtkinter is not None:
        record("PASS", "import customtkinter",
               f"version {getattr(customtkinter, '__version__', 'unknown')}")
    else:
        record("FAIL", "import customtkinter", repr(exc))


def check_i2c_modules() -> None:
    section("I2C / DAC Python modules")

    smbus2, exc = _try_import("smbus2")
    if smbus2 is not None:
        record("PASS", "import smbus2",
               f"version {getattr(smbus2, '__version__', 'unknown')}")
    else:
        record("FAIL", "import smbus2", repr(exc))

    # board/busio come from Adafruit Blinka. On a non-Pi host they raise at
    # import time by design, so distinguish absent from present-but-unhappy.
    for name in ("board", "busio"):
        module, exc = _try_import(name)
        if module is not None:
            record("PASS", f"import {name}")
        elif isinstance(exc, ImportError):
            record("FAIL", f"import {name}", f"{exc!r}\n"
                   "Provided by adafruit-blinka. Install requirements/rpi.txt.")
        else:
            record("FAIL", f"import {name} raised at import time", repr(exc))

    module, exc = _try_import("adafruit_mcp4725")
    if module is not None:
        record("PASS", "import adafruit_mcp4725",
               "hw/dac_manager.py needs this for the 0x60 / 0x61 DACs.")
    else:
        record("FAIL", "import adafruit_mcp4725", repr(exc))


def check_grove_adc() -> None:
    section("grove.py — MM32 ADC at address 0x08")

    module, exc = _try_import("grove.adc")
    if module is None:
        record("FAIL", "import grove.adc", f"{repr(exc)}\n"
               "Install the official Seeed source, without its deps:\n"
               '    .venv/bin/python -m pip install --no-deps \\\n'
               '        "git+https://github.com/Seeed-Studio/grove.py.git"')
        return
    record("PASS", "import grove.adc", f"from {getattr(module, '__file__', '?')}")

    adc_cls = getattr(module, "ADC", None)
    if adc_cls is None:
        record("FAIL", "grove.adc has no ADC class")
        return

    # The claim under test: the INSTALLED grove.py accepts a non-default
    # address, so MM32 at 0x08 needs no patching of installed files.
    try:
        sig = inspect.signature(adc_cls.__init__)
    except (TypeError, ValueError) as sig_exc:
        record("SKIP", "could not introspect ADC.__init__", str(sig_exc))
        return

    param = sig.parameters.get("address")
    if param is None:
        record("FAIL", "grove.adc.ADC.__init__ has no 'address' parameter",
               f"signature: {sig}\n"
               "The installed grove.py cannot be pointed at 0x08 through its\n"
               "public API. A project-local adapter would be required — do NOT\n"
               "edit the installed package.")
        return

    default = param.default
    default_txt = hex(default) if isinstance(default, int) else repr(default)
    record("PASS", "grove.adc.ADC accepts an 'address' argument",
           f"signature: {sig}\n"
           f"default {default_txt}; hw/opt101_rx.py passes address=0x08 explicitly,\n"
           "so no adaptation and no patching of installed files is needed.")

    # grove/i2c.py must default to bus 1 (/dev/i2c-1) on the Pi 4.
    i2c_module, i2c_exc = _try_import("grove.i2c")
    if i2c_module is None:
        record("SKIP", "import grove.i2c", repr(i2c_exc))
        return
    bus_cls = getattr(i2c_module, "Bus", None)
    if bus_cls is None:
        record("SKIP", "grove.i2c has no Bus class")
        return
    try:
        bus_default = inspect.signature(bus_cls.__init__).parameters["bus"].default
    except (TypeError, ValueError, KeyError):
        record("SKIP", "could not introspect grove.i2c.Bus.__init__")
        return
    if bus_default == 1:
        record("PASS", "grove.i2c.Bus defaults to bus 1 (/dev/i2c-1)")
    else:
        record("SKIP", f"grove.i2c.Bus defaults to bus {bus_default!r}, not 1",
               "Confirm which /dev/i2c-* node the Grove Base HAT is on.")


def check_gpio_backend() -> None:
    section("GPIO backend (import only — no line is claimed or toggled)")

    # hw/button_handler.py:begin() tries RPi.GPIO first, then lgpio.
    rpi_gpio, rpi_exc = _try_import("RPi.GPIO")
    lgpio_mod, lgpio_exc = _try_import("lgpio")

    # Both projects install the same RPi.GPIO import path, so the module's file
    # name cannot identify the provider. Ask package metadata which distribution
    # owns the top-level RPi package instead.
    try:
        from importlib.metadata import packages_distributions
        rpi_package_owners = {
            name.lower() for name in (packages_distributions().get("RPi") or [])
        }
    except Exception:                             # noqa: BLE001
        rpi_package_owners = set()

    if rpi_gpio is not None:
        source = getattr(rpi_gpio, "__file__", "") or ""
        is_shim = ("rpi-lgpio" in rpi_package_owners
                   and "rpi.gpio" not in rpi_package_owners)
        detail = f"module file: {source}"
        if is_shim:
            detail += "\nThis is the rpi-lgpio shim (RPi.GPIO API over the lgpio\n" \
                      "character-device backend) — correct for Ubuntu 24.04/26.04."
        else:
            detail += "\nThis appears to be the CLASSIC RPi.GPIO, which drives\n" \
                      "/dev/gpiomem directly. On Ubuntu 24.04/26.04 prefer rpi-lgpio.\n" \
                      "Never install both: they claim the same module name."
        record("PASS", "import RPi.GPIO (hw/button_handler.py's first choice)", detail)
    else:
        record("SKIP", "import RPi.GPIO unavailable", f"{rpi_exc!r}\n"
               "hw/button_handler.py falls back to lgpio, checked next.")

    if lgpio_mod is not None:
        record("PASS", "import lgpio (hw/button_handler.py's fallback)")
    else:
        record("SKIP", "import lgpio unavailable", repr(lgpio_exc))

    if rpi_gpio is None and lgpio_mod is None:
        record("FAIL", "no GPIO backend is importable",
               "hw/button_handler.py:begin() would find neither backend and the\n"
               "physical button would be dead. Install requirements/rpi.txt,\n"
               "which pulls rpi-lgpio (and lgpio with it).")

    # Detecting the forbidden double-install: two distributions both owning RPi.
    try:
        from importlib.metadata import distributions
        owners = sorted({
            dist.metadata["Name"]
            for dist in distributions()
            if (dist.metadata["Name"] or "").lower() in ("rpi.gpio", "rpi-lgpio")
        })
    except Exception:                             # noqa: BLE001
        owners = []
    if len(owners) > 1:
        record("FAIL", "BOTH RPi.GPIO and rpi-lgpio are installed",
               f"installed: {', '.join(owners)}\n"
               "They provide the same module name; which one wins is an\n"
               "installation-order accident. Uninstall the classic RPi.GPIO:\n"
               "    .venv/bin/python -m pip uninstall RPi.GPIO")
    elif owners:
        record("PASS", f"exactly one RPi.GPIO provider installed: {owners[0]}")


# ---------------------------------------------------------------------------
# Project configuration
# ---------------------------------------------------------------------------

def check_configured_addresses() -> None:
    section("Configured I2C addresses")

    config, exc = _try_import("config")
    if config is None:
        record("FAIL", "import config", repr(exc))
        return

    expected_map = {0x08: "GROVE_ADC_ADDR", 0x60: "DAC_ADDR_IR", 0x61: "DAC_ADDR_RED"}

    for addr, description in EXPECTED_ADDRESSES.items():
        name = expected_map[addr]
        value = getattr(config, name, None)
        if value == addr:
            record("PASS", f"config.{name} = {addr:#04x}", description)
        else:
            shown = f"{value:#04x}" if isinstance(value, int) else repr(value)
            record("FAIL", f"config.{name} = {shown}, expected {addr:#04x}",
                   description)

    if getattr(config, "DRY_RUN", False):
        record("FAIL", "config.DRY_RUN is True",
               "PPG_DRY_RUN is set in this shell, so the application would run\n"
               "simulated and never touch the hardware. Unset it before a real run:\n"
               "    unset PPG_DRY_RUN")
    else:
        record("PASS", "config.DRY_RUN is False — the hardware path is active")

    for name, expected in (("DAC_FULLSCALE_V", 3.28), ("ADC_VOLTAGE_REF", 3.28),
                           ("ADC_MAX_VALUE", 4095), ("ADC_CHANNEL_IR", 0),
                           ("ADC_CHANNEL_RED", 2)):
        value = getattr(config, name, None)
        if value == expected:
            record("PASS", f"config.{name} = {value}")
        else:
            record("FAIL", f"config.{name} = {value!r}, expected {expected!r}")


def main() -> int:
    print(_paint(_CYAN, "PPG simulator — Raspberry Pi 4 environment verification"))
    print(f"project root: {PROJECT_ROOT}")
    print("READ-ONLY: no DAC write, no GPIO toggle, no I2C transaction.")

    check_platform()
    check_venv()
    check_gui_modules()
    check_i2c_device()
    check_i2c_modules()
    check_grove_adc()
    check_gpio_backend()
    check_configured_addresses()

    section("Summary")
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for status, _, _ in _RESULTS:
        counts[status] += 1
    print(f"  PASS={counts['PASS']}  FAIL={counts['FAIL']}  SKIP={counts['SKIP']}")

    if counts["FAIL"]:
        print(_paint(_RED, "  Environment is NOT ready — see the FAIL lines above."))
        failed = [label for status, label, _ in _RESULTS if status == "FAIL"]
        for label in failed:
            print(f"    - {label}")
        return 1

    print(_paint(_GREEN, "  Software environment is ready."))
    print()
    print("  Next, scan the bus yourself (this script deliberately does not):")
    print("      i2cdetect -y 1")
    print("  Expect 0x08 (MM32 ADC), 0x60 (IR DAC) and 0x61 (Red DAC).")
    print()
    print(_paint(_YELLOW, "  An ACK is not analog or optical validation."))
    print("  i2cdetect only proves a chip pulled SDA low for one address byte. It")
    print("  says nothing about DAC output voltage, LM358P compliance, LED current,")
    print("  OPT101 response, or optical isolation between the Red and IR")
    print("  compartments. Those require a multimeter and an oscilloscope.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
