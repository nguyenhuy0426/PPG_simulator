#!/usr/bin/env bash
#
# scripts/setup_rpi_ubuntu24.sh — set up the PPG simulator on a
# Raspberry Pi 4 running Ubuntu 24.04 or 26.04 LTS (aarch64).
#
# The filename is kept for backwards compatibility. New instructions use the
# version-neutral scripts/setup_rpi_ubuntu.sh wrapper.
#
#   ./scripts/setup_rpi_ubuntu.sh                # apt deps + venv + verify
#   ./scripts/setup_rpi_ubuntu.sh --skip-apt     # venv only (apt already done)
#   ./scripts/setup_rpi_ubuntu.sh --recreate     # delete and rebuild .venv
#   ./scripts/setup_rpi_ubuntu.sh --enable-i2c   # also edit config.txt (asks first)
#
# Run as your normal user, NOT as root. The script calls sudo only for apt and
# only for the two optional system changes it asks about first.
#
# This script does NOT: write a DAC value, toggle a GPIO, probe the I2C bus, or
# reboot. Ubuntu 24.04 walkthrough: docs/setup/RASPBERRY_PI_4_UBUNTU_24_04.md
# Ubuntu 26.04 + direct SSH: docs/setup/RASPBERRY_PI_4_UBUNTU_26_04_SSH.md
#
# Legacy Raspberry Pi OS installers were removed because they assumed a
# different Grove ADC address and GPIO backend. This is the supported path.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
BOOT_CONFIG="/boot/firmware/config.txt"
GROVE_REPO="https://github.com/Seeed-Studio/grove.py.git"

# Ubuntu may already contain useful Raspberry Pi packages in
# /usr/lib/python3/dist-packages, so this project intentionally uses a venv with
# --system-site-packages. Do not, however, inherit ~/.local packages: an old
# user-installed RPi.GPIO there can shadow Ubuntu's rpi-lgpio compatibility shim
# and make GPIO backend selection depend on sys.path order.
export PYTHONNOUSERSITE=1

SKIP_APT=0
RECREATE=0
ENABLE_I2C=0
NEEDS_REBOOT=0
NEEDS_RELOGIN=0

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
        --skip-apt)   SKIP_APT=1 ;;
        --recreate)   RECREATE=1 ;;
        --enable-i2c) ENABLE_I2C=1 ;;
        -h|--help)    usage; exit 0 ;;
        *)            die "unknown option: $1 (try --help)" ;;
    esac
    shift
done

confirm() {
    # confirm "question" -> 0 if the user typed y/Y, 1 otherwise.
    local reply
    if [ ! -t 0 ]; then
        warn "not an interactive terminal; assuming NO for: $1"
        return 1
    fi
    printf '%s' "${C_WARN}$1 [y/N] ${C_OFF}"
    read -r reply
    [ "${reply}" = "y" ] || [ "${reply}" = "Y" ]
}

# -----------------------------------------------------------------------------
# 1. Confirm the platform (guide step 1)
# -----------------------------------------------------------------------------
info "Step 1 — platform"

if [ "$(id -u)" -eq 0 ]; then
    die "do not run this as root. It would create a root-owned ${VENV_DIR} that \
your normal user cannot write to. Run it as yourself; it calls sudo where needed."
fi

[ "$(uname -s)" = "Linux" ] || die "not Linux — run this ON the Raspberry Pi"

ARCH="$(uname -m)"
if [ "${ARCH}" != "aarch64" ]; then
    die "architecture is ${ARCH}, expected aarch64. Ubuntu for the Pi 4 is \
64-bit; a 32-bit userland means the wrong image was flashed and the aarch64 \
wheels below will not install."
fi
ok "architecture: aarch64"

if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    if [ "${ID:-}" = "ubuntu" ] \
       && { [ "${VERSION_ID:-}" = "24.04" ] || [ "${VERSION_ID:-}" = "26.04" ]; }; then
        ok "distribution: ${PRETTY_NAME:-Ubuntu ${VERSION_ID}}"
        if [ "${VERSION_ID}" = "26.04" ]; then
            warn "Ubuntu 26.04 uses the newer Raspberry Pi A/B boot layout."
            warn "Before future kernel upgrades, confirm the Pi 4 boot EEPROM is"
            warn "dated 2022-11-25 or later:  sudo rpi-eeprom-update"
        fi
    else
        warn "distribution is '${PRETTY_NAME:-unknown}', not supported Ubuntu 24.04/26.04 LTS."
        warn "The apt package names and the ${BOOT_CONFIG} path below are"
        warn "Ubuntu-specific. On Raspberry Pi OS the boot config lives"
        warn "elsewhere and raspi-config manages I2C."
        confirm "Continue anyway?" || die "aborted by user"
    fi
else
    warn "/etc/os-release is unreadable — cannot confirm the distribution"
fi

if [ -r /proc/device-tree/model ]; then
    MODEL="$(tr -d '\0' < /proc/device-tree/model)"
    case "${MODEL}" in
        *"Raspberry Pi 4"*) ok "board: ${MODEL}" ;;
        *"Raspberry Pi"*)   warn "board: ${MODEL} — not a Pi 4; verify the Grove
                                  Base HAT pinout and the I2C bus number" ;;
        *)                  die "board reports '${MODEL}' — not a Raspberry Pi" ;;
    esac
else
    warn "/proc/device-tree/model absent — cannot confirm the board model"
fi

# -----------------------------------------------------------------------------
# 2. System packages
# -----------------------------------------------------------------------------
if [ "${SKIP_APT}" -eq 1 ]; then
    info "Step 2 — system packages (skipped: --skip-apt)"
else
    info "Step 2 — system packages"
    #
    # Each package below is here for a reason that traces to actual code:
    #
    #   python3-venv    creating ${VENV_DIR}. Ubuntu ships venv separately.
    #   python3-dev     headers, for any dependency without an aarch64 wheel.
    #   python3-pip     bootstraps pip inside the venv.
    #   python3-tk      the stdlib tkinter module, required by customtkinter,
    #                   which ui/ctk_app.py imports. It is an OS package, NOT
    #                   a pip package.
    #   build-essential a C toolchain for the same source-build case.
    #   git             pip installs grove.py from its git repository.
    #   i2c-tools       i2cdetect, used in guide step 7 to confirm 0x08/0x60/0x61.
    #
    # Deliberately NOT installed: libgpiod-dev and python3-libgpiod (nothing in
    # this project imports gpiod; lgpio already provides character-device
    # access), and python3-rpi.gpio (it collides with the rpi-lgpio shim
    # installed below).
    #
    APT_PACKAGES=(
        python3-venv python3-dev python3-pip python3-tk
        build-essential git i2c-tools
    )
    printf '      %s\n' "packages: ${APT_PACKAGES[*]}"
    sudo apt-get update
    sudo apt-get install -y "${APT_PACKAGES[@]}"
    ok "system packages installed"
fi

# -----------------------------------------------------------------------------
# 3. I2C enablement (guide steps 2-3)
# -----------------------------------------------------------------------------
info "Step 3 — I2C controller"

if [ -e /dev/i2c-1 ]; then
    ok "/dev/i2c-1 exists — the I2C controller is already enabled"
elif [ "${ENABLE_I2C}" -eq 1 ]; then
    [ -f "${BOOT_CONFIG}" ] || die "${BOOT_CONFIG} not found — cannot enable I2C \
automatically. Enable it by hand (guide step 2)."
    if grep -qE '^\s*dtparam=i2c_arm=on' "${BOOT_CONFIG}"; then
        ok "dtparam=i2c_arm=on is already present in ${BOOT_CONFIG}"
        warn "but /dev/i2c-1 is absent — a reboot is still pending"
        NEEDS_REBOOT=1
    else
        warn "About to append 'dtparam=i2c_arm=on' to ${BOOT_CONFIG}."
        warn "This edits the boot configuration and needs a reboot to take effect."
        if confirm "Append it now (a timestamped backup will be made)?"; then
            sudo cp -a "${BOOT_CONFIG}" "${BOOT_CONFIG}.bak.$(date +%Y%m%d%H%M%S)"
            printf 'dtparam=i2c_arm=on\n' | sudo tee -a "${BOOT_CONFIG}" >/dev/null
            ok "appended; backup written next to ${BOOT_CONFIG}"
            NEEDS_REBOOT=1
        else
            warn "skipped — /dev/i2c-1 will stay absent until you enable it"
        fi
    fi
else
    warn "/dev/i2c-1 does not exist. The I2C controller is not enabled."
    warn "Either re-run with --enable-i2c, or do it by hand:"
    warn "    sudo nano ${BOOT_CONFIG}     # add a line:  dtparam=i2c_arm=on"
    warn "    sudo reboot"
    warn "Continuing — the venv can still be built, but the hardware checks in"
    warn "verify_rpi_env.py will FAIL until this is done."
fi

# -----------------------------------------------------------------------------
# 4. User permissions, without chmod 777 (guide step 4)
# -----------------------------------------------------------------------------
info "Step 4 — I2C permissions"

if getent group i2c >/dev/null 2>&1; then
    if id -nG "${USER}" | tr ' ' '\n' | grep -qx 'i2c'; then
        ok "${USER} is already in the 'i2c' group"
    else
        if [ -e /dev/i2c-1 ] && [ -r /dev/i2c-1 ] && [ -w /dev/i2c-1 ]; then
            warn "${USER} is not in the 'i2c' group, but a device ACL currently"
            warn "grants this session read/write access to /dev/i2c-1."
        else
            warn "${USER} is not in the 'i2c' group and /dev/i2c-1 is not writable."
        fi
        warn "The correct fix is group membership — never 'chmod 777' a device"
        warn "node, which would grant every process on the system raw bus access."
        if confirm "Run 'sudo usermod -aG i2c ${USER}'?"; then
            sudo usermod -aG i2c "${USER}"
            ok "added — this takes effect at your NEXT LOGIN"
            NEEDS_RELOGIN=1
        else
            warn "skipped — run it yourself before using the hardware"
        fi
    fi
else
    warn "there is no 'i2c' group on this system (usually created by i2c-tools)."
    warn "Check who owns /dev/i2c-1 and add yourself to that group:"
    warn "    ls -l /dev/i2c-1"
fi

# -----------------------------------------------------------------------------
# 5. Virtual environment (guide step 5)
# -----------------------------------------------------------------------------
info "Step 5 — virtual environment: ${VENV_DIR}"

if [ "${RECREATE}" -eq 1 ] && [ -d "${VENV_DIR}" ]; then
    warn "--recreate: removing the existing ${VENV_DIR}"
    rm -rf "${VENV_DIR}"
fi

if [ -d "${VENV_DIR}" ]; then
    # A venv copied from the x86_64 laptop is the classic failure here.
    if [ -x "${VENV_DIR}/bin/python" ] \
       && ! "${VENV_DIR}/bin/python" -c 'import sys' >/dev/null 2>&1; then
        die "${VENV_DIR} exists but its interpreter does not run. This usually \
means it was copied from another machine (x86_64 wheels, absolute-path \
shebangs). Delete it and re-run with --recreate."
    fi
    ok "already exists, reusing it (pass --recreate to rebuild from scratch)"
else
    # --system-site-packages: lets the venv see any vendor-supplied Python
    # package already installed system-wide (a distro python3-gpiod, a
    # BSP-provided module), which cannot be reproduced by pip on aarch64.
    # PYTHONNOUSERSITE above still hides unrelated packages from ~/.local.
    # Project dependencies are installed INTO the venv and shadow system ones.
    python3 -m venv --system-site-packages "${VENV_DIR}"
    ok "created with --system-site-packages"
fi

VENV_PY="${VENV_DIR}/bin/python"
[ -x "${VENV_PY}" ] || die "${VENV_PY} is missing — venv creation failed"

# -----------------------------------------------------------------------------
# 6. Python dependencies
# -----------------------------------------------------------------------------
info "Step 6 — Python dependencies"

# Everything goes through the venv's own interpreter. Never `sudo pip`; Ubuntu
# LTS marks its system Python externally-managed (PEP 668); overriding that
# breaks apt-managed packages. PYTHONNOUSERSITE also applies to these commands.
"${VENV_PY}" -m pip install --upgrade pip setuptools wheel
"${VENV_PY}" -m pip install --upgrade -r "${PROJECT_ROOT}/requirements/rpi.txt"
ok "requirements/rpi.txt installed"

# Reject the forbidden combination before it can cause a confusing runtime bug.
if "${VENV_PY}" -m pip show RPi.GPIO >/dev/null 2>&1 \
   && "${VENV_PY}" -m pip show rpi-lgpio >/dev/null 2>&1; then
    die "both RPi.GPIO and rpi-lgpio are installed. They provide the same module \
name and which one wins is an installation-order accident. Remove the classic \
one:  ${VENV_PY} -m pip uninstall RPi.GPIO"
fi

info "Installing grove.py from the official Seeed Studio repository"
# --no-deps is required, not stylistic: grove.py's setup.py reads /proc/cpuinfo
# and, when it sees a Raspberry Pi, APPENDS RPi.GPIO and rpi_ws281x to
# install_requires. Letting pip resolve those would drag the classic RPi.GPIO
# into an environment that already has rpi-lgpio — exactly the collision
# rejected above — plus a NeoPixel driver this project never uses. The only
# grove.py dependency this project's code path needs is smbus2, already
# installed from requirements/rpi.txt.
if "${VENV_PY}" -m pip show grove.py >/dev/null 2>&1; then
    ok "grove.py is already installed"
else
    "${VENV_PY}" -m pip install --no-deps "git+${GROVE_REPO}"
    ok "grove.py installed (--no-deps)"
fi

# -----------------------------------------------------------------------------
# 7. Verify (guide step 6)
# -----------------------------------------------------------------------------
info "Step 7 — environment verification (read-only)"

# Unset PPG_DRY_RUN: on the Pi we want to confirm the REAL hardware path is
# configured. The verifier itself still writes no DAC value and toggles no GPIO.
VERIFY_STATUS=0
env -u PPG_DRY_RUN "${VENV_PY}" "${PROJECT_ROOT}/scripts/verify_rpi_env.py" \
    || VERIFY_STATUS=$?

# -----------------------------------------------------------------------------
# 8. What is left for the human
# -----------------------------------------------------------------------------
echo
if [ "${NEEDS_REBOOT}" -eq 1 ]; then
    warn "REBOOT REQUIRED before /dev/i2c-1 appears:   sudo reboot"
fi
if [ "${NEEDS_RELOGIN}" -eq 1 ]; then
    warn "LOG OUT AND BACK IN before your 'i2c' group membership takes effect."
fi

if [ "${VERIFY_STATUS}" -ne 0 ]; then
    warn "verify_rpi_env.py reported failures (exit ${VERIFY_STATUS})."
    warn "Fix them, then re-run:"
    warn "    ${VENV_PY} scripts/verify_rpi_env.py"
fi

cat <<EOF

${C_INFO}Next, by hand:${C_OFF}

  Scan the bus (this script deliberately does not transact on it):
      i2cdetect -y 1
  Expect 0x08 (Grove MM32 ADC), 0x60 (IR MCP4725), 0x61 (Red MCP4725).

  Run the test suite on the Pi as well:
      PYTHONNOUSERSITE=1 PPG_DRY_RUN=1 ${VENV_PY} -m pytest -q

${C_WARN}An I2C ACK is not analog or optical validation.${C_OFF}
i2cdetect proves only that a chip pulled SDA low for one address byte. It says
nothing about MCP4725 output voltage, LM358P input common-mode or output
headroom, LED current through the sense resistors, OPT101 response, or optical
isolation between the Red and IR compartments. The 5 V driver values in
led_driver/ remain a DESIGN HYPOTHESIS until measured with a multimeter and an
oscilloscope. See docs/superpowers/ppg_design_audit/03_LED_DRIVER_ARCHITECTURE.md
EOF

exit "${VERIFY_STATUS}"
