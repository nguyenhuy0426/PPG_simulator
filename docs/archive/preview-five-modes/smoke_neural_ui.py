#!/usr/bin/env python3
"""Exercise the real Neural UI and capture only its window; no hardware writes."""
import argparse
import copy
import os
from pathlib import Path
import sys
import time

os.environ["PPG_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import ImageGrab
from core.signal_engine import SignalEngine
from config_store import config_from_ppg_params
from ui.ctk_app import CTkApp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/ui/neural"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    engine = SignalEngine.get_instance()
    engine.begin()
    app = CTkApp()
    app._save_language = lambda: None  # UI smoke must not modify the user's config.
    errors = []
    app.report_callback_exception = lambda *error: errors.append(error)

    def pump(seconds=.1):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            app.update()
            time.sleep(.01)
        assert not errors, errors

    def capture(name):
        pump()
        x, y = app.winfo_rootx(), app.winfo_rooty()
        ImageGrab.grab(xdisplay=os.environ.get("DISPLAY"),
                       bbox=(x, y, x+app.winfo_width(), y+app.winfo_height())).save(args.output / name)

    try:
        pump()
        app.attributes("-zoomed", False)
        initial_width = min(1280, app.winfo_screenwidth())
        initial_height = min(800, app.winfo_screenheight())
        app.geometry(f"{initial_width}x{initial_height}+0+0")
        app._show_frame("Neural")
        panel = app.frames["Neural"]
        assert panel.selected == "Gaussian (fitted)"
        assert panel.backend is None  # original mode works without loading torch
        params = copy.deepcopy(config_from_ppg_params(engine.ppg_params))
        panel.generate_btn.invoke()
        deadline = time.monotonic() + 45
        ticks = 0
        while panel.busy and time.monotonic() < deadline:
            pump(.05)
            ticks += 1
        assert not panel.busy and len(panel.previews) == 5, panel.status.cget("text")
        assert ticks > 0
        assert len(panel.traces["Gaussian (original)"].samples) > 1
        assert len(panel.traces["Gaussian (fitted)"].samples) > 1
        capture(f"neural-{initial_width}.png")
        panel.switch_btn.invoke()
        assert panel.selected == "Gaussian (original)"
        panel.switch_btn.invoke()
        assert panel.selected == "cWGAN-GP"
        panel.switch_btn.invoke()
        assert panel.selected == "LSM-GAN"
        panel.both.set(False)
        panel.render()
        pump()
        assert not panel.cards["cWGAN-GP"].winfo_ismapped()
        assert panel.cards["LSM-GAN"].winfo_ismapped()
        panel.position.set(22)
        panel.render()
        assert panel.traces["LSM-GAN"].samples[0][0] == 22
        capture("neural-lsm-selected.png")
        panel.both.set(True)
        panel.render()
        app.geometry("1024x600+0+0")
        pump()
        for widget in (panel.generate_btn, panel.export_btn, panel.status):
            assert widget.winfo_rootx() + widget.winfo_width() <= app.winfo_rootx() + app.winfo_width()
            assert widget.winfo_rooty() + widget.winfo_height() <= app.winfo_rooty() + app.winfo_height()
        capture("neural-1024.png")
        panel.select_mode("TCN-FiLM")
        panel.reference_menu.set("Gaussian (original)")
        panel.morphology_menu.set("With notch")
        panel.generate_btn.invoke()
        deadline = time.monotonic() + 45
        while panel.busy and time.monotonic() < deadline:
            pump(.05)
        assert not panel.busy
        assert panel.previews["TCN-FiLM"].condition[-1] == 1
        panel.render()
        capture("tcn-vs-gaussian-1024.png")
        panel.reference_menu.set("Gaussian (original)")
        panel.gaussian_profile_menu.set("With notch")
        panel.gaussian_btn.invoke()
        assert panel.selected == "Gaussian (fitted)"
        assert panel.previews[panel.selected].variant == "train_fit_With notch"
        capture("gaussian-fitted-vs-original-1024.png")
        panel.seed_entry.delete(0, "end")
        panel.seed_entry.insert(0, "invalid")
        panel.generate_btn.invoke()
        assert not panel.busy and "Enter seed" in panel.status.cget("text")
        assert config_from_ppg_params(engine.ppg_params) == params
        assert not engine.is_running
        assert engine.dac_manager.last_ir == engine.dac_manager.last_red == 0
        app.set_language("vi")
        assert app.nav_buttons["Pathology"].cget("text") == "01   Cổ điển / Theo dõi"
        app.open_signal_setup()
        pump(.1)
        assert app.language_menu.get() == "Tiếng Việt"
        app._set_language_from_label("English")
        assert app.language_menu.get() == "English"
        app.close_signal_setup()
        assert app.nav_buttons["Pathology"].cget("text") == "01   Classic / Monitor"
        app.select_pathology()
        engine.update_waveform("sine")
        app.frames["Pathology"].gaussian_btn.invoke()
        assert engine.ppg_params.waveform == "ppg"
        engine.start_simulation()
        pump(.1)
        before = config_from_ppg_params(engine.ppg_params)
        app._show_frame("Neural")
        panel.gaussian_btn.invoke()
        pump(.1)
        assert engine.is_running and config_from_ppg_params(engine.ppg_params) == before
        engine.stop_simulation()
        app.select_pathology()
        capture("classic-gaussian-1024.png")
        print("PASS: real G/D inference, responsive worker, both/single switching, native time slider, "
              "invalid input, 1280/1024 layouts, no engine mutation or DAC output")
    finally:
        app.on_closing()
        engine.shutdown()


if __name__ == "__main__":
    main()
