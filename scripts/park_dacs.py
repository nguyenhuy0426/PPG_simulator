#!/usr/bin/env python3
"""park_dacs.py — Drive both MCP4725 DACs to the safe idle code (0 V, LEDs off).

The systemd user unit runs this as ExecStopPost= after every exit of main.py.
After a clean stop main.py has already parked the outputs, so this second write
of DAC_IDLE_VALUE changes nothing. After a crash (a signal or a non-zero exit)
nothing else parks them: an MCP4725 holds its last code until it is written
again, so without this the LEDs stay lit until the restarted instance calls
DACManager.begin(), or for good once the unit's start limit trips.

systemd runs ExecStopPost only after every process of the unit has exited, so
nothing else is on the I2C bus at the DACs' addresses.

Exit status:
    0  both DACs written, or nothing to do (PPG_DRY_RUN=1 / --dry-run, or the
       DACs did not answer, e.g. on a laptop without I2C hardware)
    1  a write failed or the park did not finish within PARK_TIMEOUT_S

Usage:
    .venv/bin/python scripts/park_dacs.py [--dry-run]
"""

import argparse
import os
import signal
import sys

# Bounds the whole park: imports, bus open and two 2-byte writes. Ubuntu stops
# the user manager within 5 s at reboot (user@.service.d/timeout.conf), and the
# app's own SIGTERM path has to fit in that too.
PARK_TIMEOUT_S = 3

parser = argparse.ArgumentParser(description="Park both MCP4725 DACs at 0 V.")
parser.add_argument("--dry-run", action="store_true", help="Do not touch the I2C bus")
args = parser.parse_args()
if args.dry_run:
    os.environ["PPG_DRY_RUN"] = "1"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _timed_out(_signum, _frame):
    # Async-signal context: no logging (its handler lock may be held).
    os.write(2, f"[park_dacs] DACs not parked: timed out after {PARK_TIMEOUT_S} s\n".encode())
    os._exit(1)


signal.signal(signal.SIGALRM, _timed_out)
signal.alarm(PARK_TIMEOUT_S)

from config import DAC_ADDR_IR, DAC_ADDR_RED, DAC_IDLE_VALUE, DRY_RUN  # noqa: E402
from comm.logger import log  # noqa: E402
from hw.dac_manager import DACManager  # noqa: E402

# systemd passes how the main process ended to ExecStopPost=.
cause = " ".join(f"{name}={os.environ[name]}"
                 for name in ("SERVICE_RESULT", "EXIT_CODE", "EXIT_STATUS") if name in os.environ)
suffix = f" ({cause})" if cause else ""

if DRY_RUN:
    log.info(f"[park_dacs] DRY-RUN — no DAC write{suffix}")
    sys.exit(0)

dacs = DACManager()
# begin() opens the bus, probes 0x60 and 0x61 and writes DAC_IDLE_VALUE to both.
if not dacs.begin():
    log.info(f"[park_dacs] DACs did not answer — nothing parked{suffix}")
    sys.exit(0)

signal.alarm(0)
if dacs.error_count_ir or dacs.error_count_red:
    log.error(f"[park_dacs] DAC park write failed (IR 0x{DAC_ADDR_IR:02X}: {dacs.error_count_ir}, "
              f"Red 0x{DAC_ADDR_RED:02X}: {dacs.error_count_red} errors){suffix}")
    sys.exit(1)
log.info(f"[park_dacs] Both DACs parked at code {DAC_IDLE_VALUE} (0 V){suffix}")
sys.exit(0)
