#!/usr/bin/env bash
#
# scripts/setup_rpi_venv.sh
# -----------------------------------------------------------------------------
# RECOMMENDED installation path for the PPG Simulator on a Raspberry Pi 4.
#
# Creates an ISOLATED Python virtual environment at <project>/.venv and installs
# ONLY the packages actually imported by the live runtime path
#   (main.py -> ui.ctk_app / core.signal_engine / hw.dac_manager / hw.opt101_rx).
#
# Deliberately NOT installed (stale requirements.txt entries not in the active
# CustomTkinter runtime path): pygame, numpy, bless.
#
# For the system-Python fallback (PEP-668 externally-managed), use instead:
#   scripts/install_rpi_system_packages.sh
#
# Safe to run on a non-Pi dev machine: it will create the venv, install
# CustomTkinter, and SKIP the Pi-only hardware wheels / hardware verification
# (those are honestly reported as skipped, never faked).
# -----------------------------------------------------------------------------
set -euo pipefail

# ── Resolve project root from this script's own location (robust to CWD) ──────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }

PASS=0; FAIL=0; SKIP=0
mark_pass() { printf '  \033[1;32m[PASS]\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
mark_fail() { printf '  \033[1;31m[FAIL]\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
mark_skip() { printf '  \033[1;33m[SKIP]\033[0m %s\n' "$*"; SKIP=$((SKIP+1)); }

# ── 2. Platform / interpreter verification ───────────────────────────────────
log "Environment"
OS="$(uname -s)"
ARCH="$(uname -m)"
if [ "$OS" != "Linux" ]; then
  err "This script targets Linux (Raspberry Pi OS). Detected: $OS. Aborting."
  exit 1
fi
info "OS:            $OS ($(uname -r))"
info "Architecture:  $ARCH"
if ! command -v python3 >/dev/null 2>&1; then
  err "python3 not found on PATH. Install Python 3 first."
  exit 1
fi
info "Python:        $(python3 --version 2>&1)  [$(command -v python3)]"
info "Project root:  $PROJECT_ROOT"

IS_PI=0
if [ -e /proc/device-tree/model ] && grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
  IS_PI=1
  info "Board:         $(tr -d '\0' < /proc/device-tree/model)"
else
  warn "Not a Raspberry Pi (arch=$ARCH). Pi-only hardware wheels (RPi.GPIO, grove.py,"
  warn "Adafruit Blinka, MCP4725) and hardware import / i2cdetect checks will be SKIPPED."
  warn "CustomTkinter + project core imports are still installed and verified."
fi

# ── 3. Required apt packages (minimal, evidence-based) ───────────────────────
#   python3-venv     : create the venv (step 4)
#   python3-dev +    : compile the RPi.GPIO C extension and native Blinka deps
#     build-essential
#   python3-tk       : Tk backend required by CustomTkinter (ui/ctk_app.py imports tkinter)
#   i2c-tools        : provides i2cdetect for the 0x04/0x60/0x61 bus-scan verification
APT_PKGS=(python3-venv python3-dev build-essential python3-tk i2c-tools)
log "System packages (apt)"
if command -v apt-get >/dev/null 2>&1; then
  MISSING=()
  for p in "${APT_PKGS[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed"; then
      MISSING+=("$p")
    fi
  done
  if [ "${#MISSING[@]}" -eq 0 ]; then
    info "Already installed: ${APT_PKGS[*]}"
  else
    info "Installing missing: ${MISSING[*]}"
    sudo apt-get update
    sudo apt-get install -y "${MISSING[@]}"
  fi
else
  warn "apt-get not found (non-Debian host). Ensure equivalents exist: ${APT_PKGS[*]}"
fi

# ── 4/5. Create & activate the venv ──────────────────────────────────────────
# A venv copied from another machine/path is NOT reusable: its bin/pip shebang
# and bin/activate hardcode the ORIGINAL absolute path. (The .venv shipped in
# this repo was built at /home/halovie/.../BioSignalSimulatorPro/.venv — its
# bin/pip points at a python that does not exist here.) Detect that and rebuild.
venv_is_healthy() {
  [ -x "$VENV_DIR/bin/python" ] || return 1
  local pfx
  pfx="$("$VENV_DIR/bin/python" -c 'import sys; print(sys.prefix)' 2>/dev/null)" || return 1
  [ "$pfx" = "$VENV_DIR" ] || return 1                         # sys.prefix must be this dir
  head -1 "$VENV_DIR/bin/pip" 2>/dev/null | grep -q "$VENV_DIR" || return 1  # pip shebang local
  return 0
}
log "Virtual environment"
if venv_is_healthy; then
  info "Reusing healthy venv:  $VENV_DIR"
else
  if [ -d "$VENV_DIR" ]; then
    warn "Existing '$VENV_DIR' is missing or RELOCATED (foreign internal paths) — rebuilding with --clear."
    python3 -m venv --clear "$VENV_DIR"
  else
    info "Creating venv:         $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
fi
# Activate (step 5). Guard against `set -u` inside older activate scripts.
set +u
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
set -u
info "Activated:     VIRTUAL_ENV=${VIRTUAL_ENV}"
info "venv python:   $(python --version 2>&1)  [$(command -v python)]"

# ── 6. Upgrade pip / setuptools / wheel (inside the venv, no --break-system) ──
log "Upgrade pip / setuptools / wheel"
python -m pip install --upgrade pip setuptools wheel

# ── 7. Runtime packages actually imported by the active runtime path ─────────
# host-portable first (works on Pi and dev machines):
log "Python packages — host-portable (CustomTkinter UI)"
python -m pip install "customtkinter"

if [ "$IS_PI" -eq 1 ]; then
  # Floors mirror the project's requirements.txt where it specifies one.
  # grove.py / smbus2 / customtkinter are left UNPINNED (no verified pin evidence).
  # NOTE (Bookworm): classic RPi.GPIO may need the 'rpi-lgpio' shim; grove.i2c
  # only reads GPIO.RPI_REVISION, so the pip wheel is normally sufficient —
  # confirm at import verification below.
  log "Python packages — Raspberry Pi hardware"
  python -m pip install \
    "RPi.GPIO>=0.7.0" \
    "smbus2" \
    "grove.py" \
    "adafruit-blinka>=8.0.0" \
    "adafruit-circuitpython-mcp4725>=1.4.0"
else
  warn "Skipping Pi-only hardware wheels (not on a Raspberry Pi)."
fi

# ── 11. Verify imports (never assume — actually import) ──────────────────────
log "Verification — Python imports"

# CustomTkinter (host-portable)
if python - <<'PY'
import customtkinter
print("CustomTkinter", customtkinter.__version__)
PY
then mark_pass "import customtkinter"; else mark_fail "import customtkinter"; fi

# Project core imports (dry-run: hardware libs are lazy, so this must pass anywhere)
if PYTHONPATH="$PROJECT_ROOT" PPG_DRY_RUN=1 python - <<'PY'
import config, calibration, config_store, comm.logger
import models.ppg_model, core.signal_engine
import hw.dac_manager, hw.opt101_rx, ui.ctk_app
print("project core imports OK (dry-run; hardware libs lazy)")
PY
then mark_pass "project core imports (dry-run)"; else mark_fail "project core imports (dry-run)"; fi

if [ "$IS_PI" -eq 1 ]; then
  # grove.adc — record the ACTUAL installed API (source path, ctor, methods,
  # default address, and whether it still calls sys.exit on I2C failure).
  if PYTHONPATH="$PROJECT_ROOT" python - <<'PY'
import inspect, grove.adc
src = inspect.getsourcefile(grove.adc)
ADC = grove.adc.ADC
print("grove.adc source :", src)
print("ADC.__init__     :", inspect.signature(ADC.__init__))
methods = [m for m in ("read_raw", "read_voltage", "read") if hasattr(ADC, m)]
print("ADC methods      :", methods)
try:
    a = grove.adc.ADC()
    print("ADC default addr : 0x%02X" % getattr(a, "address", -1))
except Exception as e:
    print("ADC() default-addr probe raised:", repr(e))
with open(src) as f:
    body = f.read()
print("uses sys.exit()  :", "sys.exit" in body)
print("read_raw target  :", "0x10+channel" if "0x10" in body else "see source")
PY
  then mark_pass "grove.adc installed-API introspection"; else mark_fail "grove.adc introspection"; fi

  # MCP4725 stack (Blinka board/busio + driver)
  if python - <<'PY'
import board, busio, adafruit_mcp4725
print("MCP4725 imports OK")
PY
  then mark_pass "import board, busio, adafruit_mcp4725"; else mark_fail "import board/busio/adafruit_mcp4725"; fi

  # I2C bus scan — expect 0x04 (Grove ADC), 0x60 (MCP4725 IR), 0x61 (MCP4725 Red)
  log "Verification — I2C bus scan (i2cdetect -y 1)"
  if command -v i2cdetect >/dev/null 2>&1; then
    if [ -e /dev/i2c-1 ]; then
      SCAN="$(i2cdetect -y 1 || true)"
      printf '%s\n' "$SCAN"
      MISS=()
      for addr in 04 60 61; do
        grep -qiE "(^|[[:space:]])$addr([[:space:]]|$)" <<<"$SCAN" || MISS+=("0x$addr")
      done
      if [ "${#MISS[@]}" -eq 0 ]; then
        mark_pass "i2cdetect found 0x04, 0x60, 0x61"
      else
        mark_fail "i2cdetect missing: ${MISS[*]} (check wiring / addresses / I2C enabled)"
      fi
    else
      mark_fail "/dev/i2c-1 absent — enable I2C: sudo raspi-config nonint do_i2c 0 (then reboot)"
    fi
  else
    mark_fail "i2cdetect not found (install i2c-tools)"
  fi

  # Non-fatal hardware-access advisory (no auto-modification of boot config / groups)
  if ! id -nG "$(whoami)" | tr ' ' '\n' | grep -qx i2c; then
    warn "User '$(whoami)' is not in the 'i2c' group. For non-root I2C access run:"
    warn "  sudo usermod -aG i2c $(whoami)   # then log out/in"
  fi
else
  mark_skip "grove.adc introspection (not on Pi)"
  mark_skip "board/busio/adafruit_mcp4725 import (not on Pi)"
  mark_skip "i2cdetect -y 1 bus scan (not on Pi)"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
log "Summary"
info "venv:  $VENV_DIR"
info "PASS=$PASS  FAIL=$FAIL  SKIP=$SKIP"
if [ "$FAIL" -gt 0 ]; then
  err "One or more verification steps FAILED — see above."
  exit 1
fi
info "Setup complete. Activate with:  source \"$VENV_DIR/bin/activate\""
