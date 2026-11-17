"""Tk side of BLE protocol v3: the phone drives the Pi pages, and sees what they show.

Runs on the Tk thread from CTkApp.update_gui. Each tick it applies the page requests the BLE thread queued,
appends the new TX and RX samples of the page on screen to the stream, and a few times a second hands the
page state (as small JSON parts) to the BLE server. The page logic itself stays in the frames: a phone request
calls the same methods as the Pi's own buttons and sliders. See comm/ble_remote.py.
"""
from bisect import bisect_left
import time

from comm.ble_server import BLE_CONNECTED
from comm.ble_remote import FRAME_VIEWS, UI_PUBLISH_INTERVAL_S, VIEWS, decimate, pair
from comm.logger import log
from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED, DRY_RUN, FIRMWARE_VERSION, FS_TIMER_HZ, MODEL_SAMPLE_RATE_PPG
from hw.opt101_rx import OPT101Receiver, raw_to_millivolts

PAGE_OF = {"beep": "Pathology", "gauss": "Pathology", "cal": "Calibration", "nn": "Neural", "rec": "Playback"}
RX_PAIR_TOLERANCE_S = 0.03      # a RED sample this close to an IR sample is sent as its pair


def color_kind(color):
    """A theme colour as the phone's state name."""
    from ui import theme as T
    for kind, value in (("ok", T.OK), ("error", T.ERROR), ("warn", T.WARN), ("accent", T.ACCENT),
                        ("warn", T.WARN_INK)):
        if color == value or (isinstance(value, tuple) and color in value):
            return kind
    return "muted"


def lane_fields(lane):
    """A LaneView lane as the phone's header fields (title, detail, two badges, empty-lane message)."""
    return {"t": lane.title, "d": lane.detail, "b": lane.badge, "b2": lane.badge2,
            "m": lane.message, "s": lane.submessage}


class RemoteBridge:
    def __init__(self, app, receiver=None):
        self.app = app
        self.receiver = receiver or OPT101Receiver.get_instance()
        self._tx_last = None
        self._rx_last = None
        self._play_last = None
        self._published_at = 0.0

    @property
    def ble(self):
        ble = getattr(self.app, "ble_server", None)
        return ble if ble is not None and hasattr(ble, "take_ui_requests") else None

    # ── tick ──
    def tick(self):
        ble = self.ble
        if ble is None:
            return
        for request in ble.take_ui_requests():
            self.apply(request)
        if ble.connection_state() != BLE_CONNECTED:     # nobody subscribed: build nothing
            self._tx_last = self._rx_last = None
            return
        try:
            ble.push_stream(self._tx_pairs(), self._rx_pairs())
        except Exception:
            log.exception("[Remote] stream samples failed")
        now = time.monotonic()
        if now - self._published_at >= UI_PUBLISH_INTERVAL_S:
            self._published_at = now
            try:
                ble.publish_ui(self.parts())
            except Exception:
                log.exception("[Remote] page state failed")

    # ── phone -> Pi ──
    def apply(self, request):
        """One queued page request. The page it addresses is shown first: Calibration and the Neural playback
        stop when their page is left, and their state only updates while the page is on screen."""
        app = self.app
        view = request.get("view")
        page = VIEWS.get(view) if view else next((PAGE_OF[k] for k in request if k in PAGE_OF), None)
        if page is not None:
            try:
                app._show_frame(page)
            except Exception:
                log.exception(f"[Remote] could not show {page}")
        for key in ("beep", "gauss", "cal", "nn", "rec"):
            if key not in request:
                continue
            frame = app.frames[PAGE_OF[key]]
            try:
                if key == "beep":
                    if bool(request["beep"]) != bool(frame.beeper.enabled):
                        frame.toggle_beep()
                elif key == "gauss":
                    frame.select_gaussian()
                else:
                    frame.remote_apply(request[key])
            except Exception:
                log.exception(f"[Remote] '{key}' request failed: {request[key]!r}")

    # ── Pi -> phone: stream ──
    def _active(self):
        return getattr(self.app, "active_frame", None)

    def _tx_rows(self):
        """Rows (t, ir_mV, red_mV) the active page's TX plot is drawing now; [] when it draws none."""
        frame, engine = self._active(), self.app.engine
        name = next((key for key, f in self.app.frames.items() if f is frame), None)
        if hasattr(frame, "remote_tx_rows"):        # Recordings and Neural draw more than the DAC history
            return frame.remote_tx_rows()
        live = {"Pathology": bool(engine._running),
                "Calibration": bool(engine.is_calibrating or getattr(frame, "_spo2_run", None) is not None)
                }.get(name, False)
        if not live:
            return []
        return [(t, ir * 1000.0, red * 1000.0) for t, ir, red in engine.get_display_history()]

    def _tx_pairs(self):
        rows = self._tx_rows()
        if not rows:
            self._tx_last = None
            return []
        kept, self._tx_last = decimate(rows, self._tx_last)
        return [pair(ir, red) for _t, ir, red in kept]

    def _rx_pairs(self):
        """IR and RED received samples, paired in time on the IR lane (or RED alone when IR is not read)."""
        rx = self.receiver
        if getattr(rx, "is_simulated", False):
            return []
        lanes = {}
        for channel in (ADC_CHANNEL_IR, ADC_CHANNEL_RED):
            if rx.channel_status(channel) in ("ok", "saturated") and not rx.is_stale(channel):
                lanes[channel] = rx.get_samples_after(channel, (self._rx_last or time.monotonic() - 1.0) - 0.2)
        clock = ADC_CHANNEL_IR if lanes.get(ADC_CHANNEL_IR) else ADC_CHANNEL_RED
        rows = [(s.timestamp, s) for s in lanes.get(clock, ())]
        if not rows:
            self._rx_last = None
            return []
        kept, self._rx_last = decimate(rows, self._rx_last)
        other = lanes.get(ADC_CHANNEL_RED if clock == ADC_CHANNEL_IR else ADC_CHANNEL_IR, ())
        times = [s.timestamp for s in other]
        out = []
        for t, sample in kept:
            match = None
            if times:
                i = bisect_left(times, t)
                near = min((j for j in (i - 1, i) if 0 <= j < len(times)), key=lambda j: abs(times[j] - t))
                if abs(times[near] - t) <= RX_PAIR_TOLERANCE_S:
                    match = raw_to_millivolts(other[near].raw)
            mv = raw_to_millivolts(sample.raw)
            out.append(pair(mv, match) if clock == ADC_CHANNEL_IR else pair(match, mv))
        return out

    # ── Pi -> phone: page state ──
    def parts(self):
        app, frame = self.app, self._active()
        name = next((key for key, f in app.frames.items() if f is frame), "Pathology")
        engine = app.engine
        stats = engine.get_stats()
        if DRY_RUN:
            hw = "dry_run"
        else:
            hw = "hardware" if engine.dac_manager.output_ok else "no_dac"
        parts = [("page", {"v": FRAME_VIEWS.get(name, "monitor"), "lang": app.language, "hw": hw,
                           "st": [stats["buffer_fill"], stats["dropped_samples"], stats["clipped_samples"]],
                           "hz": [MODEL_SAMPLE_RATE_PPG, FS_TIMER_HZ], "ver": FIRMWARE_VERSION})]
        trace = getattr(frame, "trace", None)
        if trace is not None:
            lanes = [[lane.title, lane.detail] for lane in getattr(trace, "lanes", ())]
            parts.append(("tx", {"l": lanes, "p": list(getattr(trace, "placeholder", ("", "")))}))
        rx_panel = getattr(frame, "rx_panel", None)
        for lane, key in zip(getattr(rx_panel, "lanes", ()), ("rxi", "rxr")):
            parts.append((key, lane_fields(lane)))
        if hasattr(frame, "remote_parts"):
            try:
                parts.extend(frame.remote_parts())
            except Exception:
                log.exception(f"[Remote] {name} state failed")
        return parts
