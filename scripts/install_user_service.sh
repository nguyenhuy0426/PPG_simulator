#!/usr/bin/env bash
# Install, or remove, the systemd user service that starts the PPG simulator with
# the Pi's desktop session and restarts it after a crash. Run it on the Pi as the
# desktop user who is in the 'i2c' group, never with sudo.
#
# Usage:  scripts/install_user_service.sh              # install + enable: starts at the next login
#         scripts/install_user_service.sh --now        # ... and (re)start it in the running session
#         scripts/install_user_service.sh --uninstall  # stop (DACs parked at 0 V), disable, remove
#
# PPG_UNIT_DIR overrides the unit directory (default: ~/.config/systemd/user).
# The unit holds this checkout's absolute path: re-run the script after moving the
# checkout or after changing packaging/linux/ppg-simulator.service.in.

set -euo pipefail

UNIT="ppg-simulator.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE="${PROJECT_ROOT}/packaging/linux/ppg-simulator.service.in"
UNIT_DIR="${PPG_UNIT_DIR:-${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user}"
UNIT_PATH="${UNIT_DIR}/${UNIT}"
GDM_CONFIG="/etc/gdm3/custom.conf"
# Seconds an instance outside systemd gets for its SIGTERM shutdown; matches the
# unit's TimeoutStopSec.
STOP_WAIT_S=30

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
usage() { printf 'Usage: %s [--now | --uninstall]\n' "$(basename "$0")"; }

mode=install
start_now=0
for argument in "$@"; do
    case "${argument}" in
        --now) start_now=1 ;;
        --uninstall) mode=uninstall ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done

[ "$(id -u)" -ne 0 ] || die "run this as the desktop user, not as root: the simulator must not run as root"
command -v systemctl >/dev/null 2>&1 || die "systemctl not found"
systemctl --user show-environment >/dev/null 2>&1 ||
    die "no systemd user manager for $(id -un); run this in a login session (the Pi's terminal or SSH), not through sudo or su"

unit_file_state() { systemctl --user show --property=UnitFileState --value "${UNIT}" 2>/dev/null || true; }

if [ "${mode}" = uninstall ]; then
    if [ ! -e "${UNIT_PATH}" ]; then
        printf 'Nothing to remove: %s does not exist.\n' "${UNIT_PATH}"
        exit 0
    fi
    # Stopping sends SIGTERM; main.py parks both DACs at 0 V before it exits.
    systemctl --user disable --now "${UNIT}"
    rm -f -- "${UNIT_PATH}"
    systemctl --user daemon-reload
    systemctl --user reset-failed "${UNIT}" >/dev/null 2>&1 || true
    printf 'Removed %s\n' "${UNIT_PATH}"
    if [ -d "${UNIT_PATH}.d" ]; then
        printf 'Kept local overrides in %s; delete them if they are no longer wanted.\n' "${UNIT_PATH}.d"
    fi
    exit 0
fi

[ -f "${TEMPLATE}" ] || die "missing ${TEMPLATE}"
[ -x "${PROJECT_ROOT}/.venv/bin/python" ] ||
    die "missing ${PROJECT_ROOT}/.venv/bin/python; run scripts/setup_rpi_ubuntu24.sh first"
# The path goes unquoted into ExecStart= and into a pgrep pattern below.
case "${PROJECT_ROOT}" in
    *[!A-Za-z0-9._/@-]*)
        die "the checkout path '${PROJECT_ROOT}' contains characters a unit file cannot hold unquoted; move it to a plain path such as ~/final_project/PPG_simulator_raspi" ;;
esac

work="$(mktemp -d "${TMPDIR:-/tmp}/ppg-simulator-unit.XXXXXX")"
trap 'rm -rf -- "${work}"' EXIT
sed "s|@PROJECT_ROOT@|${PROJECT_ROOT}|g" "${TEMPLATE}" >"${work}/${UNIT}"
if command -v systemd-analyze >/dev/null 2>&1; then
    systemd-analyze --user verify "${work}/${UNIT}"
fi

# scripts/deploy_and_run.sh starts the app as a transient unit of the same name,
# and systemd will not enable a name that a transient unit holds. Stop it and
# bring the app back under the installed unit.
if [ "$(unit_file_state)" = transient ]; then
    printf 'Stopping the instance that scripts/deploy_and_run.sh started (DACs parked at 0 V)...\n'
    systemctl --user stop "${UNIT}"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        [ "$(unit_file_state)" = transient ] || break
        sleep 0.5
    done
    start_now=1
fi

mkdir -p "${UNIT_DIR}"
install -m0644 "${work}/${UNIT}" "${UNIT_PATH}"
systemctl --user daemon-reload
systemctl --user enable "${UNIT}"
printf 'Installed and enabled %s\n' "${UNIT_PATH}"

if ! id -nG | tr ' ' '\n' | grep -qx i2c; then
    printf 'WARNING: %s is not in the i2c group, so the DACs and the ADC will not open (setup guide step 4).\n' \
        "$(id -un)" >&2
fi
if [ -r "${GDM_CONFIG}" ] && ! {
        grep -Eiq '^[[:space:]]*AutomaticLoginEnable[[:space:]]*=[[:space:]]*(true|1)[[:space:]]*$' "${GDM_CONFIG}" &&
        grep -Eq "^[[:space:]]*AutomaticLogin[[:space:]]*=[[:space:]]*$(id -un)[[:space:]]*\$" "${GDM_CONFIG}"
    }; then
    printf 'NOTE: GDM automatic login is not set for %s, so after a reboot the simulator starts only once\n' "$(id -un)"
    printf '      someone logs in on the Pi screen (setup guide section 11).\n'
fi

if [ "${start_now}" != 1 ]; then
    if systemctl --user is-active --quiet "${UNIT}"; then
        printf 'The running instance keeps its old settings until restarted: re-run with --now.\n'
    else
        printf 'It starts with the next desktop login; re-run with --now to start it in this session.\n'
    fi
    exit 0
fi

if ! systemctl --user is-active --quiet graphical-session.target; then
    printf 'No desktop session is running for %s; the service starts with the next login.\n' "$(id -un)"
    exit 0
fi
systemctl --user stop "${UNIT}"
# An instance started from the desktop icon or by hand would fight over I2C and
# BLE. SIGTERM takes the app's own shutdown path, which parks both DACs at 0 V.
# Anchored on a python executable, so an editor open on main.py is left alone.
pattern='^[^ ]*python[0-9.]* '"${PROJECT_ROOT}"'/main\.py( |$)'
if pkill -TERM -u "$(id -u)" -f "${pattern}"; then
    printf 'Stopping the instance that runs outside systemd...\n'
    for _ in $(seq "${STOP_WAIT_S}"); do
        pgrep -u "$(id -u)" -f "${pattern}" >/dev/null || break
        sleep 1
    done
    if pgrep -u "$(id -u)" -f "${pattern}" >/dev/null; then
        die "an instance outside systemd did not exit within ${STOP_WAIT_S} s; close it and re-run with --now"
    fi
fi
systemctl --user reset-failed "${UNIT}" >/dev/null 2>&1 || true
systemctl --user start "${UNIT}"
printf 'Started %s. Logs: journalctl --user -u %s -f\n' "${UNIT}" "${UNIT%.service}"
