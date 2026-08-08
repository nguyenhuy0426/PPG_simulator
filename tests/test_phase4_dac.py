"""
Phase 4 tests — dual-DAC TX path.

Covers: fixed channel mapping (0x60=IR, 0x61=Red), 3.28 V full-scale conversion
boundaries, per-channel DAC routing and write order, dry-run status, DAC
init-failure ("disconnected") behavior, per-channel write-error isolation,
write serialization, and safe shutdown state.

All tests are hardware-free: they use dry-run mode, injected fake DAC objects,
or fake board/busio/adafruit modules. No I2C access ever occurs.
Run: python3 -m unittest tests.test_phase4_dac
"""

import ast
import os
import pathlib
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import hw.dac_manager as dac_module
from hw.dac_manager import DACManager
from calibration import dac_voltage_to_code


# ─────────────────────────── Fakes ───────────────────────────

class FakeDAC:
    """Records raw_value writes into a shared journal as (name, value)."""

    def __init__(self, name, journal):
        self._name = name
        self._journal = journal

    @property
    def raw_value(self):
        return self._journal[-1][1] if self._journal else 0

    @raw_value.setter
    def raw_value(self, val):
        self._journal.append((self._name, val))


class FailingDAC:
    """Raises OSError on every write (simulates a disconnected/NACKing DAC)."""

    @property
    def raw_value(self):
        raise OSError("simulated I2C NACK")

    @raw_value.setter
    def raw_value(self, val):
        raise OSError("simulated I2C NACK")


class LockProbeDAC:
    """Records whether the manager's write lock is held during each write."""

    def __init__(self, manager, journal):
        self._manager = manager
        self._journal = journal

    @property
    def raw_value(self):
        return 0

    @raw_value.setter
    def raw_value(self, val):
        self._journal.append(self._manager._write_lock.locked())


class _DryRunPatch(unittest.TestCase):
    """Base: force hw.dac_manager.DRY_RUN to a known value per test class."""

    DRY_RUN_VALUE = True

    def setUp(self):
        self._saved_dry_run = dac_module.DRY_RUN
        dac_module.DRY_RUN = self.DRY_RUN_VALUE

    def tearDown(self):
        dac_module.DRY_RUN = self._saved_dry_run


# ─────────────────────── Channel mapping (fixed, verified) ───────────────────────

class TestChannelMapping(unittest.TestCase):
    """0x60 = IR TX, 0x61 = Red TX [VERIFIED-USER]. Never silently swap."""

    def test_ir_address_is_0x60(self):
        self.assertEqual(config.DAC_ADDR_IR, 0x60)

    def test_red_address_is_0x61(self):
        self.assertEqual(config.DAC_ADDR_RED, 0x61)

    def test_addresses_are_distinct(self):
        self.assertNotEqual(config.DAC_ADDR_IR, config.DAC_ADDR_RED)


# ─────────────────────── 3.28 V conversion boundaries (SSOT) ───────────────────────

class TestDacConversionBoundaries(unittest.TestCase):
    """dac_voltage_to_code is the single conversion path; full-scale is 3.28 V."""

    def test_fullscale_constant_is_3v28(self):
        # [VERIFIED-USER]: MCP4725 supply = 3.28 V, DAC full-scale = 3.28 V.
        self.assertEqual(config.DAC_FULLSCALE_V, 3.28)

    def test_adc_reference_is_3v28(self):
        # [VERIFIED-USER]: Grove ADC full-scale/reference used by this
        # project = 3.28 V.
        self.assertEqual(config.ADC_VOLTAGE_REF, 3.28)

    def test_dac_and_adc_constants_stay_independent_symbols(self):
        # DAC full-scale (TX path, MCP4725) and ADC reference (RX path, Grove
        # Base HAT) are physically different quantities that currently happen
        # to share the same 3.28 V numeric value. They must never be merged
        # into one symbol or defined in terms of each other, so that a future
        # measurement can move one without silently moving the other.
        # A numeric assertNotEqual can no longer express that, so assert the
        # structural property directly from the config.py source.
        src = pathlib.Path(config.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        assigned: dict = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                assigned[node.targets[0].id] = node.value
        for name in ("DAC_FULLSCALE_V", "ADC_VOLTAGE_REF"):
            self.assertIn(name, assigned, f"{name} must be a module-level assignment")
            self.assertIsInstance(
                assigned[name], ast.Constant,
                f"{name} must be its own numeric literal, not derived from another constant")
        # Neither may be an alias of the other.
        names_in_dac = {n.id for n in ast.walk(assigned["DAC_FULLSCALE_V"])
                        if isinstance(n, ast.Name)}
        names_in_adc = {n.id for n in ast.walk(assigned["ADC_VOLTAGE_REF"])
                        if isinstance(n, ast.Name)}
        self.assertNotIn("ADC_VOLTAGE_REF", names_in_dac)
        self.assertNotIn("DAC_FULLSCALE_V", names_in_adc)

    def test_zero_volts_maps_to_code_0(self):
        self.assertEqual(dac_voltage_to_code(0.0), 0)

    def test_fullscale_maps_to_code_4095(self):
        self.assertEqual(dac_voltage_to_code(config.DAC_FULLSCALE_V), 4095)

    def test_above_fullscale_clamps_to_4095(self):
        # 3.3 V (the old nominal VDD assumption) exceeds the measured 3.28 V
        # DAC full-scale and must clamp.
        self.assertEqual(dac_voltage_to_code(3.3), 4095)

    def test_negative_voltage_clamps_to_0(self):
        self.assertEqual(dac_voltage_to_code(-0.1), 0)

    def test_midscale_1v64(self):
        # 1.64 V is half of the 3.28 V full-scale:
        # int(1.64 / 3.28 * 4095) = 2047 (truncation, not rounding)
        self.assertEqual(dac_voltage_to_code(1.64), 2047)

    def test_just_below_fullscale(self):
        # 3.2799 V / 3.28 V * 4095 = 4094.87 → 4094
        self.assertEqual(dac_voltage_to_code(3.2799), 4094)

    def test_idle_value_is_zero_code(self):
        self.assertEqual(config.DAC_IDLE_VALUE, 0)

    def test_no_duplicate_conversion_in_dac_manager(self):
        # The legacy min/max-window normalization (its own *4095 formula) was
        # removed in Phase 4; conversion must stay centralized in calibration.
        self.assertFalse(hasattr(DACManager, "ppg_sample_to_dac_value"))


# ─────────────────────── Per-channel routing and write order ───────────────────────

class TestPerChannelRouting(_DryRunPatch):
    DRY_RUN_VALUE = False

    def setUp(self):
        super().setUp()
        self.journal = []
        self.mgr = DACManager()
        self.mgr._dac_ir = FakeDAC("IR", self.journal)
        self.mgr._dac_red = FakeDAC("RED", self.journal)
        self.mgr._ready = True

    def test_values_route_to_correct_channels(self):
        self.mgr.set_values(1000, 2000)
        self.assertIn(("IR", 1000), self.journal)
        self.assertIn(("RED", 2000), self.journal)

    def test_ir_written_before_red(self):
        self.mgr.set_values(111, 222)
        self.assertEqual(self.journal, [("IR", 111), ("RED", 222)])

    def test_clamping_to_12bit_range(self):
        self.mgr.set_values(-5, 5000)
        self.assertEqual(self.journal, [("IR", 0), ("RED", 4095)])
        self.assertEqual(self.mgr.last_ir, 0)
        self.assertEqual(self.mgr.last_red, 4095)

    def test_float_inputs_are_coerced_to_int(self):
        # MCP4725 fast-mode write bit-shifts the value; it must be an int.
        self.mgr.set_values(1000.9, 2000.2)
        self.assertEqual(self.journal, [("IR", 1000), ("RED", 2000)])

    def test_write_lock_held_during_writes(self):
        probes = []
        self.mgr._dac_ir = LockProbeDAC(self.mgr, probes)
        self.mgr._dac_red = LockProbeDAC(self.mgr, probes)
        self.mgr.set_values(1, 2)
        self.assertEqual(probes, [True, True])

    def test_ir_write_failure_does_not_block_red(self):
        self.mgr._dac_ir = FailingDAC()
        self.mgr.set_values(100, 200)  # must not raise
        self.assertEqual(self.journal, [("RED", 200)])
        self.assertEqual(self.mgr.error_count_ir, 1)
        self.assertEqual(self.mgr.error_count_red, 0)

    def test_red_write_failure_does_not_affect_ir(self):
        self.mgr._dac_red = FailingDAC()
        self.mgr.set_values(100, 200)  # must not raise
        self.assertEqual(self.journal, [("IR", 100)])
        self.assertEqual(self.mgr.error_count_ir, 0)
        self.assertEqual(self.mgr.error_count_red, 1)

    def test_error_counters_accumulate(self):
        self.mgr._dac_ir = FailingDAC()
        for _ in range(5):
            self.mgr.set_values(10, 20)
        self.assertEqual(self.mgr.error_count_ir, 5)
        self.assertEqual(self.mgr.error_count_red, 0)


# ─────────────────────── begin(): address wiring and init state ───────────────────────

class TestBeginAddressWiring(_DryRunPatch):
    DRY_RUN_VALUE = False

    _FAKE_MODULES = ("board", "busio", "adafruit_mcp4725")

    def setUp(self):
        super().setUp()
        self._saved_modules = {m: sys.modules.get(m) for m in self._FAKE_MODULES}

    def tearDown(self):
        for name, mod in self._saved_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        super().tearDown()

    def _install_fake_i2c_stack(self, created_addresses):
        fake_board = types.ModuleType("board")
        fake_board.SCL = "SCL"
        fake_board.SDA = "SDA"

        fake_busio = types.ModuleType("busio")
        fake_busio.I2C = lambda scl, sda: ("fake-i2c", scl, sda)

        class FakeMCP4725:
            def __init__(self, i2c, address):
                self.address = address
                created_addresses.append(address)
                self._raw = 0

            @property
            def raw_value(self):
                return self._raw

            @raw_value.setter
            def raw_value(self, val):
                self._raw = val

        fake_adafruit = types.ModuleType("adafruit_mcp4725")
        fake_adafruit.MCP4725 = FakeMCP4725

        sys.modules["board"] = fake_board
        sys.modules["busio"] = fake_busio
        sys.modules["adafruit_mcp4725"] = fake_adafruit

    def test_begin_constructs_ir_0x60_then_red_0x61(self):
        created = []
        self._install_fake_i2c_stack(created)
        mgr = DACManager()
        self.assertTrue(mgr.begin())
        self.assertEqual(created, [0x60, 0x61])
        self.assertEqual(mgr._dac_ir.address, config.DAC_ADDR_IR)
        self.assertEqual(mgr._dac_red.address, config.DAC_ADDR_RED)

    def test_begin_parks_outputs_at_safe_idle(self):
        created = []
        self._install_fake_i2c_stack(created)
        mgr = DACManager()
        mgr.begin()
        self.assertEqual(mgr._dac_ir.raw_value, config.DAC_IDLE_VALUE)
        self.assertEqual(mgr._dac_red.raw_value, config.DAC_IDLE_VALUE)

    def test_begin_failure_leaves_manager_not_ready(self):
        # "Disconnected DAC" at init: force the import chain to fail
        # deterministically (None in sys.modules → ImportError on import).
        sys.modules["board"] = None
        mgr = DACManager()
        self.assertFalse(mgr.begin())
        self.assertFalse(mgr.is_ready)
        # Writes after a failed init must be safe no-ops (no exception).
        mgr.set_values(1000, 2000)
        self.assertEqual(mgr.last_ir, 1000)
        self.assertEqual(mgr.last_red, 2000)


# ─────────────────────── Dry-run status ───────────────────────

class TestDryRunMode(_DryRunPatch):
    DRY_RUN_VALUE = True

    def test_begin_succeeds_without_hardware(self):
        mgr = DACManager()
        self.assertTrue(mgr.begin())
        self.assertTrue(mgr.is_ready)

    def test_set_values_tracks_last_written(self):
        mgr = DACManager()
        mgr.begin()
        mgr.set_values(123, 456)
        self.assertEqual(mgr.last_ir, 123)
        self.assertEqual(mgr.last_red, 456)

    def test_initial_state_is_safe_idle(self):
        mgr = DACManager()
        self.assertEqual(mgr.last_ir, config.DAC_IDLE_VALUE)
        self.assertEqual(mgr.last_red, config.DAC_IDLE_VALUE)

    def test_shutdown_parks_at_idle_and_disables(self):
        mgr = DACManager()
        mgr.begin()
        mgr.set_values(3000, 3000)
        mgr.shutdown()
        self.assertEqual(mgr.last_ir, config.DAC_IDLE_VALUE)
        self.assertEqual(mgr.last_red, config.DAC_IDLE_VALUE)
        self.assertFalse(mgr.is_ready)
        mgr.set_values(1, 2)  # must not raise after shutdown


# ─────────────────────── Engine safe-state integration ───────────────────────

class TestEngineSafeState(_DryRunPatch):
    """SignalEngine must park DACs at safe idle on begin/stop/shutdown."""

    DRY_RUN_VALUE = True

    def _make_engine(self):
        from core.signal_engine import SignalEngine
        return SignalEngine()  # fresh instance, not the singleton

    def test_begin_parks_dacs_at_idle(self):
        engine = self._make_engine()
        engine.begin()
        self.assertEqual(engine.dac_manager.last_ir, config.DAC_IDLE_VALUE)
        self.assertEqual(engine.dac_manager.last_red, config.DAC_IDLE_VALUE)

    def test_stop_simulation_parks_dacs_at_idle(self):
        engine = self._make_engine()
        engine.begin()
        engine.dac_manager.set_values(2000, 2000)
        engine.stop_simulation()
        self.assertEqual(engine.dac_manager.last_ir, config.DAC_IDLE_VALUE)
        self.assertEqual(engine.dac_manager.last_red, config.DAC_IDLE_VALUE)

    def test_shutdown_parks_dacs_and_disables_writes(self):
        engine = self._make_engine()
        engine.begin()
        engine.dac_manager.set_values(2000, 2000)
        engine.shutdown()
        self.assertEqual(engine.dac_manager.last_ir, config.DAC_IDLE_VALUE)
        self.assertEqual(engine.dac_manager.last_red, config.DAC_IDLE_VALUE)
        self.assertFalse(engine.dac_manager.is_ready)


if __name__ == "__main__":
    unittest.main()
