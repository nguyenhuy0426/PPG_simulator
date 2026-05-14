#!/usr/bin/env python3
"""
main.py — PPG Signal Simulator for Raspberry Pi 4 (CustomTkinter GUI)

Usage:
    python3 main.py                  # Normal mode (requires RPi hardware)
    python3 main.py --dry-run        # Dry-run mode (no hardware, simulated I/O)
"""

import sys
import os
import argparse

# Parse --dry-run before importing config
parser = argparse.ArgumentParser(description="PPG Signal Simulator for Raspberry Pi 4")
parser.add_argument("--dry-run", action="store_true", help="Run without hardware (simulated I/O)")
args = parser.parse_args()

if args.dry_run:
    os.environ["PPG_DRY_RUN"] = "1"

from config import DEVICE_NAME, FIRMWARE_VERSION, FIRMWARE_DATE, DRY_RUN
from comm.logger import log
from config_store import load_config, save_config, config_from_ppg_params, apply_config_to_params
from core.signal_engine import SignalEngine
from ui.ctk_app import CTkApp

def main():
    log.info("=" * 50)
    log.info(f"  {DEVICE_NAME} v{FIRMWARE_VERSION}")
    log.info(f"  {FIRMWARE_DATE}")
    log.info(f"  Mode: {'DRY-RUN' if DRY_RUN else 'HARDWARE'}")
    log.info("=" * 50)

    engine = SignalEngine.get_instance()
    engine.begin()
    
    # Load config
    config = load_config()
    p = engine.get_ppg_params()
    apply_config_to_params(config, p)
    
    # Start simulating by default
    engine.start_simulation(p.condition)
    
    # Initialize UI
    app = CTkApp()
    
    try:
        app.mainloop()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        # Save config
        try:
            p = engine.get_ppg_params()
            cfg = config_from_ppg_params(p)
            cfg["condition"] = p.condition
            save_config(cfg)
        except Exception as e:
            log.error(f"Failed to save config: {e}")
            
        engine.stop_simulation()
        log.info("Shutdown complete.")

if __name__ == "__main__":
    main()
