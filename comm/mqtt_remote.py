"""MQTT remote control: the BLE protocol v2/v3 payloads carried over an MQTT broker.

The Pi connects out to the broker (TLS by default) and never listens on the
internet itself. Topics, for device id <id> (comm/remote_config.py):

    ppgsim/<id>/cmd      app -> Pi   QoS 1  command JSON, exactly as on the BLE command characteristic,
                                            plus an optional "cid" (command id) used to drop redelivered copies
    ppgsim/<id>/client   app -> Pi   QoS 0  presence ping (any payload) every few seconds while an app watches
    ppgsim/<id>/status   Pi -> app   QoS 1  status JSON (the BLE STATUS frame), retained
    ppgsim/<id>/online   Pi -> app   QoS 1  "1" / "0", retained; "0" is also the broker's last will
    ppgsim/<id>/stream   Pi -> app   QoS 0  "T<ir>,<red>;...|R<ir>,<red>;..." mV, ~10 per second (BLE STREAM)
    ppgsim/<id>/ui       Pi -> app   QoS 0  one page-state part per message (BLE UI)

Commands go through the same BLECommandHandler as Bluetooth writes, so the
same limits apply; v3 page requests are queued for the Tk thread exactly like
the BLE ones (ui/remote.py takes them from every link). Stream and page state
are only built and sent while an app has pinged within VIEWER_TIMEOUT_S, so an
idle Pi sends nothing but the retained status on change.

Threading: paho runs its network loop in its own thread (on_message calls the
thread-safe engine methods, like the bless thread); a publisher thread sends
stream, page state and status. The Tk thread only touches the locked queues.
"""
from collections import deque
from dataclasses import dataclass
import json
import threading
import time

from comm.ble_remote import STREAM_BACKLOG, STREAM_RATE_HZ, fit_part, pack_stream
from comm.ble_server import (
    ANDROID_GRACE_S, BLE_CONNECTED, BLE_ERROR, BLE_OFF, BLE_STARTING, BLECommandHandler, _engine_state,
    _param_snapshot, build_status_json, origin_for_tick,
)
from comm.logger import log

TOPIC_ROOT = "ppgsim"
VIEWER_TIMEOUT_S = 15.0         # an app that has not pinged for this long is gone
CMD_MAX_BYTES = 4096            # larger command payloads are dropped unread
CID_MEMORY = 64                 # recent command ids kept to drop QoS 1 redeliveries
PART_MAX_BYTES = 4096           # page-state parts: no BLE MTU here, but keep messages small
STREAM_MAX_BYTES = 2048         # one stream message carries the whole backlog of a tick
STATUS_INTERVAL_S = 0.2         # status while an app watches (5 Hz, as over BLE)
UI_REFRESH_S = 2.0              # every part re-sent this often for an app that just joined
RECONNECT_MIN_S, RECONNECT_MAX_S = 1, 60
KEEPALIVE_S = 30


@dataclass(frozen=True)
class Topics:
    cmd: str
    client: str
    status: str
    online: str
    stream: str
    ui: str

    @classmethod
    def for_device(cls, device_id):
        base = f"{TOPIC_ROOT}/{device_id}"
        return cls(*(f"{base}/{name}" for name in ("cmd", "client", "status", "online", "stream", "ui")))


class MqttRemote:
    """One broker connection; the same Tk-side interface as BleServer's v3 part (ui/remote.py)."""

    def __init__(self, engine, settings, client_factory=None):
        self.engine = engine
        self.settings = settings
        self.topics = Topics.for_device(settings.device_id)
        self._client_factory = client_factory
        self._client = None
        self._lock = threading.Lock()
        self._ui_requests = deque(maxlen=32)
        self._stream_tx = deque(maxlen=STREAM_BACKLOG)
        self._stream_rx = deque(maxlen=STREAM_BACKLOG)
        self._ui_parts = {}
        self._ui_dirty = deque()
        self._recent_cids = deque(maxlen=CID_MEMORY)
        self.handler = BLECommandHandler(engine, remote_queue=self._queue_ui_request)
        self._broker_up = False
        self._viewer_until = 0.0
        self._grace_until = 0.0
        self._echo_snapshot = None
        self._last_status = None
        self._seq = 0
        self._stop = threading.Event()
        self._thread = None
        self.last_error = ""

    # ─── lifecycle ────────────────────────────────────────────────────────
    def _make_client(self):
        if self._client_factory is not None:
            return self._client_factory()
        import paho.mqtt.client as mqtt
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"ppgsim-{self.settings.device_id}-pi",
                           clean_session=True)

    def start(self):
        """Connect in the background (paho retries on its own); returns at once."""
        s = self.settings
        client = self._make_client()
        if s.username:
            client.username_pw_set(s.username, s.password or None)
        if s.tls:
            client.tls_set(ca_certs=s.ca_file or None)      # None: the system CA store
        client.will_set(self.topics.online, "0", qos=1, retain=True)
        client.reconnect_delay_set(RECONNECT_MIN_S, RECONNECT_MAX_S)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        self._client = client
        self._stop.clear()
        client.connect_async(s.host, s.port, keepalive=KEEPALIVE_S)
        client.loop_start()
        self._thread = threading.Thread(target=self._publish_loop, daemon=True, name="mqtt-publish")
        self._thread.start()
        log.info(f"[MQTT] Connecting to {s.host}:{s.port} (tls={'on' if s.tls else 'OFF'}) "
                 f"as device '{s.device_id}'")
        if not s.tls:
            log.warning("[MQTT] TLS is off: commands, password and signals travel unencrypted")
        return True

    def stop(self):
        self._stop.set()
        client = self._client
        if client is not None:
            try:
                if self._broker_up:
                    client.publish(self.topics.online, "0", qos=1, retain=True).wait_for_publish(2.0)
            except Exception as exc:
                log.warning(f"[MQTT] Could not announce offline: {exc}")
            client.disconnect()
            client.loop_stop()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._client = None
        self._thread = None
        self._broker_up = False

    # ─── paho callbacks (network thread) ────────────────────────────────
    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None):
        if getattr(reason_code, "is_failure", False):
            self._broker_up = False
            self.last_error = str(reason_code)
            log.error(f"[MQTT] Broker refused the connection: {reason_code}")
            return
        self._broker_up = True
        self.last_error = ""
        client.subscribe([(self.topics.cmd, 1), (self.topics.client, 0)])
        client.publish(self.topics.online, "1", qos=1, retain=True)
        self._last_status = None            # republish the retained status
        log.info("[MQTT] Connected to the broker")

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties=None):
        was_up, self._broker_up = self._broker_up, False
        if was_up and not self._stop.is_set():
            log.warning(f"[MQTT] Broker connection lost ({reason_code}); reconnecting")

    def _on_message(self, _client, _userdata, msg):
        self._viewer_until = time.monotonic() + VIEWER_TIMEOUT_S
        if msg.topic != self.topics.cmd:
            return                          # presence ping
        if len(msg.payload) > CMD_MAX_BYTES:
            log.warning(f"[MQTT] Command of {len(msg.payload)} bytes dropped (limit {CMD_MAX_BYTES})")
            return
        self.on_command(msg.payload)

    def on_command(self, payload):
        """Apply one command payload (bytes). Redelivered copies (same "cid") are applied once."""
        try:
            obj = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            log.warning(f"[MQTT] Command is not JSON: {exc}")
            return {}
        if not isinstance(obj, dict):
            return {}
        cid = obj.get("cid")
        if isinstance(cid, str) and cid:
            with self._lock:
                if cid in self._recent_cids:
                    return {}
                self._recent_cids.append(cid)
        applied = self.handler.handle_command(obj)
        if applied:
            log.info(f"[MQTT] Command applied: {applied}")
            # Same echo rule as BLE: the app's own echo is labelled "android" for a moment.
            self._grace_until = time.monotonic() + ANDROID_GRACE_S
            try:
                self._echo_snapshot = _param_snapshot(self.engine.get_ppg_params(), *_engine_state(self.engine))
            except Exception:
                self._echo_snapshot = None
        return applied

    # ─── Tk-side interface (same as BleServer v3) ───────────────────────
    def connection_state(self):
        """BLE_CONNECTED while the broker is up and an app watches; ui/remote.py builds nothing otherwise."""
        if self._client is None:
            return BLE_ERROR if self.last_error else BLE_OFF
        if not self._broker_up:
            return BLE_ERROR if self.last_error else BLE_STARTING
        return BLE_CONNECTED if time.monotonic() < self._viewer_until else "broker"

    def _queue_ui_request(self, request):
        with self._lock:
            self._ui_requests.append(request)

    def take_ui_requests(self):
        with self._lock:
            requests = list(self._ui_requests)
            self._ui_requests.clear()
        return requests

    def push_stream(self, tx_pairs, rx_pairs):
        with self._lock:
            self._stream_tx.extend(tx_pairs)
            self._stream_rx.extend(rx_pairs)

    def publish_ui(self, parts):
        encoded = {name: fit_part(name, fields, limit=PART_MAX_BYTES) for name, fields in parts}
        with self._lock:
            for name, data in encoded.items():
                if self._ui_parts.get(name) != data and name not in self._ui_dirty:
                    self._ui_dirty.append(name)
            self._ui_parts = encoded
            self._ui_dirty = deque(name for name in self._ui_dirty if name in encoded)

    # ─── publisher thread ─────────────────────────────────────────────────
    def _status_payload(self):
        p = self.engine.get_ppg_params()
        state = _engine_state(self.engine)
        snapshot = _param_snapshot(p, *state)
        origin = origin_for_tick(time.monotonic(), self._grace_until)
        if origin == "android" and self._echo_snapshot is not None and snapshot != self._echo_snapshot:
            origin = "rpi"
        running, recording, record_file, pb, pb_file = state
        return snapshot, origin, (p, running, recording, record_file, pb, pb_file)

    def publish_once(self, now, last):
        """One publisher tick; `last` holds the times of the previous status and full UI refresh."""
        client = self._client
        if client is None or not self._broker_up:
            return
        watching = now < self._viewer_until
        snapshot, origin, (p, running, recording, record_file, pb, pb_file) = self._status_payload()
        if snapshot != self._last_status or (watching and now - last["status"] >= STATUS_INTERVAL_S):
            self._seq += 1
            payload = build_status_json(p, origin, self._seq, running=running, recording=recording,
                                        record_file=record_file, pb=pb, pb_file=pb_file)
            client.publish(self.topics.status, payload, qos=1, retain=True)
            self._last_status = snapshot
            last["status"] = now
        if not watching:
            with self._lock:
                self._stream_tx.clear()
                self._stream_rx.clear()
            return
        with self._lock:
            frame, used_tx, used_rx = pack_stream(list(self._stream_tx), list(self._stream_rx),
                                                  limit=STREAM_MAX_BYTES)
            for _ in range(used_tx):
                self._stream_tx.popleft()
            for _ in range(used_rx):
                self._stream_rx.popleft()
            if now - last["ui"] >= UI_REFRESH_S:
                parts = list(self._ui_parts.values())
                self._ui_dirty.clear()
                last["ui"] = now
            else:
                parts = [self._ui_parts[name] for name in self._ui_dirty if name in self._ui_parts]
                self._ui_dirty.clear()
        if used_tx or used_rx:
            client.publish(self.topics.stream, frame, qos=0)
        for data in parts:
            client.publish(self.topics.ui, data, qos=0)

    def _publish_loop(self):
        interval = 1.0 / STREAM_RATE_HZ
        last = {"status": 0.0, "ui": 0.0}
        errors = 0
        while not self._stop.wait(interval):
            try:
                self.publish_once(time.monotonic(), last)
                errors = 0
            except Exception as exc:
                errors += 1
                if errors <= 3 or errors % 100 == 0:
                    log.warning(f"[MQTT] Publish error x{errors}: {exc}")


def start_mqtt(engine, settings=None):
    """MqttRemote started from the settings file/environment, or None when no broker is configured."""
    from comm import remote_config
    try:
        settings = settings or remote_config.mqtt_settings()
    except ValueError as exc:
        log.error(f"[MQTT] Settings rejected: {exc}")
        return None
    if settings is None:
        return None
    try:
        import paho.mqtt.client  # noqa: F401
    except ImportError as exc:
        log.error(f"[MQTT] unavailable ({exc}) — install with: pip install -r requirements/remote.txt")
        return None
    remote = MqttRemote(engine, settings)
    try:
        remote.start()
    except Exception as exc:
        remote.last_error = str(exc)
        log.error(f"[MQTT] Could not start: {exc}")
    return remote
