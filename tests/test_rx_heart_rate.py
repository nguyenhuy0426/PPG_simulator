"""Received (OPT101) pulse rate: accuracy on synthetic RX streams, refusal paths, and the RX lane badge."""
import math
import os
import random
import unittest

from core.rx_heart_rate import MIN_SECONDS, estimate_rx_rate, latest_stretch
from hw.opt101_rx import RXSample

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def rx_stream(bpm, seconds=8.0, hz=100.0, ac=40.0, dc=1500.0, noise=2.0, drift=30.0, jitter=0.002, seed=0,
              sigma=0.0, clip=4095):
    """Pulse with a dicrotic wave on an LED DC level, slow drift, ADC noise, timing jitter and quantisation."""
    rng = random.Random(seed)
    onsets, t = [], -rng.uniform(0, 60/bpm)
    while t < seconds+2:
        onsets.append(t)
        t += 60/bpm*math.exp(sigma*rng.gauss(0, 1)-sigma**2/2)
    samples, k = [], 0
    for i in range(int(seconds*hz)):
        ts = i/hz+rng.uniform(-jitter, jitter)
        while k+1 < len(onsets) and onsets[k+1] <= ts:
            k += 1
        phase = 2*math.pi*(ts-onsets[k])/(onsets[k+1]-onsets[k])
        pulse = math.sin(phase)+.4*math.sin(2*phase-1.1)+.1*math.sin(3*phase-2.2)
        value = dc+ac*pulse+drift*math.sin(2*math.pi*.1*ts)+rng.gauss(0, noise)
        raw = max(0, min(clip, round(value)))
        samples.append(RXSample(100.0+ts, raw, raw >= clip))
    return samples


class EstimatorTest(unittest.TestCase):
    def test_rate_tracks_the_received_pulse_across_the_range(self):
        for bpm in (40, 60, 72, 95, 120, 150, 180):
            with self.subTest(bpm=bpm):
                rate = estimate_rx_rate(rx_stream(bpm, seed=bpm))
                self.assertEqual(rate.reason, "ok")
                self.assertAlmostEqual(rate.bpm, bpm, delta=max(2.0, .03*bpm))

    def test_mildly_irregular_rhythm_keeps_its_rate_and_a_strong_one_never_gets_a_wrong_one(self):
        mild = [estimate_rx_rate(rx_stream(95, sigma=.1, seed=k)) for k in range(10)]
        self.assertGreaterEqual(sum(r.reason == "ok" for r in mild), 8)
        for rate in mild + [estimate_rx_rate(rx_stream(95, sigma=.3, seed=k)) for k in range(10)]:
            self.assertIn(rate.reason, ("ok", "unclear"))
            if rate.bpm is not None:
                self.assertAlmostEqual(rate.bpm, 95, delta=10)

    def test_refuses_short_flat_clipped_and_noise_only_input(self):
        self.assertEqual(estimate_rx_rate(rx_stream(72, seconds=MIN_SECONDS-1)).reason, "short")
        self.assertEqual(estimate_rx_rate(rx_stream(72, ac=1.0, noise=.4, drift=0)).reason, "weak")
        self.assertEqual(estimate_rx_rate(rx_stream(72, dc=4070, ac=60)).reason, "saturated")
        rated = 0
        for seed in range(40):
            rng = random.Random(seed)
            rated += estimate_rx_rate([RXSample(i/100, round(1500+rng.gauss(0, 20)), False) for i in range(800)]).bpm is not None
        self.assertLessEqual(rated, 4)  # band-passed white noise rarely looks periodic twice over
        self.assertEqual(estimate_rx_rate([]).reason, "short")

    def test_only_the_newest_gap_free_stretch_is_used(self):
        old = rx_stream(60, seconds=4, seed=1)
        new = [RXSample(s.timestamp+10, s.raw, s.saturated) for s in rx_stream(120, seconds=7, seed=2)]
        self.assertEqual(latest_stretch(old+new), new)
        rate = estimate_rx_rate(old+new)
        self.assertAlmostEqual(rate.bpm, 120, delta=3.6)
        # A hole leaves too little after it: no rate rather than one spliced across the hole.
        late = [RXSample(s.timestamp+10, s.raw, s.saturated) for s in rx_stream(120, seconds=3, seed=2)]
        self.assertEqual(estimate_rx_rate(rx_stream(60, seconds=8)+late).reason, "short")


class FakeReceiver:
    def __init__(self, samples, simulated=False):
        self.samples, self.is_simulated = samples, simulated

    def channel_status(self, channel):
        return "ok" if channel == 0 else "disabled"

    def get_samples(self, channel):
        return tuple(self.samples) if channel == 0 else ()

    def is_stale(self, channel, now=None):
        return False


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class PanelTest(unittest.TestCase):
    def make_panel(self, receiver, language):
        import tkinter as tk
        from ui.rx_monitor import RXPanel
        root = tk.Tk()
        self.addCleanup(root.destroy)
        panel = RXPanel(root, language=language, receiver=receiver, width=600, height=300)
        panel.pack()
        root.update()
        return panel

    def test_live_lane_shows_the_received_rate_and_dry_run_shows_none(self):
        import time
        samples = rx_stream(84, seconds=8)
        shift = time.monotonic()-samples[-1].timestamp
        live = [RXSample(s.timestamp+shift, s.raw, s.saturated) for s in samples]
        panel = self.make_panel(FakeReceiver(live), "vi")
        panel.periodic_update()
        self.assertRegex(panel.lanes[0].badge, r"^Nhịp RX  8[3-5] bpm$")
        self.assertEqual(panel.lanes[1].badge, "")
        texts = [panel.itemcget(i, "text") for i in panel.find_all() if panel.type(i) == "text"]
        self.assertTrue(any(t.startswith("Nhịp RX") for t in texts))
        dry = self.make_panel(FakeReceiver(live, simulated=True), "en")
        dry.periodic_update()
        self.assertEqual([lane.badge for lane in dry.lanes], ["", ""])


if __name__ == "__main__":
    unittest.main()
