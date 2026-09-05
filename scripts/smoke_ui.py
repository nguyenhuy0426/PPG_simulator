#!/usr/bin/env python3
"""Exercise the actual Tk app on DISPLAY; capture only this app's rectangle.
Run: DISPLAY=:97 venv/bin/python scripts/smoke_ui.py --output docs/ui
Requires a display (e.g. Xvfb), Pillow and requirements/test.txt.
"""
import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["PPG_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import ImageGrab
from core.signal_engine import SignalEngine
from core.csv_logger import CSVLogger
from config_store import config_from_ppg_params
from ui.ctk_app import CTkApp
from ui.recordings import load_recording


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/ui")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    engine = SignalEngine.get_instance()
    engine.begin()
    app = CTkApp()
    errors = []
    app.report_callback_exception = lambda *error: errors.append(error)

    def pump(seconds=.1):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.update()
            time.sleep(.01)
        assert not errors, errors

    def screenshot(name):
        pump()
        x, y = app.winfo_rootx(), app.winfo_rooty()
        ImageGrab.grab(xdisplay=os.environ.get("DISPLAY"),
                      bbox=(x, y, x+app.winfo_width(), y+app.winfo_height())).save(output / name)

    try:
        with tempfile.TemporaryDirectory(prefix="ppg-ui-record-") as temporary:
            app.csv_logger = CSVLogger(temporary)
            monitor = app.frames["Pathology"]
            monitor.logger = app.csv_logger
            app.geometry("1280x800+0+0")
            pump()
            engine.update_heart_rate(90)
            engine.update_ac_levels(25, 12)
            monitor.on_show()
            monitor.toggle_simulation()
            pump(.25)
            monitor.toggle_recording()
            before = config_from_ppg_params(engine.ppg_params)
            beat_count = engine.get_beat_count()
            for page in ("Advanced", "Calibration", "Playback", "Pathology"):
                app._show_frame(page)
                pump(.2)
                assert config_from_ppg_params(engine.ppg_params) == before
                assert engine._running
                assert engine.get_beat_count() >= beat_count
            monitor.toggle_recording()
            recordings = list(Path(temporary).glob("data_*.csv"))
            assert len(recordings) == 1
            samples, _, _ = load_recording(recordings[0])
            assert len(samples) >= 50, len(samples)
            assert all(abs(b[0]-a[0]-.01)<1e-6 for a,b in zip(samples,samples[1:]))
            # Restore the default live view for documentation captures.
            engine.update_heart_rate(75)
            engine.update_ac_levels(45, None)
            monitor.on_show()
            pump(8.2)
            screenshot("monitor-1280.png")
            for page, filename in (("Advanced", "setup-1280.png"), ("Calibration", "calibration-1280.png")):
                app._show_frame(page)
                screenshot(filename)
            app.select_advanced()
            advanced = app.frames["Advanced"]
            advanced.tabs.set("Respiration")
            screenshot("respiration-1280.png")
            advanced.on_apply_respiration()
            assert "Applied" in advanced.status.cget("text")
            advanced.tabs.set("Noise & calibration")
            advanced.on_apply_noise()
            assert "Applied" in advanced.status.cget("text")
            screenshot("noise-1280.png")
            advanced.tabs.set("Amplitude & shape")
            advanced.on_apply_signal()
            assert "Applied" in advanced.status.cget("text")
            before = config_from_ppg_params(engine.ppg_params)
            advanced.entries["ac_ir_mv"].delete(0, "end")
            advanced.entries["ac_ir_mv"].insert(0, "invalid")
            advanced.on_apply_signal()
            assert config_from_ppg_params(engine.ppg_params) == before
            assert "number" in advanced.status.cget("text")
            app.select_calibration()
            calibration = app.frames["Calibration"]
            calibration.toggle()
            pump(.3)
            assert engine.is_calibrating
            app.select_pathology()
            assert not engine._running
            assert engine.dac_manager.last_ir == engine.dac_manager.last_red == 0
            monitor.toggle_simulation()
            pump(1)
            app.select_playback()
            app.frames["Playback"].load_data(recordings[0])
            app.frames["Playback"].toggle_playback()
            pump(.3)
            screenshot("recordings-1280.png")
            app.geometry("1024x600+0+0")
            app.select_pathology()
            pump()
            for value in monitor.vital_labels.values():
                parent = value.master
                assert value.winfo_y() >= 0
                assert value.winfo_y() + value.winfo_height() <= parent.winfo_height(), "Clipped vital value"
            screenshot("monitor-1024.png")
            app.select_advanced()
            screenshot("setup-1024.png")
        print("PASS: navigation, parameter entry, invalid input, recording across pages, playback, calibration, 1024x600 metrics")
    finally:
        app.on_closing()
        engine.shutdown()
    assert not engine._running
    print("PASS: shutdown parks both simulated DACs at 0; screenshots in", output)


if __name__ == "__main__":
    main()
