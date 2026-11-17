#!/usr/bin/env bash
# Create the secrets of the trial stack and the Pi's remote.json, then start it.
#   server/scripts/setup_trial.sh <server-ip-or-host> <pi-device-id> <app-user>
# Writes only git-ignored files: server/.env, server/secrets/*, server/mosquitto/{passwd,certs}.
# Prints where the credentials are, never the credentials themselves.
set -euo pipefail
HOST=${1:?server ip or host name}; DEVICE=${2:?pi device id}; APP=${3:?app user name}
cd "$(dirname "$0")/.."
IMAGE=eclipse-mosquitto:2.0.20
umask 077
mkdir -p secrets mosquitto/certs mosquitto/data
rand() { openssl rand -base64 32 | tr -d '/+=' | cut -c1-32; }

[ -f .env ] || echo "POSTGRES_PASSWORD=$(rand)" > .env

# TLS: a private CA for the trial (a public server would use a Let's Encrypt certificate instead).
if [ ! -f mosquitto/certs/server.crt ]; then
  openssl req -x509 -newkey rsa:3072 -days 825 -nodes -subj "/CN=ppgsim trial CA" \
    -keyout secrets/ca.key -out mosquitto/certs/ca.crt 2>/dev/null
  if [[ $HOST =~ ^[0-9.]+$ ]]; then SAN="IP:$HOST"; else SAN="DNS:$HOST"; fi
  openssl req -newkey rsa:3072 -nodes -subj "/CN=$HOST" -keyout mosquitto/certs/server.key \
    -out secrets/server.csr 2>/dev/null
  printf "subjectAltName=%s\nextendedKeyUsage=serverAuth\n" "$SAN" > secrets/server.ext
  openssl x509 -req -in secrets/server.csr -CA mosquitto/certs/ca.crt -CAkey secrets/ca.key \
    -CAcreateserial -days 825 -extfile secrets/server.ext -out mosquitto/certs/server.crt 2>/dev/null
  # Send the chain (server + CA): a phone paired by QR pins the CA by its fingerprint.
  cat mosquitto/certs/ca.crt >> mosquitto/certs/server.crt
fi
# The broker runs as uid 1883 and reads these through a read-only mount.
chmod 755 mosquitto/certs; chmod 644 mosquitto/certs/*

touch mosquitto/passwd
[ -f mosquitto/acl ] || cp mosquitto/acl.template mosquitto/acl   # the live ACL is git-ignored
add_user() {   # add_user <name> -> password in secrets/<name>.mqtt
  local pass; pass=$(rand); printf '%s' "$pass" > "secrets/$1.mqtt"
  docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/mosquitto:/m" $IMAGE \
    mosquitto_passwd -b /m/passwd "$1" "$pass"
}
grep -q "^$DEVICE:" mosquitto/passwd || add_user "$DEVICE"
grep -q "^$APP:" mosquitto/passwd || add_user "$APP"
chmod 644 mosquitto/passwd
if ! grep -q "^user $APP\$" mosquitto/acl; then
  printf '\nuser %s\ntopic write ppgsim/%s/cmd\ntopic write ppgsim/%s/client\ntopic read ppgsim/%s/#\n' \
    "$APP" "$DEVICE" "$DEVICE" "$DEVICE" >> mosquitto/acl
fi

# Upload token: the server keeps only its sha256.
if [ ! -f "secrets/$DEVICE.token" ]; then rand > "secrets/$DEVICE.token"; fi
python3 - "$DEVICE" <<'PY'
import hashlib, json, os, sys
device = sys.argv[1]
path = "secrets/api_tokens.json"
tokens = json.load(open(path)) if os.path.exists(path) else {}
tokens[device] = hashlib.sha256(open(f"secrets/{device}.token").read().strip().encode()).hexdigest()
json.dump(tokens, open(path, "w"), indent=1)
PY
chmod 644 secrets/api_tokens.json   # read by the API container user

# The Pi's ~/.config/ppg-simulator/remote.json (copy it with scp, then chmod 600 on the Pi).
python3 - "$HOST" "$DEVICE" "$APP" <<'PY'
import json, sys
host, device, app = sys.argv[1:]
cfg = {"device_id": device,
       "mqtt": {"host": host, "port": 8883, "tls": True, "ca_file": "~/.config/ppg-simulator/ca.crt",
                "username": device, "password": open(f"secrets/{device}.mqtt").read()},
       "sync": {"url": f"http://{host}:8000", "token": open(f"secrets/{device}.token").read().strip()},
       # The phone account shown in the Pi's pairing QR (comm/pairing.py).
       "pair": {"username": app, "password": open(f"secrets/{app}.mqtt").read()}}
json.dump(cfg, open("secrets/pi_remote.json", "w"), indent=1)
PY
if docker compose version >/dev/null 2>&1; then
  docker compose up -d --build
else
  bash scripts/run_without_compose.sh   # same three services with plain docker run
fi
echo "Stack started. Pi settings: server/secrets/pi_remote.json (+ server/mosquitto/certs/ca.crt);"
echo "app account '$APP': password in server/secrets/$APP.mqtt"
