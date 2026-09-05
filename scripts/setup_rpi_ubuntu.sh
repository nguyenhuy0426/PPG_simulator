#!/usr/bin/env bash
# Canonical Raspberry Pi 4 setup entry point for Ubuntu 24.04/26.04 LTS.
# The implementation remains in the legacy-named script so existing commands
# and documentation do not break.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/setup_rpi_ubuntu24.sh" "$@"
