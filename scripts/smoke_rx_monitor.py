"""Run with DISPLAY pointing to Xvfb. Fixtures are NOT physical measurements."""
import os
import sys
import time
from pathlib import Path

os.environ["PPG_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import ImageGrab
from hw.opt101_rx import OPT101Receiver, RXSample, raw_to_millivolts
from ui.ctk_app import CTkApp
from ui.rx_monitor import RXPanel


def main():
    output = Path("docs/ui/rx-monitor")
    output.mkdir(parents=True, exist_ok=True)
    CTkApp._maximize_to_work_area = lambda self: None
    app = CTkApp(language="vi")
    app._save_language = lambda: None
    errors = []
    app.report_callback_exception = lambda *args: errors.append(args)

    def pump(duration=.2):
        until = time.monotonic() + duration
        while time.monotonic() < until:
            app.update()
            time.sleep(.01)
        assert not errors, errors

    try:
        pump(.6)
        app.geometry("958x531+0+0")
        for page in app.frames:
            # Neural is dense; small physical screens get the compact layout,
            # which scrolls it, so check it at a size that layout serves here.
            app.geometry("1280x800+0+0" if page == "Neural" else "958x531+0+0")
            app._show_frame(page)
            pump()
            # Every page shows its own RX card next to TX; there is no shared dock.
            panel = app.frames[page].rx_panel
            assert panel.winfo_ismapped(), page
            assert panel.winfo_rooty() + panel.winfo_height() <= app.winfo_rooty() + app.winfo_height()
            assert all(not lane.points for lane in panel.lanes)
            assert panel.lanes[1].message == "Chưa gắn cảm biến"
            ImageGrab.grab(xdisplay=os.environ["DISPLAY"], bbox=(0, 0, 958, 531)).save(output / f"{page.lower()}.png")
        app.geometry("958x531+0+0")
        app.open_signal_setup()
        pump()

        def has_rx(widget):
            return isinstance(widget, RXPanel) or any(has_rx(child) for child in widget.winfo_children())
        assert not has_rx(app.signal_setup_window), "Signal setup must not carry an RX view"
        app.set_language("en")
        pump()
        app.close_signal_setup()

        # Deterministic channel fixtures test mapping, independent timestamps,
        # stale status and missing-data gaps without ADC/DAC access.
        rx = OPT101Receiver(dry_run=False, enabled_channels=(0, 2))
        now = time.monotonic()
        for channel, raw in ((0, 100), (2, 2000)):
            state = rx._channels[channel]
            state.status = "ok"
            state.buffer.extend(RXSample(now + dt, raw, False) for dt in (-.4, -.39, -.1, -.09))
        view = app.frames["Playback"].rx_panel
        view.receiver = rx
        view._last_update = 0.0
        app._show_frame("Playback")
        pump()
        for lane, raw in zip(view.lanes, (100, 2000)):
            assert len(lane.points) == 4
            assert abs(lane.points[-1][1] - raw_to_millivolts(raw)) < 1e-9
            # The 0.29 s hole between the two pairs breaks the line in two.
            wave_lines = [item for item in view.find_all() if view.type(item) == "line"
                          and view.itemcget(item, "fill") == lane.color]
            assert len(wave_lines) == 2, wave_lines
        for state in rx._channels.values():
            state.buffer.clear()
            state.buffer.append(RXSample(time.monotonic() - 20, 999, False))
        view._last_update = 0.0
        pump()
        assert all(not lane.points for lane in view.lanes)
        assert view.lanes[0].message == "No fresh samples"
        # The Classic RX card applies the same rules to the same receiver.
        classic = app.frames["Pathology"].rx_panel
        classic.receiver = rx
        app._show_frame("Pathology")
        pump()
        assert all(not lane.points for lane in classic.lanes)
        assert classic.lanes[0].message == "No fresh samples"
        now = time.monotonic()
        for channel, raw in ((0, 100), (2, 2000)):
            rx._channels[channel].buffer.extend(RXSample(now + dt, raw, False) for dt in (-.4, -.39, -.1, -.09))
        classic._last_update = 0.0
        pump()
        for lane, raw in zip(classic.lanes, (100, 2000)):
            assert len(lane.points) == 4
            assert abs(lane.points[-1][1] - raw_to_millivolts(raw)) < 1e-9
        assert "Live" in classic.lanes[0].detail
        assert not rx.is_running
        assert not app.engine._running
        print("PASS: RX beside TX on four pages, none in settings, languages, channel mapping, missing data, stale data, read-only UI")
    finally:
        app.on_closing()


if __name__ == "__main__":
    main()
