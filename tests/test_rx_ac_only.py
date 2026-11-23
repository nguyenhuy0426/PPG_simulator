"""RX lanes plot the AC part only (DC level removed); the Calibration page keeps the received level.

The samples are synthetic fixtures, not OPT101 measurements. The Tk test needs a display (Xvfb is fine).
"""
import math
import os
import time
import unittest

from ui.rx_monitor import remove_dc

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
DC_MV = 1240.0
AC_MV = 30.0          # peak amplitude, so 60 mV peak to peak


def pulse(now, seconds=8.0, rate_hz=100):
    n = int(seconds * rate_hz)
    return [(now - seconds + i / rate_hz, DC_MV + AC_MV * math.sin(2 * math.pi * 1.25 * i / rate_hz))
            for i in range(n)]


class RemoveDcTest(unittest.TestCase):
    def test_mean_is_removed_and_the_swing_kept(self):
        out = remove_dc(pulse(100.0))
        values = [v for _t, v in out]
        self.assertAlmostEqual(sum(values) / len(values), 0.0, places=6)
        self.assertAlmostEqual(max(values) - min(values), 2 * AC_MV, delta=0.5)
        self.assertEqual([t for t, _ in out], [t for t, _ in pulse(100.0)])

    def test_empty_lane_stays_empty(self):
        self.assertEqual(remove_dc([]), [])

    def test_a_dark_stretch_still_shows_as_a_step(self):
        points = [(i * 0.01, DC_MV) for i in range(400)] + [(4 + i * 0.01, 5.0) for i in range(400)]
        values = [v for _t, v in remove_dc(points)]
        self.assertAlmostEqual(values[0] - values[-1], DC_MV - 5.0, places=6)


class FakeReceiver:
    is_simulated = False
    sample_period_s = 0.01

    def __init__(self, samples):
        self.samples = samples

    def channel_status(self, channel):
        return "ok"

    def is_stale(self, channel, now=None):
        return False

    def get_samples_since(self, channel, since):
        return [s for s in self.samples if s.timestamp >= since]


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class RxPanelAcOnlyTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from hw.opt101_rx import RXSample
        from ui.rx_monitor import MV_PER_CODE
        self.root = tk.Tk()
        now = time.monotonic()
        self.receiver = FakeReceiver([RXSample(t, round(v / MV_PER_CODE), False) for t, v in pulse(now)])

    def tearDown(self):
        self.root.destroy()

    def panel(self, **kwargs):
        from ui.rx_monitor import RXPanel
        panel = RXPanel(self.root, language="en", receiver=self.receiver, vitals=False, width=600, height=300,
                        **kwargs)
        panel.pack(fill="both", expand=True)
        self.root.update()
        panel.periodic_update()
        return panel

    def test_lanes_are_centred_on_zero_and_the_header_gives_the_ac_swing(self):
        panel = self.panel()
        for lane in panel.lanes:
            values = [v for _t, v in lane.points]
            self.assertLess(abs(sum(values) / len(values)), 1.0)
            self.assertLess(max(abs(v) for v in values), 2 * AC_MV)
            self.assertIn("AC", lane.detail)
            self.assertIn("p-p", lane.detail)
            self.assertNotIn(f"{DC_MV:.0f}", lane.detail)

    def test_calibration_keeps_the_received_level(self):
        panel = self.panel(ac_only=False)
        for lane in panel.lanes:
            values = [v for _t, v in lane.points]
            self.assertAlmostEqual(sum(values) / len(values), DC_MV, delta=5.0)
            self.assertNotIn("AC", lane.detail)


if __name__ == "__main__":
    unittest.main()
