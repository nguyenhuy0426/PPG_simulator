# Remote control over MQTT and recordings in a database (trial)

On `main` since 18 November 2026. Bluetooth (docs/ble_protocol.md) is unchanged; MQTT is a second link for
control from anywhere, and the user can send a recording to PostgreSQL with **Upload to DB**.

```
Phone app ──MQTT/TLS 8883──► broker(s) ◄──MQTT── Pi 4 (main.py)
             (Mosquitto on the Pi over Tailscale,   │ dataset/*.csv  (primary copy, never waits for the network)
              and/or a cloud broker such as EMQX)   └─HTTP(S) PUT──► recordings API ──► PostgreSQL
                                                        (only files the user uploads)
```

The Pi connects out to the brokers. The broker it may run itself (`server/pi_broker/`) takes phones on TLS
8883 on every interface of the Pi, meant for the tailnet and the LAN: keep the Pi off a public address or
firewall that port. Signal generation and the DACs stay on the Pi, so network delay never changes the
output waveform, only how fast a setpoint arrives.

## Connecting a phone (quickest path)

1. On the Pi: **Phone** on the left menu shows a QR code (`ui/pair_dialog.py`, `comm/pairing.py`).
2. In the app: connect icon → **Scan the Pi's QR code**. The phone saves the Pi and connects at once:
   over the internet when the Pi has a broker set up, otherwise straight to its Bluetooth address (no scan list).
3. Next time the app opens it reconnects by itself to the link that last worked. **Disconnect** turns that
   off until the next connection. The connect menu also offers **Connect to <Pi>** as a single tap.

The code is `ppgsim://pair?v=1&n=<BLE name>&a=<BLE address>&d=<device>&h=<host>&p=<port>&t=1&u=<app user>&k=<app
password>&f=<CA sha256>&h2=<second host>&p2=<its port>`. `h2`/`p2` are present when two brokers are listed;
the phone tries `h` first and `h2` when `h` cannot be reached, with the same account on both. The code carries
the phone account from the `"pair"` section of `remote.json`, never the Pi's own broker password. Anyone who can
see the Pi screen can pair, as with a Wi-Fi QR; the broker ACL keeps that account to this Pi's topics. With a
private CA the phone pins it by fingerprint: the broker sends its chain (server + CA; `setup_trial.sh` and
`make_bundle.sh` build it), the CA whose SHA-256 matches becomes the only trust anchor and the chain is
validated against it; the host name is checked as usual. Without `f` the system CAs apply. A TLS connection
is accepted when either the system CAs or the pinned CA vouch for the broker, so a cloud broker with a public
certificate and the Pi's own broker with the private CA work from the same QR.

Bluetooth without the QR: the scan list connects by itself when exactly one simulator answers within 1.5 s.

`"pair"` in `remote.json`, one broker: `{"username": "phone1", "password": "…", "host": "<optional public
host>", "port": 8883}`. Brokers that phones reach at other addresses than the Pi does (the Pi uses its own
Mosquitto on 127.0.0.1, phones reach it over Tailscale) are listed in order, at most two:

```json
"pair": {"username": "phone1", "password": "…", "ca_file": "~/.config/ppg-simulator/ca.crt",
         "brokers": [{"host": "ppg-rpi4.<tailnet>.ts.net", "port": 8883}, {"host": "<id>.emqxsl.com", "port": 8883}]}
```

The QR needs `qrcode` (`requirements/remote.txt`).

## MQTT topics (`comm/mqtt_remote.py`)

| Topic | Direction | QoS | Payload |
|---|---|---|---|
| `ppgsim/<id>/cmd` | app → Pi | 1 | the BLE command JSON (v2/v3), plus `cid` so a redelivered copy is applied once |
| `ppgsim/<id>/client` | app → Pi | 0 | presence ping every 5 s; the Pi streams only for 15 s after the last ping |
| `ppgsim/<id>/status` | Pi → app | 1 | the BLE STATUS JSON: 5 Hz while an app watches (not retained); retained on change, at most once per 1.1 s |
| `ppgsim/<id>/online` | Pi → app | 1, retained | `1`, or `0` (also the broker's last will) |
| `ppgsim/<id>/stream` | Pi → app | 0 | `T<ir>,<red>;…\|R<ir>,<red>;…` mV, ~10 messages/s |
| `ppgsim/<id>/ui` | Pi → app | 0 | one page-state part per message (the BLE UI parts, up to 4 KB) |

Commands from MQTT go through the same `BLECommandHandler` as Bluetooth writes (same limits, same page
requests through `ui/remote.py`). The status echo uses the same `origin` grace rule. Use one link at a time
per phone; the app switches between them.

With several brokers (`"mqtt"` is a list) the Pi keeps one client per broker (`MqttGroup`). A command is
applied from whichever broker it arrives on; stream and page state go only to brokers where an app has pinged.
Keep-alive is 30 s and reconnects back off from 1 s to 60 s, so a link that drops without a clean close is
noticed only when the keep-alive runs out.

The Recordings page sends one more part, `{"k":"sy","s":"lspe"}`: the database state of each listed file in
list order (`l` local, never uploaded; `s` synced; `p` pending; `e` error). Both apps show `✓ DB`, `… DB`,
`✗ DB` for the last three.

## Recording upload (`comm/record_sync.py`)

Nothing leaves the Pi unless the user asks. A finished file in `dataset/` (not `temp_recording.csv`, not
changed in the last 2 s) is listed in the outbox (`dataset/.sync/outbox.sqlite3`) as **local**. It is sent
only after **Upload to DB** for that file: on the Pi's Recordings page (two taps: the button asks once) or on
the phone, which also asks twice and then sends `{"rec": {"up": "<file name>"}}`. The consent is per version:
a file saved again under the same name is local again. `"sync": {"auto_upload": true}` in `remote.json`
restores the earlier behaviour (every finished file is uploaded). An outbox written before 18 November keeps
its synced rows synced; the rest become local.

An approved file is sent once with `PUT /api/v1/recordings/<uuid>?name=…`, `Authorization: Bearer <token>`,
`X-Content-SHA256`. The uuid is derived from device, name and sha256, so a retry is idempotent; a file is
"synced" only when the server returns the same sha256. Network errors back off from 5 s to 5 min; a rejected
token waits 10 min. The Pi's Recordings page shows the selected file as **Upload to DB**, **Uploading…**,
**In the DB**, **DB upload error** or **No database set up**. Deleting a recording on the Pi removes only the
file in `dataset/`; a copy already in the database stays there.

## Settings on the Pi

`~/.config/ppg-simulator/remote.json` (or the path in `PPG_REMOTE_CONFIG`), mode 600; the app warns if others
can read it. One broker:

```json
{"device_id": "pi4-lab1",
 "mqtt": {"host": "broker.example.org", "port": 8883, "tls": true, "ca_file": "",
          "username": "pi4-lab1", "password": "…"},
 "sync": {"url": "https://api.example.org", "token": "…"}}
```

Several brokers, as `server/pi_broker/make_bundle.sh` writes it (the names label each broker in the log):

```json
{"device_id": "pi4-lab1",
 "mqtt": [{"name": "pi-broker", "host": "127.0.0.1", "port": 1883, "tls": false, "username": "pi4-lab1", "password": "…"},
          {"name": "cloud", "host": "<id>.emqxsl.com", "port": 8883, "tls": true, "ca_file": "",
           "username": "pi4-lab1", "password": "…"}],
 "pair": {"…": "see above"},
 "sync": {"url": "http://<server>:8000", "token": "…", "auto_upload": false}}
```

- `ca_file` empty means the system CA store (a broker with a public certificate).
- `cert_file` and `key_file` (both or neither, TLS only) log in with a client certificate instead of a password.
- Plain MQTT (`"tls": false`) is meant for a broker on the Pi itself (127.0.0.1).
- `sync.url` must start with `https://`; `http://` is accepted on a trusted LAN and logs a warning, because the
  token and the recordings then travel unencrypted.
- Environment variables `PPG_MQTT_*` (first broker only), `PPG_SYNC_*` and `PPG_DEVICE_ID` override single values.

Without the file both links stay off; `--no-remote` turns them off. Install the client:
`.venv/bin/python -m pip install -r requirements/remote.txt`.

## Trial server (`server/`)

```bash
server/scripts/setup_trial.sh <server-ip> pi4-lab1 phone1
```

creates the secrets (git-ignored: `server/.env`, `server/secrets/`, `server/mosquitto/{passwd,certs}`), a
private CA and broker certificate, the broker accounts with an ACL (the Pi may only use its own topics, the app
account only the Pi listed for it), the upload token (the API stores only its sha256), the Pi's
`secrets/pi_remote.json`, and starts Mosquitto 2.0.20, PostgreSQL 16 and the API (docker compose, or plain
`docker run` through `scripts/run_without_compose.sh`). Copy `pi_remote.json` and `mosquitto/certs/ca.crt` to
the Pi's `~/.config/ppg-simulator/`. In the phone app: scan the Pi's QR, or connect icon → Internet (manual):
broker host, device id, account, password, and "Import CA…" for the private CA.

## Broker on the Pi over Tailscale (`server/pi_broker/`)

A Mosquitto broker on the Pi itself, reached by phones over Tailscale, so no server has to stay on. It reuses
the trial CA and accounts from `setup_trial.sh`, so a phone paired before keeps its CA pin. A cloud broker can
run beside it as a second entry; the same account names and passwords must exist there.

1. On the Pi (needs sudo): `bash server/pi_broker/install_pi.sh [tailscale-hostname]` installs Tailscale from
   its apt repository and Mosquitto from the distribution, then starts the Tailscale login (a URL to open).
2. On the laptop that ran `setup_trial.sh`:
   `server/pi_broker/make_bundle.sh <tailscale-dns-name> <tailscale-ip> <device> <app-user> [cloud-host [cloud-port]]`
   writes `server/secrets/pi_broker/` (git-ignored, mode 600): a broker certificate for the tailnet name and IP
   signed by the trial CA (sent as a chain), the accounts, the ACL, `ppgsim.conf` and a `remote.json` that lists
   the Pi broker and the optional cloud broker. It prints where the files are, never the passwords.
3. Copy that folder to the Pi and run `configure_pi.sh` from it (the script prints the exact `scp`/`ssh`
   commands). It installs the certificate, accounts (hashed in place), ACL and `ppgsim.conf` into
   `/etc/mosquitto`, restarts Mosquitto, puts `remote.json` and `ca.crt` into `~/.config/ppg-simulator/` (the
   previous `remote.json` is kept as `remote.json.bak-<time>`) and deletes the plain-text copies. Restart the
   simulator app afterwards.

`ppgsim.conf` opens plain 1883 on 127.0.0.1 only (the simulator app on the Pi) and TLS 8883 on all interfaces
for phones; no anonymous login.

## Before a public deployment

- remove the plain `listener 1883` from `server/mosquitto/mosquitto.conf`;
- give the broker a certificate from a public CA (Let's Encrypt) so phones need no imported CA;
- put the API behind a TLS reverse proxy (it listens on plain HTTP 8000 in the trial) and switch the Pi's
  `sync.url` to `https://`;
- file ownership: the trial makes `passwd`, the broker key and `api_tokens.json` world-readable because the
  containers run as other users; chown them to those users instead;
- the API keeps each CSV in a `bytea` column and reads a whole upload into memory (200 MB cap); move the files to
  object storage (S3/MinIO) when recordings get long.

## What was tested

2026-11-17, laptop trial stack + Pi 4 on the same Wi-Fi + Samsung SM-G960F:
- Host tests: `tests/test_mqtt_remote.py` (fake client), `tests/test_record_sync.py` (in-process HTTP server).
- The phone connected over TLS 8883 with the imported private CA; heart rate, Start/Stop output, Record CSV,
  page change all applied on the Pi (`[MQTT] Command applied`); TX/RX traces and status shown on the phone.
  Uploads were automatic then: a new recording reached PostgreSQL about 12 s after it was saved.
- Wrong password refused; a phone account could not command another device id; the Pi account could not
  publish commands. Switching the phone back to Bluetooth worked.

2026-11-18, Pi 4 + the same phone:
- Commands applied through the Pi's own broker over Tailscale and through EMQX Serverless.
- Upload on request: a saved Model window reached the database after two taps on the phone, and the file next
  to it stayed local. Host tests cover "nothing uploaded until asked", one version per consent and the outbox
  migration.
- A Model window's CSV sent to the phone over MQTT: 412 parts in 1.0 s; the phone saved 3001 lines.

Not tested: mobile data / NAT, a public certificate on the trial broker, broker or Wi-Fi outages during a
long session, long recordings, several phones at once.
