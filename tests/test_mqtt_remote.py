"""MQTT remote (comm/mqtt_remote.py) without a broker: a fake paho client records what is published.

Run: PPG_DRY_RUN=1 python3 -m pytest tests/test_mqtt_remote.py -q
"""
import json
import time
from types import SimpleNamespace

import pytest

from comm.ble_server import BLE_CONNECTED
from comm.mqtt_remote import (
    CMD_MAX_BYTES, UI_REFRESH_S, VIEWER_TIMEOUT_S, MqttRemote, Topics,
)
from comm.remote_config import MqttSettings
from models.limits import HEART_RATE
from tests.test_ble_server import FakeEngine


class FakeClient:
    def __init__(self):
        self.published = []
        self.subscribed = []
        self.calls = []

    def username_pw_set(self, user, password):
        self.calls.append(("auth", user, password is not None))

    def tls_set(self, ca_certs=None):
        self.calls.append(("tls", ca_certs))

    def will_set(self, topic, payload, qos=0, retain=False):
        self.calls.append(("will", topic, payload, retain))

    def reconnect_delay_set(self, a, b):
        pass

    def connect_async(self, host, port, keepalive=60):
        self.calls.append(("connect", host, port))

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def disconnect(self):
        self.calls.append(("disconnect",))

    def subscribe(self, topics):
        self.subscribed.extend(topics)

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload if isinstance(payload, (bytes, str)) else bytes(payload), qos, retain))
        return SimpleNamespace(wait_for_publish=lambda timeout=None: None)

    def on(self, topic):
        return [p for p in self.published if p[0] == topic]


SETTINGS = MqttSettings(device_id="pi4-test", host="broker.local", port=8883, tls=True, ca_file="/tmp/ca.crt",
                        username="pi4-test", password="secret")


@pytest.fixture()
def remote():
    client = FakeClient()
    r = MqttRemote(FakeEngine(), SETTINGS, client_factory=lambda: client)
    r.start()
    r._stop.set()                       # keep the publisher thread out of the way; ticks are driven by hand
    r._on_connect(client, None, None, SimpleNamespace(is_failure=False))
    yield r, client
    r.stop()


def message(topic, payload):
    return SimpleNamespace(topic=topic, payload=payload if isinstance(payload, bytes) else payload.encode())


def test_topics_are_scoped_to_the_device():
    t = Topics.for_device("pi4-lab1")
    assert t.cmd == "ppgsim/pi4-lab1/cmd" and t.stream == "ppgsim/pi4-lab1/stream"


def test_start_sets_tls_auth_and_last_will(remote):
    r, client = remote
    assert ("tls", "/tmp/ca.crt") in client.calls
    assert ("auth", "pi4-test", True) in client.calls
    assert ("will", "ppgsim/pi4-test/online", "0", True) in client.calls
    assert ("ppgsim/pi4-test/cmd", 1) in client.subscribed
    assert ("ppgsim/pi4-test/online", "1", 1, True) in client.published


def test_password_is_not_in_the_settings_repr():
    assert "secret" not in repr(SETTINGS)


def test_command_applies_through_the_ble_handler_with_its_limits(remote):
    r, _client = remote
    r._on_message(None, None, message(r.topics.cmd, json.dumps({"hr": 9999, "origin": "android"})))
    assert r.engine.ppg_params.heart_rate == HEART_RATE.clamp(9999) < 9999   # clamped like a BLE write


def test_redelivered_command_id_is_applied_once(remote):
    r, _client = remote
    cmd = json.dumps({"cid": "a1", "nn": {"gen": True}})
    r._on_message(None, None, message(r.topics.cmd, cmd))
    r._on_message(None, None, message(r.topics.cmd, cmd))
    assert r.take_ui_requests() == [{"nn": {"gen": True}}]


def test_oversized_and_garbage_commands_are_dropped(remote):
    r, _client = remote
    r._on_message(None, None, message(r.topics.cmd, b"{" + b" " * CMD_MAX_BYTES + b"}"))
    r._on_message(None, None, message(r.topics.cmd, b"\xff\xfe"))
    r._on_message(None, None, message(r.topics.cmd, b"[1, 2]"))
    assert r.engine.calls == [] and r.take_ui_requests() == []


def test_nothing_but_status_is_sent_until_an_app_pings(remote):
    r, client = remote
    assert r.connection_state() == "broker"
    r.push_stream(["1,2"], ["3,4"])
    r.publish_ui([("page", {"v": "monitor"})])
    r.publish_once(time.monotonic(), {"status": 0.0, "ui": 0.0})
    assert client.on(r.topics.stream) == [] and client.on(r.topics.ui) == []
    status = client.on(r.topics.status)
    assert len(status) == 1 and status[0][3] is True      # retained
    assert json.loads(status[0][1])["origin"] == "rpi"


def test_a_watching_app_gets_stream_and_page_parts(remote):
    r, client = remote
    r._on_message(None, None, message(r.topics.client, "hi"))
    assert r.connection_state() == BLE_CONNECTED
    r.push_stream(["1000,900", "1001,901"], ["500,400"])
    r.publish_ui([("page", {"v": "monitor"}), ("rec", {"sel": "data_1.csv"})])
    now = time.monotonic()
    last = {"status": 0.0, "ui": now}                     # not yet time for the full refresh
    r.publish_once(now, last)
    frames = client.on(r.topics.stream)
    assert frames and frames[0][1].decode().startswith("T1000,900;1001,901|R500,400")
    kinds = sorted(json.loads(p[1])["k"] for p in client.on(r.topics.ui))
    assert kinds == ["page", "rec"]
    client.published.clear()
    r.publish_once(now + 0.1, last)                      # unchanged parts are not sent again...
    assert client.on(r.topics.ui) == []
    r.publish_once(now + UI_REFRESH_S + 0.2, last)       # ...until the periodic refresh
    assert len(client.on(r.topics.ui)) == 2


def test_viewer_expires(remote, monkeypatch):
    r, _client = remote
    r._on_message(None, None, message(r.topics.client, "hi"))
    later = time.monotonic() + VIEWER_TIMEOUT_S + 1
    monkeypatch.setattr("comm.mqtt_remote.time.monotonic", lambda: later)
    assert r.connection_state() == "broker"


def test_own_echo_is_labelled_android_then_rpi(remote, monkeypatch):
    r, client = remote
    r._on_message(None, None, message(r.topics.cmd, json.dumps({"hr": 90})))
    r.publish_once(time.monotonic(), {"status": 0.0, "ui": 0.0})
    assert json.loads(client.on(r.topics.status)[-1][1])["origin"] == "android"


def test_refused_connection_is_reported(remote):
    r, client = remote
    r._on_connect(client, None, None, SimpleNamespace(is_failure=True, __str__=lambda self: "Not authorized"))
    assert r.connection_state() != BLE_CONNECTED and r.last_error
