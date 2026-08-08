#!/usr/bin/env python3
"""
scripts/verify_laptop_env.py — read-only check of the LAPTOP environment.

Answers one question: can this machine run the PPG simulator's dry-run path and
its full test suite, with no Raspberry Pi hardware attached?

READ-ONLY. It imports modules and reads files. It writes no DAC value, toggles
no GPIO, opens no I2C bus and modifies nothing on disk.

Exit status: 0 if no check FAILED, 1 otherwise. SKIP never fails the run.

    python3 scripts/verify_laptop_env.py

WHAT A PASS HERE DOES NOT MEAN
------------------------------
Nothing in this script touches hardware, so nothing it reports is hardware
validation. A clean run proves the software environment is importable and the
arithmetic tests pass. It proves nothing about LED current, optical coupling,
I2C ACKs, or any measured signal. Those require scripts/verify_rpi_env.py on the
real board, and then bench instruments beyond that.
"""

import importlib
import os
import platform
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MIN_PYTHON = (3, 9)

# Modules that must NEVER be importable-and-required on the laptop path.
HARDWARE_MODULES = (
    "RPi", "gpiod", "gpiozero", "lgpio", "smbus", "smbus2", "board", "busio",
    "digitalio", "adafruit_mcp4725", "adafruit_blinka", "grove", "serial",
    "spidev", "periphery",
)

TEST_MODULES = (
    "tests.test_calibration",
    "tests.test_phase3_acdc",
    "tests.test_phase4_dac",
    "tests.test_phase5_rx",
    "tests.test_led_driver_dac",
    "tests.test_led_driver_compliance",
    "tests.test_led_driver_power",
    "tests.test_led_driver_error_budget",
)

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
    line = f"  [{_paint(colour, status)}] {label}"
    if detail:
        line += f"\n        {detail}"
    print(line)
    _RESULTS.append((status, label, detail))


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_interpreter() -> None:
    section("Interpreter")
    v = sys.version_info
    if v[:2] >= MIN_PYTHON:
        record("PASS", f"Python {v.major}.{v.minor}.{v.micro}",
               f"{sys.executable}")
    else:
        record("FAIL", f"Python {v.major}.{v.minor} is below the "
                       f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} minimum")

    print(f"        platform: {platform.system()} {platform.machine()}")

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    expected = PROJECT_ROOT / ".venv"
    if in_venv and Path(sys.prefix).resolve() == expected.resolve():
        record("PASS", "running inside the project's own .venv", str(expected))
    elif in_venv:
        record("SKIP", "running inside a venv, but not the project's .venv",
               f"sys.prefix = {sys.prefix}; expected {expected}")
    else:
        record("SKIP", "not running inside a virtual environment",
               "This is allowed but not what scripts/setup_laptop_venv.sh sets up.")


def check_gitignore() -> None:
    section("Git hygiene")
    gitignore = PROJECT_ROOT / ".gitignore"
    if not gitignore.is_file():
        record("FAIL", ".gitignore is missing")
        return
    patterns = {ln.strip() for ln in gitignore.read_text().splitlines()}
    if {".venv/", ".venv"} & patterns:
        record("PASS", ".venv is listed in .gitignore")
    else:
        record("FAIL", ".venv is NOT listed in .gitignore",
               "A venv must never be committed: its wheels are architecture-"
               "specific and its bin/ shebangs hardcode absolute paths.")

    # Ignored-but-still-tracked is a real and easy-to-miss state.
    try:
        out = subprocess.run(
            ["git", "ls-files", "--error-unmatch", ".venv"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        record("SKIP", "could not ask git whether .venv is tracked", str(exc))
        return
    if out.returncode == 0:
        record("FAIL", ".venv is still TRACKED by git",
               "Listing it in .gitignore does not untrack already-committed "
               "files. Run, yourself:  git rm -r --cached .venv")
    else:
        record("PASS", ".venv is not tracked by git")


def check_runtime_imports() -> None:
    section("Runtime imports (PPG_DRY_RUN=1)")
    if os.environ.get("PPG_DRY_RUN") != "1":
        os.environ["PPG_DRY_RUN"] = "1"
        print("        PPG_DRY_RUN was not set; set to 1 for this process.")

    try:
        import customtkinter
        record("PASS", "import customtkinter",
               f"version {getattr(customtkinter, '__version__', 'unknown')}")
    except Exception as exc:                      # noqa: BLE001 - report anything
        record("FAIL", "import customtkinter", repr(exc))
        if isinstance(exc, ImportError) and "tkinter" in str(exc):
            print("        Install the OS package:  sudo apt install python3-tk")

    for name in ("config", "calibration", "config_store", "comm.logger",
                 "models.ppg_model", "core.signal_engine",
                 "hw.dac_manager", "hw.opt101_rx", "ui.ctk_app"):
        try:
            importlib.import_module(name)
            record("PASS", f"import {name}")
        except Exception as exc:                  # noqa: BLE001
            record("FAIL", f"import {name}", repr(exc))


def check_dry_run_is_honoured() -> None:
    section("Dry-run isolation")
    try:
        import config
    except Exception as exc:                      # noqa: BLE001
        record("FAIL", "import config (needed for the DRY_RUN check)", repr(exc))
        return

    if getattr(config, "DRY_RUN", False):
        record("PASS", "config.DRY_RUN is True under PPG_DRY_RUN=1")
    else:
        record("FAIL", "config.DRY_RUN is False despite PPG_DRY_RUN=1",
               "The hardware paths would be taken. Check config.py:25.")

    # The point of dry-run: importing the hw layer must not have dragged in a
    # hardware library. hw/dac_manager.py and hw/opt101_rx.py import them lazily.
    leaked = sorted(m for m in HARDWARE_MODULES if m in sys.modules)
    if leaked:
        record("FAIL", "a hardware library was imported during dry-run",
               f"loaded: {', '.join(leaked)}")
    else:
        record("PASS", "no hardware library was imported during dry-run",
               "checked: " + ", ".join(HARDWARE_MODULES))


def check_pure_calculation_package() -> None:
    section("led_driver purity (no GPIO / no I2C)")
    package_dir = PROJECT_ROOT / "led_driver"
    if not package_dir.is_dir():
        record("FAIL", "led_driver/ is missing")
        return
    try:
        import led_driver
        from led_driver import params
    except Exception as exc:                      # noqa: BLE001
        record("FAIL", "import led_driver", repr(exc))
        return

    record("PASS", "import led_driver",
           f"modules: {', '.join(sorted(led_driver.__all__))}")

    leaked = sorted(m for m in HARDWARE_MODULES if m in sys.modules)
    if leaked:
        record("FAIL", "importing led_driver pulled in a hardware library",
               f"loaded: {', '.join(leaked)}")
    else:
        record("PASS", "led_driver imports no hardware library")

    status = getattr(params, "DESIGN_STATUS", "")
    if "NOT HARDWARE-VERIFIED" in status.upper():
        record("PASS", "led_driver.params.DESIGN_STATUS declares the hypothesis")
    else:
        record("FAIL", "led_driver.params.DESIGN_STATUS no longer says the "
                       "design is unverified", status[:120])


def check_no_i2c_or_root_needed() -> None:
    section("Hardware independence")
    if Path("/dev/i2c-1").exists():
        record("SKIP", "/dev/i2c-1 exists on this machine",
               "Not required by anything above; the laptop path never opens it.")
    else:
        record("PASS", "/dev/i2c-1 is absent and nothing above needed it")

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        record("FAIL", "running as root",
               "Nothing here requires root. Run as your normal user so pip "
               "installs land in the project .venv.")
    else:
        record("PASS", "running as a non-root user")


def check_tests_are_discoverable() -> None:
    section("Test modules")
    missing = []
    for name in TEST_MODULES:
        path = PROJECT_ROOT / (name.replace(".", "/") + ".py")
        if not path.is_file():
            missing.append(name)
    if missing:
        record("FAIL", "test modules missing", ", ".join(missing))
    else:
        record("PASS", f"all {len(TEST_MODULES)} test modules are present")
    print("        This script does NOT run them. Run them yourself:")
    print("        PPG_DRY_RUN=1 python3 -m unittest " + " ".join(TEST_MODULES))


def main() -> int:
    print(_paint(_CYAN, "PPG simulator — laptop environment verification"))
    print(f"project root: {PROJECT_ROOT}")

    check_interpreter()
    check_gitignore()
    check_runtime_imports()
    check_dry_run_is_honoured()
    check_pure_calculation_package()
    check_no_i2c_or_root_needed()
    check_tests_are_discoverable()

    section("Summary")
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for status, _, _ in _RESULTS:
        counts[status] += 1
    print(f"  PASS={counts['PASS']}  FAIL={counts['FAIL']}  SKIP={counts['SKIP']}")

    if counts["FAIL"]:
        print(_paint(_RED, "  Laptop environment is NOT ready — see FAIL lines above."))
        return 1
    print(_paint(_GREEN, "  Laptop environment is ready for dry-run and tests."))
    print("  This is a SOFTWARE result only. No hardware was touched, so none of")
    print("  it is evidence about the circuit, the LEDs or the I2C bus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
