"""ml.kaggle_multidomain.openox_download: resume, checksum retry and credential handling (wget mocked, no network)."""
import hashlib
from pathlib import Path
import stat
import subprocess

import pytest

from ml.kaggle_multidomain import openox_download as od


class Wget:
    """Stands in for subprocess.run(["wget", ...]): each call appends (with -c) or writes the next body."""
    def __init__(self, results):
        self.results, self.calls = list(results), []

    def __call__(self, args, env=None, **kwargs):
        self.calls.append(args)
        code, body, stderr = self.results.pop(0)
        path = Path(args[args.index("-P")+1])/args[-1].rsplit("/", 1)[1]
        if body is not None:
            with open(path, "ab" if "-c" in args else "wb") as f:
                f.write(body)
        return subprocess.CompletedProcess(args, code, "", stderr)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(od.time, "sleep", lambda s: None)


def test_fetch_resumes_a_partial_file_and_verifies_it(tmp_path, monkeypatch):
    data = b"0123456789"
    (tmp_path/"a.dat").write_bytes(data[:4])
    wget = Wget([(0, data[4:], "")])
    monkeypatch.setattr(od.subprocess, "run", wget)
    path, size = od.fetch("a.dat", tmp_path, {}, hashlib.sha256(data).hexdigest())
    assert path.read_bytes() == data and size == len(data) and "-c" in wget.calls[0]


def test_fetch_restarts_a_corrupt_file_and_skips_a_verified_one(tmp_path, monkeypatch):
    data = b"abc"
    monkeypatch.setattr(od.subprocess, "run", Wget([(0, b"xyz", ""), (0, data, "")]))
    od.fetch("b.dat", tmp_path, {}, hashlib.sha256(data).hexdigest())
    assert (tmp_path/"b.dat").read_bytes() == data
    monkeypatch.setattr(od.subprocess, "run", Wget([]))
    assert od.fetch("b.dat", tmp_path, {}, hashlib.sha256(data).hexdigest())[1] == 0


@pytest.mark.parametrize("code, stderr", [(od.WGET_AUTH_FAILED, "Username/Password Authentication Failed."),
                                          (od.WGET_SERVER_ERROR, "ERROR 403: Forbidden.")])
def test_fetch_stops_on_rejected_credentials(tmp_path, monkeypatch, code, stderr):
    monkeypatch.setattr(od.subprocess, "run", Wget([(code, None, stderr)]))
    with pytest.raises(PermissionError):
        od.fetch("c.dat", tmp_path, {}, "0"*64)


def test_fetch_retries_a_server_error_that_is_not_a_denial(tmp_path, monkeypatch):
    data = b"ok"
    monkeypatch.setattr(od.subprocess, "run", Wget([(od.WGET_SERVER_ERROR, None, "ERROR 503: Service Unavailable."),
                                                    (0, data, "")]))
    assert od.fetch("d.dat", tmp_path, {}, hashlib.sha256(data).hexdigest())[0].read_bytes() == data


def test_wgetrc_is_private_and_keeps_the_password_off_the_command_line(tmp_path, monkeypatch):
    rc = od.wgetrc("someone", "not-a-real-password", tmp_path)
    assert stat.S_IMODE(rc.stat().st_mode) == 0o600
    wget = Wget([(0, b"x", "")])
    monkeypatch.setattr(od.subprocess, "run", wget)
    od.fetch("e.dat", tmp_path/"out", {"WGETRC": str(rc)})
    assert not any("not-a-real-password" in a for a in wget.calls[0])
    with pytest.raises(ValueError):
        od.wgetrc("someone", "two\nlines", tmp_path)


def test_missing_credentials_name_the_secrets(monkeypatch):
    monkeypatch.delenv("PHYSIONET_USER", raising=False)
    monkeypatch.delenv("PHYSIONET_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="PHYSIONET_PASSWORD"):
        od.credentials()
