"""
limits.py — single source of truth for user-adjustable parameter ranges.

Why this module exists
----------------------
Before v5, every range in the project was written down three times: once as a
clamp inside models/ppg_model.py, once as a slider min/max inside
ui/frames/pathology_frame.py, and once (implicitly) inside config_store.py.
They disagreed — the HR slider spanned 20-300 BPM while set_heart_rate()
clamped to 40-180, so the top and bottom thirds of the slider silently did
nothing. This module is the one place a range is declared; the model, the UI
and the persistence layer all read it from here.

Where the numbers come from
---------------------------
[BENCHMARK] The ranges are the UNION of the WhaleTeq AECG100 reflectance and
transmittance PPG/SpO2 module specifications, read from
docs/whale_device/user_manual.pdf (PC software 1.0.10.40, 2025-12-08):

    Table 7  PPG test mode, reflectance   BPM 10-300, PI 0.025-30 %,
                                          DC 100-3000 mV, AC 0.75-30 mV,
                                          feature times 0-1000 ms,
                                          noise 0.05-2.00 mV,
                                          respiration 1-150 BrPM,
                                          respiration variation 1-16 %,
                                          apnea 1-60 s / 1-10 min
    Table 10 SpO2 test mode, reflectance  SpO2 0-100 %, per-channel AC/DC,
                                          output DC offset 0-2000 mV with
                                          DC + offset <= 3000 mV
    Table 11 PPG test mode, transmittance PI 0.01-20 %, DC 300-3000 mV,
                                          AC 0.1-300 mV
    Table 13 SpO2 test mode, transmittance same as Table 11

The union is used because this simulator drives ONE hardware output path, not
two interchangeable optical modules; restricting it to the reflectance numbers
alone would make the transmittance operating points unreachable.

[HARDWARE] A range being reachable in software does NOT mean the analogue path
reproduces it. The MCP4725 full scale on this board is 3.28 V, so a 3000 mV DC
plus a 2000 mV offset (5000 mV) is rejected by validate_dc_with_offset() on
the AECG100 rule alone, and the DAC clamp in models/ppg_model.py rejects the
remainder. Nothing here has been validated against a bench measurement.

Stdlib only. No hardware access, no project imports beyond typing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Tuple

__all__ = [
    "Limit",
    "HEART_RATE",
    "PERFUSION_INDEX",
    "RESP_RATE",
    "SPO2",
    "DC_LEVEL_MV",
    "AC_LEVEL_MV",
    "OUTPUT_DC_OFFSET_MV",
    "FEATURE_TIME_MS",
    "FEATURE_AMPLITUDE_MV",
    "NOISE_AMPLITUDE_MV",
    "RESP_VARIATION_PCT",
    "APNEA_DURATION_S",
    "APNEA_CYCLE_MIN",
    "DICROTIC_NOTCH_DEPTH",
    "AMPLIFICATION",
    "NOISE_LEVEL",
    "DC_PLUS_OFFSET_MAX_MV",
    "INHALE_EXHALE_RATIOS",
    "all_limits",
    "validate_dc_with_offset",
    "inhale_fraction",
]


def _is_finite_number(value: Any) -> bool:
    """True only for a real, finite int/float. Rejects bool, NaN and inf.

    Mirrors calibration._is_finite_number so the two validation layers agree.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


@dataclass(frozen=True)
class Limit:
    """One adjustable parameter's range, resolution and default.

    Attributes:
        minimum: Smallest accepted value, inclusive.
        maximum: Largest accepted value, inclusive.
        default: Power-on value. Always inside [minimum, maximum].
        step: UI/protocol resolution. 0.0 means continuous (no quantisation).
        unit: Display unit, for labels and for the remote-control API.
        label: Human-readable parameter name.
    """

    minimum: float
    maximum: float
    default: float
    step: float
    unit: str
    label: str = ""

    def contains(self, value: float) -> bool:
        """True when `value` is a finite number inside the closed range."""
        if not _is_finite_number(value):
            return False
        return self.minimum <= float(value) <= self.maximum

    def clamp(self, value: float) -> float:
        """Return `value` restricted to the range. Non-numbers fall back to the default."""
        if not _is_finite_number(value):
            return self.default
        return min(self.maximum, max(self.minimum, float(value)))

    def validate(self, value: float) -> float:
        """Return `value` as a float, or raise ValueError if it is not admissible.

        Use this at a system boundary (remote API, text entry, file load) where
        a wrong value must be reported rather than silently corrected. Use
        clamp() on a slider, where silent correction is the expected behaviour.
        """
        if not _is_finite_number(value):
            raise ValueError(f"{self.label or 'value'} must be a finite number, got {value!r}")
        as_float = float(value)
        if not (self.minimum <= as_float <= self.maximum):
            raise ValueError(
                f"{self.label or 'value'} {as_float}{self.unit} outside "
                f"[{self.minimum}, {self.maximum}]{self.unit}"
            )
        return as_float

    def quantise(self, value: float) -> float:
        """Snap `value` to the nearest multiple of `step`, offset from `minimum`.

        A zero step means the parameter is continuous and the value is returned
        unchanged. Quantisation happens AFTER clamping so a snapped value can
        never leave the range.
        """
        clamped = self.clamp(value)
        if self.step <= 0.0:
            return clamped
        steps = round((clamped - self.minimum) / self.step)
        snapped = self.minimum + steps * self.step
        # Guard against float drift pushing the result outside the range.
        snapped = min(self.maximum, max(self.minimum, snapped))
        # Re-round to the step's own decimal resolution to avoid 0.30000000004.
        decimals = max(0, -int(math.floor(math.log10(self.step)))) + 3
        return round(snapped, decimals)


# ---------------------------------------------------------------------------
# Physiological parameters
# ---------------------------------------------------------------------------

HEART_RATE = Limit(10.0, 300.0, 75.0, 1.0, " BPM", "Heart rate")
"""AECG100 Table 7: BPM 10-300, step 1 (equivalently 0.17-5 Hz, step 0.01)."""

PERFUSION_INDEX = Limit(0.01, 30.0, 2.0, 0.001, " %", "Perfusion index")
"""Union of Table 7 (0.025-30 %) and Table 11 (0.01-20 %)."""

RESP_RATE = Limit(1.0, 150.0, 16.0, 1.0, " BrPM", "Respiration rate")
"""AECG100 Table 7 respiration: 1-150 BrPM, default 20 (we keep 16, the
adult-normal midpoint already used by this project's config default)."""

SPO2 = Limit(0.0, 100.0, 98.0, 1.0, " %", "SpO2")
"""AECG100 Table 10: 0-100 %, step 1, default 98."""

# ---------------------------------------------------------------------------
# Amplitude parameters (per channel)
# ---------------------------------------------------------------------------

DC_LEVEL_MV = Limit(100.0, 3000.0, 1500.0, 1.0, " mV", "DC level")
"""Union of Table 7/10 (100-3000 mV) and Table 11/13 (300-3000 mV).
Default stays 1500 mV: that is this project's existing persisted value and
changing it would silently alter every saved config."""

AC_LEVEL_MV = Limit(0.1, 300.0, 45.0, 0.01, " mV", "AC level")
"""Union of Table 7/10 (0.75-30 mV) and Table 11/13 (0.1-300 mV).
Default 45 mV = PERFUSION_INDEX 3 % x DC_LEVEL_MV 1500 mV, this project's
existing operating point."""

OUTPUT_DC_OFFSET_MV = Limit(0.0, 2000.0, 0.0, 1.0, " mV", "Output DC offset")
"""AECG100 Table 10 'Output DC': an extra DC pedestal added on top of the DC
level, used to fine-tune a DUT's measured-vs-set PI mismatch (manual 4.6)."""

DC_PLUS_OFFSET_MAX_MV = 3000.0
"""AECG100 Table 10 constraint: DC + Output DC offset <= 3000 mV."""

# ---------------------------------------------------------------------------
# Waveform morphology
# ---------------------------------------------------------------------------

FEATURE_TIME_MS = Limit(0.0, 1000.0, 150.0, 1.0, " ms", "Feature time")
"""AECG100 Table 7 time parameters, quoted at 60 BPM (one 1000 ms cycle):
Systolic Peak 150 ms, Dicrotic Notch 360 ms, Diastolic Peak 460 ms.
Because they are specified at 60 BPM, the simulator stores them as a fraction
of the cardiac cycle: fraction = time_ms / 1000."""

FEATURE_AMPLITUDE_MV = Limit(0.0, 300.0, 12.5, 0.01, " mV", "Feature amplitude")
"""AECG100 Table 7: SP/DN/DP each 0.75-30.00 mV. Extended to the
transmittance AC ceiling (300 mV) for the same reason as AC_LEVEL_MV, and
down to 0 so a feature can be switched off entirely (the AECG100 has no
'no dicrotic notch' setting; this project's condition presets do)."""

DICROTIC_NOTCH_DEPTH = Limit(0.0, 1.0, 0.25, 0.01, "", "Dicrotic notch depth")
"""Project-specific normalised notch depth, retained from v4."""

AMPLIFICATION = Limit(0.1, 5.0, 1.0, 0.01, " x", "Amplification")
"""Project-specific overall AC gain multiplier, retained from v4."""

# ---------------------------------------------------------------------------
# Artefacts
# ---------------------------------------------------------------------------

NOISE_AMPLITUDE_MV = Limit(0.0, 2.0, 0.0, 0.05, " mV", "Noise amplitude")
"""AECG100 Table 7 noise generator: 0.05-2.00 mV, step 0.05, default 0.
0 is included here because 'off' must be expressible as an amplitude."""

NOISE_LEVEL = Limit(0.0, 1.0, 0.0, 0.01, "", "Noise level")
"""Project-specific normalised proportional-noise level, retained from v4."""

# ---------------------------------------------------------------------------
# Respiration
# ---------------------------------------------------------------------------

RESP_VARIATION_PCT = Limit(0.0, 16.0, 4.0, 1.0, " %", "Respiration variation")
"""AECG100 Table 7: Variation R 1-16 %, IR 1-16 %, step 1 %. 0 is included so
a modulation can be disabled by depth as well as by its enable flag."""

APNEA_DURATION_S = Limit(1.0, 60.0, 10.0, 1.0, " s", "Apnea duration")
"""AECG100 Table 7 apnea: duration 1-60 s, default 10."""

APNEA_CYCLE_MIN = Limit(1.0, 10.0, 1.0, 1.0, " min", "Apnea cycle")
"""AECG100 Table 7 apnea: cycle 1-10 min, default 1."""

INHALE_EXHALE_RATIOS: Tuple[int, ...] = (1, 2, 3, 4, 5)
"""AECG100 Table 7: inhale-exhale ratio 1:1, 1:2, 1:3, 1:4, 1:5.
Stored as the exhale side of the ratio (inhale is always 1)."""


def inhale_fraction(exhale_ratio: int) -> float:
    """Fraction of a respiratory cycle spent inhaling, for a 1:N ratio.

    Args:
        exhale_ratio: The N in 1:N. Must be one of INHALE_EXHALE_RATIOS.

    Returns:
        1 / (1 + N) — e.g. 0.5 for 1:1, 0.2 for 1:4.

    Raises:
        ValueError: If the ratio is not one the AECG100 supports.
    """
    if exhale_ratio not in INHALE_EXHALE_RATIOS:
        raise ValueError(
            f"inhale:exhale ratio 1:{exhale_ratio} not supported; "
            f"expected one of {INHALE_EXHALE_RATIOS}"
        )
    return 1.0 / (1.0 + float(exhale_ratio))


def validate_dc_with_offset(dc_mv: float, offset_mv: float) -> Tuple[float, float]:
    """Validate a DC level together with its Output-DC offset.

    Enforces both individual ranges and the AECG100 sum rule
    DC + offset <= DC_PLUS_OFFSET_MAX_MV.

    Args:
        dc_mv: DC level in millivolts.
        offset_mv: Output DC offset in millivolts.

    Returns:
        The validated (dc_mv, offset_mv) pair as floats.

    Raises:
        ValueError: If either value is out of range or the sum exceeds the cap.
    """
    dc = DC_LEVEL_MV.validate(dc_mv)
    offset = OUTPUT_DC_OFFSET_MV.validate(offset_mv)
    total = dc + offset
    if total > DC_PLUS_OFFSET_MAX_MV:
        raise ValueError(
            f"DC {dc} mV + output offset {offset} mV = {total} mV exceeds the "
            f"{DC_PLUS_OFFSET_MAX_MV} mV limit"
        )
    return dc, offset


def all_limits() -> Dict[str, Limit]:
    """Every Limit declared in this module, keyed by its module-level name.

    Used by the remote-control API to publish the machine-readable parameter
    schema, and by tests to assert every default is inside its own range.
    """
    return {
        name: value
        for name, value in globals().items()
        if isinstance(value, Limit)
    }
