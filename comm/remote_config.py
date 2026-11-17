"""Settings of the internet links (MQTT remote control and recording sync).

They live outside the repository, in a JSON file only the Pi user can read
(default ~/.config/ppg-simulator/remote.json, or the path in PPG_REMOTE_CONFIG),
because they hold the broker password and the upload token. Environment
variables override single values (PPG_MQTT_HOST, PPG_MQTT_PASSWORD, ...), so a
systemd unit can supply them instead. Both links stay off unless configured.

    {
      "device_id": "pi4-lab1",
      "mqtt": {"host": "broker.example.org", "port": 8883, "tls": true,
               "ca_file": "", "username": "pi4-lab1", "password": "..."},
      "sync": {"url": "https://api.example.org", "token": "...", "ca_file": ""}
    }
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

    def __repr__(self):     # never print the password
        return (f"MqttSettings(device_id={self.device_id!r}, host={self.host!r}, port={self.port}, "
                f"tls={self.tls}, username={self.username!r})")


@dataclass(frozen=True)
class SyncSettings:
    device_id: str
    url: str
    token: str = ""
    ca_file: str = ""
    interval_s: float = 15.0

    def __repr__(self):     # never print the token
        return f"SyncSettings(device_id={self.device_id!r}, url={self.url!r}, interval_s={self.interval_s})"


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
    """MqttSettings, or None when no broker host is configured."""
    data = load_file() if data is None else data
    section = data.get("mqtt") or {}
    env = os.environ.get
    host = str(env("PPG_MQTT_HOST") or section.get("host") or "").strip()
    if not host:
        return None
    tls = _bool(env("PPG_MQTT_TLS", section.get("tls", True)), True)
    return MqttSettings(
        device_id=device_id(data),
        host=host,
        port=int(env("PPG_MQTT_PORT") or section.get("port") or (8883 if tls else 1883)),
        tls=tls,
        ca_file=os.path.expanduser(str(env("PPG_MQTT_CA_FILE") or section.get("ca_file") or "")),
        username=str(env("PPG_MQTT_USERNAME") or section.get("username") or ""),
        password=str(env("PPG_MQTT_PASSWORD") or section.get("password") or ""),
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
    )
