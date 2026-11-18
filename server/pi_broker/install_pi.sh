#!/bin/bash
# Step 1 on the Pi (Ubuntu/Raspberry Pi OS, needs sudo): Tailscale from its official apt repository and
# Mosquitto from the distribution, then the Tailscale login (a URL to open in a browser).
# Step 2 (configure_pi.sh) gives Mosquitto its TLS listener, accounts and ACL.
#   bash server/pi_broker/install_pi.sh [tailscale-hostname]
set -euo pipefail
NAME="${1:-ppg-rpi4}"
. /etc/os-release
case "$ID" in ubuntu|debian|raspbian) ;; *) echo "unsupported OS: $ID" >&2; exit 1 ;; esac
DISTRO="$ID"; [ "$DISTRO" = raspbian ] && DISTRO=debian

sudo -v                                     # ask for the sudo password once, up front
if ! command -v tailscale >/dev/null; then
  command -v curl >/dev/null || { sudo apt-get update; sudo apt-get install -y curl ca-certificates; }
  curl -fsSL "https://pkgs.tailscale.com/stable/${DISTRO}/${VERSION_CODENAME}.noarmor.gpg" \
    | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
  curl -fsSL "https://pkgs.tailscale.com/stable/${DISTRO}/${VERSION_CODENAME}.tailscale-keyring.list" \
    | sudo tee /etc/apt/sources.list.d/tailscale.list >/dev/null
  sudo apt-get update
fi
sudo apt-get install -y tailscale mosquitto mosquitto-clients
sudo systemctl enable --now tailscaled

echo
echo "== Tailscale login: open the URL below in a browser and sign in (Google, Microsoft, GitHub ...) =="
sudo tailscale up --hostname="$NAME"
echo
echo "Tailscale address of this Pi:"
tailscale ip -4
tailscale status --self --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))'
