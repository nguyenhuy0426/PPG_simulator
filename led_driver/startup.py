"""
Startup, shutdown and I2C-loss behaviour of the TX chain (Stage 1 items
17 and 18).

Stdlib only. No hardware access.

Grounded in docs/ds_linhkien/MCP4725-Data-Sheet.pdf (DS20002039E)
[VERIFIED-DATASHEET]:

  - Table 5-3: the factory-default EEPROM is normal mode with D11 = 1 and
    all other data bits 0, i.e. DAC code 0x800 (mid-scale) at power-on.
  - Section 5.4: on POR (V_POR = 2 V typ) the EEPROM contents are uploaded
    into the DAC register - the output is driven BEFORE any I2C traffic.
  - Equation 5-1: V_OUT = V_DD * D / 4096.
  - Sections 7.3/7.4: General Call Reset (0x06) and Wake-up (0x09) address
    EVERY device on the bus, so they must not be used as a per-channel
    control in a two-DAC system.
  - Output settling 6 us typ; abs max output current 25 mA; DC specs are
    characterised into a 5 kohm load.

The consequence: a module whose EEPROM still holds the factory default
drives V_DD/2 = 1.64 V at power-on, which this circuit turns into LED
current (half of full scale) before any Raspberry Pi software runs. The
installed modules' actual EEPROM contents are MEASUREMENT-REQUIRED; the
MCP4725 read command returns both the DAC register and the EEPROM, so
they can be verified read-only, without any EEPROM write.
"""

from typing import Optional

from led_driver import dac
from led_driver.params import ChannelDesign, DacSpec, DividerSpec

# [VERIFIED-DATASHEET] MCP4725 Table 5-3 factory default: mid-scale.
POR_DEFAULT_DAC_CODE = 0x800
# [VERIFIED-DATASHEET] Section 5.4, typical POR threshold.
V_POR_TYP_V = 2.0
# [VERIFIED-DATASHEET] Output settling time, typical.
SETTLING_TIME_TYP_S = 6e-6
# [VERIFIED-DATASHEET] Absolute maximum output current.
OUTPUT_MAX_LOAD_A = 25e-3
# [VERIFIED-DATASHEET] DC accuracy is specified into a 5 kohm load; lighter
# loads (higher resistance) are safe, heavier loads sag the output.
MIN_RECOMMENDED_LOAD_OHM = 5000.0
# DC load the 10k + 10k divider presents to the DAC output.
DIVIDER_LOAD_OHM = DividerSpec().dac_load_ohm

# The software parking value on every exit path (normal, exception, Ctrl+C,
# timeout). Must equal config.DAC_IDLE_VALUE.
SHUTDOWN_PARK_CODE = 0

EEPROM_CONTENTS_STATUS = (
    "MEASUREMENT-REQUIRED - the installed modules' EEPROM contents have not "
    "been read. The MCP4725 read command returns the DAC register AND the "
    "EEPROM, so the power-up code is verifiable read-only; no EEPROM write "
    "is needed or permitted.")

GENERAL_CALL_RESET_CAVEAT = (
    "The MCP4725 General Call Reset (0x00, 0x06) and Wake-up (0x00, 0x09) "
    "act on every device on the I2C bus, including the second DAC and any "
    "other General-Call-aware part. They are bus-wide commands, not "
    "per-channel controls, and must not be used to manage one LED channel.")


def power_on_dac_output_v(eeprom_code: int = POR_DEFAULT_DAC_CODE,
                          spec: Optional[DacSpec] = None) -> float:
    """DAC output right after POR, before any I2C write (Equation 5-1)."""
    if spec is None:
        spec = DacSpec()
    return dac.code_to_voltage(eeprom_code, spec)


def power_on_command_v(eeprom_code: int = POR_DEFAULT_DAC_CODE,
                       divider: Optional[DividerSpec] = None,
                       spec: Optional[DacSpec] = None) -> float:
    """Op-amp command voltage right after POR (DAC output after the divider)."""
    if divider is None:
        divider = DividerSpec()
    return power_on_dac_output_v(eeprom_code, spec) * divider.ratio


def power_on_sense_current_a(channel: ChannelDesign,
                             eeprom_code: int = POR_DEFAULT_DAC_CODE) -> float:
    """LED-path current the loop regulates to at power-on, before software."""
    v_cmd = dac.command_voltage_from_code(eeprom_code, channel)
    return dac.sense_current(v_cmd, channel)


def power_on_current_is_safe(channel: ChannelDesign,
                             eeprom_code: int = POR_DEFAULT_DAC_CODE) -> bool:
    """True when the pre-software current stays under the LED's continuous
    abs-max rating. Safe-by-rating is not the same as intended: with the
    factory default the LEDs are ON at boot."""
    return (power_on_sense_current_a(channel, eeprom_code)
            < channel.led.if_max_continuous_a)


def leds_on_at_boot(eeprom_code: int = POR_DEFAULT_DAC_CODE) -> bool:
    """Whether any LED current flows before the Raspberry Pi takes control."""
    return eeprom_code > 0


def divider_load_current_a(spec: Optional[DacSpec] = None) -> float:
    """Worst-case DC current the divider draws from the DAC output."""
    if spec is None:
        spec = DacSpec()
    return spec.fullscale_v / DIVIDER_LOAD_OHM


def i2c_loss_sense_current_a(channel: ChannelDesign, last_code: int) -> float:
    """Item 18: the MCP4725 has no watchdog and holds its register through
    an I2C failure, so the LED continues at the LAST commanded current
    indefinitely. Only parking the DACs at code 0 before/after risky
    operations bounds this exposure."""
    v_cmd = dac.command_voltage_from_code(last_code, channel)
    return dac.sense_current(v_cmd, channel)
