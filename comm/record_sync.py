"""Copy finished recordings (dataset/*.csv) to the recordings database over HTTPS.

The CSV on the Pi stays the primary copy: recording never waits for the
network. A background thread looks for finished files, keeps an outbox in
SQLite (dataset/.sync/outbox.sqlite3) and uploads each file once:

    PUT {url}/api/v1/recordings/{uuid}?name=<file name>
        Authorization: Bearer <token>        (the server knows the device from its token)
        X-Content-SHA256: <hex>              (the server checks the body against it)
        body: the CSV bytes

The uuid is derived from (device, name, sha256), so a retry after a crash or a
lost reply sends the same id and the server stores the file only once. A file
counts as synced only when the server answers with the same sha256. Failures
are retried with a growing delay (SYNC_BACKOFF_MAX_S at most); a rejected
token or a conflicting id is kept as an error and shown, not retried at once.
A recording replaced under the same name (CSVLogger reuses a name the phone
chose) has a new sha256 and is uploaded as a new version.
"""
import hashlib
import json
import os
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from comm.logger import log

UUID_NAMESPACE = uuid.UUID("6f0c2a52-4f4e-4e65-9d61-7070676d7369")   # fixed: ids must stay stable across versions
TEMP_NAME = "temp_recording.csv"            # core/csv_logger.py writes here, then renames
SETTLE_S = 2.0                              # a file changed more recently than this is left for the next scan
SYNC_BACKOFF_MIN_S = 5.0
SYNC_BACKOFF_MAX_S = 300.0
AUTH_RETRY_S = 600.0                        # a rejected token is tried again only this rarely
HTTP_TIMEOUT_S = 30.0
HASH_CHUNK = 1 << 20

PENDING, SYNCED, ERROR = "pending", "synced", "error"


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def recording_uuid(device_id, name, sha256):
    return str(uuid.uuid5(UUID_NAMESPACE, f"{device_id}/{name}/{sha256}"))


def backoff_s(attempts):
    return min(SYNC_BACKOFF_MAX_S, SYNC_BACKOFF_MIN_S * (2 ** max(0, attempts - 1)))


class UploadError(Exception):
    def __init__(self, message, permanent=False, retry_after=None):
        super().__init__(message)
        self.permanent = permanent
        self.retry_after = retry_after


class Outbox:
    """SQLite record of every file version seen and whether the server has it. One connection per thread."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS files (
        name TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
        uuid TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        next_try REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '', synced_at REAL,
        PRIMARY KEY (name, sha256));
    CREATE INDEX IF NOT EXISTS files_due ON files(state, next_try);
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(self.SCHEMA)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def known(self, name, size, mtime_ns):
        with self._connect() as db:
            return db.execute("SELECT 1 FROM files WHERE name=? AND size=? AND mtime_ns=?",
                              (name, size, mtime_ns)).fetchone() is not None

    def add(self, name, sha256, size, mtime_ns, rec_uuid):
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO files(name, sha256, size, mtime_ns, uuid, state) "
                       "VALUES (?, ?, ?, ?, ?, ?)", (name, sha256, size, mtime_ns, rec_uuid, PENDING))
            # The same bytes again with a new mtime (copied back, touched): keep the row, update the stamp.
            db.execute("UPDATE files SET size=?, mtime_ns=? WHERE name=? AND sha256=?",
                       (size, mtime_ns, name, sha256))

    def due(self, now, limit=5):
        with self._connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM files WHERE state != ? AND next_try <= ? ORDER BY next_try LIMIT ?",
                (SYNCED, now, limit))]

    def mark(self, name, sha256, state, error="", next_try=0.0, attempts=None):
        with self._connect() as db:
            if attempts is None:
                db.execute("UPDATE files SET state=?, last_error=?, next_try=?, synced_at=? "
                           "WHERE name=? AND sha256=?",
                           (state, error, next_try, time.time() if state == SYNCED else None, name, sha256))
            else:
                db.execute("UPDATE files SET state=?, last_error=?, next_try=?, attempts=? "
                           "WHERE name=? AND sha256=?", (state, error, next_try, attempts, name, sha256))

    def latest_states(self):
        """{file name: (state, last_error)} of the newest version of each name."""
        with self._connect() as db:
            rows = db.execute("SELECT name, state, last_error FROM files f WHERE mtime_ns = "
                              "(SELECT MAX(mtime_ns) FROM files g WHERE g.name = f.name)").fetchall()
        return {r["name"]: (r["state"], r["last_error"]) for r in rows}


class RecordSync:
    def __init__(self, settings, folder="dataset", outbox_path=None, opener=None):
        self.settings = settings
        self.folder = Path(folder)
        self.outbox = Outbox(outbox_path or self.folder / ".sync" / "outbox.sqlite3")
        self._opener = opener or self._build_opener()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._states = {}
        self._states_lock = threading.Lock()

    def _build_opener(self):
        context = ssl.create_default_context(cafile=self.settings.ca_file or None)
        return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))

    # ─── lifecycle ────────────────────────────────────────────────────────
    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="record-sync")
        self._thread.start()
        log.info(f"[Sync] Uploading recordings from {self.folder} to {self.settings.url}")

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=HTTP_TIMEOUT_S + 2)
        self._thread = None

    def nudge(self):
        """Scan now (a recording was just saved)."""
        self._wake.set()

    def state_of(self, name):
        """(state, error) of a file name for the Recordings page, None when not seen yet."""
        with self._states_lock:
            return self._states.get(name)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("[Sync] pass failed")
            self._wake.wait(self.settings.interval_s)
            self._wake.clear()

    # ─── one pass ─────────────────────────────────────────────────────────
    def scan(self, now=None):
        """Add finished CSV files that the outbox has not seen (by name, size and mtime) yet."""
        now = time.time() if now is None else now
        if not self.folder.is_dir():
            return 0
        added = 0
        for path in sorted(self.folder.glob("*.csv")):
            if path.name == TEMP_NAME:
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            if now - st.st_mtime < SETTLE_S or self.outbox.known(path.name, st.st_size, st.st_mtime_ns):
                continue
            sha = file_sha256(path)
            self.outbox.add(path.name, sha, st.st_size, st.st_mtime_ns,
                            recording_uuid(self.settings.device_id, path.name, sha))
            added += 1
        return added

    def run_once(self, now=None):
        self.scan(now)
        for row in self.outbox.due(time.time() if now is None else now):
            if self._stop.is_set():
                break
            self._upload_row(row)
        states = self.outbox.latest_states()
        with self._states_lock:
            self._states = states

    def _upload_row(self, row):
        name, sha = row["name"], row["sha256"]
        path = self.folder / name
        try:
            if not path.exists() or file_sha256(path) != sha:
                # Replaced or deleted since the scan: this version no longer exists here.
                self.outbox.mark(name, sha, ERROR, "file changed or removed before upload", next_try=float("inf"))
                return
            self.upload(path, row["uuid"], sha)
        except UploadError as exc:
            attempts = row["attempts"] + 1
            if exc.permanent:
                wait = AUTH_RETRY_S if exc.retry_after is None else exc.retry_after
            else:
                wait = backoff_s(attempts) if exc.retry_after is None else exc.retry_after
            self.outbox.mark(name, sha, ERROR, str(exc), next_try=time.time() + wait, attempts=attempts)
            log.warning(f"[Sync] {name}: {exc} (retry in {wait:.0f} s)")
            return
        self.outbox.mark(name, sha, SYNCED)
        log.info(f"[Sync] {name} uploaded ({row['size']} bytes, id {row['uuid']})")

    def upload(self, path, rec_uuid, sha):
        url = (f"{self.settings.url}/api/v1/recordings/{rec_uuid}?"
               + urllib.parse.urlencode({"name": path.name}))
        size = path.stat().st_size
        headers = {"Content-Type": "text/csv", "Content-Length": str(size), "X-Content-SHA256": sha}
        if self.settings.token:
            headers["Authorization"] = f"Bearer {self.settings.token}"
        try:
            with open(path, "rb") as body:
                request = urllib.request.Request(url, data=body, method="PUT", headers=headers)
                with self._opener.open(request, timeout=HTTP_TIMEOUT_S) as response:
                    reply = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read(300).decode("utf-8", "replace")
            if exc.code in (401, 403):
                raise UploadError(f"server rejected the token (HTTP {exc.code})", permanent=True) from exc
            if exc.code == 409:
                raise UploadError(f"id already holds different data (HTTP 409) {detail}", permanent=True,
                                  retry_after=float("inf")) from exc
            if 400 <= exc.code < 500 and exc.code not in (408, 429):
                raise UploadError(f"HTTP {exc.code} {detail}", permanent=True) from exc
            raise UploadError(f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise UploadError(f"network: {getattr(exc, 'reason', exc)}") from exc
        if reply.get("sha256") != sha:
            raise UploadError(f"server stored sha256 {reply.get('sha256')!r}, expected {sha}")


_current = None


def current():
    """The running RecordSync of this process (for the Recordings page), or None."""
    return _current


def start_sync(folder="dataset", settings=None):
    """RecordSync started from the settings file/environment, or None when no upload URL is configured."""
    global _current
    from comm import remote_config
    try:
        settings = settings or remote_config.sync_settings()
    except ValueError as exc:
        log.error(f"[Sync] Settings rejected: {exc}")
        return None
    if settings is None:
        return None
    if not settings.token:
        log.warning("[Sync] No upload token configured; the server will refuse the uploads")
    sync = RecordSync(settings, folder=os.fspath(folder))
    sync.start()
    _current = sync
    return sync


def stop_sync(sync):
    global _current
    if sync is not None:
        sync.stop()
    if _current is sync:
        _current = None
