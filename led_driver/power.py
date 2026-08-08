"""
Dissipation, LED current limits and the 5 V rail-current budget.

Stdlib only. No hardware access.

Rail-current result worth stating up front, because it corrects an earlier
hand calculation: for each channel the current drawn FROM the 5 V rail is
exactly the sense current, independent of hFE and of R_BE.

    rail = I_C (through the LED) + I_RB (out of the op-amp output)
         = I_C + I_B + I_RBE
         = I_E + I_RBE
         = I_sense

So the budget is 16.40 mA + 20.00 mA + 2 x 600 uA = 37.60 mA, not 37.3 mA.
hFE and R_BE move current between the LED branch and the op-amp branch; they
do not change the total. They DO change how much of it reaches the LED.
"""

from typing import Dict, List, Optional, Sequence

from led_driver.compliance import (
    base_current,
    collector_emitter_voltage,
    forward_voltage,
)
from led_driver.dac import alpha, rbe_bleed_current, sense_current
from led_driver.params import ChannelDesign

_UNSET = object()


class CurrentLimitError(ValueError):
    """Raised when an operating point would exceed an LED absolute maximum."""


# --------------------------------------------------------------------------
# Dissipation
# --------------------------------------------------------------------------

def rsense_dissipation_w(current_a: float, channel: ChannelDesign) -> float:
    """I^2 * R in the sense resistor."""
    return current_a * current_a * channel.rsense_ohm


def led_dissipation_w(current_a: float, channel: ChannelDesign,
                      vf_selector: str = "max") -> float:
    return current_a * forward_voltage(channel, vf_selector)


def led_dissipation_fraction(current_a: float, channel: ChannelDesign,
                             vf_selector: str = "max") -> float:
    return led_dissipation_w(current_a, channel, vf_selector) / channel.led.pd_max_w


def transistor_dissipation_w(current_a: float, channel: ChannelDesign,
                             v_sense: float, vf_selector: str = "min",
                             rail_v: Optional[float] = None) -> float:
    """V_CE * I_C. Worst case is at MINIMUM V_F, which maximises V_CE."""
    vce = collector_emitter_voltage(channel, v_sense, vf_selector, rail_v)
    return vce * current_a


def dissipation_report(channel: ChannelDesign, current_a: float,
                       v_sense: float,
                       rail_v: Optional[float] = None) -> Dict[str, float]:
    """Every dissipation term for one channel at one operating point."""
    return {
        "channel": channel.name,
        "current_a": current_a,
        "rsense_w": rsense_dissipation_w(current_a, channel),
        "led_w_at_vf_max": led_dissipation_w(current_a, channel, "max"),
        "led_pd_max_w": channel.led.pd_max_w,
        "transistor_w_at_vf_min": transistor_dissipation_w(
            current_a, channel, v_sense, "min", rail_v),
        "transistor_pc_max_w": channel.transistor.pc_max_w,
    }


# --------------------------------------------------------------------------
# LED current limits
# --------------------------------------------------------------------------

def current_limit_fraction(current_a: float, channel: ChannelDesign) -> float:
    """Operating current as a fraction of the LED absolute maximum I_F."""
    return current_a / channel.led.if_max_continuous_a


def check_led_current_or_raise(current_a: float, channel: ChannelDesign,
                               vf_selector: str = "max") -> None:
    """Raise if the current breaches the LED I_F or P_D absolute maximum."""
    led = channel.led
    if current_a > led.if_max_continuous_a:
        raise CurrentLimitError(
            f"Channel {channel.name}: {current_a * 1e3:.3f} mA exceeds the "
            f"{led.name} absolute maximum I_F of "
            f"{led.if_max_continuous_a * 1e3:.1f} mA")
    p = led_dissipation_w(current_a, channel, vf_selector)
    if p > led.pd_max_w:
        raise CurrentLimitError(
            f"Channel {channel.name}: {current_a * 1e3:.3f} mA at "
            f"V_F({vf_selector}) dissipates {p * 1e3:.1f} mW, above the "
            f"{led.name} rating of {led.pd_max_w * 1e3:.1f} mW")


# --------------------------------------------------------------------------
# Rail-current budget
# --------------------------------------------------------------------------

def rail_current_budget(channels: Sequence[ChannelDesign], v_sense: float,
                        hfe: Optional[float] = None, rbe_ohm=_UNSET,
                        vbe_on_v: Optional[float] = None) -> Dict[str, object]:
    """Full KCL budget on the 5 V rail at one common operating point.

    hfe=None models the ideal alpha = 1. rbe_ohm defaults to each channel's own
    value; pass an explicit number or None (DNP) to override both channels.
    """
    per_channel: List[Dict[str, float]] = []
    led_total = base_total = rbe_total = 0.0

    for channel in channels:
        this_rbe = channel.rbe_ohm if rbe_ohm is _UNSET else rbe_ohm
        this_vbe = (channel.transistor.vbe_on_v if vbe_on_v is None else vbe_on_v)

        i_sense = sense_current(v_sense, channel)
        i_rbe = rbe_bleed_current(this_rbe, this_vbe)
        i_emitter = max(i_sense - i_rbe, 0.0)
        i_led = alpha(hfe) * i_emitter
        if hfe is None:
            i_base = 0.0
        else:
            i_base = base_current(v_sense, channel, hfe, this_rbe, this_vbe)

        led_total += i_led
        base_total += i_base
        rbe_total += i_rbe
        per_channel.append({
            "channel": channel.name,
            "sense_a": i_sense,
            "led_a": i_led,
            "base_a": i_base,
            "rbe_a": i_rbe,
            "rail_a": i_led + i_base + i_rbe,
        })

    # One LM358 amplifier per channel. The datasheet I_Q is quoted per
    # amplifier, so a dual package driving both channels contributes twice.
    iq_total = sum(ch.opamp.iq_max_a_per_amplifier for ch in channels)

    return {
        "per_channel": per_channel,
        "led_a": led_total,
        "base_a": base_total,
        "rbe_a": rbe_total,
        "opamp_quiescent_a": iq_total,
        "total_a": led_total + base_total + rbe_total + iq_total,
    }
