"""Phone pairing QR: everything the app needs to connect, in one scan.

    ppgsim://pair?v=1&n=<BLE name>&a=<BLE address>          Bluetooth (always, when the adapter is known)
                 &d=<device id>&h=<broker host>&p=<port>     internet link (when remote.json configures it
                 &t=1&u=<app user>&k=<app password>           and has a "pair" section with the app account)
                 &f=<sha256 of the broker CA, hex>            pin of a private CA (absent: system CAs)
                 &h2=<second broker host>&p2=<its port>       optional second broker, tried when the first
                                                              cannot be reached (same account on both)

The app account is the broker account phones use (server/scripts/setup_trial.sh
creates it), not the Pi's own account. Showing the QR shares that password with
whoever can see the Pi screen, as a Wi-Fi QR does; the broker ACL limits the
account to this Pi's topics.

remote.json:
    "pair": {"username": "phone1", "password": "...", "host": "<optional public host>", "port": 8883}
or, for brokers the phone reaches at other addresses than the Pi does (a Mosquitto on the Pi itself, which
the Pi uses on 127.0.0.1 and phones over Tailscale; plus a cloud broker):
    "pair": {"username": "phone1", "password": "...", "ca_file": "<private CA of a broker, optional>",
             "brokers": [{"host": "ppg-rpi4.tailnet.ts.net", "port": 8883}, {"host": "x.emqxsl.com", "port": 8883}]}
A TLS connection is accepted when either the system CAs or the pinned CA vouch for the broker.
"""
import hashlib
import os
import re
import ssl
import subprocess
from urllib.parse import parse_qs, urlencode, urlparse

from comm.logger import log

SCHEME = "ppgsim"
VERSION = "1"
MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
MAX_BROKERS = 2


def ca_fingerprint(path):
    """SHA-256 of the DER form of the first certificate in a PEM file, lower-case hex."""
    with open(path, "r", encoding="ascii") as fh:
        pem = fh.read()
    match = re.search(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", pem, re.S)
    if match is None:
        raise ValueError(f"{path} holds no PEM certificate")
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(match.group(0))).hexdigest()


def local_ble_address(timeout_s=3.0):
    """Address of the default Bluetooth controller from `bluetoothctl list`, or "" when unknown."""
    try:
        out = subprocess.run(["bluetoothctl", "list"], capture_output=True, text=True, timeout=timeout_s).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning(f"[Pair] Bluetooth address unknown: {exc}")
        return ""
    lines = [line.split() for line in out.splitlines() if line.startswith("Controller ")]
    default = [parts for parts in lines if "[default]" in parts] or lines
    address = default[0][1].upper() if default and len(default[0]) > 1 else ""
    return address if MAC_RE.match(address) else ""


def pairing_uri(ble_name="", ble_address="", mqtt=None, pair=None):
    """The QR text. `mqtt` is MqttSettings (or None); `pair` the remote.json "pair" section (or None)."""
    fields = {"v": VERSION}
    if ble_name:
        fields["n"] = ble_name
    if ble_address and MAC_RE.match(ble_address.upper()):
        fields["a"] = ble_address.upper()
    pair = pair or {}
    if mqtt is not None and pair.get("username"):
        brokers = phone_brokers(mqtt, pair)
        if brokers:
            (host, port), rest = brokers[0], brokers[1:]
            fields.update({
                "d": mqtt.device_id,
                "h": host,
                "p": str(port),
                "t": "1" if (mqtt.tls or pair.get("brokers")) else "0",
                "u": str(pair["username"]),
                "k": str(pair.get("password") or ""),
            })
            for n, (host, port) in enumerate(rest, start=2):
                fields[f"h{n}"], fields[f"p{n}"] = host, str(port)
            ca_file = pair.get("ca_file") or (mqtt.ca_file if mqtt.tls else "")
            if ca_file:
                fields["f"] = ca_fingerprint(os.path.expanduser(str(ca_file)))
    return f"{SCHEME}://pair?{urlencode(fields)}"


def phone_brokers(mqtt, pair):
    """[(host, port)] the phone should try in order: "brokers" from the pair section, else the single host
    (a loopback broker is not reachable from a phone and gives none)."""
    listed = pair.get("brokers")
    if listed:
        out = []
        for item in listed[:MAX_BROKERS]:
            host, port = str(item.get("host") or "").strip(), int(item.get("port") or 8883)
            if not HOST_RE.match(host) or not 0 < port < 65536:
                raise ValueError(f"pair broker {host!r}:{port} is not a valid host and port")
            out.append((host, port))
        return out
    host = str(pair.get("host") or ("" if mqtt.loopback else mqtt.host))
    return [(host, int(pair.get("port") or mqtt.port))] if host else []


def parse_pairing_uri(uri):
    """Inverse of pairing_uri for tests and tools: {key: value}; ValueError when it is not a pairing QR."""
    parsed = urlparse(uri)
    if parsed.scheme != SCHEME or parsed.netloc != "pair":
        raise ValueError("not a ppgsim pairing code")
    fields = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    if fields.get("v") != VERSION:
        raise ValueError(f"unsupported pairing version {fields.get('v')!r}")
    return fields


def has_internet(fields):
    return all(fields.get(k) for k in ("d", "h", "p", "u"))


def current_uri(ble_name):
    """The pairing text for this Pi from remote.json and the Bluetooth adapter (may hold only Bluetooth)."""
    from comm import remote_config
    data = remote_config.load_file()
    try:
        mqtt = remote_config.mqtt_settings(data)
    except ValueError as exc:
        log.error(f"[Pair] MQTT settings rejected: {exc}")
        mqtt = None
    return pairing_uri(ble_name, local_ble_address(), mqtt, data.get("pair"))
