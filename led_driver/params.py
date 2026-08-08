"""
Component and design parameters for the 5 V LED-driver candidate.

Stdlib only. No hardware access.

Sources
-------
[VERIFIED-USER]      Rail/supply configuration, I2C addresses, channel mapping,
                     the two isolated optical compartments.
[VERIFIED-DATASHEET] LM358 and 2SC1815 limits quoted below come from the
                     datasheets already collected in this repository under
                     docs/superpowers/ppg_design_audit/.
[ENGINEERING-INFERENCE] The candidate component values (R_sense, divider, R_B).

The candidate values are a HYPOTHESIS. They have not been built, probed or
measured. See DESIGN_STATUS.
"""

from dataclasses import dataclass, field
from typing import Optional

# --------------------------------------------------------------------------
# Global status marker
# --------------------------------------------------------------------------

DESIGN_STATUS = (
    "HYPOTHESIS - NOT HARDWARE-VERIFIED. Values are calculated from datasheet "
    "limits and the user-stated 5 V configuration. No board has been built, "
    "no current, voltage or optical measurement has been taken."
)

# DAC code -> voltage conventions ------------------------------------------
#
# CONVENTION_RATIOMETRIC reproduces the MCP4725 transfer relation as usually
# written for a ratiometric DAC:  V_OUT = V_DD * D / 2**N   (D = 0..2**N-1).
# CONVENTION_MAX_CODE reproduces what calibration.dac_voltage_to_code() in this
# repository actually implements:  code = round_down(V / V_FS * (2**N - 1)).
#
# They are NOT the same mapping. dac.convention_discrepancy() quantifies the
# difference. [VERIFIED-DATASHEET] The ratiometric relation is Equation 5-1 of
# docs/ds_linhkien/MCP4725-Data-Sheet.pdf (DS20002039E): V_OUT = V_DD * D / 4096
# with V_DD as the reference. CONVENTION_MAX_CODE remains what
# calibration.dac_voltage_to_code() in this repository actually implements.
CONVENTION_RATIOMETRIC = "ratiometric_2n"
CONVENTION_MAX_CODE = "fullscale_at_max_code"

VALID_CONVENTIONS = (CONVENTION_RATIOMETRIC, CONVENTION_MAX_CODE)


# --------------------------------------------------------------------------
# Component specifications
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DacSpec:
    """MCP4725 as configured in this project. [VERIFIED-USER] supply 3.28 V."""

    fullscale_v: float = 3.28
    resolution_bits: int = 12

    @property
    def level_count(self) -> int:
        """Number of distinct output levels (2**N)."""
        return 2 ** self.resolution_bits

    @property
    def max_code(self) -> int:
        """Largest writable code. One less than the level count."""
        return self.level_count - 1

    @property
    def lsb_v(self) -> float:
        """One code step, in volts. Full scale divided by the LEVEL COUNT."""
        return self.fullscale_v / self.level_count


@dataclass(frozen=True)
class DividerSpec:
    """Resistive attenuator between the DAC output and the op-amp + input."""

    r_top_ohm: float = 10_000.0
    r_bottom_ohm: float = 10_000.0
    tolerance_frac: float = 0.01

    @property
    def ratio(self) -> float:
        return self.r_bottom_ohm / (self.r_top_ohm + self.r_bottom_ohm)

    @property
    def thevenin_ohm(self) -> float:
        """Source impedance seen by the op-amp + input (parallel combination)."""
        return (self.r_top_ohm * self.r_bottom_ohm
                / (self.r_top_ohm + self.r_bottom_ohm))

    @property
    def dac_load_ohm(self) -> float:
        """DC load the divider presents to the DAC output (series sum)."""
        return self.r_top_ohm + self.r_bottom_ohm


@dataclass(frozen=True)
class LedSpec:
    """LED electrical limits. [VERIFIED-DATASHEET] unless noted."""

    name: str
    vf_typ_v: float
    vf_max_v: float
    vf_min_v: float
    if_max_continuous_a: float
    pd_max_w: float
    # True when vf_min_v is a real datasheet minimum. False when the datasheet
    # gives no minimum and the typical value is used as the lowest DOCUMENTED
    # forward voltage instead. A lower real V_F raises transistor dissipation,
    # so a False here means the transistor dissipation figure is optimistic.
    vf_min_is_datasheet_minimum: bool = True
    # Manufacturer "suggestion using current" window, when the datasheet gives
    # one. None means the datasheet states only an absolute maximum.
    if_suggested_a: Optional[tuple] = None
    # Absolute-maximum reverse voltage, when the datasheet states one. None
    # means the datasheet gives NO reverse abs max (the Red datasheet only
    # characterises leakage, 10 uA at V_R = 5 V), so the reverse destruction
    # threshold is [UNKNOWN].
    vr_max_v: Optional[float] = None


RED_LED = LedSpec(
    name="Red LED (TX Red channel)",
    vf_typ_v=2.00,
    vf_max_v=2.20,
    vf_min_v=1.80,
    if_max_continuous_a=0.020,
    pd_max_w=0.105,
    vf_min_is_datasheet_minimum=True,
    if_suggested_a=(0.016, 0.018),
    vr_max_v=None,
)

IR_LED = LedSpec(
    name="IR LED (TX IR channel)",
    vf_typ_v=1.30,
    vf_max_v=1.65,
    # [ENGINEERING-INFERENCE] The IR datasheet quotes typ 1.30 V and max 1.65 V
    # but no minimum. 1.30 V is used as the lowest DOCUMENTED value.
    vf_min_v=1.30,
    if_max_continuous_a=0.100,
    pd_max_w=0.150,
    vf_min_is_datasheet_minimum=False,
    if_suggested_a=None,
    # [VERIFIED-DATASHEET] SIR234 absolute maximum V_R = 5 V.
    vr_max_v=5.0,
)


@dataclass(frozen=True)
class OpAmpSpec:
    """LM358P classic PDIP on a 5.00 V single supply. [VERIFIED-USER] rail."""

    supply_v: float = 5.00
    negative_rail_v: float = 0.00

    vos_max_v: float = 7.0e-3            # 25 C
    vos_max_over_temp_v: float = 9.0e-3  # full temperature range
    ib_max_a: float = 250e-9             # 25 C, magnitude
    ib_max_over_temp_a: float = 500e-9

    # Input common-mode range is specified as (V-) to (V+) - 1.5 V at 25 C,
    # degrading to (V+) - 2.0 V over the full temperature range.
    cm_headroom_25c_v: float = 1.5
    cm_headroom_over_temp_v: float = 2.0

    # Output swing high is limited to roughly (V+) - 1.5 V for R_L >= 2 kohm.
    output_headroom_v: float = 1.5

    iq_max_a_per_amplifier: float = 600e-6
    gbw_hz: float = 0.7e6
    slew_rate_v_per_us: float = 0.3
    # Minimum guaranteed sink current with the output held near ground.
    sink_at_200mv_min_a: float = 12e-6

    @property
    def cm_max_25c_v(self) -> float:
        return self.supply_v - self.cm_headroom_25c_v

    @property
    def cm_max_over_temp_v(self) -> float:
        return self.supply_v - self.cm_headroom_over_temp_v

    @property
    def output_max_v(self) -> float:
        return self.supply_v - self.output_headroom_v


@dataclass(frozen=True)
class TransistorSpec:
    """2SC1815 NPN. [VERIFIED-DATASHEET] limits; V_BE is an inference."""

    vceo_max_v: float = 50.0
    ic_max_a: float = 0.150
    pc_max_w: float = 0.400
    hfe_bin_min: float = 200.0   # GR bin
    hfe_bin_max: float = 400.0
    hfe_abs_min: float = 70.0    # worst case across all bins
    hfe_abs_max: float = 700.0
    ft_hz: float = 80e6
    vce_sat_max_v: float = 0.25
    # Emitter-base breakdown, abs max (V_EBO). Stressed only in the
    # reversed-transistor fault case; see led_driver.faults.
    vebo_max_v: float = 5.0

    # [ENGINEERING-INFERENCE] V_BE at the few-mA operating points used here.
    # The datasheet characterises V_BE at much higher currents, so this is a
    # modelling assumption, not a datasheet number. [MEASUREMENT-REQUIRED]
    vbe_on_v: float = 0.70
    vbe_on_min_v: float = 0.65
    vbe_on_max_v: float = 0.75
    # Thermal voltage kT/q at 25 C, used for the small-signal V_BE model.
    thermal_voltage_v: float = 0.025852


LM358P = OpAmpSpec()
Q_2SC1815 = TransistorSpec()


# --------------------------------------------------------------------------
# Channel design
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ChannelDesign:
    """One TX channel: DAC -> divider -> LM358 -> 2SC1815 -> R_sense -> LED."""

    name: str
    led: LedSpec
    rsense_ohm: float
    rail_v: float = 5.00
    rsense_tolerance_frac: float = 0.01
    rb_ohm: float = 1_000.0
    # None means DNP (not fitted). R_BE is deliberately NOT finalised here:
    # see error_budget.rbe_comparison() and RBE_DECISION.
    rbe_ohm: Optional[float] = None
    divider: DividerSpec = field(default_factory=DividerSpec)
    dac: DacSpec = field(default_factory=DacSpec)
    opamp: OpAmpSpec = field(default_factory=OpAmpSpec)
    transistor: TransistorSpec = field(default_factory=TransistorSpec)
    status: str = DESIGN_STATUS


RED_CHANNEL_5V = ChannelDesign(
    name="Red",
    led=RED_LED,
    rsense_ohm=100.0,
)

IR_CHANNEL_5V = ChannelDesign(
    name="IR",
    led=IR_LED,
    rsense_ohm=82.0,
)

CHANNELS_5V = (RED_CHANNEL_5V, IR_CHANNEL_5V)
