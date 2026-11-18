#!/usr/bin/env bash
# On the laptop that ran setup_trial.sh: the files for a Mosquitto broker on the Pi itself, reached by phones
# over Tailscale, plus the Pi's remote.json listing that broker and (optionally) a cloud broker.
#   server/pi_broker/make_bundle.sh <tailscale-dns-name> <tailscale-ip> <device> <app-user> [cloud-host [cloud-port]]
# Reuses the trial CA (a phone paired before keeps its pin) and the accounts in server/secrets/*.mqtt (the same
# user names and passwords must exist on the cloud broker). Writes only git-ignored server/secrets/pi_broker/.
# Prints where the files are, never the passwords.
set -euo pipefail
TS_NAME=${1:?tailscale dns name}; TS_IP=${2:?tailscale ip}; DEVICE=${3:?device id}; APP=${4:?app user}
CLOUD=${5:-}; CLOUD_PORT=${6:-8883}
cd "$(dirname "$0")/.."
OUT=secrets/pi_broker
umask 077
mkdir -p "$OUT"
for f in secrets/ca.key mosquitto/certs/ca.crt "secrets/$DEVICE.mqtt" "secrets/$APP.mqtt"; do
  [ -f "$f" ] || { echo "missing $f: run server/scripts/setup_trial.sh first" >&2; exit 1; }
done

cp mosquitto/certs/ca.crt "$OUT/ca.crt"
openssl req -newkey rsa:3072 -nodes -subj "/CN=$TS_NAME" -keyout "$OUT/server.key" -out "$OUT/server.csr" 2>/dev/null
printf "subjectAltName=DNS:%s,IP:%s\nextendedKeyUsage=serverAuth\n" "$TS_NAME" "$TS_IP" > "$OUT/server.ext"
openssl x509 -req -in "$OUT/server.csr" -CA mosquitto/certs/ca.crt -CAkey secrets/ca.key -CAcreateserial \
  -days 825 -extfile "$OUT/server.ext" -out "$OUT/server.crt" 2>/dev/null
cat mosquitto/certs/ca.crt >> "$OUT/server.crt"          # send the chain: the phone pins the CA
rm -f "$OUT/server.csr"

printf '%s:%s\n%s:%s\n' "$DEVICE" "$(cat "secrets/$DEVICE.mqtt")" "$APP" "$(cat "secrets/$APP.mqtt")" > "$OUT/passwd.plain"
{ cat mosquitto/acl.template
  printf '\nuser %s\ntopic write ppgsim/%s/cmd\ntopic write ppgsim/%s/client\ntopic read ppgsim/%s/#\n' \
    "$APP" "$DEVICE" "$DEVICE" "$DEVICE"; } > "$OUT/acl"
cp pi_broker/ppgsim.conf "$OUT/ppgsim.conf"

python3 - "$OUT" "$TS_NAME" "$DEVICE" "$APP" "$CLOUD" "$CLOUD_PORT" <<'PY'
import json, os, sys
out, ts_name, device, app, cloud, cloud_port = sys.argv[1:]
secret = lambda name: open(f"secrets/{name}.mqtt").read().strip()
mqtt = [{"name": "pi-broker", "host": "127.0.0.1", "port": 1883, "tls": False,
         "username": device, "password": secret(device)}]
brokers = [{"host": ts_name, "port": 8883}]
if cloud:
    mqtt.append({"name": "cloud", "host": cloud, "port": int(cloud_port), "tls": True, "ca_file": "",
                 "username": device, "password": secret(device)})
    brokers.append({"host": cloud, "port": int(cloud_port)})
remote = {"device_id": device, "mqtt": mqtt,
          "pair": {"username": app, "password": secret(app), "ca_file": "~/.config/ppg-simulator/ca.crt",
                   "brokers": brokers}}
try:
    sync = json.load(open("secrets/pi_remote.json")).get("sync")
except (OSError, ValueError):
    sync = None
if sync:
    remote["sync"] = sync
path = os.path.join(out, "remote.json")
with open(path, "w") as fh:
    json.dump(remote, fh, indent=2)
PY
chmod 600 "$OUT"/*
echo "Wrote $PWD/$OUT: server.crt (chain, SAN $TS_NAME $TS_IP), server.key, ca.crt, passwd.plain, acl, ppgsim.conf, remote.json"
echo "Next: scp -r $OUT <pi>:/tmp/ppgsim_broker && ssh -t <pi> 'bash /tmp/ppgsim_broker/configure_pi.sh'"
