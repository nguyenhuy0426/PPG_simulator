"""main.py --ble-secure / --no-ble-secure reach the GATT table the BLE server
registers.

main.py parses its arguments at import time and its headless --ble-only path
starts a real BLE backend, so each case runs main.py in a subprocess with a
stub `bless` package first on PYTHONPATH. The stub records the permissions of
every characteristic and refuses to start, so --ble-only exits with status 1
right after registration: no D-Bus, no BlueZ, no advertising, no config saved.

Run: PPG_DRY_RUN=1 python3 -m pytest tests/test_main_ble_flags.py -q
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from comm.ble_server import NOTIFY_UUID, SECURE_WRITES_DEFAULT, STATUS_UUID, WRITE_UUID

ROOT = Path(__file__).resolve().parents[1]

# GATTAttributePermissions values in bless 0.3.0 (bless/backends/attribute.py).
READABLE, WRITEABLE, WRITE_ENCRYPTION_REQUIRED = 0x1, 0x2, 0x8

STUB_BLESS = {
    "bless/__init__.py": """
        import json
        import os


        class BlessServer:
            def __init__(self, name, loop=None, **kwargs):
                self.table = {}

            async def add_new_service(self, uuid):
                pass

            async def add_new_characteristic(self, service_uuid, char_uuid, properties,
                                             value, permissions):
                self.table[char_uuid] = permissions.value

            async def start(self, **kwargs):
                with open(os.environ["BLESS_STUB_RECORD"], "w", encoding="utf-8") as fh:
                    json.dump(self.table, fh)
                return False
        """,
    "bless/backends/__init__.py": "",
    "bless/backends/attribute.py": """
        from enum import Flag


        class GATTAttributePermissions(Flag):
            readable = 0x1
            writeable = 0x2
            read_encryption_required = 0x4
            write_encryption_required = 0x8
        """,
    "bless/backends/characteristic.py": """
        from enum import Flag


        class GATTCharacteristicProperties(Flag):
            read = 0x2
            write_without_response = 0x4
            write = 0x8
            notify = 0x10
        """,
}


def run_headless_main(tmp_path, *flags):
    """Run main.py --dry-run --ble-only against the stub; return its GATT table."""
    stub = tmp_path / "stub"
    for relative, source in STUB_BLESS.items():
        path = stub / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")
    record = tmp_path / "gatt_table.json"

    env = {key: value for key, value in os.environ.items() if not key.startswith("PPG_BLE_")}
    env.update(PYTHONPATH=str(stub), PPG_DRY_RUN="1", PPG_LOG_ENABLED="0",
               BLESS_STUB_RECORD=str(record))
    proc = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--dry-run", "--ble-only", *flags],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    output = proc.stdout + proc.stderr
    # The stub refuses to advertise, so headless mode must give up with status 1.
    assert proc.returncode == 1, output
    assert "advertising failed" in output, output
    assert record.exists(), output
    return json.loads(record.read_text(encoding="utf-8"))


@pytest.mark.parametrize("flags, secure", [
    ((), SECURE_WRITES_DEFAULT),
    (("--ble-secure",), True),
    (("--no-ble-secure",), False),
])
def test_main_flag_sets_command_write_permissions(tmp_path, flags, secure):
    table = run_headless_main(tmp_path, *flags)
    encryption = WRITE_ENCRYPTION_REQUIRED if secure else 0
    assert table[WRITE_UUID] == READABLE | WRITEABLE | encryption
    assert table[NOTIFY_UUID] == READABLE
    assert table[STATUS_UUID] == READABLE
