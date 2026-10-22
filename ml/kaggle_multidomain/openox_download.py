"""Download the OpenOximetry 1.1.1 files that data_openox reads (tables it needs and every discrete PPG record), with
the user's own PhysioNet credentials, parallel connections, resume and SHA-256 checks against SHA256SUMS.txt.

physionet.org serves about 4 KB/s per connection to the laptop and about 40 KB/s per connection to a Kaggle host
(measured 2026-10-22 on an open-access file), so round 13 downloads inside its private Kaggle kernel into /tmp; the
files are never written to the kernel outputs. Credentials come from the environment or the kernel's Kaggle Secrets
(PHYSIONET_USER, PHYSIONET_PASSWORD) and are never printed or written.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import time

BASE = "https://physionet.org/files/openox-repo/1.1.1/"
TABLES = ("SHA256SUMS.txt", "RECORDS", "encounter.csv", "LICENSE.txt")
CHUNK = 1 << 16


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


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(session, relative, dest, expected=None, tries=8):
    """Resume-capable download of one file; verified when its checksum is known."""
    import requests
    path = Path(dest)/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if expected and path.exists() and sha256(path) == expected:
        return path, 0
    for attempt in range(tries):
        done = path.stat().st_size if path.exists() else 0
        try:
            with session.get(BASE+relative, headers={"Range": f"bytes={done}-"} if done else {}, stream=True,
                             timeout=(30, 120)) as r:
                if r.status_code == 401:
                    raise PermissionError("PhysioNet rejected the credentials (401)")
                if r.status_code == 403:
                    raise PermissionError("PhysioNet denied access (403): sign the data use agreement first")
                if r.status_code == 416:            # already complete
                    pass
                else:
                    r.raise_for_status()
                    with open(path, "ab" if done and r.status_code == 206 else "wb") as f:
                        for block in r.iter_content(CHUNK):
                            f.write(block)
            if expected is None or sha256(path) == expected:
                return path, path.stat().st_size
            path.unlink()                           # corrupt: start this file again
        except (requests.RequestException, OSError) as error:
            if isinstance(error, PermissionError):
                raise
            time.sleep(min(60, 5*2**attempt))
    raise RuntimeError(f"OpenOximetry download failed after {tries} tries: {relative}")


def download_openox(dest, threads=8, log=print):
    import requests
    user, password = credentials()
    session = requests.Session()
    session.auth = (user, password)
    adapter = requests.adapters.HTTPAdapter(pool_connections=threads, pool_maxsize=threads)
    session.mount("https://", adapter)
    dest = Path(dest)
    fetch(session, "SHA256SUMS.txt", dest)
    sums = {line.split()[1]: line.split()[0] for line in (dest/"SHA256SUMS.txt").read_text().splitlines() if line.strip()}
    for name in TABLES[1:]:
        fetch(session, name, dest, sums[name])
    records = [r for r in (dest/"RECORDS").read_text().split() if r.endswith("_ppg")]
    files = sorted((r+s for r in records for s in (".hea", ".dat")), key=lambda f: not f.endswith(".hea"))
    start, total = time.monotonic(), 0
    with ThreadPoolExecutor(threads) as pool:
        for i, (_, size) in enumerate(pool.map(lambda f: fetch(session, f, dest, sums[f]), files), 1):
            total += size
            if i % 50 == 0 or i == len(files):
                log(f"openox files {i}/{len(files)}, {total/1e6:.1f} MB, {total/max(time.monotonic()-start, 1)/1e3:.1f} kB/s")
    return dest, dict(files=len(files), records=len(records), bytes=total, seconds=time.monotonic()-start)
