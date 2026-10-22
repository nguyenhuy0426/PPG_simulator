"""ml.kaggle_multidomain.openox_download: resume, checksum retry and credential handling (no network)."""
import hashlib

import pytest

requests = pytest.importorskip("requests")

from ml.kaggle_multidomain import openox_download as od


class Response:
    def __init__(self, status, body=b""):
        self.status_code, self.body = status, body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, size):
        yield self.body


class Session:
    def __init__(self, responses):
        self.responses, self.ranges = list(responses), []

    def get(self, url, headers=None, **kwargs):
        self.ranges.append((headers or {}).get("Range"))
        return self.responses.pop(0)


def test_fetch_resumes_a_partial_file_and_verifies_it(tmp_path, monkeypatch):
    monkeypatch.setattr(od.time, "sleep", lambda s: None)
    data = b"0123456789"
    (tmp_path/"a.dat").write_bytes(data[:4])
    session = Session([Response(206, data[4:])])
    path, size = od.fetch(session, "a.dat", tmp_path, hashlib.sha256(data).hexdigest())
    assert path.read_bytes() == data and size == len(data) and session.ranges == ["bytes=4-"]


def test_fetch_restarts_a_corrupt_file_and_skips_a_verified_one(tmp_path, monkeypatch):
    monkeypatch.setattr(od.time, "sleep", lambda s: None)
    data = b"abc"
    session = Session([Response(200, b"xyz"), Response(200, data)])
    od.fetch(session, "b.dat", tmp_path, hashlib.sha256(data).hexdigest())
    assert (tmp_path/"b.dat").read_bytes() == data
    assert od.fetch(Session([]), "b.dat", tmp_path, hashlib.sha256(data).hexdigest())[1] == 0


@pytest.mark.parametrize("status", [401, 403])
def test_fetch_stops_on_rejected_credentials(tmp_path, status):
    with pytest.raises(PermissionError):
        od.fetch(Session([Response(status)]), "c.dat", tmp_path, "0"*64)


def test_missing_credentials_name_the_secrets(monkeypatch):
    monkeypatch.delenv("PHYSIONET_USER", raising=False)
    monkeypatch.delenv("PHYSIONET_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="PHYSIONET_PASSWORD"):
        od.credentials()
