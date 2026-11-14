"""The first DAC samples of a run come from the run itself, never from mid-scale.

Mid-scale (2048 = 1.64 V) for one model tick overloads the IR receive path,
whose reading then falls for seconds (hardware check 2026-11-14).
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("PPG_DRY_RUN", "1")

from config import UPSAMPLE_RATIO_PPG  # noqa: E402
from core.signal_engine import SignalEngine  # noqa: E402


def first_tick(engine, **start):
    # Workers not started: the test drives exactly one model tick itself.
    with mock.patch("core.signal_engine.threading.Thread.start"):
        engine.start_simulation(engine.ppg_params.condition, **start)
    engine._generate_one_tick()
    return engine._buf_ir[:UPSAMPLE_RATIO_PPG], engine._buf_red[:UPSAMPLE_RATIO_PPG]


class EngineStartupTest(unittest.TestCase):
    def setUp(self):
        self.engine = SignalEngine()

    def tearDown(self):
        self.engine._running = False

    def test_ppg_run_starts_at_its_own_level(self):
        self.engine.ppg_params.dc_ir_mv = 300.0
        self.engine.ppg_params.ac_ir_mv = 40.0
        ir, red = first_tick(self.engine)
        self.assertEqual(len(set(ir)), 1, ir)       # flat first tick: no ramp from another level
        self.assertLess(max(ir), 500)               # 300 mV + AC is ~375-425 codes, mid-scale is 2048
        self.assertEqual(len(set(red)), 1, red)

    def test_calibration_has_separate_ir_and_red_levels(self):
        with mock.patch("core.signal_engine.threading.Thread.start"):
            self.engine.start_calibration(1.0, 300.0, 1500.0, 100.0)
        self.assertEqual(self.engine._calibration, (1.0, 300.0, 1500.0, 100.0))
        ir, red = first_tick(self.engine, calibration=(1.0, 300.0, 1500.0, 100.0))
        self.assertLess(max(ir), 520)              # 300 ± 100 mV
        self.assertGreater(min(red), 1600)         # 1500 ± 100 mV on its own level
        with self.assertRaises(ValueError):
            self.engine.start_calibration(1.0, 50.0, 1000.0, 100.0)   # level - swing below 0


if __name__ == "__main__":
    unittest.main()
