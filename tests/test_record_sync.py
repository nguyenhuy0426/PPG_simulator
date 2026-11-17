"""Recording upload (comm/record_sync.py) against a small in-process HTTP server that behaves like server/api.

Run: PPG_DRY_RUN=1 python3 -m pytest tests/test_record_sync.py -q
"""
import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from comm import record_sync as rs
from comm.remote_config import SyncSettings

TOKEN = "t0ken"


class Api:
    """In-memory recordings API with switchable failures."""

    def __init__(self):
        self.store = {}
        self.fail_next = []          # HTTP codes to answer with before behaving
        self.requests = 0

    def handler(self):
        api = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_PUT(self):
                api.requests += 1
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if api.fail_next:
                    return self._reply(api.fail_next.pop(0), {"detail": "planned"})
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self._reply(401, {"detail": "unknown token"})
                sha = hashlib.sha256(body).hexdigest()
                if sha != self.headers.get("X-Content-SHA256"):
                    return self._reply(422, {"detail": "sha mismatch"})
                url = urlparse(self.path)
                rec_id = url.path.rsplit("/", 1)[-1]
                old = api.store.get(rec_id)
                if old and old["sha256"] != sha:
                    return self._reply(409, {"detail": "conflict"})
                api.store[rec_id] = {"sha256": sha, "name": parse_qs(url.query)["name"][0], "body": body}
                self._reply(200 if old else 201, {"id": rec_id, "sha256": sha})

            def _reply(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return H


@pytest.fixture()
def api():
    a = Api()
    server = ThreadingHTTPServer(("127.0.0.1", 0), a.handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    a.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield a
    server.shutdown()


def make_sync(tmp_path, api, token=TOKEN):
    folder = tmp_path / "dataset"
    folder.mkdir(exist_ok=True)
    settings = SyncSettings(device_id="pi4-test", url=api.url, token=token)
    return rs.RecordSync(settings, folder=folder), folder


def write_csv(folder, name, text, age_s=10):
    path = folder / name
    path.write_text(text)
    old = time.time() - age_s
    os.utime(path, (old, old))
    return path


def test_finished_file_is_uploaded_once_and_marked_synced(tmp_path, api):
    sync, folder = make_sync(tmp_path, api)
    write_csv(folder, "data_1.csv", "IR_Raw,RED_Raw\n1,2\n")
    sync.run_once()
    assert len(api.store) == 1 and sync.state_of("data_1.csv")[0] == rs.SYNCED
    sync.run_once()
    assert api.requests == 1                               # nothing to resend


def test_temp_and_fresh_files_wait(tmp_path, api):
    sync, folder = make_sync(tmp_path, api)
    write_csv(folder, rs.TEMP_NAME, "being written\n")
    write_csv(folder, "data_2.csv", "just saved\n", age_s=0)
    sync.run_once()
    assert api.requests == 0


def test_network_failure_backs_off_then_succeeds(tmp_path, api):
    sync, folder = make_sync(tmp_path, api)
    write_csv(folder, "data_1.csv", "a\n")
    api.fail_next = [503]
    sync.run_once()
    state, error = sync.state_of("data_1.csv")
    assert state == rs.ERROR and "503" in error
    sync.run_once()
    assert api.requests == 1                               # still waiting for the back-off
    sync.run_once(now=time.time() + rs.SYNC_BACKOFF_MIN_S + 1)
    assert sync.state_of("data_1.csv")[0] == rs.SYNCED


def test_rejected_token_is_not_hammered(tmp_path, api):
    sync, folder = make_sync(tmp_path, api, token="wrong")
    write_csv(folder, "data_1.csv", "a\n")
    sync.run_once()
    sync.run_once(now=time.time() + rs.SYNC_BACKOFF_MAX_S)
    assert api.requests == 1 and "token" in sync.state_of("data_1.csv")[1]


def test_retry_after_lost_reply_reuses_the_same_id(tmp_path, api):
    sync, folder = make_sync(tmp_path, api)
    write_csv(folder, "data_1.csv", "a\n")
    rec_id = rs.recording_uuid("pi4-test", "data_1.csv", hashlib.sha256(b"a\n").hexdigest())
    api.store[rec_id] = {"sha256": hashlib.sha256(b"a\n").hexdigest()}   # stored, reply lost
    sync.run_once()
    assert sync.state_of("data_1.csv")[0] == rs.SYNCED and len(api.store) == 1


def test_replaced_recording_is_a_new_version(tmp_path, api):
    sync, folder = make_sync(tmp_path, api)
    write_csv(folder, "data_1.csv", "first\n", age_s=20)
    sync.run_once()
    write_csv(folder, "data_1.csv", "second take\n", age_s=10)
    sync.run_once()
    assert len(api.store) == 2 and sync.state_of("data_1.csv")[0] == rs.SYNCED


def test_outbox_survives_a_restart(tmp_path, api):
    sync, folder = make_sync(tmp_path, api)
    write_csv(folder, "data_1.csv", "a\n")
    sync.run_once()
    again, _ = make_sync(tmp_path, api)
    again.run_once()
    assert api.requests == 1 and again.state_of("data_1.csv")[0] == rs.SYNCED


def test_token_is_not_in_the_settings_repr():
    assert TOKEN not in repr(SyncSettings(device_id="d", url="https://x", token=TOKEN))
