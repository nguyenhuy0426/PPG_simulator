#!/usr/bin/env bash
# Launcher entry point used by the Linux desktop file.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PY="${PROJECT_ROOT}/.venv/bin/python"
STATE_HOME="${XDG_STATE_HOME:-${HOME}/.local/state}"
STATE_DIR="${STATE_HOME}/ppg-simulator"
LOG_FILE="${STATE_DIR}/launcher.log"
LOCK_FILE="${STATE_DIR}/app.lock"
UNIT="ppg-simulator.service"

mkdir -p "${STATE_DIR}"

notify_error() {
    if command -v notify-send >/dev/null 2>&1; then
        notify-send --urgency=critical "PPG Simulator" "$1" >/dev/null 2>&1 || true
    fi
}

if [ ! -x "${VENV_PY}" ]; then
    message="Python environment is missing. Run scripts/setup_rpi_ubuntu.sh first."
    printf '[%s] ERROR: %s\n' "$(date --iso-8601=seconds)" "${message}" >>"${LOG_FILE}"
    notify_error "${message}"
    exit 1
fi

# Keep one GUI/BLE server per user. The lock descriptor survives exec and is
# released automatically when Python exits, including after a crash.
exec 9>"${LOCK_FILE}"
if command -v flock >/dev/null 2>&1 && ! flock -n 9; then
    notify_error "The simulator is already running."
    exit 0
fi

# An instance under systemd (the autostart service, or the transient unit of
# scripts/deploy_and_run.sh) does not hold that lock, so ask systemd as well.
# "activating" covers the wait before a crash restart, "deactivating" an
# instance that is still shutting down.
if command -v systemctl >/dev/null 2>&1; then
    active_state="$(systemctl --user show --property=ActiveState --value "${UNIT}" 2>/dev/null)"
    case "${active_state}" in
        active|activating|deactivating|reloading|refreshing)
            notify_error "The simulator is already running."
            exit 0 ;;
    esac
    # With the autostart service installed (scripts/install_user_service.sh) the
    # icon starts that service, so systemd owns the only instance and restarts it
    # after a crash. reset-failed clears an earlier start-limit hit.
    unit_state="$(systemctl --user show --property=UnitFileState --value "${UNIT}" 2>/dev/null)"
    if [ "$#" -eq 0 ] && [ -n "${unit_state}" ] && [ "${unit_state}" != transient ]; then
        printf '\n[%s] Starting %s\n' "$(date --iso-8601=seconds)" "${UNIT}" >>"${LOG_FILE}"
        systemctl --user reset-failed "${UNIT}" >/dev/null 2>&1
        if ! systemctl --user start "${UNIT}" >>"${LOG_FILE}" 2>&1; then
            notify_error "Could not start ${UNIT}. See: journalctl --user -u ${UNIT}"
            exit 1
        fi
        exit 0
    fi
fi

cd "${PROJECT_ROOT}" || exit 1
export PYTHONNOUSERSITE=1
export PYTHONUNBUFFERED=1
printf '\n[%s] Launching PPG Simulator\n' "$(date --iso-8601=seconds)" >>"${LOG_FILE}"
exec "${VENV_PY}" "${PROJECT_ROOT}/main.py" "$@" >>"${LOG_FILE}" 2>&1
