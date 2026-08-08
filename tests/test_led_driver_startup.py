"""
Theoretical driver tests — startup, shutdown and I2C-loss behaviour (Stage 1
items 17 and 18).

Grounded in MCP4725-Data-Sheet.pdf (DS20002039E), read locally:
  - Equation 5-1:  V_OUT = V_DD * D / 4096 (ratiometric).
  - Table 5-3:     factory-default EEPROM = normal mode, D11=1 and all other
                   bits 0 -> DAC register code 0x800 at power-on.
  - Section 5.4:   POR threshold V_POR = 2 V (typ); EEPROM is uploaded into
                   the DAC register when V_DD crosses it.
  - Section 7.3/4: General Call Reset (0x06) / Wake-up (0x09) act on EVERY
                   device on the bus, not one address.

The consequence under test: an MCP4725 module whose EEPROM still holds the
factory default drives V_DD/2 = 1.64 V at power-on, which this circuit turns
into LED current BEFORE any Raspberry Pi software runs. The installed modules'
actual EEPROM contents are MEASUREMENT-REQUIRED (readable over I2C without any
EEPROM write).

Run: python3 -m unittest tests.test_led_driver_startup
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from led_driver import startup
from led_driver.params import IR_CHANNEL_5V, RED_CHANNEL_5V

MA = 1e-3


class TestFactoryDefaultPowerOn(unittest.TestCase):
    """Item 17: state before the Raspberry Pi takes control."""

    def test_factory_default_eeprom_code_is_mid_scale(self):
        self.assertEqual(startup.POR_DEFAULT_DAC_CODE, 0x800)

    def test_power_on_dac_output_is_half_the_supply(self):
        v = startup.power_on_dac_output_v()
        self.assertAlmostEqual(v, 3.28 * 0x800 / 4096, places=6)
        self.assertAlmostEqual(v, 1.640, places=3)

    def test_power_on_command_after_divider_is_0_82_v(self):
        self.assertAlmostEqual(startup.power_on_command_v(), 0.820, places=3)

    def test_red_led_draws_8_2_ma_at_power_on(self):
        i = startup.power_on_sense_current_a(RED_CHANNEL_5V)
        self.assertAlmostEqual(i / MA, 8.200, places=3)

    def test_ir_led_draws_10_0_ma_at_power_on(self):
        i = startup.power_on_sense_current_a(IR_CHANNEL_5V)
        self.assertAlmostEqual(i / MA, 10.000, places=3)

    def test_power_on_current_is_exactly_half_of_full_scale(self):
        from led_driver import dac
        for ch in (RED_CHANNEL_5V, IR_CHANNEL_5V):
            with self.subTest(channel=ch.name):
                self.assertAlmostEqual(
                    startup.power_on_sense_current_a(ch),
                    dac.full_scale_current(ch) / 2.0, places=9)

    def test_power_on_current_is_under_both_channel_ceilings(self):
        for ch in (RED_CHANNEL_5V, IR_CHANNEL_5V):
            with self.subTest(channel=ch.name):
                self.assertTrue(startup.power_on_current_is_safe(ch))

    def test_leds_are_on_at_boot_with_factory_default_eeprom(self):
        self.assertTrue(startup.leds_on_at_boot())

    def test_a_zero_eeprom_keeps_leds_off_at_boot(self):
        self.assertFalse(startup.leds_on_at_boot(eeprom_code=0))
        self.assertEqual(startup.power_on_sense_current_a(
            RED_CHANNEL_5V, eeprom_code=0), 0.0)

    def test_installed_eeprom_contents_are_measurement_required(self):
        self.assertIn("MEASUREMENT-REQUIRED", startup.EEPROM_CONTENTS_STATUS)
        self.assertIn("read", startup.EEPROM_CONTENTS_STATUS.lower())

    def test_por_threshold_and_settling_come_from_the_datasheet(self):
        self.assertAlmostEqual(startup.V_POR_TYP_V, 2.0)
        self.assertAlmostEqual(startup.SETTLING_TIME_TYP_S, 6e-6)
        # Settling is far faster than the 1 ms DAC update period.
        self.assertLess(startup.SETTLING_TIME_TYP_S, 1e-3 / 10)


class TestDacOutputDrive(unittest.TestCase):
    """Resolves the old F-B3 [UNKNOWN]: MCP4725 output drive capability."""

    def test_divider_load_is_far_above_the_minimum_recommended_load(self):
        self.assertGreater(startup.DIVIDER_LOAD_OHM,
                           2 * startup.MIN_RECOMMENDED_LOAD_OHM)

    def test_divider_current_is_far_below_the_25_ma_output_limit(self):
        # 3.28 V across 20 kohm = 164 uA << 25 mA.
        self.assertLess(startup.divider_load_current_a(),
                        startup.OUTPUT_MAX_LOAD_A / 100)


class TestI2cLossAndShutdown(unittest.TestCase):
    """Item 18: shutdown, exception and loss-of-I2C behaviour."""

    def test_dac_holds_the_last_code_when_i2c_is_lost(self):
        # The MCP4725 has no watchdog: LED current continues at the last
        # commanded value indefinitely.
        i = startup.i2c_loss_sense_current_a(RED_CHANNEL_5V, last_code=2496)
        from led_driver import dac
        expected = dac.sense_current(
            dac.command_voltage_from_code(2496, RED_CHANNEL_5V),
            RED_CHANNEL_5V)
        self.assertAlmostEqual(i, expected, places=9)
        self.assertGreater(i, 0.0)

    def test_i2c_loss_at_code_zero_leaves_leds_off(self):
        self.assertEqual(
            startup.i2c_loss_sense_current_a(RED_CHANNEL_5V, last_code=0), 0.0)

    def test_general_call_reset_caveat_mentions_all_devices(self):
        text = startup.GENERAL_CALL_RESET_CAVEAT.lower()
        self.assertIn("every", text)
        self.assertIn("bus", text)

    def test_software_shutdown_parks_both_dacs_at_code_zero(self):
        import config
        self.assertEqual(config.DAC_IDLE_VALUE, 0)
        self.assertEqual(startup.SHUTDOWN_PARK_CODE, config.DAC_IDLE_VALUE)


if __name__ == "__main__":
    unittest.main()
