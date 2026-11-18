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


def make_sync(tmp_path, api, token=TOKEN, auto_upload=True):
    """auto_upload=True: the upload-everything mode these transport tests exercise; the default is consent."""
    folder = tmp_path / "dataset"
    folder.mkdir(exist_ok=True)
    settings = SyncSettings(device_id="pi4-test", url=api.url, token=token, auto_upload=auto_upload)
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


def test_nothing_is_uploaded_until_the_user_asks_for_that_file(tmp_path, api):
    sync, folder = make_sync(tmp_path, api, auto_upload=False)
    write_csv(folder, "data_1.csv", "a,b\n1,2\n")
    write_csv(folder, "data_2.csv", "a,b\n3,4\n")
    sync.run_once()
    assert api.requests == 0 and sync.state_of("data_1.csv")[0] == rs.LOCAL
    assert sync.request_upload("data_2.csv")
    sync.run_once()
    assert api.requests == 1 and [v["name"] for v in api.store.values()] == ["data_2.csv"]
    assert sync.state_of("data_2.csv")[0] == rs.SYNCED and sync.state_of("data_1.csv")[0] == rs.LOCAL


def test_consent_covers_one_version_and_refuses_odd_names(tmp_path, api):
    sync, folder = make_sync(tmp_path, api, auto_upload=False)
    path = write_csv(folder, "data_1.csv", "a,b\n1,2\n")
    assert sync.request_upload("data_1.csv")
    sync.run_once()
    path.write_text("a,b\n9,9\n")                      # saved again under the same name
    old = time.time() - 10
    os.utime(path, (old + 5, old + 5))
    sync.run_once()
    assert api.requests == 1 and sync.state_of("data_1.csv")[0] == rs.LOCAL
    write_csv(folder, "temp_recording.csv", "x\n")
    assert not sync.request_upload("temp_recording.csv")
    assert not sync.request_upload("missing.csv")


def test_an_outbox_from_before_consent_keeps_synced_rows_and_holds_the_rest(tmp_path, api):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE files (name TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
        mtime_ns INTEGER NOT NULL, uuid TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        next_try REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '', synced_at REAL,
        PRIMARY KEY (name, sha256));""")
    db.execute("INSERT INTO files VALUES ('a.csv','1',1,1,'u1','synced',1,0,'',1)")
    db.execute("INSERT INTO files VALUES ('b.csv','2',1,1,'u2','error',3,0,'HTTP 500',NULL)")
    db.commit()
    db.close()
    outbox = rs.Outbox(path)
    assert outbox.latest_states() == {"a.csv": (rs.SYNCED, ""), "b.csv": (rs.LOCAL, "")}
    assert outbox.due(time.time()) == []


def test_auto_upload_setting_is_off_unless_set():
    from comm.remote_config import sync_settings
    assert sync_settings({"sync": {"url": "https://x"}}).auto_upload is False
    assert sync_settings({"sync": {"url": "https://x", "auto_upload": True}}).auto_upload is True
