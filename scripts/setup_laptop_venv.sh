#!/usr/bin/env bash
#
# scripts/setup_laptop_venv.sh — create the LAPTOP development environment.
#
# Creates <project>/.venv and installs only what a laptop needs to run the UI in
# dry-run mode and to run the full test suite. No Raspberry Pi hardware, no
# /dev/i2c-1, no root, no GPIO or I2C library.
#
#   ./scripts/setup_laptop_venv.sh                 # UI + tests
#   ./scripts/setup_laptop_venv.sh --with-analysis # + numpy/pandas/matplotlib
#   ./scripts/setup_laptop_venv.sh --recreate      # delete and rebuild .venv
#
# Do NOT run this on the Raspberry Pi — use scripts/setup_rpi_ubuntu24.sh there.
# Do NOT copy the resulting .venv between machines: the wheels are
# architecture-specific and the bin/ shebangs hardcode absolute paths.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"

WITH_ANALYSIS=0
RECREATE=0

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_INFO=$'\033[1;36m'; C_OK=$'\033[1;32m'; C_WARN=$'\033[1;33m'
    C_ERR=$'\033[1;31m';  C_OFF=$'\033[0m'
else
    C_INFO=''; C_OK=''; C_WARN=''; C_ERR=''; C_OFF=''
fi

info() { printf '%s\n' "${C_INFO}==> $*${C_OFF}"; }
ok()   { printf '%s\n' "${C_OK}  OK  $*${C_OFF}"; }
warn() { printf '%s\n' "${C_WARN}  !!  $*${C_OFF}" >&2; }
die()  { printf '%s\n' "${C_ERR}  ERROR  $*${C_OFF}" >&2; exit 1; }

usage() {
    # Print this file's leading comment block, minus the shebang.
    sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | grep '^#' | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --with-analysis) WITH_ANALYSIS=1 ;;
        --recreate)      RECREATE=1 ;;
        -h|--help)       usage; exit 0 ;;
        *)               die "unknown option: $1 (try --help)" ;;
    esac
    shift
done

# -----------------------------------------------------------------------------
# 0. Refuse to run as root, and refuse to run on a Raspberry Pi
# -----------------------------------------------------------------------------
info "Pre-flight checks"

if [ "$(id -u)" -eq 0 ]; then
    die "do not run this as root. A project venv belongs to your own user; \
running as root leaves root-owned files in ${VENV_DIR} that you then cannot \
write to. Re-run without sudo."
fi

# The two setup scripts install different dependency sets. Catch the mix-up.
if [ -r /proc/device-tree/model ] && grep -qi 'raspberry pi' /proc/device-tree/model 2>/dev/null; then
    warn "this looks like a Raspberry Pi ($(tr -d '\0' < /proc/device-tree/model))."
    warn "This script installs the LAPTOP dependency set, which has no I2C, no"
    warn "DAC and no GPIO support. For the Pi use:"
    warn "    scripts/setup_rpi_ubuntu24.sh"
    die  "refusing to build a laptop environment on Pi hardware."
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
command -v "${PYTHON_BIN}" >/dev/null 2>&1 || die "${PYTHON_BIN} not found on PATH"

PY_VER="$("${PYTHON_BIN}" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
"${PYTHON_BIN}" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 9) else 1)' \
    || die "Python 3.9+ required, found ${PY_VER}"
ok "python: ${PYTHON_BIN} (${PY_VER}), $(uname -s) $(uname -m)"

# venv and tkinter are OS packages on Debian/Ubuntu, not pip packages.
if ! "${PYTHON_BIN}" -c 'import venv' >/dev/null 2>&1; then
    die "the 'venv' module is missing. Install it:  sudo apt install python3-venv"
fi
if "${PYTHON_BIN}" -c 'import tkinter' >/dev/null 2>&1; then
    ok "tkinter is available (needed by customtkinter)"
else
    warn "tkinter is NOT available. customtkinter will import but the UI cannot"
    warn "open a window. The test suite does not need it. To fix:"
    warn "    sudo apt install python3-tk"
fi

# -----------------------------------------------------------------------------
# 1. Create the venv
# -----------------------------------------------------------------------------
info "Virtual environment: ${VENV_DIR}"

if [ "${RECREATE}" -eq 1 ] && [ -d "${VENV_DIR}" ]; then
    warn "--recreate: removing the existing ${VENV_DIR}"
    rm -rf "${VENV_DIR}"
fi

if [ -d "${VENV_DIR}" ]; then
    ok "already exists, reusing it (pass --recreate to rebuild from scratch)"
else
    # No --system-site-packages on the laptop: there is no Pi vendor package to
    # inherit, and isolation makes the dependency list honest.
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
    ok "created"
fi

VENV_PY="${VENV_DIR}/bin/python"
[ -x "${VENV_PY}" ] || die "${VENV_PY} is missing — venv creation failed"

# -----------------------------------------------------------------------------
# 2. Install dependencies
# -----------------------------------------------------------------------------
info "Installing dependencies"

# Every call goes through the venv's own interpreter. Never `sudo pip`, never
# `pip install --user`, never a global site-packages edit.
"${VENV_PY}" -m pip install --upgrade pip setuptools wheel

"${VENV_PY}" -m pip install -r "${PROJECT_ROOT}/requirements/test.txt"
ok "requirements/test.txt installed (UI + test dependencies)"

if [ "${WITH_ANALYSIS}" -eq 1 ]; then
    "${VENV_PY}" -m pip install -r "${PROJECT_ROOT}/requirements/analysis.txt"
    ok "requirements/analysis.txt installed (numpy, pandas, matplotlib)"
else
    printf '      %s\n' "skipped requirements/analysis.txt (pass --with-analysis to include it)"
fi

# Guard the constraint that makes this a *laptop* environment.
info "Confirming no hardware library was pulled in"
if "${VENV_PY}" - <<'PY'
import importlib.util, sys
HARDWARE = ("RPi", "gpiod", "gpiozero", "lgpio", "smbus", "smbus2", "board",
            "busio", "digitalio", "adafruit_mcp4725", "adafruit_blinka",
            "grove", "serial", "spidev", "periphery")
found = [m for m in HARDWARE if importlib.util.find_spec(m) is not None]
if found:
    print("   installed hardware modules: " + ", ".join(found))
sys.exit(1 if found else 0)
PY
then
    ok "none present — this environment cannot touch hardware even by accident"
else
    warn "hardware modules are present in this venv. That is not what"
    warn "requirements/test.txt installs; something else put them there."
fi

# -----------------------------------------------------------------------------
# 3. Verify
# -----------------------------------------------------------------------------
info "Running the environment verifier (read-only)"
PPG_DRY_RUN=1 "${VENV_PY}" "${PROJECT_ROOT}/scripts/verify_laptop_env.py"

# -----------------------------------------------------------------------------
# 4. Next steps
# -----------------------------------------------------------------------------
cat <<EOF

${C_OK}Laptop environment ready.${C_OFF}

  Activate:
      source .venv/bin/activate

  Run the full test suite (261 tests, no hardware needed):
      PPG_DRY_RUN=1 .venv/bin/python -m unittest \\
          tests.test_calibration tests.test_phase3_acdc tests.test_phase4_dac \\
          tests.test_phase5_rx tests.test_led_driver_dac \\
          tests.test_led_driver_compliance tests.test_led_driver_power \\
          tests.test_led_driver_error_budget

  Run the UI without hardware:
      PPG_DRY_RUN=1 .venv/bin/python main.py

${C_WARN}This environment proves nothing about hardware.${C_OFF} Every result it produces is
software-only: arithmetic, imports and the simulated dry-run path. LED current,
op-amp compliance, I2C ACKs and optical coupling are unverified until measured on
the real board. See docs/setup/RASPBERRY_PI_4_UBUNTU_24_04.md.
EOF
