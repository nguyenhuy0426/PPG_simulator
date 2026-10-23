"""Widgets the running app destroys must be finalized on the Tk thread.

Re-showing Recordings destroys the previous list rows, which leaves CTkFont and
PhotoImage objects in reference cycles. If the automatic collector then runs on
SignalDAC, each of their Tcl finalizers waits for the Tk thread with no
timeout. A Stop pressed at that moment holds the Tk thread in
SignalEngine._stop_thread, so the worker cannot finish before the 2 s join and
Stop fails with "refusing a second writer".

Automatic GC is disabled during the test so that the only collections are the
app's own and the one forced inside the DAC worker; that makes the race
deterministic. Needs a real display; skips on a headless machine.
"""

import gc
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
RECORDING_ROWS = 6


class CollectingDac:
    """Stands in for DACManager; collects once on SignalDAC when asked."""

    is_ready = True
    error_count_ir = error_count_red = 0

    def __init__(self):
        self.collect_requested = threading.Event()
        self.collecting = threading.Event()

    def begin(self):
        return True

    def shutdown(self):
        pass

    def set_values(self, ir, red):
        if threading.current_thread().name == "SignalDAC" and self.collect_requested.is_set():
            self.collect_requested.clear()
            self.collecting.set()
            gc.collect()


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class TestTkGarbageStaysOffOutputWorkers(unittest.TestCase):

    def test_stop_succeeds_while_dac_worker_collects_after_recordings_rebuild(self):
        from ui.ctk_app import CTkApp

        gc_was_enabled = gc.isenabled()
        gc.disable()
        dataset = tempfile.TemporaryDirectory()
        for i in range(RECORDING_ROWS):
            (Path(dataset.name) / f"session_{i}.csv").touch()
        app = CTkApp()
        app.withdraw()
        engine = app.engine
        real_dac = engine.dac_manager
        dac = CollectingDac()
        engine.dac_manager = dac
        app.frames["Playback"].dataset_dir = Path(dataset.name)
        result = {}

        def rebuild_recordings():
            # The second show destroys the rows the first one built.
            for _ in range(2):
                app.select_playback()
                app.select_pathology()
            app.after(200, press_stop)

        def press_stop():
            dac.collect_requested.set()
            result["worker_collected"] = dac.collecting.wait(2.0)
            time.sleep(0.05)
            started = time.perf_counter()
            try:
                engine.stop_simulation()
                result["stop"] = "stopped"
            except RuntimeError as exc:
                result["stop"] = str(exc)
            result["stop_s"] = time.perf_counter() - started
            wait_for_worker(time.perf_counter() + 10.0)

        def wait_for_worker(deadline):
            # A worker still waiting on a Tcl call needs a running mainloop:
            # _tkinter only hands calls over while mainloop dispatches.
            if engine._dac_thread.is_alive() and time.perf_counter() < deadline:
                app.after(20, wait_for_worker, deadline)
            else:
                app.quit()

        try:
            engine.start_simulation(engine.ppg_params.condition)
            app.after(300, rebuild_recordings)
            app.after(20000, app.quit)
            app.mainloop()
        finally:
            engine.dac_manager = real_dac
            app.on_closing()
            dataset.cleanup()
            if gc_was_enabled:
                gc.enable()

        self.assertTrue(result.get("worker_collected"), "the DAC worker never ran its collection")
        self.assertEqual(result.get("stop"), "stopped")
        self.assertLess(result["stop_s"], 1.0)


if __name__ == "__main__":
    unittest.main()
