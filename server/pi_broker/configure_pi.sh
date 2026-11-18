#!/bin/bash
# Step 2 on the Pi (needs sudo), from the directory make_bundle.sh produced (copied to the Pi):
#   bash /tmp/ppgsim_broker/configure_pi.sh
# Installs the broker certificate, accounts, ACL and listeners into /etc/mosquitto, restarts Mosquitto, and puts
# remote.json + ca.crt into ~/.config/ppg-simulator/ (the previous remote.json is kept as remote.json.bak-<time>).
set -euo pipefail
SRC=$(cd "$(dirname "$0")" && pwd)
for f in server.crt server.key ca.crt passwd.plain acl ppgsim.conf remote.json; do
  [ -f "$SRC/$f" ] || { echo "missing $SRC/$f" >&2; exit 1; }
done
sudo -v
sudo install -d -m 750 -o mosquitto -g mosquitto /etc/mosquitto/ppgsim
sudo install -m 644 -o mosquitto -g mosquitto "$SRC/server.crt" /etc/mosquitto/ppgsim/server.crt
sudo install -m 600 -o mosquitto -g mosquitto "$SRC/server.key" /etc/mosquitto/ppgsim/server.key
sudo install -m 600 -o mosquitto -g mosquitto "$SRC/acl" /etc/mosquitto/ppgsim/acl
sudo install -m 600 -o mosquitto -g mosquitto "$SRC/passwd.plain" /etc/mosquitto/ppgsim/passwd
sudo mosquitto_passwd -U /etc/mosquitto/ppgsim/passwd       # hash the passwords in place
sudo chown mosquitto:mosquitto /etc/mosquitto/ppgsim/passwd && sudo chmod 600 /etc/mosquitto/ppgsim/passwd
sudo install -m 644 "$SRC/ppgsim.conf" /etc/mosquitto/conf.d/ppgsim.conf
sudo systemctl enable mosquitto >/dev/null
sudo systemctl restart mosquitto
sleep 1
systemctl is-active mosquitto
sudo ss -ltnp | grep -E ':(1883|8883) ' || true

CONF=~/.config/ppg-simulator
mkdir -p "$CONF" && chmod 700 "$CONF"
[ -f "$CONF/remote.json" ] && cp -p "$CONF/remote.json" "$CONF/remote.json.bak-$(date +%Y%m%d%H%M%S)"
install -m 600 "$SRC/remote.json" "$CONF/remote.json"
install -m 644 "$SRC/ca.crt" "$CONF/ca.crt"
shred -u "$SRC/passwd.plain" "$SRC/server.key" "$SRC/remote.json" 2>/dev/null || rm -f "$SRC/passwd.plain" "$SRC/server.key" "$SRC/remote.json"
echo "Broker configured; restart the simulator app to use $CONF/remote.json"
