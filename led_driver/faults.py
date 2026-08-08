"""
Single-fault behaviour of the current-sink LED driver (Stage 1 item 16).

Stdlib only. No hardware access.

Seven faults are analysed per channel: open LED, shorted LED, open R_sense,
shorted R_sense, broken feedback, reversed transistor, reversed LED. Every
number is a CALCULATION from datasheet limits and the candidate values in
led_driver.params; nothing here has been provoked or measured on hardware.
The results are predictions for the bring-up procedure, not observations.

`destructive` marks faults whose predicted STEADY STATE necessarily exceeds a
component rating. Faults whose outcome is indeterminate (broken feedback) are
NOT marked destructive even when their worst-case bound exceeds a rating;
the bound is exposed on the result instead (exceeds_led_abs_max).

Key shared quantity: the op-amp output ceiling is (rail - 1.5 V) for the
classic LM358 with R_L >= 2 kohm. After the ~0.70 V V_BE(on) drop, at most
(rail - 1.5 - 0.70) V is available to push current through R_B + R_sense.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Union

from led_driver.params import ChannelDesign


def _drive_ceiling_v(channel: ChannelDesign,
                     rail_v: Optional[float] = None) -> float:
    """Maximum voltage available across R_B + R_sense with the op-amp
    saturated high. The LM358 shares the LED rail, so an overridden rail
    moves the output ceiling too."""
    if rail_v is None:
        rail_v = channel.rail_v
    output_max_v = rail_v - channel.opamp.output_headroom_v
    return output_max_v - channel.transistor.vbe_on_v


# --------------------------------------------------------------------------
# Result records
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class OpenLedFault:
    channel_name: str
    max_base_path_current_a: float
    sense_clamp_v: float
    led_current_a: float
    opamp_saturates_high: bool
    destructive: bool


@dataclass(frozen=True)
class ShortedLedFault:
    channel_name: str
    regulation_intact: bool
    vce_v: float
    transistor_dissipation_w: float
    destructive: bool


@dataclass(frozen=True)
class OpenRsenseFault:
    channel_name: str
    led_current_a: float
    sense_node_v: Optional[float]
    sense_node_state: str
    destructive: bool


@dataclass(frozen=True)
class ShortedRsenseFault:
    channel_name: str
    base_drive_a: float
    min_gain_current_bound_a: float
    destructive: bool


@dataclass(frozen=True)
class BrokenFeedbackFault:
    channel_name: str
    output_state: str
    worst_case_current_bound_a: float
    exceeds_led_abs_max: bool
    destructive: bool


@dataclass(frozen=True)
class ReversedTransistorFault:
    channel_name: str
    veb_reverse_bound_v: float
    vebo_abs_max_v: float
    reverse_hfe: Optional[float]
    regulation_state: str
    destructive: bool


@dataclass(frozen=True)
class ReversedLedFault:
    channel_name: str
    max_base_path_current_a: float
    sense_clamp_v: float
    led_current_a: float
    led_reverse_v: float
    reverse_abs_max_v: Optional[float]
    within_reverse_rating: Optional[bool]
    destructive: bool


FaultResult = Union[OpenLedFault, ShortedLedFault, OpenRsenseFault,
                    ShortedRsenseFault, BrokenFeedbackFault,
                    ReversedTransistorFault, ReversedLedFault]


# --------------------------------------------------------------------------
# The seven faults
# --------------------------------------------------------------------------

def open_led(channel: ChannelDesign) -> OpenLedFault:
    """Collector path broken. Only the base path (op-amp -> R_B -> B-E ->
    R_sense -> GND) can conduct, so regulation survives only up to
    (rail - 1.5 - V_BE) / (R_B + R_sense); above that the op-amp saturates
    high and V_sense clamps. No LED current flows; the fault is self-limiting
    and non-destructive (well under the 50 mA I_B abs max)."""
    drive_v = _drive_ceiling_v(channel)
    i_base_path = drive_v / (channel.rb_ohm + channel.rsense_ohm)
    return OpenLedFault(
        channel_name=channel.name,
        max_base_path_current_a=i_base_path,
        sense_clamp_v=i_base_path * channel.rsense_ohm,
        led_current_a=0.0,
        opamp_saturates_high=True,
        destructive=False,
    )


def shorted_led(channel: ChannelDesign,
                i_led_a: Optional[float] = None) -> ShortedLedFault:
    """LED failed short (collector tied to the rail). Feedback still senses
    R_sense, so regulation is unaffected; the transistor absorbs the voltage
    the LED used to drop. V_CE = rail - I * R_sense at the commanded current
    (defaults to full scale, the worst case)."""
    if i_led_a is None:
        from led_driver import dac
        i_led_a = dac.full_scale_current(channel)
    vce_v = channel.rail_v - i_led_a * channel.rsense_ohm
    dissipation_w = vce_v * i_led_a
    return ShortedLedFault(
        channel_name=channel.name,
        regulation_intact=True,
        vce_v=vce_v,
        transistor_dissipation_w=dissipation_w,
        destructive=dissipation_w > channel.transistor.pc_max_w,
    )


def open_rsense(channel: ChannelDesign) -> OpenRsenseFault:
    """Sense resistor open. The emitter has no path to ground, so no emitter
    or collector current can flow at all: the LED stays dark. The op-amp
    saturates high (feedback reads the floating node), but the DC level of
    the open sense node depends on leakage paths, so it is reported as
    INDETERMINATE rather than given a fabricated number."""
    return OpenRsenseFault(
        channel_name=channel.name,
        led_current_a=0.0,
        sense_node_v=None,
        sense_node_state=(
            "INDETERMINATE - the node floats through B-E and leakage paths; "
            "its DC level is not predictable from datasheet values"),
        destructive=False,
    )


def shorted_rsense(channel: ChannelDesign) -> ShortedRsenseFault:
    """Sense resistor shorted. Feedback reads 0 V regardless of current, so
    any nonzero command drives the op-amp output to its ceiling: base drive
    becomes (rail - 1.5 - V_BE) / R_B. Even the worst-gain transistor
    (hFE abs min = 70) then tries hFE * I_B, which exceeds both the LED
    continuous rating and the transistor I_C rating on both channels.

    This is the one destructive single fault of this topology."""
    drive_v = _drive_ceiling_v(channel)
    base_drive_a = drive_v / channel.rb_ohm
    min_bound_a = base_drive_a * channel.transistor.hfe_abs_min
    return ShortedRsenseFault(
        channel_name=channel.name,
        base_drive_a=base_drive_a,
        min_gain_current_bound_a=min_bound_a,
        destructive=(min_bound_a > channel.led.if_max_continuous_a
                     or min_bound_a > channel.transistor.ic_max_a),
    )


def broken_feedback(channel: ChannelDesign) -> BrokenFeedbackFault:
    """Feedback wire open. The inverting input floats, so the output state
    depends on stray leakage and offset polarity: INDETERMINATE. The worst
    case (output saturated high, alpha -> 1) bounds the current at
    (rail - 1.5 - V_BE) / R_sense. That bound exceeds the Red LED 20 mA
    abs max but stays inside the IR LED 100 mA rating. Because the outcome
    is not deterministic the fault is not marked destructive; the Red risk
    is carried by exceeds_led_abs_max."""
    drive_v = _drive_ceiling_v(channel)
    bound_a = drive_v / channel.rsense_ohm
    return BrokenFeedbackFault(
        channel_name=channel.name,
        output_state=(
            "INDETERMINATE - with the inverting input floating the output "
            "may sit anywhere between the rails"),
        worst_case_current_bound_a=bound_a,
        exceeds_led_abs_max=bound_a > channel.led.if_max_continuous_a,
        destructive=False,
    )


def reversed_transistor(channel: ChannelDesign) -> ReversedTransistorFault:
    """Collector and emitter swapped (reverse-active operation). The real
    emitter now faces the LED side and can be pulled up to roughly
    rail - V_F(min) while the base sits near ground, reverse-stressing the
    E-B junction by up to that amount - still under the 5 V V_EBO abs max
    at a 5.00 V rail. Reverse-mode gain is not characterised in the
    datasheet, so the resulting current regulation is UNKNOWN, not
    predicted."""
    veb_bound_v = channel.rail_v - channel.led.vf_min_v
    return ReversedTransistorFault(
        channel_name=channel.name,
        veb_reverse_bound_v=veb_bound_v,
        vebo_abs_max_v=channel.transistor.vebo_max_v,
        reverse_hfe=None,
        regulation_state=(
            "UNKNOWN - reverse-active hFE is not specified in the 2SC1815 "
            "datasheet; the loop may partially regulate at degraded gain"),
        destructive=False,
    )


def reversed_led(channel: ChannelDesign,
                 rail_v: Optional[float] = None) -> ReversedLedFault:
    """LED installed backwards. The collector path blocks, so the base path
    clamps exactly as in the open-LED case and no LED current flows. The
    blocked LED sees a reverse voltage bounded by rail - V(sense clamp)
    (conservative: V_CE taken as 0, which maximises the reverse stress).

    IR (SIR234): V_R abs max = 5 V - the predicted ~4.79 V at a 5.00 V rail
    is inside the rating, but a 5.25 V rail exceeds it.
    Red: the datasheet gives no reverse abs max (leakage only), so whether
    the part survives is UNKNOWN (within_reverse_rating = None)."""
    if rail_v is None:
        rail_v = channel.rail_v
    drive_v = _drive_ceiling_v(channel, rail_v=rail_v)
    i_base_path = drive_v / (channel.rb_ohm + channel.rsense_ohm)
    sense_clamp_v = i_base_path * channel.rsense_ohm
    led_reverse_v = rail_v - sense_clamp_v
    vr_max = channel.led.vr_max_v
    within = None if vr_max is None else led_reverse_v <= vr_max
    return ReversedLedFault(
        channel_name=channel.name,
        max_base_path_current_a=i_base_path,
        sense_clamp_v=sense_clamp_v,
        led_current_a=0.0,
        led_reverse_v=led_reverse_v,
        reverse_abs_max_v=vr_max,
        within_reverse_rating=within,
        destructive=False,
    )


def all_faults(channel: ChannelDesign) -> Dict[str, FaultResult]:
    """All seven single faults at their default (worst-case) settings."""
    return {
        "open_led": open_led(channel),
        "shorted_led": shorted_led(channel),
        "open_rsense": open_rsense(channel),
        "shorted_rsense": shorted_rsense(channel),
        "broken_feedback": broken_feedback(channel),
        "reversed_transistor": reversed_transistor(channel),
        "reversed_led": reversed_led(channel),
    }
