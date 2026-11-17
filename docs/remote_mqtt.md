# Remote control over MQTT and recordings in a database (trial)

Branch `feature/mqtt-remote-db`. Bluetooth (docs/ble_protocol.md) is unchanged; this adds a second link
for control from anywhere, and a copy of every recording in PostgreSQL.

```
Phone app ──MQTT/TLS 8883──► Mosquitto ◄──MQTT/TLS── Pi 4 (main.py)
                                                       │ dataset/*.csv  (primary copy, written first)
                                                       └─HTTP(S) PUT──► recordings API ──► PostgreSQL
```

The Pi only connects out; it never listens on the internet. Signal generation and the DACs stay on the Pi,
so network delay never changes the output waveform, only how fast a setpoint arrives.

## Connecting a phone (quickest path)

1. On the Pi: **Phone** on the left menu shows a QR code (`ui/pair_dialog.py`, `comm/pairing.py`).
2. In the app: connect icon → **Scan the Pi's QR code**. The phone saves the Pi and connects at once:
   over the internet when the Pi has a broker set up, otherwise straight to its Bluetooth address (no scan list).
3. Next time the app opens it reconnects by itself to the link that last worked. **Disconnect** turns that
   off until the next connection. The connect menu also offers **Connect to <Pi>** as a single tap.

The code is `ppgsim://pair?v=1&n=<BLE name>&a=<BLE address>&d=<device>&h=<host>&p=<port>&t=1&u=<app user>&k=<app
password>&f=<CA sha256>`. It carries the phone account from the `"pair"` section of `remote.json`, never the
Pi's own broker password. Anyone who can see the Pi screen can pair, as with a Wi-Fi QR; the broker ACL keeps
that account to this Pi's topics. With a private CA the phone pins it by fingerprint: the broker sends its
chain (server + CA, `setup_trial.sh` builds it), the CA whose SHA-256 matches becomes the only trust anchor and
the chain is validated against it; the host name is checked as usual. Without `f` the system CAs apply.

Bluetooth without the QR: the scan list connects by itself when exactly one simulator answers within 1.5 s.

`"pair"` in `remote.json`: `{"username": "phone1", "password": "…", "host": "<optional public host>",
"port": 8883}`. The QR needs `qrcode` (`requirements/remote.txt`).

## MQTT topics (`comm/mqtt_remote.py`)

| Topic | Direction | QoS | Payload |
|---|---|---|---|
| `ppgsim/<id>/cmd` | app → Pi | 1 | the BLE command JSON (v2/v3), plus `cid` so a redelivered copy is applied once |
| `ppgsim/<id>/client` | app → Pi | 0 | presence ping every 5 s; the Pi streams only for 15 s after the last ping |
| `ppgsim/<id>/status` | Pi → app | 1, retained | the BLE STATUS JSON (5 Hz while an app watches, on change otherwise) |
| `ppgsim/<id>/online` | Pi → app | 1, retained | `1`, or `0` (also the broker's last will) |
| `ppgsim/<id>/stream` | Pi → app | 0 | `T<ir>,<red>;…\|R<ir>,<red>;…` mV, ~10 messages/s |
| `ppgsim/<id>/ui` | Pi → app | 0 | one page-state part per message (the BLE UI parts, up to 4 KB) |

Commands from MQTT go through the same `BLECommandHandler` as Bluetooth writes (same limits, same page
requests through `ui/remote.py`). The status echo uses the same `origin` grace rule. Use one link at a time
per phone; the app switches between them.

The Recordings page sends one more part, `{"k":"sy","s":"sspe"}`: the database state of each listed file in
list order (`s` synced, `p` pending, `e` error). Both apps show it as `✓ DB`, `… DB`, `✗ DB`.

## Recording upload (`comm/record_sync.py`)

Finished files in `dataset/` (not `temp_recording.csv`, not changed in the last 2 s) enter an outbox
(`dataset/.sync/outbox.sqlite3`) and are sent once with
`PUT /api/v1/recordings/<uuid>?name=…`, `Authorization: Bearer <token>`, `X-Content-SHA256`. The uuid is
derived from device, name and sha256, so a retry is idempotent; a file is "synced" only when the server
returns the same sha256. Network errors back off from 5 s to 5 min; a rejected token waits 10 min.
A recording saved again under the same name is a new version.

## Settings on the Pi

`~/.config/ppg-simulator/remote.json`, mode 600 (the app warns if others can read it):

```json
{"device_id": "pi4-lab1",
 "mqtt": {"host": "broker.example.org", "port": 8883, "tls": true, "ca_file": "",
          "username": "pi4-lab1", "password": "…"},
 "sync": {"url": "https://api.example.org", "token": "…"}}
```

`ca_file` empty means the system CA store (a broker with a public certificate). Environment variables
`PPG_MQTT_*`, `PPG_SYNC_*`, `PPG_DEVICE_ID` override single values. Without the file both links stay off;
`--no-remote` turns them off. Install the client: `.venv/bin/python -m pip install -r requirements/remote.txt`.

## Trial server (`server/`)

```bash
server/scripts/setup_trial.sh <server-ip> pi4-lab1 phone1
```

creates the secrets (git-ignored: `server/.env`, `server/secrets/`, `server/mosquitto/{passwd,certs}`), a
private CA and broker certificate, the broker accounts with an ACL (the Pi may only use its own topics, the app
account only the Pi listed for it), the upload token (the API stores only its sha256), the Pi's
`secrets/pi_remote.json`, and starts Mosquitto 2.0.20, PostgreSQL 16 and the API (docker compose, or plain
`docker run` through `scripts/run_without_compose.sh`). Copy `pi_remote.json` and `mosquitto/certs/ca.crt` to
the Pi's `~/.config/ppg-simulator/`. In the phone app: connect icon → Internet (MQTT broker), broker host,
device id, account, password, and "Import CA…" for the private CA.

Before a public deployment:
- remove the plain `listener 1883` from `server/mosquitto/mosquitto.conf`;
- give the broker a certificate from a public CA (Let's Encrypt) so phones need no imported CA;
- put the API behind a TLS reverse proxy (it listens on plain HTTP 8000 in the trial) and switch the Pi's
  `sync.url` to `https://`;
- file ownership: the trial makes `passwd`, the broker key and `api_tokens.json` world-readable because the
  containers run as other users; chown them to those users instead;
- the API keeps each CSV in a `bytea` column and reads a whole upload into memory (200 MB cap); move the files to
  object storage (S3/MinIO) when recordings get long.

## What was tested (2026-11-17)

- Host tests: `tests/test_mqtt_remote.py` (fake client), `tests/test_record_sync.py` (in-process HTTP server).
- Laptop trial stack + Pi 4 on the same Wi-Fi + Samsung SM-G960F: phone connected over TLS 8883 with the
  imported private CA; heart rate, Start/Stop output, Record CSV, page change all applied on the Pi
  (`[MQTT] Command applied`); TX/RX traces and status shown on the phone; the new recording reached PostgreSQL
  about 12 s after it was saved and both apps showed `✓ DB`; the existing three recordings uploaded at start-up.
  Wrong password refused; a phone account could not command another device id; the Pi account could not
  publish commands. Switching the phone back to Bluetooth worked.
- Not tested: a broker on the public internet, mobile data / NAT, a public certificate, broker or Wi-Fi
  outages during a session, long recordings, several phones at once.
