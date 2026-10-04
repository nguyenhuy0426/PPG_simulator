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
            app._show_frame(page)
            pump()
            if page in app.OWN_RX_PAGES:
                # Classic and Calibration show RX next to TX instead of the dock.
                assert not app.rx_monitor.winfo_ismapped()
                panel = app.frames[page].rx_panel
                assert panel.winfo_ismapped()
                assert all(not lane.points for lane in panel.lanes)
                assert panel.lanes[1].message == "Chưa gắn cảm biến"
            else:
                panel = app.rx_monitor
                assert panel.winfo_ismapped()
                assert panel.winfo_y() + panel.winfo_height() <= app.winfo_height()
                assert all(not p.lanes[0].points for p in panel.panels.values())
                assert panel.panels[2].lanes[0].message == "Chưa gắn cảm biến"
            ImageGrab.grab(xdisplay=os.environ["DISPLAY"], bbox=(0, 0, 958, 531)).save(output / f"{page.lower()}.png")
        app.open_signal_setup()
        pump()
        assert app.settings_rx_monitor.winfo_ismapped()
        app.set_language("en")
        pump()
        assert app.settings_rx_monitor.panels[2].lanes[0].message == "No sensor installed"
        app.close_signal_setup()

        # Deterministic channel fixtures test mapping, independent timestamps,
        # stale status and missing-data gaps without ADC/DAC access.
        rx = OPT101Receiver(dry_run=False, enabled_channels=(0, 2))
        now = time.monotonic()
        for channel, raw in ((0, 100), (2, 2000)):
            state = rx._channels[channel]
            state.status = "ok"
            state.buffer.extend(RXSample(now + dt, raw, False) for dt in (-.4, -.39, -.1, -.09))
        app.rx_monitor.receiver = rx
        app._show_frame("Playback")
        pump()
        for channel, raw in ((0, 100), (2, 2000)):
            view = app.rx_monitor.panels[channel]
            lane = view.lanes[0]
            assert len(lane.points) == 4
            assert abs(lane.points[-1][1] - raw_to_millivolts(raw)) < 1e-9
            # The 0.29 s hole between the two pairs breaks the line in two.
            wave_lines = [item for item in view.find_all() if view.type(item) == "line"
                          and view.itemcget(item, "fill") == lane.color]
            assert len(wave_lines) == 2, wave_lines
        for state in rx._channels.values():
            state.buffer.clear()
            state.buffer.append(RXSample(time.monotonic() - 20, 999, False))
        pump()
        assert all(not p.lanes[0].points for p in app.rx_monitor.panels.values())
        assert app.rx_monitor.panels[0].lanes[0].message == "No fresh samples"
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
        print("PASS: four pages, settings, languages, channel mapping, missing data, stale data, read-only UI")
    finally:
        app.on_closing()


if __name__ == "__main__":
    main()
