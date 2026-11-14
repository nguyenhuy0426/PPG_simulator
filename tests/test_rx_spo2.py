"""Received SpO2 estimate: R recovered from synthetic IR/RED streams, refusal paths, and the RED lane reading."""
import math
import os
import random
import time
import unittest

from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED
from core.rx_spo2 import estimate_rx_spo2
from hw.opt101_rx import RXSample

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
A, B = 110.0, 25.0


def channel(ac, dc, bpm=75, seconds=8.0, hz=100.0, offset=0.0, noise=2.0, seed=0, clip=4095, base=100.0, phase=0.0):
    rng = random.Random(seed)
    out = []
    for i in range(int(seconds*hz)):
        t = i/hz+offset
        beat = 2*math.pi*bpm/60*t+phase
        value = dc+ac*(math.sin(beat)+.4*math.sin(2*beat-1.1))+15*math.sin(2*math.pi*.1*t)+rng.gauss(0, noise)
        raw = max(0, min(clip, round(value)))
        out.append(RXSample(base+t, raw, raw >= clip))
    return out


def pair(ratio, ac_ir=60.0, dc_ir=1500.0, dc_red=1200.0, **kwargs):
    """IR and RED streams whose true R is `ratio`, with different DC levels."""
    ac_red = ratio*ac_ir*dc_red/dc_ir
    return channel(ac_ir, dc_ir, seed=1, **kwargs), channel(ac_red, dc_red, seed=2, **kwargs)


class EstimatorTest(unittest.TestCase):
    def test_ratio_and_spo2_are_recovered_with_different_dc_levels(self):
        for ratio in (.5, .6, .8, 1.0, 1.4):
            with self.subTest(ratio=ratio):
                result = estimate_rx_spo2(*pair(ratio), A, B)
                self.assertEqual(result.reason, "ok")
                self.assertAlmostEqual(result.ratio, ratio, delta=.03)
                self.assertAlmostEqual(result.spo2, A-B*ratio, delta=1.0)

    def test_tdm_rate_with_channels_read_at_different_times(self):
        ir = channel(60, 1500, hz=22.2, offset=0.0, seed=1)
        red = channel(48, 1200, hz=22.2, offset=0.015, seed=2)
        result = estimate_rx_spo2(ir, red, A, B)
        self.assertEqual(result.reason, "ok")
        self.assertAlmostEqual(result.ratio, 1.0, delta=.05)

    def test_dark_level_is_taken_out_of_dc(self):
        ir, red = channel(60, 1500, seed=1), channel(60, 300, seed=2)
        plain = estimate_rx_spo2(ir, red, A, B)
        dark = estimate_rx_spo2(ir, red, A, B, ir_dark=100, red_dark=100)
        self.assertAlmostEqual(plain.ratio, 5.0, delta=.2)
        self.assertAlmostEqual(dark.ratio, (60/200)/(60/1400), delta=.3)

    def test_refuses_what_it_cannot_read(self):
        ir, red = pair(.8)
        self.assertEqual(estimate_rx_spo2([], red, A, B).reason, "short")
        self.assertEqual(estimate_rx_spo2(ir[:300], red, A, B).reason, "short")
        self.assertEqual(estimate_rx_spo2(channel(60, 4070, seed=1), red, A, B).reason, "saturated")
        self.assertEqual(estimate_rx_spo2(ir, channel(1, 1200, noise=.3), A, B).reason, "weak")
        self.assertEqual(estimate_rx_spo2(ir, channel(60, 1200, bpm=110), A, B).reason, "mismatch")
        self.assertEqual(estimate_rx_spo2(ir, channel(60, 1200, phase=math.pi), A, B).reason, "mismatch")
        self.assertEqual(estimate_rx_spo2(channel(20, 40, seed=1), red, A, B, ir_dark=35).reason, "no_dc")

    def test_out_of_scale_keeps_r_and_gives_no_value(self):
        result = estimate_rx_spo2(*pair(.2), A, B)  # 110 - 25*0.2 = 105 %
        self.assertEqual(result.reason, "out_of_range")
        self.assertIsNone(result.spo2)
        self.assertAlmostEqual(result.ratio, .2, delta=.03)


class FakeReceiver:
    is_simulated = False

    def __init__(self, streams, statuses=None):
        self.streams, self.statuses = streams, statuses or {}

    def channel_status(self, channel):
        return self.statuses.get(channel, "ok")

    def get_samples(self, channel):
        return tuple(self.streams.get(channel, ()))

    def is_stale(self, channel, now=None):
        return False


def live(samples):
    shift = time.monotonic()-samples[-1].timestamp
    return [RXSample(s.timestamp+shift, s.raw, s.saturated) for s in samples]


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class PanelTest(unittest.TestCase):
    def make_panel(self, receiver):
        import tkinter as tk
        from ui.rx_monitor import RXPanel
        root = tk.Tk()
        self.addCleanup(root.destroy)
        panel = RXPanel(root, language="vi", receiver=receiver, width=600, height=300)
        panel.pack()
        root.update()
        return panel

    def test_red_lane_shows_rate_and_spo2_estimate_together(self):
        ir, red = pair(.6)
        panel = self.make_panel(FakeReceiver({ADC_CHANNEL_IR: live(ir), ADC_CHANNEL_RED: live(red)}))
        panel.periodic_update()
        self.assertRegex(panel.lanes[0].badge, r"^Nhịp RX  7[4-6] bpm$")
        self.assertRegex(panel.lanes[1].badge, r"^Nhịp RX  7[4-6] bpm$")
        self.assertEqual(panel.lanes[0].badge2, "")
        self.assertRegex(panel.lanes[1].badge2, r"^SpO₂ RX ước tính  \d+ %  R 0\.[56]\d$")
        texts = [panel.itemcget(i, "text") for i in panel.find_all() if panel.type(i) == "text"]
        self.assertTrue(any(t.startswith("SpO₂ RX ước tính") for t in texts))

    def test_no_spo2_without_both_channels(self):
        ir, _red = pair(.6)
        panel = self.make_panel(FakeReceiver({ADC_CHANNEL_IR: live(ir)}, {ADC_CHANNEL_RED: "disabled"}))
        panel.periodic_update()
        self.assertEqual(panel.lanes[1].badge2, "")


if __name__ == "__main__":
    unittest.main()
