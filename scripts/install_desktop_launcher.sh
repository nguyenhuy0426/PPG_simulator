#!/usr/bin/env bash
# Install the per-user GNOME application and desktop launchers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE="${PROJECT_ROOT}/packaging/linux/ppg-simulator.desktop.in"
ICON_SOURCE="${PROJECT_ROOT}/assets/icons/ppg-simulator.svg"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
APPLICATIONS_DIR="${DATA_HOME}/applications"
ICON_THEME_DIR="${DATA_HOME}/icons/hicolor"
ICON_TARGET="${ICON_THEME_DIR}/scalable/apps/ppg-simulator.svg"
APPLICATION_TARGET="${APPLICATIONS_DIR}/ppg-simulator.desktop"

if [ -n "${PPG_DESKTOP_DIR:-}" ]; then
    DESKTOP_DIR="${PPG_DESKTOP_DIR}"
elif command -v xdg-user-dir >/dev/null 2>&1; then
    DESKTOP_DIR="$(xdg-user-dir DESKTOP)"
else
    DESKTOP_DIR="${HOME}/Desktop"
fi
[ -n "${DESKTOP_DIR}" ] || DESKTOP_DIR="${HOME}/Desktop"
DESKTOP_TARGET="${DESKTOP_DIR}/ppg-simulator.desktop"

for required in "${TEMPLATE}" "${ICON_SOURCE}" "${PROJECT_ROOT}/scripts/launch_ppg_simulator.sh"; do
    [ -f "${required}" ] || { printf 'Missing required file: %s\n' "${required}" >&2; exit 1; }
done
[ -x "${PROJECT_ROOT}/.venv/bin/python" ] || {
    printf 'Missing executable %s/.venv/bin/python\n' "${PROJECT_ROOT}" >&2
    printf 'Run scripts/setup_rpi_ubuntu.sh before installing the launcher.\n' >&2
    exit 1
}

temporary="$(mktemp --suffix=.desktop "${TMPDIR:-/tmp}/ppg-simulator.XXXXXX")"
trap 'rm -f -- "${temporary}"' EXIT
escaped_root="${PROJECT_ROOT//\\/\\\\}"
escaped_root="${escaped_root//&/\\&}"
escaped_root="${escaped_root//|/\\|}"
sed "s|@PROJECT_ROOT@|${escaped_root}|g" "${TEMPLATE}" >"${temporary}"

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "${temporary}"
fi

install -Dm0644 "${ICON_SOURCE}" "${ICON_TARGET}"
install -Dm0644 "${temporary}" "${APPLICATION_TARGET}"
mkdir -p "${DESKTOP_DIR}"
install -m0755 "${temporary}" "${DESKTOP_TARGET}"

# GNOME Desktop Icons marks launchers copied to the Desktop as untrusted until
# this metadata flag is present. App-grid launchers do not need the flag.
if command -v gio >/dev/null 2>&1; then
    gio set "${DESKTOP_TARGET}" metadata::trusted true >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APPLICATIONS_DIR}" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${ICON_THEME_DIR}" >/dev/null 2>&1 || true
fi

printf 'Installed application launcher: %s\n' "${APPLICATION_TARGET}"
printf 'Installed desktop shortcut:    %s\n' "${DESKTOP_TARGET}"
printf 'Installed icon:               %s\n' "${ICON_TARGET}"
