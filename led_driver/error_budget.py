"""
Error budget for the 5 V LED-driver candidate, plus the unresolved decisions.

Stdlib only. No hardware access.

The central distinction
----------------------
PI = AC/DC x 100 and R = (AC_red/DC_red)/(AC_ir/DC_ir) are ratios. A constant
multiplicative error on a channel divides out of both. An additive error does
not. So the budget must be split:

  GAIN   (cancels in PI and R)     divider tolerance, R_sense tolerance,
                                   constant alpha = hFE/(hFE+1)
  OFFSET (does NOT cancel)         LM358 V_OS and I_B, the R_BE bleed current

"Cancels" here means cancels in the RATIO. It does not mean the absolute LED
current is correct, and it says nothing about optical output.

What this module refuses to decide
----------------------------------
R_BE and C2 are deliberately left without values. Both depend on the real loop
behaviour of a real board, which nobody has measured. RBE_DECISION and
C2_COMPENSATION raise MeasurementRequiredError if code tries to read a number
out of them.
"""

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from led_driver.dac import rbe_bleed_current, sense_current, voltage_to_code
from led_driver.params import ChannelDesign, DividerSpec

HfeModel = Union[None, float, Callable[[float], float]]

# PPG bands used to judge whether an alias lands somewhere that matters.
# [ENGINEERING-INFERENCE] Conventional adult ranges, not a clinical standard.
PPG_HR_BAND_HZ = (0.5, 4.0)          # 30-240 bpm
PPG_BASELINE_BAND_HZ = (0.0, 0.5)    # DC and baseline wander, feeds the DC term


class MeasurementRequiredError(RuntimeError):
    """Raised when code asks for a value that only a bench measurement can supply."""


# --------------------------------------------------------------------------
# Unresolved component decisions
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ComponentDecision:
    designator: str
    status: str
    evidence: str
    rationale: str
    value: Optional[float] = None

    def require_value(self) -> float:
        if self.value is None:
            raise MeasurementRequiredError(
                f"{self.designator} has no value: status {self.status}, "
                f"evidence {self.evidence}. {self.rationale}")
        return self.value


RBE_DECISION = ComponentDecision(
    designator="R_BE",
    status="NOT-FINALISED",
    evidence="MEASUREMENT-REQUIRED",
    rationale=(
        "R_BE trades turn-off behaviour against an offset current that does "
        "NOT cancel in PI or R. 10 kohm costs about 0.94 percent of PI at the "
        "7.5 mA Red operating point and blanks the bottom 17 DAC codes; "
        "100 kohm costs about 0.09 percent and one code; DNP costs nothing but "
        "leaves turn-off to the LM358 output sink, specified only as 12 uA "
        "minimum near ground. Choosing between them needs a scope on the "
        "emitter node during a real code-0 transition."),
    value=None,
)

C2_COMPENSATION = ComponentDecision(
    designator="C2",
    status="DNP",
    evidence="MEASUREMENT-REQUIRED",
    rationale=(
        "C2 is the feedback compensation capacitor around the LM358 current "
        "loop. Its correct value depends on the loop gain, the transistor "
        "beta at the operating point and the layout parasitics, none of which "
        "are known. Fit the footprint, leave it unpopulated, and set it only "
        "after a scope step response or a validated loop model shows the "
        "actual phase margin."),
    value=None,
)


# --------------------------------------------------------------------------
# Offset errors (do NOT cancel in PI or R)
# --------------------------------------------------------------------------

def input_referred_offset_v(channel: ChannelDesign,
                            over_temperature: bool = False) -> float:
    """Worst-case error voltage at the op-amp input: V_OS + I_B * R_thevenin."""
    opamp = channel.opamp
    vos = opamp.vos_max_over_temp_v if over_temperature else opamp.vos_max_v
    ib = opamp.ib_max_over_temp_a if over_temperature else opamp.ib_max_a
    return vos + ib * channel.divider.thevenin_ohm


def offset_current_error_a(channel: ChannelDesign,
                           over_temperature: bool = False) -> float:
    """The input offset expressed as an LED-current error."""
    return input_referred_offset_v(channel, over_temperature) / channel.rsense_ohm


def offset_error_fraction(channel: ChannelDesign, at_current_a: float,
                          over_temperature: bool = False) -> float:
    """Offset current as a fraction of a given operating current."""
    if at_current_a <= 0:
        raise ValueError("at_current_a must be positive")
    return offset_current_error_a(channel, over_temperature) / at_current_a


# --------------------------------------------------------------------------
# Gain errors (cancel in PI and R)
# --------------------------------------------------------------------------

def divider_ratio_extremes(divider: DividerSpec) -> Tuple[float, float]:
    """(min, max) attenuation ratio over the resistor tolerance."""
    t = divider.tolerance_frac
    rt, rb = divider.r_top_ohm, divider.r_bottom_ohm
    lo = (rb * (1 - t)) / (rb * (1 - t) + rt * (1 + t))
    hi = (rb * (1 + t)) / (rb * (1 + t) + rt * (1 - t))
    return lo, hi


def divider_gain_error_fraction(divider: DividerSpec) -> Tuple[float, float]:
    lo, hi = divider_ratio_extremes(divider)
    return lo / divider.ratio - 1.0, hi / divider.ratio - 1.0


def rsense_gain_error_fraction(channel: ChannelDesign) -> Tuple[float, float]:
    """Current is inversely proportional to R_sense, so the sign flips."""
    t = channel.rsense_tolerance_frac
    return 1.0 / (1.0 + t) - 1.0, 1.0 / (1.0 - t) - 1.0


def total_gain_error_fraction(channel: ChannelDesign) -> Tuple[float, float]:
    """Worst-case combined multiplicative error on the commanded current."""
    d_lo, d_hi = divider_gain_error_fraction(channel.divider)
    r_lo, r_hi = rsense_gain_error_fraction(channel)
    return ((1 + d_lo) * (1 + r_lo) - 1.0,
            (1 + d_hi) * (1 + r_hi) - 1.0)


def error_classification() -> Dict[str, str]:
    """Which error sources divide out of a ratio and which do not."""
    return {
        "divider_tolerance": "gain",
        "rsense_tolerance": "gain",
        "alpha_hfe_constant": "gain",
        "dac_gain_error": "gain",
        "opamp_offset": "offset",
        "rbe_bleed": "offset",
        "dac_offset_error": "offset",
        "hfe_nonlinearity": "neither",
        "hfe_temperature_drift": "neither",
    }


# --------------------------------------------------------------------------
# hFE cancellation
# --------------------------------------------------------------------------

HFE_CANCELLATION_CAVEAT = (
    "A CONSTANT alpha = hFE/(hFE+1) is a pure multiplicative gain, so it "
    "divides out of PI = AC/DC and out of R. That is an algebraic result, not "
    "a hardware claim. Real hFE is a function of collector current and of "
    "junction temperature, and the 2SC1815 bin spread alone is 200-400 (70-700 "
    "across bins). Any hFE variation ACROSS the AC swing, or any thermal drift "
    "correlated with the modulation, survives the ratio. A 20000 per amp "
    "current dependence at the 7.5 mA operating point already produces about "
    "0.12 percent of PI error. MEASUREMENT-REQUIRED: the residual must be "
    "measured on the real transistor at the real operating point and over the "
    "real temperature range before any accuracy figure is quoted."
)


def _alpha_for(i_emitter: float, hfe_model: HfeModel) -> float:
    """alpha = I_C/I_E, solving the implicit relation when hFE depends on I_C."""
    if hfe_model is None:
        return 1.0
    if not callable(hfe_model):
        hfe = float(hfe_model)
        if hfe <= 0:
            raise ValueError(f"hfe must be positive, got {hfe}")
        return hfe / (hfe + 1.0)
    if i_emitter <= 0.0:
        return 1.0
    i_c = i_emitter
    for _ in range(64):
        hfe = float(hfe_model(i_c))
        if hfe <= 0:
            raise ValueError(f"hfe model returned {hfe} at I_C = {i_c}")
        nxt = i_emitter * hfe / (hfe + 1.0)
        if abs(nxt - i_c) <= 1e-21:
            i_c = nxt
            break
        i_c = nxt
    return i_c / i_emitter


def led_current_with_hfe_model(v_cmd: float, channel: ChannelDesign,
                               hfe_model: HfeModel = None,
                               rbe_ohm: Optional[float] = None,
                               vbe_on_v: Optional[float] = None) -> float:
    if vbe_on_v is None:
        vbe_on_v = channel.transistor.vbe_on_v
    i_emitter = sense_current(v_cmd, channel) - rbe_bleed_current(rbe_ohm, vbe_on_v)
    if i_emitter <= 0.0:
        return 0.0
    return _alpha_for(i_emitter, hfe_model) * i_emitter


def ac_dc_ratio_from_command(dc_cmd_v: float, ac_cmd_v: float,
                             channel: ChannelDesign,
                             hfe_model: HfeModel = None,
                             rbe_ohm: Optional[float] = None,
                             vbe_on_v: Optional[float] = None) -> float:
    """AC/DC of the LED current for a commanded AC/DC of the control voltage.

    With a constant hFE and no R_BE this returns exactly ac_cmd/dc_cmd: the
    gain cancels. Anything that returns something else is an error source that
    a ratio metric cannot remove.
    """
    if dc_cmd_v <= 0:
        raise ValueError("dc_cmd_v must be positive")
    if ac_cmd_v <= 0 or ac_cmd_v >= dc_cmd_v:
        raise ValueError("ac_cmd_v must be positive and smaller than dc_cmd_v")

    kw = dict(channel=channel, hfe_model=hfe_model, rbe_ohm=rbe_ohm,
              vbe_on_v=vbe_on_v)
    i_dc = led_current_with_hfe_model(dc_cmd_v, **kw)
    i_hi = led_current_with_hfe_model(dc_cmd_v + ac_cmd_v, **kw)
    i_lo = led_current_with_hfe_model(dc_cmd_v - ac_cmd_v, **kw)
    if i_dc <= 0.0:
        raise ValueError("DC operating point produces no LED current")
    return ((i_hi - i_lo) / 2.0) / i_dc


# --------------------------------------------------------------------------
# R_BE comparison
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RbeOption:
    rbe_ohm: Optional[float]
    bleed_a: float
    dead_zone_command_v: float
    dead_zone_codes: int
    dc_error_fraction: float
    pi_error_fraction: float
    ac_modulation_fraction: float
    turn_off_note: str


_TURN_OFF_WITH_RBE = (
    "R_BE holds the base-emitter junction off actively. Below the dead zone "
    "the transistor is fully off and the LED is dark.")

_TURN_OFF_WITHOUT_RBE = (
    "With R_BE unfitted (DNP) turn-off depends entirely on the LM358 output "
    "pulling the base down. The datasheet guarantees only 12 uA of sink "
    "current with the output near ground, so the turn-off edge and the "
    "residual LED current at code 0 are MEASUREMENT-REQUIRED.")


def rbe_ac_modulation_fraction(channel: ChannelDesign, dc_current_a: float,
                               ac_fraction: float,
                               rbe_ohm: Optional[float]) -> float:
    """How much of the AC signal R_BE steals, as a fraction of the AC amplitude.

    R_BE is not a perfectly constant bleed. V_BE moves by V_T * ln(1 + x) over
    a fractional current swing x, so the bleed current itself is modulated and
    a small part of the AC is lost. [ENGINEERING-INFERENCE] simple diode model.
    """
    if rbe_ohm is None:
        return 0.0
    if dc_current_a <= 0 or ac_fraction <= 0:
        raise ValueError("dc_current_a and ac_fraction must be positive")
    vt = channel.transistor.thermal_voltage_v
    d_vbe = vt * math.log(1.0 + ac_fraction)
    d_i_rbe = d_vbe / rbe_ohm
    ac_amplitude = ac_fraction * dc_current_a
    return d_i_rbe / ac_amplitude


def rbe_comparison(channel: ChannelDesign, dc_current_a: float,
                   hfe: float = 300.0,
                   vbe_on_v: Optional[float] = None,
                   ac_fraction: float = 0.01,
                   candidates: Sequence[Optional[float]] = (10_000.0, 100_000.0, None),
                   ) -> List[RbeOption]:
    """Compare R_BE candidates at one operating point. Decides nothing."""
    if vbe_on_v is None:
        vbe_on_v = channel.transistor.vbe_on_v
    alpha_const = hfe / (hfe + 1.0)
    options: List[RbeOption] = []

    for rbe in candidates:
        bleed = rbe_bleed_current(rbe, vbe_on_v)
        i_emitter = max(dc_current_a - bleed, 0.0)
        i_led = alpha_const * i_emitter
        dead_v = bleed * channel.rsense_ohm
        # Dead zone expressed in DAC codes, using the project's own mapping.
        dead_codes = voltage_to_code(
            min(dead_v / channel.divider.ratio, channel.dac.fullscale_v),
            channel.dac)
        # PI = AC/DC. A constant bleed leaves AC alone and shrinks DC, so the
        # measured PI is inflated by DC_ideal / (DC_ideal - bleed).
        pi_err = (dc_current_a / i_emitter - 1.0) if i_emitter > 0 else float("inf")
        options.append(RbeOption(
            rbe_ohm=rbe,
            bleed_a=bleed,
            dead_zone_command_v=dead_v,
            dead_zone_codes=dead_codes,
            dc_error_fraction=(i_led - dc_current_a) / dc_current_a,
            pi_error_fraction=pi_err,
            ac_modulation_fraction=rbe_ac_modulation_fraction(
                channel, dc_current_a, ac_fraction, rbe),
            turn_off_note=(_TURN_OFF_WITHOUT_RBE if rbe is None
                           else _TURN_OFF_WITH_RBE),
        ))
    return options


# --------------------------------------------------------------------------
# Aliasing
# --------------------------------------------------------------------------

ALIASING_CAVEAT = (
    "The TX updates at 1 kHz and the RX samples at 100 Hz, so with two ideal "
    "clocks the 1 kHz update tone folds to 0 Hz. That is a statement about "
    "ideal clocks, not about this system, and it must NOT be reported as a "
    "guarantee. Three things break it on Linux. First, phase: the fold to zero "
    "assumes a fixed phase relationship between the update instants and the "
    "sample instants, which nothing here enforces. Second, clock drift: the TX "
    "timer and the ADC sampling are derived from independent oscillators, so a "
    "relative error of only 100 ppm moves the alias anywhere in 0-0.2 Hz, "
    "which lands in the baseline region that feeds the DC term, and 500 ppm "
    "reaches 1 Hz, inside the heart-rate band. Third, jitter: userspace timer "
    "jitter means the update train is not a clean comb, so its energy spreads "
    "across frequency instead of collapsing onto one line. The real spectrum "
    "is MEASUREMENT-REQUIRED."
)


def alias_frequency_hz(f_signal_hz: float, f_sample_hz: float) -> float:
    """Folded frequency of a tone sampled below Nyquist. Ideal clocks only."""
    if f_sample_hz <= 0:
        raise ValueError("f_sample_hz must be positive")
    folded = abs(f_signal_hz - round(f_signal_hz / f_sample_hz) * f_sample_hz)
    return min(folded, f_sample_hz / 2.0)


def alias_band_hz(f_tx_hz: float, f_rx_hz: float,
                  tolerance_ppm: float) -> Tuple[float, float]:
    """Range the alias can occupy when the two clocks are independent.

    Worst case the two oscillators sit at opposite tolerance corners, so the
    alias spans 0 to f_tx * 2 * tolerance.
    """
    if tolerance_ppm < 0:
        raise ValueError("tolerance_ppm must not be negative")
    return 0.0, f_tx_hz * 2.0 * tolerance_ppm * 1e-6


def overlaps_band(band: Tuple[float, float],
                  target: Tuple[float, float]) -> bool:
    """True when two closed frequency intervals share any point."""
    return band[0] <= target[1] and target[0] <= band[1]
