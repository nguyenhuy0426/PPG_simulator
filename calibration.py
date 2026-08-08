"""
calibration.py — SpO2 calibration model and DAC voltage scaling.

Single source of truth for two previously-duplicated concerns (Phase 2):

  1. SpO2 linear calibration coefficients (A, B) and the forward/inverse
     mapping between the ratio-of-ratios R and SpO2:
         SpO2      = A - B * R          (forward)
         R_target  = (A - SpO2) / B     (inverse)
     Default A=110.0, B=25.0 reproduce the WhaleTeq AECG100 default
     `SpO2 = 110.0 - 25.0 * R` (Webster linear). A/B are configurable so the
     same coefficients can later feed both target generation (Phase 3) and
     measured-SpO2 mapping (Phase 6). [VERIFIED-DATASHEET: Phase 1 §17,
     E1/E4/E5 — WhaleTeq AECG100 functional reference]

  2. MCP4725 DAC voltage->code conversion against the 3.28 V full-scale
     (config.DAC_FULLSCALE_V), replacing the 3.3 V hardcoding that was
     scattered across signal_engine, ppg_model and the calibration UI.

Phase 3 adds the pure, hardware-free AC/DC/PI and ratio-of-ratios primitives
below (perfusion_index_from_ac_dc, ratio_of_ratios, ac_red_from_target,
validate_ac_dc). The AC/DC-as-master *ownership/wiring* lives in
models/ppg_model.py; this module only holds the reusable math. It still does
NOT implement any acquisition/measurement path (Phase 5/6).
"""

import math
from dataclasses import dataclass

from config import DAC_FULLSCALE_V, DAC_FULLSCALE_MV, DAC_MAX_VALUE

# ─── SpO2 calibration defaults (WhaleTeq AECG100 Webster-linear default) ───
SPO2_COEFF_A_DEFAULT = 110.0
SPO2_COEFF_B_DEFAULT = 25.0

# Physiological clamp for the ratio-of-ratios R. Preserved verbatim from the
# prior hardcoded model (ppg_model previously clamped R to [0.4, 1.6]).
R_CLAMP_MIN = 0.4
R_CLAMP_MAX = 1.6


def _is_finite_number(value) -> bool:
    """True only for real, finite int/float (rejects bool, NaN, inf, non-numeric)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def validate_coefficients(a, b) -> tuple:
    """
    Validate SpO2 coefficients A and B.

    Rules (Phase 2 spec):
      - A and B must be finite numeric values.
      - B must be > 0 (B <= 0 would make the mapping non-invertible / non-physical).

    Returns:
        (float(a), float(b)) on success.

    Raises:
        ValueError: if A or B is non-finite/non-numeric, or if B <= 0.
    """
    if not _is_finite_number(a):
        raise ValueError(f"SpO2 coefficient A must be a finite number, got {a!r}")
    if not _is_finite_number(b):
        raise ValueError(f"SpO2 coefficient B must be a finite number, got {b!r}")
    b = float(b)
    if b <= 0.0:
        raise ValueError(f"SpO2 coefficient B must be > 0, got {b!r}")
    return float(a), b


def spo2_from_r(r: float, a: float = SPO2_COEFF_A_DEFAULT,
                b: float = SPO2_COEFF_B_DEFAULT) -> float:
    """Forward mapping: SpO2 = A - B * R. Coefficients are validated."""
    a, b = validate_coefficients(a, b)
    if not _is_finite_number(r):
        raise ValueError(f"R must be a finite number, got {r!r}")
    return a - b * float(r)


def r_target_from_spo2(spo2: float, a: float = SPO2_COEFF_A_DEFAULT,
                       b: float = SPO2_COEFF_B_DEFAULT) -> float:
    """Inverse mapping: R_target = (A - SpO2) / B. Coefficients are validated."""
    a, b = validate_coefficients(a, b)
    if not _is_finite_number(spo2):
        raise ValueError(f"SpO2 must be a finite number, got {spo2!r}")
    return (a - float(spo2)) / b


@dataclass(frozen=True)
class SpO2Calibration:
    """
    Immutable SpO2 calibration (A, B). Validates on construction.

    Use as a single source of truth object where an owner wants to carry the
    coefficients together rather than as two loose floats.
    """
    a: float = SPO2_COEFF_A_DEFAULT
    b: float = SPO2_COEFF_B_DEFAULT

    def __post_init__(self):
        # Normalise/validate; frozen dataclass requires object.__setattr__.
        a, b = validate_coefficients(self.a, self.b)
        object.__setattr__(self, "a", a)
        object.__setattr__(self, "b", b)

    def spo2_from_r(self, r: float) -> float:
        return spo2_from_r(r, self.a, self.b)

    def r_target_from_spo2(self, spo2: float) -> float:
        return r_target_from_spo2(spo2, self.a, self.b)


# ─── DAC voltage -> 12-bit code (3.28 V full-scale) ───
def dac_voltage_to_code(voltage_v: float,
                        fullscale_v: float = DAC_FULLSCALE_V,
                        max_code: int = DAC_MAX_VALUE) -> int:
    """
    Convert a signal voltage to a 12-bit MCP4725 code.

    Linear mapping: 0 V -> 0, fullscale_v -> max_code (3.28 V -> 4095 by default).
    The result is clamped to [0, max_code]. Truncation (int()) matches the
    prior behavior; only the 3.3 V -> 3.28 V full-scale changes.

    Args:
        voltage_v:   Signal voltage in Volts.
        fullscale_v: DAC full-scale voltage (defaults to the verified 3.28 V).
        max_code:    Maximum DAC code (defaults to 4095 for 12-bit).

    Raises:
        ValueError: if voltage_v is non-finite or fullscale_v <= 0.
    """
    if not _is_finite_number(voltage_v):
        raise ValueError(f"voltage_v must be a finite number, got {voltage_v!r}")
    if not _is_finite_number(fullscale_v) or fullscale_v <= 0.0:
        raise ValueError(f"fullscale_v must be a positive finite number, got {fullscale_v!r}")
    code = int((float(voltage_v) / float(fullscale_v)) * max_code)
    return max(0, min(int(max_code), code))


# ─── AC / DC / Perfusion-Index & ratio-of-ratios (Phase 3) ───
#
# These are the pure, hardware-free primitives for the AC/DC-as-master model.
# AC and DC may use any consistent unit (mV or V) as long as both operands of a
# single call share it — PI is a ratio, so units cancel. The full clinical
# relationships are (Phase 1 §17/§18, WhaleTeq AECG100):
#
#     PI      = AC / DC * 100                                   (per channel)
#     R       = (AC_red / DC_red) / (AC_ir / DC_ir)             (ratio-of-ratios)
#     AC_red  = R_target * AC_ir * (DC_red / DC_ir)             (target Red amplitude)
#
# AC_red simplifies to R_target * AC_ir only when DC_red == DC_ir; the DC ratio
# is mandatory for correct R when the two channels have unequal DC levels.


def perfusion_index_from_ac_dc(ac: float, dc: float) -> float:
    """Perfusion index (percent): PI = AC / DC * 100.

    AC and DC must share the same unit. DC must be > 0 (a zero/negative DC has
    no physical meaning and would make PI undefined).

    Raises:
        ValueError: if AC/DC is non-finite, DC <= 0, or AC < 0.
    """
    if not _is_finite_number(ac):
        raise ValueError(f"AC must be a finite number, got {ac!r}")
    if not _is_finite_number(dc):
        raise ValueError(f"DC must be a finite number, got {dc!r}")
    ac = float(ac)
    dc = float(dc)
    if dc <= 0.0:
        raise ValueError(f"DC must be > 0, got {dc!r}")
    if ac < 0.0:
        raise ValueError(f"AC must be >= 0, got {ac!r}")
    return ac / dc * 100.0


def ratio_of_ratios(ac_red: float, dc_red: float,
                    ac_ir: float, dc_ir: float) -> float:
    """Full ratio-of-ratios: R = (AC_red / DC_red) / (AC_ir / DC_ir).

    Each (AC, DC) pair must share a unit; the two pairs need not share the same
    unit as each other (R is dimensionless). The IR channel forms the
    denominator, so DC_ir, DC_red > 0 and AC_ir > 0 are required for R to be
    defined.

    Raises:
        ValueError: on non-finite inputs, DC <= 0, AC_red < 0, or AC_ir <= 0.
    """
    for name, val in (("ac_red", ac_red), ("dc_red", dc_red),
                      ("ac_ir", ac_ir), ("dc_ir", dc_ir)):
        if not _is_finite_number(val):
            raise ValueError(f"{name} must be a finite number, got {val!r}")
    ac_red = float(ac_red); dc_red = float(dc_red)
    ac_ir = float(ac_ir); dc_ir = float(dc_ir)
    if dc_red <= 0.0 or dc_ir <= 0.0:
        raise ValueError(f"DC values must be > 0, got dc_red={dc_red!r}, dc_ir={dc_ir!r}")
    if ac_red < 0.0:
        raise ValueError(f"AC_red must be >= 0, got {ac_red!r}")
    if ac_ir <= 0.0:
        raise ValueError(f"AC_ir must be > 0 (denominator PI_ir), got {ac_ir!r}")
    return (ac_red / dc_red) / (ac_ir / dc_ir)


def ac_red_from_target(r_target: float, ac_ir: float,
                       dc_red: float, dc_ir: float) -> float:
    """Target Red AC amplitude: AC_red = R_target * AC_ir * (DC_red / DC_ir).

    This is the correct derivation from a target SpO2 (via R_target) and possibly
    unequal channel DC levels. It reduces to R_target * AC_ir when DC_red == DC_ir.
    AC_red is returned in the same unit as AC_ir.

    Raises:
        ValueError: on non-finite inputs, DC <= 0, R_target < 0, or AC_ir < 0.
    """
    for name, val in (("r_target", r_target), ("ac_ir", ac_ir),
                      ("dc_red", dc_red), ("dc_ir", dc_ir)):
        if not _is_finite_number(val):
            raise ValueError(f"{name} must be a finite number, got {val!r}")
    r_target = float(r_target); ac_ir = float(ac_ir)
    dc_red = float(dc_red); dc_ir = float(dc_ir)
    if dc_red <= 0.0 or dc_ir <= 0.0:
        raise ValueError(f"DC values must be > 0, got dc_red={dc_red!r}, dc_ir={dc_ir!r}")
    if r_target < 0.0:
        raise ValueError(f"R_target must be >= 0, got {r_target!r}")
    if ac_ir < 0.0:
        raise ValueError(f"AC_ir must be >= 0, got {ac_ir!r}")
    return r_target * ac_ir * (dc_red / dc_ir)


def validate_ac_dc(ac_mv: float, dc_mv: float,
                   fullscale_mv: float = DAC_FULLSCALE_MV) -> tuple:
    """Validate a master AC/DC pair (in millivolts) against the DAC headroom.

    Enforces the hard safety/physical constraints so a caller cannot command an
    AC/DC pair that is non-physical or that cannot be represented within the
    configured DAC full-scale (3.28 V = 3280 mV). Both above-DC and
    below-DC polarities must fit, so the signal envelope [DC-AC, DC+AC] must lie
    within [0, fullscale].

    Args:
        ac_mv:        AC amplitude in mV (peak pulsatile, one-sided).
        dc_mv:        DC level in mV.
        fullscale_mv: DAC full-scale in mV (defaults to the verified 3280 mV).

    Returns:
        (float(ac_mv), float(dc_mv)) on success.

    Raises:
        ValueError: if inputs are non-finite; DC <= 0; AC < 0; DC > full-scale;
            DC + AC > full-scale (above-DC peak clips); or DC - AC < 0 (below-DC
            trough clips / goes non-physical).
    """
    if not _is_finite_number(ac_mv):
        raise ValueError(f"AC (mV) must be a finite number, got {ac_mv!r}")
    if not _is_finite_number(dc_mv):
        raise ValueError(f"DC (mV) must be a finite number, got {dc_mv!r}")
    if not _is_finite_number(fullscale_mv) or fullscale_mv <= 0.0:
        raise ValueError(f"fullscale_mv must be a positive finite number, got {fullscale_mv!r}")
    ac_mv = float(ac_mv)
    dc_mv = float(dc_mv)
    fs = float(fullscale_mv)
    if dc_mv <= 0.0:
        raise ValueError(f"DC must be > 0 mV, got {dc_mv!r}")
    if ac_mv < 0.0:
        raise ValueError(f"AC must be >= 0 mV, got {ac_mv!r}")
    if dc_mv > fs:
        raise ValueError(f"DC ({dc_mv} mV) exceeds DAC full-scale ({fs} mV)")
    if dc_mv + ac_mv > fs:
        raise ValueError(
            f"DC+AC ({dc_mv + ac_mv} mV) exceeds DAC full-scale ({fs} mV): "
            f"above-DC peak would clip")
    if dc_mv - ac_mv < 0.0:
        raise ValueError(
            f"DC-AC ({dc_mv - ac_mv} mV) is below 0 mV: below-DC trough would clip")
    return ac_mv, dc_mv
