"""APFT-GAN on the Neural page: worker contract, HR request, its own 300 s limit, one BLAS thread.

The worker is mocked; tests/test_apft_preview.py runs the real checkpoint when assets/apft/generator.pt is present.
"""
from dataclasses import asdict
import contextlib
import io
import json
import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("PPG_DRY_RUN", "1")

from core import sequence_worker
from core.neural_preview import Preview

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def fake_preview(seed=7, hr=90.0):
    samples = [(i / 40, 1.5 + .045 * (i % 40) / 40, 1.5 + .0216 * (i % 40) / 40) for i in range(1200)]
    return Preview("APFT-GAN", samples, 40, seed, hr, None, "sha", (hr,), "apft_gan_v3_hr_v1",
                   dict(checkpoint_step=1250, paired_ir_red=False))


class WorkerTest(unittest.TestCase):
    def test_apft_runs_with_the_requested_heart_rate(self):
        calls = []

        class FakeGenerator:
            def generate(self, seed, hr):
                calls.append((seed, hr))
                return fake_preview(seed, hr)
        module = types.ModuleType("core.apft_preview")
        module.APFTSequenceGenerator, module.RangeMiss = FakeGenerator, ValueError
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"core.apft_preview": module}), contextlib.redirect_stdout(out):
            sequence_worker.main(["7", "APFT-GAN", "90"])
        self.assertEqual(calls, [(7, 90.0)])
        preview = json.loads(out.getvalue())
        self.assertEqual((preview["name"], preview["hr_target"], len(preview["samples"])), ("APFT-GAN", 90.0, 1200))

    def test_apft_gets_its_own_time_limit(self):
        # Pi 4: 12 s load + 91-100 s per window; the 120 s limit of the other models would kill it.
        self.assertEqual(sequence_worker.timeout_s("APFT-GAN"), 300)
        self.assertEqual(sequence_worker.timeout_s("PSF-GAN"), 120)
        self.assertEqual(sequence_worker.timeout_s("LSM-GAN"), 120)
        self.assertIn("APFT-GAN", sequence_worker.HR_MODELS)


class FakeProcess:
    def __init__(self, command, cwd=None, stdout=None, stderr=None, env=None):
        self.command, self.env, self.stdout, self.result, self.killed = command, env, stdout, None, False

    def poll(self):
        return self.result

    def kill(self):
        self.killed, self.result = True, -9

    def wait(self, timeout=None):
        return self.result


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class NeuralPageApftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ui.ctk_app import CTkApp
        from ui.frames import neural_frame
        cls.neural_frame = neural_frame
        CTkApp._maximize_to_work_area = lambda self: None
        cls.app = CTkApp(language="vi")
        cls.app._save_language = lambda: None
        cls.app.withdraw()
        cls.page = cls.app.frames["Neural"]

    @classmethod
    def tearDownClass(cls):
        cls.app.on_closing()

    def setUp(self):
        self.started = []
        self._popen = self.neural_frame.subprocess.Popen

        def popen(command, **kwargs):
            process = FakeProcess(command, **kwargs)
            self.started.append(process)
            return process
        self.neural_frame.subprocess.Popen = popen
        page = self.page
        if page._process is not None:          # the page's own start-up generation
            page._process = None
            page._busy = False
        page.previews.pop("APFT-GAN", None)

    def tearDown(self):
        self.neural_frame.subprocess.Popen = self._popen
        self.page._process, self.page._busy = None, False

    def select_apft(self, lo=70, hi=80):
        page = self.page
        page.mode = "Gaussian (fitted)"
        page.hr_min_slider.set(lo)
        page.hr_max_slider.set(hi)
        page.adjust("hr_max")
        page.change_mode(self.neural_frame.COPY["vi"]["apft"])
        self.assertEqual(page.mode, "APFT-GAN")
        return self.started[-1]

    def range_preview(self, measured=74.2, lo=70.0, hi=80.0):
        preview = fake_preview(7, (lo + hi) / 2)
        preview.provenance.update(hr_range=[lo, hi], hr_measured_bpm=measured, batch_index=1,
                                  tries=[[7, 0, 72.5, 88.0, 0.0], [7, 1, 77.5, measured, 0.0]])
        return preview

    def test_apft_asks_the_worker_for_the_hr_range(self):
        process = self.select_apft(70, 80)
        page = self.page
        self.assertIn(self.neural_frame.COPY["vi"]["apft"], page.mode_menu._values)
        self.assertEqual(process.command[-5:], ["APFT-GAN", "75", "--hr-range", "70", "80"])
        self.assertEqual((process.env["OMP_NUM_THREADS"], process.env["OPENBLAS_NUM_THREADS"]), ("1", "1"))
        self.assertEqual(page.previews["Real sequence"].variant, "real_train_30s")
        self.assertTrue(page.hr_min_slider._disabled and page.hr_max_slider._disabled)   # fixed while generating

    def test_apft_shows_min_and_max_instead_of_one_hr(self):
        page = self.page
        self.select_apft()
        page.update_idletasks()
        self.assertFalse(page.hr_slider.winfo_ismapped() and page.hr_slider.grid_info())
        self.assertTrue(page.hr_min_slider.grid_info() and page.hr_max_slider.grid_info())
        self.assertEqual((page.hr_min_slider.minimum, page.hr_max_slider.maximum), (60.0, 100.0))
        page._process, page._busy = None, False
        page.change_mode(self.neural_frame.COPY["vi"]["fitted"])
        self.assertTrue(page.hr_slider.grid_info())
        self.assertFalse(page.hr_min_slider.grid_info())

    def test_min_and_max_keep_two_bpm_apart(self):
        page = self.page
        self.select_apft(70, 80)
        page._process, page._busy = None, False
        page._set_hr_controls("normal")
        page.hr_min_slider.set(95)
        page.adjust("hr_min")
        self.assertEqual(page.hr_range, [95.0, 97.0])
        page.hr_max_slider.set(60)
        page.adjust("hr_max")
        self.assertEqual(page.hr_range, [60.0, 62.0])
        page.hr_min_slider.set(100)
        page.adjust("hr_min")
        self.assertEqual(page.hr_range, [98.0, 100.0])

    def test_apft_survives_past_120_s_and_stops_at_300_s(self):
        page = self.page
        process = self.select_apft()
        page._started -= 150
        page.periodic_update()
        self.assertFalse(process.killed)
        self.assertIn("150 s", page.status.cget("text"))
        page._started -= 160
        page.periodic_update()
        self.assertTrue(process.killed)
        self.assertIn("300 s", page.status.cget("text"))
        self.assertFalse(page._busy)

    def test_window_in_range_is_shown_with_its_measured_rate(self):
        page = self.page
        process = self.select_apft(70, 80)
        page._stdout.write(json.dumps(asdict(self.range_preview(74.2))).encode())
        process.result = 0
        page.periodic_update()
        self.assertIn("APFT-GAN", page.previews)
        self.assertFalse(page._busy)
        text = page.status.cget("text")
        for part in ("74.2", "70–80", "2 lần", "1250"):
            self.assertIn(part, text)

    def test_no_window_in_range_is_reported_not_played(self):
        page = self.page
        process = self.select_apft(70, 72)
        page._stdout.write(json.dumps(dict(error="hr_range", range=[70.0, 72.0],
                                           tries=[[1, 0, 70.5, 83.4, 0.0], [1, 1, 71.5, None, 1.0],
                                                  [2, 0, 60.0, 74.6, 0.0]])).encode())
        process.result = 2
        page.periodic_update()
        self.assertNotIn("APFT-GAN", page.previews)
        text = page.status.cget("text")
        for part in ("3 đoạn", "70–72", "75–83 bpm"):
            self.assertIn(part, text)
        self.assertEqual(str(page.play_btn.cget("state")), "disabled")

    def test_changing_the_range_drops_the_stale_window(self):
        page = self.page
        self.select_apft(70, 80)
        page._process, page._busy = None, False
        page._set_hr_controls("normal")
        page.previews["APFT-GAN"] = self.range_preview(74.2, 70.0, 80.0)
        page.hr_max_slider.set(90)
        page.adjust("hr_max")
        self.assertNotIn("APFT-GAN", page.previews)


if __name__ == "__main__":
    unittest.main()
