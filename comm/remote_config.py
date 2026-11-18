"""Settings of the internet links (MQTT remote control and recording sync).

They live outside the repository, in a JSON file only the Pi user can read
(default ~/.config/ppg-simulator/remote.json, or the path in PPG_REMOTE_CONFIG),
because they hold the broker password and the upload token. Environment
variables override single values (PPG_MQTT_HOST, PPG_MQTT_PASSWORD, ...), so a
systemd unit can supply them instead. Both links stay off unless configured.

    {
      "device_id": "pi4-lab1",
      "mqtt": {"host": "broker.example.org", "port": 8883, "tls": true,
               "ca_file": "", "username": "pi4-lab1", "password": "...",
               "cert_file": "", "key_file": ""},
      "sync": {"url": "https://api.example.org", "token": "...", "ca_file": ""}
    }

cert_file/key_file: a client certificate instead of a password.

"mqtt" may also be a list: the Pi then keeps a connection to every broker in it at
once (for example its own Mosquitto reached by phones over Tailscale, and a cloud
broker), and a phone may use whichever it reaches. An optional "name" labels each
one in the log.
"""
from dataclasses import dataclass
import json
import os
import re
import stat
from pathlib import Path

from comm.logger import log

DEFAULT_PATH = Path.home() / ".config" / "ppg-simulator" / "remote.json"
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")   # it becomes part of MQTT topics: no '/', '+' or '#'


@dataclass(frozen=True)
class MqttSettings:
    device_id: str
    host: str
    port: int = 8883
    tls: bool = True
    ca_file: str = ""
    username: str = ""
    password: str = ""
    cert_file: str = ""     # client certificate (PEM) and its private key, both or neither
    key_file: str = ""
    name: str = ""          # label in the log when several brokers are configured

    def __repr__(self):     # never print the password
        return (f"MqttSettings(name={self.name!r}, device_id={self.device_id!r}, host={self.host!r}, port={self.port}, "
                f"tls={self.tls}, username={self.username!r}, cert_file={self.cert_file!r})")

    @property
    def client_id(self):
        return f"ppgsim-{self.device_id}-pi"

    @property
    def label(self):
        return self.name or f"{self.host}:{self.port}"

    @property
    def loopback(self):
        """A broker on this Pi itself: plain MQTT never leaves the machine."""
        return self.host in ("127.0.0.1", "::1", "localhost")


@dataclass(frozen=True)
class SyncSettings:
    device_id: str
    url: str
    token: str = ""
    ca_file: str = ""
    interval_s: float = 15.0
    auto_upload: bool = False   # False: a recording is uploaded only when the user asks (privacy)

    def __repr__(self):     # never print the token
        return (f"SyncSettings(device_id={self.device_id!r}, url={self.url!r}, interval_s={self.interval_s}, "
                f"auto_upload={self.auto_upload})")


def _bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def load_file(path=None):
    """The JSON settings file as a dict ({} when absent or unreadable)."""
    path = Path(path or os.environ.get("PPG_REMOTE_CONFIG") or DEFAULT_PATH)
    if not path.exists():
        return {}
    try:
        mode = path.stat().st_mode
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            log.warning(f"[Remote] {path} is readable by other users; run: chmod 600 {path}")
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        log.error(f"[Remote] Could not read {path}: {exc}")
        return {}


def device_id(data):
    value = str(os.environ.get("PPG_DEVICE_ID") or data.get("device_id") or "pi4").strip()
    if not DEVICE_ID_RE.match(value):
        raise ValueError(f"device_id {value!r} must be 1-32 letters, digits, '-' or '_'")
    return value


def mqtt_settings(data=None):
    """MqttSettings of the first broker, or None when no broker host is configured."""
    brokers = mqtt_settings_list(data)
    return brokers[0] if brokers else None


def mqtt_settings_list(data=None):
    """MqttSettings of every configured broker ("mqtt" is one object or a list); [] when none.

    The PPG_MQTT_* environment variables apply to the first broker only.
    """
    data = load_file() if data is None else data
    sections = data.get("mqtt") or {}
    if isinstance(sections, dict):
        sections = [sections]
    if not isinstance(sections, list):
        raise ValueError("mqtt must be an object or a list of objects")
    out = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise ValueError(f"mqtt[{index}] must be an object")
        settings = _one_broker(data, section, os.environ.get if index == 0 else (lambda *_a: None))
        if settings is not None:
            out.append(settings)
    labels = [s.label for s in out]
    if len(set(labels)) != len(labels):
        raise ValueError(f"mqtt brokers must differ: {labels}")
    return out


def _one_broker(data, section, env):
    host = str(env("PPG_MQTT_HOST") or section.get("host") or "").strip()
    if not host:
        return None
    tls = _bool(env("PPG_MQTT_TLS") or section.get("tls", True), True)
    cert_file = os.path.expanduser(str(env("PPG_MQTT_CERT_FILE") or section.get("cert_file") or ""))
    key_file = os.path.expanduser(str(env("PPG_MQTT_KEY_FILE") or section.get("key_file") or ""))
    if bool(cert_file) != bool(key_file):
        raise ValueError("mqtt cert_file and key_file must be given together")
    if cert_file and not tls:
        raise ValueError("a client certificate needs tls")
    return MqttSettings(
        device_id=device_id(data),
        host=host,
        port=int(env("PPG_MQTT_PORT") or section.get("port") or (8883 if tls else 1883)),
        tls=tls,
        ca_file=os.path.expanduser(str(env("PPG_MQTT_CA_FILE") or section.get("ca_file") or "")),
        username=str(env("PPG_MQTT_USERNAME") or section.get("username") or ""),
        password=str(env("PPG_MQTT_PASSWORD") or section.get("password") or ""),
        cert_file=cert_file,
        key_file=key_file,
        name=str(section.get("name") or ""),
    )


def sync_settings(data=None):
    """SyncSettings, or None when no upload URL is configured."""
    data = load_file() if data is None else data
    section = data.get("sync") or {}
    env = os.environ.get
    url = str(env("PPG_SYNC_URL") or section.get("url") or "").strip().rstrip("/")
    if not url:
        return None
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"sync url must start with https:// (http:// only on a trusted LAN): {url!r}")
    if url.startswith("http://"):
        log.warning("[Sync] Upload URL is plain http: the token and recordings travel unencrypted")
    return SyncSettings(
        device_id=device_id(data),
        url=url,
        token=str(env("PPG_SYNC_TOKEN") or section.get("token") or ""),
        ca_file=os.path.expanduser(str(env("PPG_SYNC_CA_FILE") or section.get("ca_file") or "")),
        interval_s=float(section.get("interval_s", 15.0)),
        auto_upload=_bool(section.get("auto_upload"), False),
    )
