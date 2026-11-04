"""Download the OpenOximetry 1.1.1 files that data_openox reads (tables it needs and every discrete PPG record), with
the user's own PhysioNet credentials, parallel connections, resume and SHA-256 checks against SHA256SUMS.txt.

physionet.org serves about 4 KB/s per connection to the laptop and about 40 KB/s per connection to a Kaggle host
(measured 2026-10-22 on an open-access file), so round 13 downloads inside its private Kaggle kernel into /tmp; the
files are never written to the kernel outputs. Credentials come from the environment or the kernel's Kaggle Secrets
(PHYSIONET_USER, PHYSIONET_PASSWORD) and are never printed or written outside a private temporary wgetrc.

Files are fetched with wget, the client PhysioNet documents for its restricted projects: on 2026-10-22 physionet.org
answered a restricted file with 403 and no login challenge for the python-requests client, and with a 401 Basic
challenge for wget (both without credentials; open-access files returned 200 to both).
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

BASE = "https://physionet.org/files/openox-repo/1.1.1/"
TABLES = ("SHA256SUMS.txt", "RECORDS", "encounter.csv", "LICENSE.txt")
WGET_AUTH_FAILED, WGET_SERVER_ERROR = 6, 8   # wget exit statuses
TIMEOUT_S = 120


def credentials():
    user, password = os.environ.get("PHYSIONET_USER"), os.environ.get("PHYSIONET_PASSWORD")
    if not (user and password):
        try:
            from kaggle_secrets import UserSecretsClient
            client = UserSecretsClient()
            user, password = client.get_secret("PHYSIONET_USER"), client.get_secret("PHYSIONET_PASSWORD")
        except Exception as error:          # the client raises its own types when a secret is not attached
            raise RuntimeError("PhysioNet credentials missing: attach the Kaggle Secrets PHYSIONET_USER and "
                               "PHYSIONET_PASSWORD to this notebook") from error
    return user, password


def wgetrc(user, password, directory):
    """wget startup file holding the login, readable by this user only, so it is never on a command line or in a log."""
    if any(c in s for s in (user, password) for c in "\r\n"):
        raise ValueError("PhysioNet credentials must be single-line")
    path = Path(directory)/"wgetrc"
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(f"user = {user}\npassword = {password}\n")
    return path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(relative, dest, env, expected=None, tries=8):
    """Resume-capable download of one file with wget -c; verified when its checksum is known."""
    path = Path(dest)/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if expected and path.exists() and sha256(path) == expected:
        return path, 0
    for attempt in range(tries):
        done = subprocess.run(["wget", "-nv", "-c", "-nd", "--tries=1", f"--timeout={TIMEOUT_S}",
                               "-P", str(path.parent), BASE+relative], env=env, capture_output=True, text=True)
        if done.returncode == WGET_AUTH_FAILED:
            raise PermissionError("PhysioNet rejected the credentials (401)")
        if done.returncode == WGET_SERVER_ERROR and "403" in done.stderr:
            raise PermissionError("PhysioNet denied access (403): sign the data use agreement first")
        if done.returncode == 0 and path.exists():
            if expected is None or sha256(path) == expected:
                return path, path.stat().st_size
            path.unlink()                           # corrupt: start this file again
        time.sleep(min(60, 5*2**attempt))
    raise RuntimeError(f"OpenOximetry download failed after {tries} tries: {relative}")


def download_openox(dest, threads=8, log=print):
    if shutil.which("wget") is None:
        raise RuntimeError("wget is required to download OpenOximetry")
    user, password = credentials()
    dest = Path(dest)
    with tempfile.TemporaryDirectory() as private:
        env = dict(os.environ, WGETRC=str(wgetrc(user, password, private)))
        fetch("SHA256SUMS.txt", dest, env)
        sums = {line.split()[1]: line.split()[0] for line in (dest/"SHA256SUMS.txt").read_text().splitlines()
                if line.strip()}
        for name in TABLES[1:]:
            fetch(name, dest, env, sums[name])
        records = [r for r in (dest/"RECORDS").read_text().split() if r.endswith("_ppg")]
        files = sorted((r+s for r in records for s in (".hea", ".dat")), key=lambda f: not f.endswith(".hea"))
        start, total = time.monotonic(), 0
        with ThreadPoolExecutor(threads) as pool:
            for i, (_, size) in enumerate(pool.map(lambda f: fetch(f, dest, env, sums[f]), files), 1):
                total += size
                if i % 50 == 0 or i == len(files):
                    log(f"openox files {i}/{len(files)}, {total/1e6:.1f} MB, "
                        f"{total/max(time.monotonic()-start, 1)/1e3:.1f} kB/s")
    return dest, dict(files=len(files), records=len(records), bytes=total, seconds=time.monotonic()-start)
