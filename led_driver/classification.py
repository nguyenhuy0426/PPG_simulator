"""
Stage 1 value classification for the 5 V LED-driver candidate.

Stdlib only. No hardware access.

Every value in the candidate design is classified as exactly one of:

  FIXED                 - fixed by datasheet or by calculation; changing it
                          contradicts local evidence.
  RECOMMENDED           - a recommended starting value; calculation-backed
                          but expected to be adjusted on the bench.
  MEASUREMENT_REQUIRED  - cannot be settled without a bench measurement;
                          deliberately carries NO value here so a number
                          cannot be mistaken for a decision.
  UNKNOWN               - no reliable grounding in the local evidence.

Per the task instruction, R_BE, the C1 input filter and C2 are NOT finalised
from theory: they are MEASUREMENT_REQUIRED with their permitted option sets
recorded in the basis text.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from led_driver.params import IR_CHANNEL_5V, RED_CHANNEL_5V

FIXED = "FIXED BY DATASHEET/CALCULATION"
RECOMMENDED = "RECOMMENDED STARTING VALUE"
MEASUREMENT_REQUIRED = "MEASUREMENT-REQUIRED"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ValueEntry:
    name: str
    description: str
    value: Optional[float]
    unit: str
    classification: str
    basis: str


VALUE_TABLE: Tuple[ValueEntry, ...] = (
    # -- Fixed by datasheet or calculation ---------------------------------
    ValueEntry(
        "dac_fullscale", "MCP4725 full-scale / V_DD reference",
        RED_CHANNEL_5V.dac.fullscale_v, "V", FIXED,
        "[VERIFIED-USER] measured 3.28 V rail; Equation 5-1 of "
        "MCP4725-Data-Sheet.pdf makes V_DD the reference."),
    ValueEntry(
        "adc_reference", "Grove Base HAT ADC reference (independent symbol)",
        3.28, "V", FIXED,
        "[VERIFIED-USER] 3.28 V. Kept as a separate symbol from the DAC "
        "full scale (see 00_BASE_CONTEXT F-10 vs F-15)."),
    ValueEntry(
        "rail_5v", "LED / LM358P supply rail",
        5.00, "V", FIXED,
        "[VERIFIED-USER] the LM358P and LED strings run from 5.00 V; the "
        "task forbids introducing a 12 V design."),
    ValueEntry(
        "divider_ratio", "DAC-to-command attenuation ratio",
        RED_CHANNEL_5V.divider.ratio, "V/V", FIXED,
        "Fixed by calculation: the classic LM358 common-mode ceiling is "
        "(V+)-2.0 V = 3.00 V over temperature, so the 3.28 V DAC full scale "
        "must be attenuated; /2 puts the maximum command at 1.64 V."),
    ValueEntry(
        "opamp_output_ceiling", "LM358P output swing high (R_L >= 2 kohm)",
        RED_CHANNEL_5V.opamp.output_max_v, "V", FIXED,
        "[VERIFIED-DATASHEET] classic LM358 table at V+ = 5 V."),
    ValueEntry(
        "opamp_cm_limit", "LM358P input common-mode ceiling over temperature",
        RED_CHANNEL_5V.opamp.cm_max_over_temp_v, "V", FIXED,
        "[VERIFIED-DATASHEET] classic LM358 table: (V+)-2.0 V over "
        "temperature. The binding constraint behind the divider."),

    # -- Recommended starting values ---------------------------------------
    ValueEntry(
        "rsense_red", "Red channel sense resistor",
        RED_CHANNEL_5V.rsense_ohm, "ohm", RECOMMENDED,
        "100 ohm puts full scale at 16.40 mA, inside the datasheet "
        "suggestion window (16-18 mA) and under the 20 mA abs max. "
        "Compliance and dissipation close with margin; may be adjusted "
        "after optical measurements."),
    ValueEntry(
        "rsense_ir", "IR channel sense resistor",
        IR_CHANNEL_5V.rsense_ohm, "ohm", RECOMMENDED,
        "82 ohm puts full scale at 20.00 mA, one fifth of the SIR234 "
        "100 mA continuous rating; may be adjusted after optical "
        "measurements."),
    ValueEntry(
        "rb", "Base series resistor",
        RED_CHANNEL_5V.rb_ohm, "ohm", RECOMMENDED,
        "1 kohm limits the shorted-R_sense base drive to 2.8 mA and "
        "isolates the op-amp from the base; loop stability against C2 is "
        "bench-dependent."),
    ValueEntry(
        "divider_r_abs", "Divider absolute resistance (each leg)",
        RED_CHANNEL_5V.divider.r_top_ohm, "ohm", RECOMMENDED,
        "10 kohm legs load the DAC with 20 kohm (well above the 5 kohm "
        "characterisation load) and give a 5 kohm Thevenin source for C1. "
        "The 1:1 ratio is FIXED; the absolute value is a starting choice."),
    ValueEntry(
        "c3_lm358_bypass", "LM358P V+ bypass",
        100e-9, "F", RECOMMENDED,
        "Standard local decoupling practice; placement at the V+ pin "
        "matters more than the exact value."),
    ValueEntry(
        "c4_5v_bulk", "5 V rail bulk + HF pair",
        10e-6, "F", RECOMMENDED,
        "10 uF bulk plus 100 nF HF at the rail entry; standard practice."),
    ValueEntry(
        "c5_opt101_bypass", "OPT101 supply bypass, one per channel",
        100e-9, "F", RECOMMENDED,
        "Per OPT101 datasheet good practice on the 3.28 V rail."),

    # -- Measurement-required (no number is a decision) --------------------
    ValueEntry(
        "rbe", "Base-emitter bleed resistor", None, "ohm",
        MEASUREMENT_REQUIRED,
        "Options DNP / 100 kohm / 10 kohm. Theory quantifies the trade "
        "(dead zone and PI distortion vs turn-off assistance: see "
        "error_budget.rbe_comparison) but the task forbids finalising R_BE "
        "from theory alone; footprint fitted, value chosen on the bench."),
    ValueEntry(
        "c1_input_filter", "Command-node input filter", None, "F",
        MEASUREMENT_REQUIRED,
        "Options DNP / 10 nF / 100 nF / 220 nF against the 5 kohm Thevenin "
        "source (see led_driver.filters). Chosen with a scope on TP_CMD_*."),
    ValueEntry(
        "c2", "Feedback/compensation capacitor", None, "F",
        MEASUREMENT_REQUIRED,
        "DNP initially. Fitted only if the bench shows loop instability; "
        "value cannot be derived without measured parasitics."),
    ValueEntry(
        "transistor_hfe_installed", "hFE of the installed 2SC1815", None, "",
        MEASUREMENT_REQUIRED,
        "Bin unknown until measured (O/Y/GR/BL span 70-700). Feedback "
        "makes the design first-order insensitive, but base-current error "
        "depends on it."),
    ValueEntry(
        "vbe_on", "V_BE(on) at the few-mA operating points", None, "V",
        MEASUREMENT_REQUIRED,
        "[ENGINEERING-INFERENCE] 0.65-0.75 V modelling band; datasheet "
        "characterises V_BE at much higher currents."),
    ValueEntry(
        "transistor_pinout_installed", "Pinout of the installed 2SC1815",
        None, "", MEASUREMENT_REQUIRED,
        "Datasheet order is E-C-B, but the installed part must be DMM-"
        "confirmed before power-on; package pin ordering is never assumed "
        "from the part name."),
    ValueEntry(
        "led_polarity_installed", "Anode/cathode of both installed LEDs",
        None, "", MEASUREMENT_REQUIRED,
        "DMM diode-test before power-on. A reversed SIR234 sits within "
        "~0.2 V of its 5 V reverse abs max at a 5.00 V rail (see "
        "led_driver.faults.reversed_led)."),
    ValueEntry(
        "mcp4725_eeprom_contents", "Power-on EEPROM code of each MCP4725",
        None, "", MEASUREMENT_REQUIRED,
        "Factory default is mid-scale (Table 5-3) which lights both LEDs "
        "at boot. Readable over I2C without any EEPROM write (see "
        "led_driver.startup)."),
    ValueEntry(
        "opt101_feedback_strap", "OPT101 pin 4-to-5 strap (1 Mohm feedback)",
        None, "", MEASUREMENT_REQUIRED,
        "Continuity-check on the assembled module before trusting the "
        "transimpedance gain."),

    # -- Unknown -----------------------------------------------------------
    ValueEntry(
        "red_led_reverse_abs_max", "Red LED reverse-voltage absolute maximum",
        None, "V", UNKNOWN,
        "The YSL-R341R3D-D2 datasheet characterises only leakage (10 uA at "
        "V_R = 5 V) and states no reverse abs max; the destruction "
        "threshold has no local grounding."),
)


def by_name(name: str) -> Optional[ValueEntry]:
    for entry in VALUE_TABLE:
        if entry.name == name:
            return entry
    return None
