"""
Compliance and headroom checks for the 5 V LED-driver candidate.

Stdlib only. No hardware access.

Three independent constraints must hold simultaneously for the current sink to
regulate at all:

  1. Input common mode : 0 <= V_cmd <= (V+) - 1.5 V at 25 C,
                                    <= (V+) - 2.0 V over the full temp range.
  2. Output headroom   : V_sense + V_BE + (I_B + I_RBE) * R_B <= (V+) - 1.5 V.
  3. Collector headroom: V_rail - V_F - V_sense >= MIN_VCE_V.

If any of them fails, the loop leaves its linear region and the "current sink"
silently stops sinking the commanded current. check_compliance_or_raise()
turns that into a loud failure instead.
"""

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from led_driver.dac import rbe_bleed_current, sense_current
from led_driver.params import ChannelDesign

_UNSET = object()

# Required collector-emitter voltage for the transistor to stay in the active
# region with margin. [ENGINEERING-INFERENCE] The 2SC1815 V_CE(sat) max is
# 0.25 V; 0.50 V leaves headroom for V_F spread and temperature.
# [MEASUREMENT-REQUIRED] The real onset of gain compression must be scoped.
MIN_VCE_V = 0.50

_VF_SELECTORS = ("min", "typ", "max")


class ComplianceError(ValueError):
    """Raised when the driver loop cannot regulate at the requested operating point."""


@dataclass(frozen=True)
class ComplianceResult:
    name: str
    channel: str
    ok: bool
    actual_v: float
    limit_v: float
    margin_v: float
    detail: str

    def __str__(self) -> str:
        state = "OK" if self.ok else "FAIL"
        return (f"[{state}] {self.channel}/{self.name}: "
                f"actual {self.actual_v:.4f} V, limit {self.limit_v:.4f} V, "
                f"margin {self.margin_v:+.4f} V - {self.detail}")


def forward_voltage(channel: ChannelDesign, vf_selector: str) -> float:
    """LED forward voltage for the named datasheet corner."""
    if vf_selector not in _VF_SELECTORS:
        raise ValueError(
            f"unknown vf_selector {vf_selector!r}; expected one of {_VF_SELECTORS}")
    return {
        "min": channel.led.vf_min_v,
        "typ": channel.led.vf_typ_v,
        "max": channel.led.vf_max_v,
    }[vf_selector]


# --------------------------------------------------------------------------
# 1. Input common mode
# --------------------------------------------------------------------------

def input_common_mode(v_cmd: float, channel: ChannelDesign,
                      over_temperature: bool = True) -> ComplianceResult:
    """Check the op-amp + input against its common-mode ceiling."""
    opamp = channel.opamp
    limit = (opamp.cm_max_over_temp_v if over_temperature
             else opamp.cm_max_25c_v)
    ok = opamp.negative_rail_v <= v_cmd <= limit
    scope = "0-70 C" if over_temperature else "25 C"
    return ComplianceResult(
        name="input_common_mode",
        channel=channel.name,
        ok=ok,
        actual_v=v_cmd,
        limit_v=limit,
        margin_v=limit - v_cmd,
        detail=f"LM358 common-mode ceiling (V+) - "
               f"{opamp.supply_v - limit:.1f} V over {scope}",
    )


# --------------------------------------------------------------------------
# 2. Output headroom
# --------------------------------------------------------------------------

def base_current(v_sense: float, channel: ChannelDesign, hfe: float,
                 rbe_ohm=_UNSET, vbe_on_v: Optional[float] = None) -> float:
    """Base current the op-amp must supply, after R_BE takes its share."""
    if hfe is None or hfe <= 0:
        raise ValueError(f"hfe must be positive, got {hfe}")
    if rbe_ohm is _UNSET:
        rbe_ohm = channel.rbe_ohm
    if vbe_on_v is None:
        vbe_on_v = channel.transistor.vbe_on_v
    i_emitter = sense_current(v_sense, channel) - rbe_bleed_current(
        rbe_ohm, vbe_on_v)
    if i_emitter <= 0.0:
        return 0.0
    return i_emitter / (hfe + 1.0)


def opamp_output_required_v(v_sense: float, channel: ChannelDesign,
                            hfe: float = None, rbe_ohm=_UNSET,
                            vbe_on_v: Optional[float] = None) -> float:
    """V_OUT the op-amp must produce: V_sense + V_BE + (I_B + I_RBE) * R_B.

    Both correction terms matter. The earlier analysis counted only I_B, which
    understates the R_B drop whenever R_BE is fitted.
    """
    if hfe is None:
        hfe = channel.transistor.hfe_abs_min
    if rbe_ohm is _UNSET:
        rbe_ohm = channel.rbe_ohm
    if vbe_on_v is None:
        vbe_on_v = channel.transistor.vbe_on_v

    i_base = base_current(v_sense, channel, hfe, rbe_ohm, vbe_on_v)
    i_rbe = rbe_bleed_current(rbe_ohm, vbe_on_v)
    return v_sense + vbe_on_v + (i_base + i_rbe) * channel.rb_ohm


def opamp_output_headroom(v_sense: float, channel: ChannelDesign,
                          hfe: float = None, rbe_ohm=_UNSET,
                          vbe_on_v: Optional[float] = None,
                          rail_v: Optional[float] = None) -> ComplianceResult:
    opamp = channel.opamp
    rail = opamp.supply_v if rail_v is None else rail_v
    limit = rail - opamp.output_headroom_v
    required = opamp_output_required_v(v_sense, channel, hfe, rbe_ohm, vbe_on_v)
    return ComplianceResult(
        name="opamp_output_headroom",
        channel=channel.name,
        ok=required <= limit,
        actual_v=required,
        limit_v=limit,
        margin_v=limit - required,
        detail="V_sense + V_BE + (I_B + I_RBE) * R_B against the LM358 "
               "high-side output limit",
    )


# --------------------------------------------------------------------------
# 3. Collector headroom
# --------------------------------------------------------------------------

def collector_emitter_voltage(channel: ChannelDesign, v_sense: float,
                              vf_selector: str = "max",
                              rail_v: Optional[float] = None) -> float:
    """V_CE across the transistor. May be negative; that is a real failure."""
    rail = channel.rail_v if rail_v is None else rail_v
    return rail - forward_voltage(channel, vf_selector) - v_sense


def led_compliance(channel: ChannelDesign, v_sense: float,
                   vf_selector: str = "max",
                   rail_v: Optional[float] = None,
                   min_vce_v: float = MIN_VCE_V) -> ComplianceResult:
    vce = collector_emitter_voltage(channel, v_sense, vf_selector, rail_v)
    rail = channel.rail_v if rail_v is None else rail_v
    return ComplianceResult(
        name="collector_headroom",
        channel=channel.name,
        ok=vce >= min_vce_v,
        actual_v=vce,
        limit_v=min_vce_v,
        margin_v=vce - min_vce_v,
        detail=f"V_CE = {rail:.2f} V rail - V_F({vf_selector}) "
               f"{forward_voltage(channel, vf_selector):.2f} V - V_sense {v_sense:.3f} V",
    )


def minimum_rail_v(channel: ChannelDesign, v_sense: float,
                   vf_selector: str = "max",
                   min_vce_v: float = MIN_VCE_V) -> float:
    """Lowest supply at which the collector branch still has its margin."""
    return forward_voltage(channel, vf_selector) + v_sense + min_vce_v


# --------------------------------------------------------------------------
# Sweeps and hard failure
# --------------------------------------------------------------------------

def supply_sweep(channels: Sequence[ChannelDesign],
                 rail_values_v: Iterable[float],
                 v_sense: float,
                 vf_selector: str = "max",
                 min_vce_v: float = MIN_VCE_V) -> List[ComplianceResult]:
    """Collector-headroom result for every (rail, channel) pair, in order."""
    results: List[ComplianceResult] = []
    for rail in rail_values_v:
        for channel in channels:
            results.append(
                led_compliance(channel, v_sense, vf_selector, rail, min_vce_v))
    return results


def compliance_report(channel: ChannelDesign, v_sense: float,
                      rail_v: Optional[float] = None,
                      vf_selector: str = "max",
                      hfe: float = None, rbe_ohm=_UNSET,
                      vbe_on_v: Optional[float] = None,
                      over_temperature: bool = True,
                      min_vce_v: float = MIN_VCE_V) -> List[ComplianceResult]:
    """All three constraints for one channel at one operating point."""
    return [
        input_common_mode(v_sense, channel, over_temperature),
        opamp_output_headroom(v_sense, channel, hfe, rbe_ohm, vbe_on_v, rail_v),
        led_compliance(channel, v_sense, vf_selector, rail_v, min_vce_v),
    ]


def check_compliance_or_raise(channel: ChannelDesign, v_sense: float,
                              rail_v: Optional[float] = None,
                              vf_selector: str = "max",
                              hfe: float = None, rbe_ohm=_UNSET,
                              vbe_on_v: Optional[float] = None,
                              over_temperature: bool = True,
                              min_vce_v: float = MIN_VCE_V) -> List[ComplianceResult]:
    """Raise ComplianceError if any constraint fails. Never clamps silently."""
    results = compliance_report(channel, v_sense, rail_v, vf_selector, hfe,
                                rbe_ohm, vbe_on_v, over_temperature, min_vce_v)
    failures = [r for r in results if not r.ok]
    if failures:
        rail = channel.rail_v if rail_v is None else rail_v
        lines = "\n  ".join(_failure_line(r) for r in failures)
        raise ComplianceError(
            f"Channel {channel.name} cannot regulate at V_sense = "
            f"{v_sense:.4f} V on a {rail:.2f} V rail:\n  {lines}")
    return results


def _failure_line(result: ComplianceResult) -> str:
    """Name the failing quantity in the form an engineer will grep for."""
    label = {
        "collector_headroom": "V_CE",
        "opamp_output_headroom": "V_OUT(op-amp)",
        "input_common_mode": "V_CM(input)",
    }.get(result.name, result.name)
    return (f"{label} = {result.actual_v:.4f} V, needs "
            f"{result.limit_v:.4f} V (short by {-result.margin_v:.4f} V) "
            f"- {result.detail}")
