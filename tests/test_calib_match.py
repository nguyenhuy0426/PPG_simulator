"""RX-vs-TX level match behind the Calibration pass dot."""
import math
import unittest

from core.calib_match import level_match


def sine(level, swing, n=200, offset=0.0, noise=0.0):
    return [level + offset + swing * math.sin(2 * math.pi * i / 100) + noise * ((i * 37) % 7 - 3) for i in range(n)]


class LevelMatchTest(unittest.TestCase):
    def test_steady_level_within_and_outside_tolerance(self):
        self.assertTrue(level_match([1004.0] * 50, 1000, 0, 5).ok)
        miss = level_match([1012.0] * 50, 1000, 0, 5)
        self.assertFalse(miss.ok)
        self.assertAlmostEqual(miss.error_mv, 12)

    def test_sine_compares_peak_and_trough(self):
        self.assertTrue(level_match(sine(1000, 200, noise=1), 1000, 200, 10).ok)
        shrunk = level_match(sine(1000, 150), 1000, 200, 10)     # amplitude lost, same mean
        self.assertFalse(shrunk.ok)
        self.assertLess(shrunk.error_mv, -40)
        self.assertFalse(level_match(sine(1000, 200, offset=30), 1000, 200, 10).ok)

    def test_too_few_samples_is_undecided(self):
        self.assertIsNone(level_match([1000.0] * 5, 1000, 0, 10))


if __name__ == "__main__":
    unittest.main()
