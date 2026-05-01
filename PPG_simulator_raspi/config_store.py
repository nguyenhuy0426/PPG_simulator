"""
config_store.py — Non-volatile configuration persistence for PPG Signal Simulator

Saves the current condition and last parameters to config.json.
Restores state on reboot.
"""

import json
import os
from typing import Optional

from config import CONFIG_JSON_PATH
from comm.logger import log


# Default configuration values
_DEFAULTS = {
    "condition": 0,
    "heart_rate": 75.0,
    "perfusion_index": 3.0,
    "spo2": 98.0,
    "resp_rate": 16.0,
    "noise_level": 0.0,
    "dicrotic_notch": 0.25,
    "amplification": 1.0,
    "edit_mode": 0,
}


def load_config() -> dict:
    """
    Load configuration from config.json.
    Returns defaults if the file doesn't exist or is corrupted.
    """
    if not os.path.exists(CONFIG_JSON_PATH):
        log.info(f"No config file found at {CONFIG_JSON_PATH}, using defaults")
        return dict(_DEFAULTS)

    try:
        with open(CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults to fill any missing keys
        merged = dict(_DEFAULTS)
        merged.update(data)
        log.info(f"Configuration loaded from {CONFIG_JSON_PATH}")
        log.debug(f"Loaded config: {merged}")
        return merged
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to load config: {e}, using defaults")
        return dict(_DEFAULTS)


def save_config(config: dict) -> bool:
    """
    Save configuration to config.json.

    Args:
        config: Dictionary with configuration values.

    Returns:
        True if saved successfully.
    """
    try:
        with open(CONFIG_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, sort_keys=True)
        log.debug(f"Configuration saved to {CONFIG_JSON_PATH}")
        return True
    except OSError as e:
        log.error(f"Failed to save config: {e}")
        return False


def config_from_ppg_params(params) -> dict:
    """
    Convert a PPGParameters-like object to a config dictionary.

    Args:
        params: Object with PPG parameter attributes.

    Returns:
        Configuration dictionary suitable for save_config().
    """
    return {
        "condition": params.condition,
        "heart_rate": params.heart_rate,
        "perfusion_index": params.perfusion_index,
        "spo2": params.spo2,
        "resp_rate": params.resp_rate,
        "noise_level": params.noise_level,
        "dicrotic_notch": params.dicrotic_notch,
        "amplification": params.amplification,
    }


def apply_config_to_params(config: dict, params):
    """
    Apply a config dictionary to a PPGParameters-like object.

    Args:
        config: Configuration dictionary.
        params: Object with PPG parameter attributes to update.
    """
    params.condition = config.get("condition", 0)
    params.heart_rate = config.get("heart_rate", 75.0)
    params.perfusion_index = config.get("perfusion_index", 3.0)
    params.spo2 = config.get("spo2", 98.0)
    params.resp_rate = config.get("resp_rate", 16.0)
    params.noise_level = config.get("noise_level", 0.0)
    params.dicrotic_notch = config.get("dicrotic_notch", 0.25)
    params.amplification = config.get("amplification", 1.0)
