#!/usr/bin/env bash
# Run on the LAPTOP from this repository. One command that:
#   1. checks the Pi answers over SSH (default alias: ppg-rpi4-ethernet, 10.42.0.2),
#   2. scans I2C bus 1 on the Pi and reports 0x08 / 0x60 / 0x61,
#   3. copies this checkout to the Pi (no --delete, no venvs, no .git),
#   4. makes sure Pillow (button icons) is in the Pi venv,
#   5. restarts the app on the Pi's own display as a transient user service,
#   6. starts the same UI on the laptop in --dry-run (no I2C there).
#
# Usage:  scripts/deploy_and_run.sh            # Pi + laptop
#         scripts/deploy_and_run.sh --pi-only
#         PI_HOST=ppg-rpi4 scripts/deploy_and_run.sh   # Wi-Fi alias instead
#
# An I2C ACK only proves the device answers on the bus. It does not prove DAC
# voltage, LED current, OPT101 response or optical isolation.
set -euo pipefail

PI_HOST="${PI_HOST:-ppg-rpi4-ethernet}"
PI_DIR="${PI_DIR:-final_project/PPG_simulator_raspi}"   # relative to the Pi user's home
UNIT="ppg-simulator"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_ONLY=0
[ "${1:-}" = "--pi-only" ] && PI_ONLY=1
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=6 "${PI_HOST}")

step() { printf '\n\033[1m[%s] %s\033[0m\n' "$1" "$2"; }

step 1/6 "SSH to ${PI_HOST}"
if ! "${SSH[@]}" true; then
    echo "Cannot reach ${PI_HOST}. Check the cable, 'ping -c 3 10.42.0.2' and"
    echo "docs/setup/RASPBERRY_PI_4_UBUNTU_26_04_SSH.md (key-based login is required)."
    exit 1
fi
"${SSH[@]}" 'echo "  $(hostname) · $(uname -m) · up $(uptime -p)"'

step 2/6 "I2C scan on bus 1"
if scan="$("${SSH[@]}" 'i2cdetect -y 1' 2>&1)"; then
    echo "${scan}"
    for addr in 08 60 61; do
        if printf '%s\n' "${scan}" | grep -E '^[0-7]0:' | cut -c5- | grep -qw "${addr}"; then
            echo "  0x${addr}: ACK"
        else
            echo "  0x${addr}: no answer"
        fi
    done
else
    echo "${scan}"
    echo "  i2cdetect failed (missing i2c-tools or the user is not in the 'i2c' group)."
fi

step 3/6 "Copy ${ROOT} -> ${PI_HOST}:~/${PI_DIR}"
"${SSH[@]}" "mkdir -p ~/${PI_DIR}"
rsync -a --info=stats1 \
    --exclude='.git/' --exclude='.venv/' --exclude='venv/' --exclude='.venv-ml/' \
    --exclude='.cad_venv/' --exclude='.pio/' --exclude='.pytest_cache/' \
    --exclude='.codegraph/' --exclude='.codebase-memory/' --exclude='__pycache__/' \
    --exclude='*.pyc' --exclude='dataset/' --exclude='ml/runs/' \
    "${ROOT}/" "${PI_HOST}:${PI_DIR}/"

step 4/6 "Pillow in the Pi venv"
"${SSH[@]}" "cd ~/${PI_DIR} && if .venv/bin/python -c 'import PIL.ImageTk' 2>/dev/null; then
        echo '  already installed';
    else
        .venv/bin/python -m pip install -q 'pillow>=12.0,<13' && echo '  installed' ||
        echo '  WARNING: pip failed (no internet on the Pi?); buttons will show text without icons';
    fi"

step 5/6 "Restart the app on the Pi display"
"${SSH[@]}" "bash -s" <<EOF
set -u
cd ~/${PI_DIR}
if ! systemctl --user show-environment | grep -qE '^(DISPLAY|WAYLAND_DISPLAY)='; then
    echo "  No graphical session for this user on the Pi. Log in on the Pi screen first."
    exit 3
fi
systemctl --user stop ${UNIT}.service 2>/dev/null || true
systemctl --user reset-failed ${UNIT}.service 2>/dev/null || true
# An instance started from the desktop icon would fight over I2C and BLE.
# SIGTERM takes the app's own shutdown path, which parks both DACs at 0 V.
if pkill -TERM -f "\$PWD/.venv/bin/python.* main.py|\$PWD/main.py" 2>/dev/null; then
    echo "  stopped a running instance"; sleep 3
fi
systemd-run --user --unit=${UNIT} --collect --same-dir \
    -E PYTHONNOUSERSITE=1 -E PYTHONUNBUFFERED=1 \
    "\$PWD/.venv/bin/python" "\$PWD/main.py" >/dev/null
sleep 8
state=\$(systemctl --user is-active ${UNIT}.service || true)
echo "  service: \${state}"
journalctl --user -u ${UNIT}.service -n 25 --no-pager -o cat || true
[ "\${state}" = active ]
EOF

if [ "${PI_ONLY}" = 1 ]; then
    exit 0
fi

step 6/6 "Start the UI on the laptop (dry run: no I2C on this machine)"
cd "${ROOT}"
if [ ! -x .venv/bin/python ]; then
    echo "  No .venv here. Run scripts/setup_laptop_venv.sh once, then re-run this script."
    exit 1
fi
.venv/bin/python -c 'import PIL.ImageTk' 2>/dev/null || .venv/bin/python -m pip install -q 'pillow>=12.0,<13'
LOG="${XDG_STATE_HOME:-${HOME}/.local/state}/ppg-simulator/laptop.log"
mkdir -p "$(dirname "${LOG}")"
PYTHONNOUSERSITE=1 nohup .venv/bin/python main.py --dry-run --no-ble >"${LOG}" 2>&1 &
echo "  laptop UI started (pid $!), log: ${LOG}"
