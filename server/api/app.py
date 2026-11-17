"""Recordings API: stores the CSV recordings the Pi uploads (comm/record_sync.py) in PostgreSQL.

    PUT  /api/v1/recordings/{id}?name=data_1.csv   body: CSV, header X-Content-SHA256   (device token)
    GET  /api/v1/recordings?limit=50                metadata of the caller's device         (device token)
    GET  /api/v1/recordings/{id}/file               the CSV bytes                           (device token)
    GET  /healthz

Authentication: "Authorization: Bearer <token>". API_TOKENS_FILE is a JSON object
{device_id: sha256 hex of its token}; only the hashes are stored on the server.
A PUT is idempotent: the same id with the same sha256 returns the stored row
(200), the same id with other bytes is refused (409).

Trial service: the whole body is held in memory (MAX_UPLOAD_BYTES caps it) and
the CSV is stored in a bytea column. For long recordings an object store
(S3/MinIO) with the metadata here is the next step.
"""
import csv
import hashlib
import hmac
import io
import json
import os
import re
import statistics
import uuid
from contextlib import contextmanager

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response

DATABASE_URL = os.environ["DATABASE_URL"]
TOKENS_FILE = os.environ.get("API_TOKENS_FILE", "/run/secrets/api_tokens.json")
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(200 * 1024 * 1024)))
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}\.csv$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id          uuid PRIMARY KEY,
    device_id   text NOT NULL,
    name        text NOT NULL,
    sha256      char(64) NOT NULL,
    size_bytes  bigint NOT NULL,
    rows        integer,
    duration_s  double precision,
    hr_mean     double precision,
    uploaded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS recordings_device_time ON recordings (device_id, uploaded_at DESC);
CREATE TABLE IF NOT EXISTS recording_files (
    id      uuid PRIMARY KEY REFERENCES recordings(id) ON DELETE CASCADE,
    content bytea NOT NULL
);
"""

app = FastAPI(title="PPG simulator recordings", version="0.1")


@contextmanager
def db():
    with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
        yield conn


@app.on_event("startup")
def create_schema():
    with db() as conn:
        conn.execute(SCHEMA)
        conn.commit()


def load_tokens():
    with open(TOKENS_FILE, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {str(k): str(v).lower() for k, v in data.items()}


def device_for(authorization: str = Header(default="")):
    """The device id whose token is presented; 401 otherwise. Compared in constant time."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "missing bearer token")
    digest = hashlib.sha256(token.strip().encode("utf-8")).hexdigest()
    match = None
    for device, expected in load_tokens().items():
        if hmac.compare_digest(digest, expected):
            match = device
    if match is None:
        raise HTTPException(401, "unknown token")
    return match


def summarize(content):
    """Rows, duration and mean heart rate of a simulator CSV (core/csv_logger.py columns); None when absent."""
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8", "replace")))
        rows, times, hrs = 0, [], []
        for row in reader:
            rows += 1
            for key, out in (("Time_s", times), ("HR_BPM", hrs)):
                try:
                    out.append(float(row.get(key) or ""))
                except ValueError:
                    pass
        duration = (times[-1] - times[0]) if len(times) > 1 else None
        return rows, duration, (statistics.fmean(hrs) if hrs else None)
    except csv.Error:
        return None, None, None


def row_json(r):
    return {"id": str(r[0]), "device_id": r[1], "name": r[2], "sha256": r[3], "size_bytes": r[4], "rows": r[5],
            "duration_s": r[6], "hr_mean": r[7], "uploaded_at": r[8].isoformat()}


COLUMNS = "id, device_id, name, sha256, size_bytes, rows, duration_s, hr_mean, uploaded_at"


@app.get("/healthz")
def healthz():
    with db() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


@app.put("/api/v1/recordings/{rec_id}")
async def put_recording(rec_id: uuid.UUID, request: Request, response: Response,
                        name: str = Query(...), x_content_sha256: str = Header(...),
                        device: str = Depends(device_for)):
    if not NAME_RE.match(name):
        raise HTTPException(422, "name must be a plain .csv file name")
    claimed = x_content_sha256.strip().lower()
    if not SHA_RE.match(claimed):
        raise HTTPException(422, "X-Content-SHA256 must be 64 hex digits")
    length = int(request.headers.get("content-length") or 0)
    if length > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"larger than {MAX_UPLOAD_BYTES} bytes")
    content = await request.body()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"larger than {MAX_UPLOAD_BYTES} bytes")
    actual = hashlib.sha256(content).hexdigest()
    if actual != claimed:
        raise HTTPException(422, f"body sha256 {actual} does not match the header")
    with db() as conn:
        existing = conn.execute(f"SELECT {COLUMNS} FROM recordings WHERE id = %s", (rec_id,)).fetchone()
        if existing is not None:
            if existing[1] != device or existing[3] != actual:
                raise HTTPException(409, "this id already holds another recording")
            response.status_code = 200
            return row_json(existing)
        rows, duration, hr_mean = summarize(content)
        row = conn.execute(
            f"INSERT INTO recordings (id, device_id, name, sha256, size_bytes, rows, duration_s, hr_mean) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {COLUMNS}",
            (rec_id, device, name, actual, len(content), rows, duration, hr_mean)).fetchone()
        conn.execute("INSERT INTO recording_files (id, content) VALUES (%s, %s)", (rec_id, content))
        conn.commit()
    response.status_code = 201
    return row_json(row)


@app.get("/api/v1/recordings")
def list_recordings(limit: int = Query(50, ge=1, le=500), device: str = Depends(device_for)):
    with db() as conn:
        rows = conn.execute(f"SELECT {COLUMNS} FROM recordings WHERE device_id = %s "
                            "ORDER BY uploaded_at DESC LIMIT %s", (device, limit)).fetchall()
    return [row_json(r) for r in rows]


@app.get("/api/v1/recordings/{rec_id}/file")
def get_file(rec_id: uuid.UUID, device: str = Depends(device_for)):
    with db() as conn:
        row = conn.execute("SELECT r.name, f.content FROM recordings r JOIN recording_files f ON f.id = r.id "
                           "WHERE r.id = %s AND r.device_id = %s", (rec_id, device)).fetchone()
    if row is None:
        raise HTTPException(404, "not found")
    return Response(bytes(row[1]), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{row[0]}"'})
