#!/usr/bin/env bash
#
# scripts/install_rpi_system_packages.sh
# -----------------------------------------------------------------------------
# FALLBACK installer for the PPG Simulator (Raspberry Pi 4).
#
# Use this ONLY if the recommended venv path (scripts/setup_rpi_venv.sh) is not
# viable — e.g. when grove.py must live in the system interpreter alongside a
# Seeed vendor install, or a venv cannot see kernel GPIO/I2C access.
#
# On PEP-668 "externally-managed" Raspberry Pi OS (Bookworm+), every pip
# install here appends  --break-system-packages  AT THE END of the command,
# and runs as the NORMAL user (installs into ~/.local, no sudo).
#
#   Rules honoured:  no 'sudo pip'   ·   no 'chmod 777'   ·   not run as root
#
# Installs ONLY the packages actually imported by the active runtime path.
# NOT installed (stale requirements.txt, not in the CustomTkinter runtime path):
# pygame, numpy, bless.
# -----------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }

PASS=0; FAIL=0; SKIP=0
mark_pass() { printf '  \033[1;32m[PASS]\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
mark_fail() { printf '  \033[1;31m[FAIL]\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
mark_skip() { printf '  \033[1;33m[SKIP]\033[0m %s\n' "$*"; SKIP=$((SKIP+1)); }

# ── Guard rails ──────────────────────────────────────────────────────────────
if [ "$(uname -s)" != "Linux" ]; then err "Linux only. Aborting."; exit 1; fi
if [ "$(id -u)" -eq 0 ]; then
  err "Do NOT run this as root. Run as the normal user so packages land in ~/.local."
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then err "python3 not found."; exit 1; fi

log "Environment"
info "OS:            $(uname -s) ($(uname -r))"
info "Architecture:  $(uname -m)"
info "Python:        $(python3 --version 2>&1)  [$(command -v python3)]"
info "User:          $(whoami)  (target: ~/.local site-packages)"

IS_PI=0
if [ -e /proc/device-tree/model ] && grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
  IS_PI=1
  info "Board:         $(tr -d '\0' < /proc/device-tree/model)"
else
  warn "Not a Raspberry Pi. Pi-only hardware wheels and hardware checks will be SKIPPED."
fi

# ── Required apt packages (same minimal, evidence-based set) ──────────────────
APT_PKGS=(python3-dev build-essential python3-tk i2c-tools)
log "System packages (apt)"
if command -v apt-get >/dev/null 2>&1; then
  MISSING=()
  for p in "${APT_PKGS[@]}"; do
    dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" || MISSING+=("$p")
  done
  if [ "${#MISSING[@]}" -eq 0 ]; then
    info "Already installed: ${APT_PKGS[*]}"
  else
    info "Installing missing: ${MISSING[*]}"
    sudo apt-get update
    sudo apt-get install -y "${MISSING[@]}"
  fi
else
  warn "apt-get not found. Ensure equivalents exist: ${APT_PKGS[*]}"
fi

# ── pip tooling upgrade (system interpreter, --break-system-packages LAST) ────
log "Upgrade pip / setuptools / wheel (system interpreter)"
python3 -m pip install --upgrade pip setuptools wheel --break-system-packages

# ── Runtime packages actually imported by the active runtime path ────────────
log "Python packages — host-portable (CustomTkinter UI)"
python3 -m pip install customtkinter --break-system-packages

if [ "$IS_PI" -eq 1 ]; then
  log "Python packages — Raspberry Pi hardware"
  python3 -m pip install "RPi.GPIO>=0.7.0" --break-system-packages
  python3 -m pip install "smbus2" --break-system-packages
  python3 -m pip install "grove.py" --break-system-packages
  python3 -m pip install "adafruit-blinka>=8.0.0" --break-system-packages
  python3 -m pip install "adafruit-circuitpython-mcp4725>=1.4.0" --break-system-packages
else
  warn "Skipping Pi-only hardware wheels (not on a Raspberry Pi)."
fi

# ── Verify imports (system python3) ──────────────────────────────────────────
log "Verification — Python imports (system python3)"

if python3 - <<'PY'
import customtkinter
print("CustomTkinter", customtkinter.__version__)
PY
then mark_pass "import customtkinter"; else mark_fail "import customtkinter"; fi

if PYTHONPATH="$PROJECT_ROOT" PPG_DRY_RUN=1 python3 - <<'PY'
import config, calibration, config_store, comm.logger
import models.ppg_model, core.signal_engine
import hw.dac_manager, hw.opt101_rx, ui.ctk_app
print("project core imports OK (dry-run; hardware libs lazy)")
PY
then mark_pass "project core imports (dry-run)"; else mark_fail "project core imports (dry-run)"; fi

if [ "$IS_PI" -eq 1 ]; then
  if PYTHONPATH="$PROJECT_ROOT" python3 - <<'PY'
import inspect, grove.adc
print("grove.adc source :", inspect.getsourcefile(grove.adc))
print("ADC.__init__     :", inspect.signature(grove.adc.ADC.__init__))
print("ADC methods      :", [m for m in ("read_raw","read_voltage","read") if hasattr(grove.adc.ADC, m)])
PY
  then mark_pass "grove.adc introspection"; else mark_fail "grove.adc introspection"; fi

  if python3 - <<'PY'
import board, busio, adafruit_mcp4725
print("MCP4725 imports OK")
PY
  then mark_pass "import board, busio, adafruit_mcp4725"; else mark_fail "import board/busio/adafruit_mcp4725"; fi

  log "Verification — I2C bus scan (i2cdetect -y 1)"
  if command -v i2cdetect >/dev/null 2>&1 && [ -e /dev/i2c-1 ]; then
    SCAN="$(i2cdetect -y 1 || true)"; printf '%s\n' "$SCAN"
    MISS=(); for a in 04 60 61; do grep -qiE "(^|[[:space:]])$a([[:space:]]|$)" <<<"$SCAN" || MISS+=("0x$a"); done
    if [ "${#MISS[@]}" -eq 0 ]; then mark_pass "i2cdetect found 0x04, 0x60, 0x61"
    else mark_fail "i2cdetect missing: ${MISS[*]}"; fi
  else
    mark_fail "i2cdetect/-dev/i2c-1 unavailable — install i2c-tools and enable I2C (raspi-config)"
  fi
else
  mark_skip "grove.adc introspection (not on Pi)"
  mark_skip "board/busio/adafruit_mcp4725 import (not on Pi)"
  mark_skip "i2cdetect -y 1 bus scan (not on Pi)"
fi

log "Summary"
info "PASS=$PASS  FAIL=$FAIL  SKIP=$SKIP"
[ "$FAIL" -gt 0 ] && { err "One or more verification steps FAILED."; exit 1; } || true
info "Fallback install complete (system interpreter, ~/.local)."
