"""
config_store.py — Non-volatile configuration persistence for PPG Signal Simulator

Saves the current condition and last parameters to config.json.
Restores state on reboot.
"""

import json
import os
from typing import Optional

from config import CONFIG_JSON_PATH
from calibration import (
    SPO2_COEFF_A_DEFAULT,
    SPO2_COEFF_B_DEFAULT,
    validate_coefficients,
    validate_ac_dc,
)
from comm.logger import log

# Phase 3 AC/DC/polarity defaults. Sourced from the model so there is a single
# source of truth for the default per-channel DC and polarity. models.ppg_model
# does not import config_store, so this module-level import introduces no cycle.
from models.ppg_model import DEFAULT_DC_BASELINE_V, POLARITY_ABOVE_DC, POLARITY_BELOW_DC

_DEFAULT_DC_MV = DEFAULT_DC_BASELINE_V * 1000.0    # 1500.0 mV


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
    # SpO2 calibration coefficients (SpO2 = A - B*R). Added in Phase 2.
    # Older config.json files lack these keys; load_config merges defaults,
    # so they load as 110/25 — backward compatible.
    "spo2_coeff_a": SPO2_COEFF_A_DEFAULT,
    "spo2_coeff_b": SPO2_COEFF_B_DEFAULT,
    # Phase 3: independent per-channel DC (mV) and AC polarity. Older config.json
    # files lack these; merge yields DC_ir = DC_red = 1500 mV and above-DC
    # polarity — the legacy equal-DC pulse-up model — backward compatible.
    "dc_ir_mv": _DEFAULT_DC_MV,
    "dc_red_mv": _DEFAULT_DC_MV,
    "ac_polarity": POLARITY_ABOVE_DC,
}


_EXTRA_FIELDS = (
    "waveform", "ac_ir_mv", "ac_red_mv", "output_dc_offset_mv", "lock_ac", "lock_dc",
    "sp_ms_ir", "dn_ms_ir", "dp_ms_ir", "sp_ms_red", "dn_ms_red", "dp_ms_red",
    "resp_ie_ratio", "resp_mod_baseline", "resp_mod_amplitude", "resp_mod_frequency",
    "resp_variation_ir_pct", "resp_variation_red_pct", "apnea_enabled",
    "apnea_duration_s", "apnea_cycle_min", "noise_kind", "noise_amplitude_mv",
    "noise_freq_hz", "noise_seed", "hr_amplitude_enabled", "spo2_coupling_enabled", "variability_enabled",
)


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
        if not isinstance(data, dict):
            raise ValueError("configuration must be an object")
        merged.update(data)
        log.info(f"Configuration loaded from {CONFIG_JSON_PATH}")
        log.debug(f"Loaded config: {merged}")
        return merged
    except (ValueError, OSError) as e:
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
    import tempfile
    temporary = None
    try:
        target = os.path.abspath(CONFIG_JSON_PATH)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(target),
                                         prefix=".ppg-config-", delete=False) as handle:
            temporary = handle.name
            json.dump(config, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return True
    except (OSError, ValueError, TypeError) as exc:
        log.error(f"Failed to save config: {exc}")
        return False
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def config_from_ppg_params(params) -> dict:
    """
    Convert a PPGParameters-like object to a config dictionary.

    Args:
        params: Object with PPG parameter attributes.

    Returns:
        Configuration dictionary suitable for save_config().
    """
    result = {
        "condition": params.condition,
        "heart_rate": params.heart_rate,
        "perfusion_index": params.perfusion_index,
        "spo2": params.spo2,
        "resp_rate": params.resp_rate,
        "noise_level": params.noise_level,
        "dicrotic_notch": params.dicrotic_notch,
        "amplification": params.amplification,
        "spo2_coeff_a": getattr(params, "spo2_coeff_a", SPO2_COEFF_A_DEFAULT),
        "spo2_coeff_b": getattr(params, "spo2_coeff_b", SPO2_COEFF_B_DEFAULT),
        # Phase 3: per-channel DC (mV) + polarity. getattr defaults keep this
        # working for params-like objects without the Phase 3 fields.
        "dc_ir_mv": getattr(params, "dc_ir_mv", _DEFAULT_DC_MV),
        "dc_red_mv": getattr(params, "dc_red_mv", _DEFAULT_DC_MV),
        "ac_polarity": getattr(params, "ac_polarity", POLARITY_ABOVE_DC),
    }
    for name in _EXTRA_FIELDS:
        if hasattr(params, name):
            result[name] = getattr(params, name)
    return result



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

    # SpO2 calibration coefficients: validate on load; fall back to defaults on
    # corrupted/invalid persisted values rather than crashing or storing a
    # non-invertible mapping (B <= 0 / non-finite).
    a = config.get("spo2_coeff_a", SPO2_COEFF_A_DEFAULT)
    b = config.get("spo2_coeff_b", SPO2_COEFF_B_DEFAULT)
    try:
        a, b = validate_coefficients(a, b)
    except ValueError as e:
        log.warning(f"Invalid persisted SpO2 coefficients ({e}); using defaults "
                    f"{SPO2_COEFF_A_DEFAULT}/{SPO2_COEFF_B_DEFAULT}")
        a, b = SPO2_COEFF_A_DEFAULT, SPO2_COEFF_B_DEFAULT
    if hasattr(params, "spo2_coeff_a"):
        params.spo2_coeff_a = a
        params.spo2_coeff_b = b

    # Phase 3: per-channel DC (mV) + polarity. Validate each DC against the DAC
    # headroom (0 < DC <= full-scale) via validate_ac_dc with AC=0; fall back to
    # the default DC on invalid/corrupt values rather than crashing. Polarity
    # must be a known enum value, else fall back to above-DC.
    dc_ir = config.get("dc_ir_mv", _DEFAULT_DC_MV)
    dc_red = config.get("dc_red_mv", _DEFAULT_DC_MV)
    try:
        _, dc_ir = validate_ac_dc(0.0, dc_ir)
    except ValueError as e:
        log.warning(f"Invalid persisted dc_ir_mv ({e}); using default {_DEFAULT_DC_MV}")
        dc_ir = _DEFAULT_DC_MV
    try:
        _, dc_red = validate_ac_dc(0.0, dc_red)
    except ValueError as e:
        log.warning(f"Invalid persisted dc_red_mv ({e}); using default {_DEFAULT_DC_MV}")
        dc_red = _DEFAULT_DC_MV
    polarity = config.get("ac_polarity", POLARITY_ABOVE_DC)
    if polarity not in (POLARITY_ABOVE_DC, POLARITY_BELOW_DC):
        log.warning(f"Invalid persisted ac_polarity ({polarity!r}); using above-DC")
        polarity = POLARITY_ABOVE_DC
    if hasattr(params, "dc_ir_mv"):
        params.dc_ir_mv = dc_ir
        params.dc_red_mv = dc_red
        params.ac_polarity = polarity

    from models.ppg_model import PPGParameters
    from models.waveform import validate_kind
    from models.noise import NOISE_KINDS
    from models import limits
    defaults = PPGParameters()
    for name in _EXTRA_FIELDS:
        value = config.get(name, getattr(defaults, name))
        default = getattr(defaults, name)
        try:
            if name == "waveform":
                value = validate_kind(value)
            elif name == "noise_kind":
                if value not in NOISE_KINDS:
                    raise ValueError("unknown noise kind")
            elif isinstance(default, bool):
                if not isinstance(value, bool):
                    raise ValueError("expected boolean")
            elif value is not None:
                import math
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("expected finite number")
                if name == "noise_seed" and not isinstance(value, int):
                    raise ValueError("seed must be an integer")
            if hasattr(params, name):
                setattr(params, name, value)
        except (ValueError, TypeError):
            setattr(params, name, default)
    # Validate persisted numeric fields individually. Legacy files retain defaults.
    fields = {"heart_rate": limits.HEART_RATE, "perfusion_index": limits.PERFUSION_INDEX,
              "spo2": limits.SPO2, "resp_rate": limits.RESP_RATE,
              "noise_level": limits.NOISE_LEVEL, "dicrotic_notch": limits.DICROTIC_NOTCH_DEPTH,
              "amplification": limits.AMPLIFICATION, "output_dc_offset_mv": limits.OUTPUT_DC_OFFSET_MV,
              "resp_variation_ir_pct": limits.RESP_VARIATION_PCT,
              "resp_variation_red_pct": limits.RESP_VARIATION_PCT,
              "apnea_duration_s": limits.APNEA_DURATION_S, "apnea_cycle_min": limits.APNEA_CYCLE_MIN}
    for name, span in fields.items():
        if hasattr(params, name) and not span.contains(getattr(params, name)):
            setattr(params, name, getattr(defaults, name))
    if params.resp_ie_ratio not in limits.INHALE_EXHALE_RATIOS:
        params.resp_ie_ratio = defaults.resp_ie_ratio
    for channel in ("ir", "red"):
        names = [kind + "_ms_" + channel for kind in ("sp", "dn", "dp")]
        values = [getattr(params, name) for name in names]
        if not (all(limits.FEATURE_TIME_MS.contains(v) for v in values) and values[0] < values[1] < values[2]):
            for name in names:
                setattr(params, name, getattr(defaults, name))
    for name in ("ac_ir_mv", "ac_red_mv"):
        value = getattr(params, name)
        if value is not None and not 0 <= value <= 3000:
            setattr(params, name, None)
    if params.apnea_duration_s >= params.apnea_cycle_min * 60:
        params.apnea_enabled = False
    if max(params.dc_ir_mv, params.dc_red_mv) + params.output_dc_offset_mv > limits.DC_PLUS_OFFSET_MAX_MV:
        params.output_dc_offset_mv = 0.0
    if params.condition not in range(6):
        params.condition = 0

    # Check the noise tuple as a unit; e.g. sine with 0 Hz is invalid even
    # though each number is individually finite. Invalid stored tuples reset.
    from models.noise import NoiseGenerator
    from config import MODEL_SAMPLE_RATE_PPG
    try:
        if params.noise_seed is not None and not isinstance(params.noise_seed, int):
            raise ValueError("invalid seed")
        gen = NoiseGenerator(MODEL_SAMPLE_RATE_PPG, seed=params.noise_seed)
        gen.configure(params.noise_kind, amplitude_mv=params.noise_amplitude_mv,
                      freq_hz=params.noise_freq_hz, level=params.noise_level)
    except (ValueError, TypeError):
        for name in ("noise_kind", "noise_amplitude_mv", "noise_freq_hz", "noise_seed", "noise_level"):
            setattr(params, name, getattr(defaults, name))
