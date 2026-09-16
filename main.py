#!/usr/bin/env python3
"""
main.py — PPG Signal Simulator for Raspberry Pi 4 (CustomTkinter GUI)

Usage:
    python3 main.py                        # Normal mode + BLE (requires RPi hardware)
    python3 main.py --dry-run              # Dry-run + BLE (no hardware, simulated I/O)
    python3 main.py --no-ble               # Diagnostic GUI mode without BLE
    python3 main.py --dry-run --ble-only   # Headless: engine + BLE, no GUI (testing/CI)
"""

import sys
import os
import argparse
import time

# Parse --dry-run before importing config
parser = argparse.ArgumentParser(description="PPG Signal Simulator for Raspberry Pi 4")
parser.add_argument("--dry-run", action="store_true", help="Run without hardware (simulated I/O)")
parser.add_argument("--ble", action="store_true",
                    help="Deprecated compatibility flag; BLE starts by default")
parser.add_argument("--no-ble", action="store_true",
                    help="Disable the BLE GATT server (diagnostics only)")
parser.add_argument("--ble-only", action="store_true",
                    help="Headless mode: engine + BLE server, no GUI (Ctrl+C to stop)")
args = parser.parse_args()

if args.dry_run:
    os.environ["PPG_DRY_RUN"] = "1"

from config import DEVICE_NAME, FIRMWARE_VERSION, FIRMWARE_DATE, DRY_RUN
from comm.logger import log
from config_store import load_config, save_config, config_from_ppg_params, apply_config_to_params
from core.signal_engine import SignalEngine
from hw.opt101_rx import OPT101Receiver
from ui.ctk_app import CTkApp


def start_ble(engine):
    """Start the BLE GATT server; returns the BleServer or None on failure."""
    try:
        from comm.ble_server import BleServer
    except ImportError as exc:
        log.error(f"BLE unavailable ({exc}) — install with: pip install -r requirements/ble.txt")
        return None
    ble = BleServer(engine)
    try:
        ble.start()
    except RuntimeError as exc:
        log.error(f"BLE unavailable: {exc}")
        return None
    return ble


def save_current_config(engine):
    try:
        p = engine.get_ppg_params()
        cfg = config_from_ppg_params(p)
        cfg["condition"] = p.condition
        save_config(cfg)
    except Exception as e:
        log.error(f"Failed to save config: {e}")


def main():
    log.info("=" * 50)
    log.info(f"  {DEVICE_NAME} v{FIRMWARE_VERSION}")
    log.info(f"  {FIRMWARE_DATE}")
    log.info(f"  Mode: {'DRY-RUN' if DRY_RUN else 'HARDWARE'}")
    log.info("=" * 50)

    engine = SignalEngine.get_instance()
    engine.begin()

    # Phase 5: OPT101 RX acquisition (Grove ADC 0x08, IR=A0 / Red=A2).
    # RX failure must not block TX/UI — the app degrades to TX-only.
    rx = OPT101Receiver.get_instance()
    if rx.begin():
        rx.start()
    else:
        log.error("RX unavailable — continuing TX-only (no OPT101 acquisition)")

    # Load config
    config = load_config()
    p = engine.get_ppg_params()
    apply_config_to_params(config, p)
    engine.load_parameters(p)

    # BLE remote control starts with every normal Pi app launch.  --no-ble is
    # retained only as a recovery/diagnostic escape hatch; --ble remains a
    # harmless compatibility flag for existing launchers.
    ble_server = None
    if not args.no_ble or args.ble_only:
        ble_server = start_ble(engine)

    # ─── Headless BLE mode: no GUI, run until interrupted ────────────────────
    if args.ble_only:
        if ble_server is None:
            rx.shutdown()
            engine.shutdown()
            sys.exit(1)
        log.info("Headless BLE mode — simulation auto-starts, press Ctrl+C to stop")
        try:
            engine.start_simulation(engine.get_ppg_params().condition)
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("Interrupted by user")
        finally:
            if ble_server is not None:
                ble_server.stop()
            save_current_config(engine)
            rx.shutdown()
            engine.shutdown()
            log.info("Shutdown complete.")
        return

    # ─── Normal GUI mode (BLE enabled by default) ─────────────────────────────
    # Simulation will be started manually via the GUI

    # Initialize UI
    app = CTkApp()

    try:
        app.mainloop()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        if ble_server is not None:
            ble_server.stop()
        save_current_config(engine)
        rx.shutdown()
        engine.shutdown()
        log.info("Shutdown complete.")


if __name__ == "__main__":
    main()
