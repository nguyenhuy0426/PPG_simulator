"""
DAC code / voltage / current equations for the TX LED driver.

Stdlib only. No hardware access.

Signal chain modelled here:

    code -> V_dac -> (10k/10k divider) -> V_cmd -> op-amp forces V_sense = V_cmd
         -> I_sense = V_cmd / R_sense  (current through the sense resistor)
         -> I_E = I_sense - I_RBE      (R_BE steals part of it, if fitted)
         -> I_LED = I_C = alpha * I_E  (alpha = hFE / (hFE + 1))

The two subtractions above are the corrections to the earlier analysis: the
base current and the R_BE bleed current are NOT negligible bookkeeping, they
change what the LED actually receives.
"""

from typing import Optional

from led_driver.params import (
    CONVENTION_MAX_CODE,
    CONVENTION_RATIOMETRIC,
    VALID_CONVENTIONS,
    ChannelDesign,
    DacSpec,
)

_UNSET = object()


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------

def _check_code(code, dac: DacSpec) -> int:
    if isinstance(code, bool) or not isinstance(code, int):
        raise ValueError(f"DAC code must be an int, got {type(code).__name__}")
    if code < 0 or code > dac.max_code:
        raise ValueError(
            f"DAC code {code} out of range 0..{dac.max_code} "
            f"({dac.level_count} levels)")
    return code


def _check_convention(convention: str) -> str:
    if convention not in VALID_CONVENTIONS:
        raise ValueError(
            f"unknown DAC convention {convention!r}; "
            f"expected one of {VALID_CONVENTIONS}")
    return convention


def _check_non_negative(value: float, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be a real number")
    if value != value:  # NaN
        raise ValueError(f"{label} must not be NaN")
    if value < 0.0:
        raise ValueError(f"{label} must not be negative, got {value}")
    return float(value)


# --------------------------------------------------------------------------
# Code <-> voltage
# --------------------------------------------------------------------------

def code_to_voltage(code, dac: DacSpec,
                    convention: str = CONVENTION_RATIOMETRIC) -> float:
    """DAC output voltage for a code, under an explicit convention."""
    _check_convention(convention)
    _check_code(code, dac)
    divisor = dac.level_count if convention == CONVENTION_RATIOMETRIC else dac.max_code
    return dac.fullscale_v * code / divisor


def voltage_to_code(voltage_v: float, dac: DacSpec,
                    convention: str = CONVENTION_MAX_CODE) -> int:
    """Inverse of code_to_voltage, truncating toward zero (as the project does)."""
    _check_convention(convention)
    _check_non_negative(voltage_v, "voltage_v")
    if voltage_v > dac.fullscale_v:
        raise ValueError(
            f"voltage {voltage_v} V exceeds DAC full scale {dac.fullscale_v} V")
    divisor = dac.level_count if convention == CONVENTION_RATIOMETRIC else dac.max_code
    return min(int(voltage_v / dac.fullscale_v * divisor), dac.max_code)


def convention_discrepancy(dac: DacSpec) -> dict:
    """Quantify the 4096-levels versus 4095-max-code mismatch at full code."""
    v_ratiometric = code_to_voltage(dac.max_code, dac, CONVENTION_RATIOMETRIC)
    v_max_code = code_to_voltage(dac.max_code, dac, CONVENTION_MAX_CODE)
    delta_v = v_max_code - v_ratiometric
    return {
        "max_code": dac.max_code,
        "level_count": dac.level_count,
        "lsb_v": dac.lsb_v,
        "v_ratiometric": v_ratiometric,
        "v_max_code": v_max_code,
        "delta_v": delta_v,
        "delta_lsb": delta_v / dac.lsb_v,
        "delta_fraction": delta_v / dac.fullscale_v,
    }


# --------------------------------------------------------------------------
# Voltage -> current
# --------------------------------------------------------------------------

def command_voltage_from_dac_v(v_dac: float, channel: ChannelDesign) -> float:
    """Op-amp + input voltage after the attenuator."""
    _check_non_negative(v_dac, "v_dac")
    return v_dac * channel.divider.ratio


def command_voltage_from_code(code, channel: ChannelDesign,
                              convention: str = CONVENTION_RATIOMETRIC) -> float:
    return command_voltage_from_dac_v(
        code_to_voltage(code, channel.dac, convention), channel)


def sense_current(v_cmd: float, channel: ChannelDesign) -> float:
    """Current through R_sense. The feedback loop forces this, not I_LED."""
    _check_non_negative(v_cmd, "v_cmd")
    return v_cmd / channel.rsense_ohm


def full_scale_current(channel: ChannelDesign) -> float:
    """Ideal full-scale LED current (alpha = 1, R_BE not fitted, no offset)."""
    return (channel.dac.fullscale_v * channel.divider.ratio) / channel.rsense_ohm


def current_lsb(channel: ChannelDesign) -> float:
    """LED-current change per DAC code step."""
    return channel.dac.lsb_v * channel.divider.ratio / channel.rsense_ohm


def alpha(hfe: Optional[float]) -> float:
    """Common-base current gain. hfe=None models the ideal alpha = 1."""
    if hfe is None:
        return 1.0
    if hfe <= 0:
        raise ValueError(f"hfe must be positive, got {hfe}")
    return hfe / (hfe + 1.0)


def rbe_bleed_current(rbe_ohm: Optional[float], vbe_on_v: float) -> float:
    """Current diverted through R_BE instead of into the base."""
    if rbe_ohm is None:
        return 0.0
    if rbe_ohm <= 0:
        raise ValueError(f"rbe_ohm must be positive or None (DNP), got {rbe_ohm}")
    return vbe_on_v / rbe_ohm


def led_current_from_command(v_cmd: float, channel: ChannelDesign,
                             hfe: Optional[float] = None,
                             rbe_ohm=_UNSET,
                             vbe_on_v: Optional[float] = None) -> float:
    """LED (collector) current for a given op-amp command voltage.

    I_LED = alpha * max(V_cmd / R_sense - V_BE / R_BE, 0)

    Below the R_BE dead zone the transistor is off and the LED current is
    exactly zero: R_BE turns a small command into no light at all.
    """
    _check_non_negative(v_cmd, "v_cmd")
    if rbe_ohm is _UNSET:
        rbe_ohm = channel.rbe_ohm
    if vbe_on_v is None:
        vbe_on_v = channel.transistor.vbe_on_v

    i_sense = sense_current(v_cmd, channel)
    i_emitter = i_sense - rbe_bleed_current(rbe_ohm, vbe_on_v)
    if i_emitter <= 0.0:
        return 0.0
    return alpha(hfe) * i_emitter


def led_current_from_code(code, channel: ChannelDesign,
                          hfe: Optional[float] = None,
                          rbe_ohm=_UNSET,
                          vbe_on_v: Optional[float] = None,
                          convention: str = CONVENTION_RATIOMETRIC) -> float:
    v_cmd = command_voltage_from_code(code, channel, convention)
    return led_current_from_command(
        v_cmd, channel, hfe=hfe, rbe_ohm=rbe_ohm, vbe_on_v=vbe_on_v)


def dead_zone_command_v(channel: ChannelDesign,
                        rbe_ohm=_UNSET,
                        vbe_on_v: Optional[float] = None) -> float:
    """Command voltage below which R_BE keeps the transistor off."""
    if rbe_ohm is _UNSET:
        rbe_ohm = channel.rbe_ohm
    if vbe_on_v is None:
        vbe_on_v = channel.transistor.vbe_on_v
    return rbe_bleed_current(rbe_ohm, vbe_on_v) * channel.rsense_ohm


def code_for_target_current(target_a: float, channel: ChannelDesign,
                            convention: str = CONVENTION_MAX_CODE) -> int:
    """DAC code that commands a target ideal LED current.

    Uses the ideal relation (alpha = 1, R_BE unfitted). The real current will
    be slightly lower; see led_current_from_code() and error_budget.
    """
    _check_non_negative(target_a, "target_a")
    v_cmd = target_a * channel.rsense_ohm
    v_dac = v_cmd / channel.divider.ratio
    if v_dac > channel.dac.fullscale_v:
        raise ValueError(
            f"target {target_a * 1e3:.3f} mA needs {v_dac:.4f} V from the DAC, "
            f"above full scale {channel.dac.fullscale_v} V "
            f"(channel {channel.name}, R_sense {channel.rsense_ohm} ohm)")
    return voltage_to_code(v_dac, channel.dac, convention)
