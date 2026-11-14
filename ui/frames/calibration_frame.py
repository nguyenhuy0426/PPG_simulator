"""Calibration: per-channel test level (± sine) on the DACs and a pass dot per RX lane.

The IR and RED levels are DAC output millivolts. The dot next to each RX lane
blinks green while the OPT101 lane reads the same millivolts within ± tolerance
(Δ = received − sent), so the optics/levels can be adjusted until TX and RX agree.
"""
import time

import customtkinter as ctk

from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED, DAC_FULLSCALE_MV, OPT101_SATURATION_MV
from core import rx_spo2_cal
from core.calib_match import SETTLE_S, WINDOW_S, level_match
from core.signal_engine import SignalEngine
from hw.opt101_rx import OPT101Receiver, raw_to_millivolts
from ui import page_kit as K
from ui import theme as T
from ui.rx_monitor import RXPanel
from ui.touch_slider import TouchSlider
from ui.trace_view import TraceView

# Slider ranges. A level is compared 1:1 with the OPT101 reading, so it stops where the
# OPT101 output saturates; the amplitude can then swing the full 0..LEVEL_MAX_MV span.
LEVEL_MAX_MV = OPT101_SATURATION_MV          # 2400 mV
SWING_MAX_MV = LEVEL_MAX_MV / 2              # 1200 → 1200 ± 1200 = 0..2400 mV
FREQ_RANGE_HZ = (1.0, 5.0, 0.5)              # ≥ 20 RX samples/cycle at ~100 Hz; 1 Hz = two cycles in WINDOW_S
TOLERANCE_RANGE_MV = (1, 100, 1)
DARK_MV = 30                  # a lane below this while its LED is commanded ≥ LIT_MIN_MV is not lit
LIT_MIN_MV = 200
RX_OFFLINE_MV = 2             # a powered OPT101 never reads below its dark output (4-12 mV on both lanes,
                              # docs/hardware-validation/2026-11-14-ir-overload §12); 0 mV = receiver offline
MATCH_REFRESH_S = 0.25
BLINK_S = 0.5
SAVE_DELAY_MS = 800          # tolerance is written once the slider has rested

COPY = {
    "vi": dict(title="Hiệu chuẩn & thu tín hiệu",
               subtitle="Đặt mức IR/RED rồi Bắt đầu; chấm xanh nhấp nháy khi mức thu = mức phát ± dung sai. Rời trang sẽ dừng.",
               controls="Tín hiệu thử (mV phát)", frequency="Tần số Hz", ir="IR mức mV", red="RED mức mV",
               swing="Biên độ sine ± mV", tolerance="Dung sai ± mV",
               start="Bắt đầu", stop="Dừng", tx="Tín hiệu phát TX (mV DAC)", rx="Tín hiệu thu RX (mV OPT101)",
               idle="Chưa phát", running="Đang phát", no_output="Chưa ra LED: DAC không phản hồi trên I2C",
               waiting="chờ", dark="{name} LED chưa sáng ({v:.0f} mV): DAC đã ghi, kiểm tra driver/LED",
               offline="{name} RX 0 mV, thấp hơn mức tối ~6 mV: OPT101 {name} mất nguồn/GND hoặc dây ADC, không phải LED",
               steady="{name} {v:.0f} mV  Δ{e:+.0f}", wave="{name} {hi:.0f}/{lo:.0f} mV  Δ{e:+.0f}",
               note="So khớp mức điện áp, không phải hiệu chuẩn SpO₂ lâm sàng.",
               delta="Δ = mức thu − mức phát (mV)",
               tx_range="Phát: IR {ir} · RED {red} mV",
               spo2_cal="Hiệu chuẩn SpO₂",
               spo2_progress="Hiệu chuẩn SpO₂ thu: điểm {i}/{n} (SpO₂ {s:.0f} %), còn {left:.0f} s. Không chạm carrier.",
               spo2_done="Đã lưu: SpO₂ thu = {a:.1f} − {b:.1f}·R, lệch tối đa {res:.1f} % ở DC IR {ir:.0f} / RED {red:.0f} mV."
                         " Đổi DC hay chỉnh carrier thì chạy lại.",
               spo2_unsaved=" Không ghi được config.json: chỉ dùng đến khi tắt app.",
               spo2_failed="Hiệu chuẩn SpO₂ không thành: {why}",
               spo2_why=dict(aborted="đã dừng", residual="R thu không theo đường thẳng (lệch {x} % > 2 %): làn thu chưa ổn định",
                             flat="R thu không đổi giữa các mức SpO₂")),
    "en": dict(title="Calibration & acquisition",
               subtitle="Set IR/RED levels and Start; the dot blinks green while received = sent ± tolerance. Leaving stops it.",
               controls="Test signal (sent mV)", frequency="Frequency Hz", ir="IR level mV", red="RED level mV",
               swing="Sine amplitude ± mV", tolerance="Tolerance ± mV",
               start="Start", stop="Stop", tx="TX output (DAC mV)", rx="RX received (OPT101 mV)",
               idle="Output stopped", running="Running", no_output="Not reaching the LEDs: the DACs do not answer on I2C",
               waiting="wait", dark="{name} LED not lit ({v:.0f} mV): DAC written, check the driver/LED",
               offline="{name} RX 0 mV, below the ~6 mV dark level: OPT101 {name} lost supply/GND or its ADC wire, not the LED",
               steady="{name} {v:.0f} mV  Δ{e:+.0f}", wave="{name} {hi:.0f}/{lo:.0f} mV  Δ{e:+.0f}",
               note="Matches voltage levels; not a clinical SpO₂ calibration.",
               delta="Δ = received − sent (mV)",
               tx_range="Sent: IR {ir} · RED {red} mV",
               spo2_cal="SpO₂ calibration",
               spo2_progress="Receive SpO₂ calibration: point {i}/{n} (SpO₂ {s:.0f} %), {left:.0f} s left. Do not touch the carriers.",
               spo2_done="Saved: received SpO₂ = {a:.1f} − {b:.1f}·R, worst error {res:.1f} % at DC IR {ir:.0f} / RED {red:.0f} mV."
                         " Run again after changing DC or moving a carrier.",
               spo2_unsaved=" config.json could not be written: used until the app closes.",
               spo2_failed="SpO₂ calibration failed: {why}",
               spo2_why=dict(aborted="stopped", residual="received R is not on a straight line ({x} % > 2 %): the lanes are not stable",
                             flat="received R did not change between the SpO₂ points")),
}
LANES = (("IR", ADC_CHANNEL_IR), ("RED", ADC_CHANNEL_RED))


class CalibrationFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.engine = SignalEngine.get_instance()
        self.receiver = OPT101Receiver.get_instance()
        self.language = getattr(master, "language", "en")
        u = T.ui
        self._running_shown = None
        self._output_ok_shown = None
        self._started_at = 0.0
        self._target = None           # (ir_level, red_level, swing) of the running output
        self._matches = {}
        self._match_at = 0.0
        self._save_job = None
        self._spo2_run = None         # core.rx_spo2_cal.CalibrationRun while the SpO2 sweep plays

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.title_label, self.subtitle, actions = K.page_header(self)
        self.run_btn = K.primary_button(actions, command=self.toggle, width=118)
        self.run_btn.pack(side="right")
        self.spo2_btn = K.secondary_button(actions, command=self.start_spo2_calibration, width=150)
        self.spo2_btn.pack(side="right", padx=(0, u(8)))

        # One compact row: label above an inline − value [slider] + control.
        controls, self.controls_title, controls_tools = K.section(self, span=5)
        self.delta_legend = T.label(controls_tools, "", u(12), True, text_color=T.INK)
        self.delta_legend.pack(side="right")
        controls.grid(row=1, column=0, sticky="ew", pady=(0, u(6)))
        controls.grid_columnconfigure(tuple(range(5)), weight=1, uniform="controls")
        self.slider_labels = {}
        tolerance = float(self._load_config().get("calib_tolerance_mv", 20.0))
        for column, (key, control) in enumerate((
                ("frequency", TouchSlider(controls, *FREQ_RANGE_HZ, value=1, inline=True)),
                ("ir", TouchSlider(controls, 0, LEVEL_MAX_MV, 10, value=1000, inline=True)),
                ("red", TouchSlider(controls, 0, LEVEL_MAX_MV, 10, value=1000, inline=True)),
                ("swing", TouchSlider(controls, 0, SWING_MAX_MV, 10, value=0, inline=True)),
                ("tolerance", TouchSlider(controls, *TOLERANCE_RANGE_MV, value=tolerance, inline=True,
                                          command=self._tolerance_changed)))):
            label = T.label(controls, "", u(11), text_color=T.MUTED, anchor="w", height=u(16))
            label.grid(row=1, column=column, sticky="ew", padx=u(8))
            control.grid(row=2, column=column, sticky="ew", padx=u(6), pady=(0, u(8)))
            self.slider_labels[key] = label
            setattr(self, f"{key}_slider", control)

        panels = ctk.CTkFrame(self, fg_color="transparent")
        panels.grid(row=2, column=0, sticky="nsew")
        panels.grid_columnconfigure(0, weight=1, uniform="signals")
        panels.grid_columnconfigure(1, weight=2, uniform="signals")
        panels.grid_rowconfigure(0, weight=1)
        tx, self.tx_title, _ = K.section(panels)
        tx.grid(row=0, column=0, sticky="nsew", padx=(0, u(4)))
        self.trace = TraceView(K.plot_holder(tx), height=240)
        self.trace.pack(fill="both", expand=True, padx=u(3), pady=u(3))
        self.tx_range = T.label(tx, "", u(11), text_color=T.MUTED, anchor="w")   # under the plot: the head is too narrow
        self.tx_range.grid(row=2, column=0, sticky="ew", padx=u(10), pady=(0, u(6)))
        rx, self.rx_title, rx_tools = K.section(panels)
        rx.grid(row=0, column=1, sticky="nsew", padx=(u(4), 0))
        self.dots, self.dot_text = {}, {}
        for name, _channel in reversed(LANES):
            text = T.label(rx_tools, "", u(12), True, text_color=T.MUTED)
            text.pack(side="right", padx=(0, u(10)))
            dot = T.label(rx_tools, "●", u(18), text_color=T.FAINT)
            dot.pack(side="right", padx=(u(4), u(2)))
            self.dots[name], self.dot_text[name] = dot, text
        self.rx_panel = RXPanel(K.plot_holder(rx), language=self.language, height=240, vitals=False)
        self.rx_panel.pack(fill="both", expand=True, padx=u(3), pady=u(3))

        self.status = T.label(self, "", u(12), text_color=T.MUTED, anchor="w")
        self.status.grid(row=3, column=0, sticky="ew", pady=(u(4), 0))
        self.set_language(self.language)

    # ---- config ----
    @staticmethod
    def _load_config():
        try:
            from config_store import load_config
            return load_config()
        except Exception:
            return {}

    def _tolerance_changed(self, _value):
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(SAVE_DELAY_MS, self._save_tolerance)

    def _save_tolerance(self):
        from comm.logger import log
        from config_store import load_config, save_config
        self._save_job = None
        config = load_config()
        config["calib_tolerance_mv"] = float(self.tolerance_slider.get())
        if not save_config(config):
            log.error("[Calibration] could not save the tolerance")

    # ---- texts ----
    def set_language(self, language):
        self.language = language if language in COPY else "en"
        t = COPY[self.language]
        self.title_label.configure(text=t["title"])
        self.subtitle.configure(text=t["subtitle"])
        self.controls_title.configure(text=t["controls"])
        self.tx_title.configure(text=t["tx"])
        self.rx_title.configure(text=t["rx"])
        self.delta_legend.configure(text=t["delta"])
        self.spo2_btn.configure(text=t["spo2_cal"])
        for key, label in self.slider_labels.items():
            label.configure(text=t[key])
        self.trace.empty_text = t["idle"]
        self.rx_panel.set_language(self.language)
        self._running_shown = None
        self.status.configure(text=t["note"], text_color=T.MUTED)

    # ---- actions ----
    def toggle(self):
        t = COPY[self.language]
        if self._spo2_run is not None:
            self._spo2_run.abort()
            self._spo2_finished()
        elif self.engine.is_calibrating:
            self.engine.stop_simulation()
            self.status.configure(text=t["note"], text_color=T.MUTED)
        else:
            try:
                if self.master.frames["Pathology"].is_recording:
                    self.master.frames["Pathology"].toggle_recording()
                frequency = float(self.frequency_slider.get())
                ir_level, red_level = float(self.ir_slider.get()), float(self.red_slider.get())
                swing = float(self.swing_slider.get())
                self.engine.start_calibration(frequency, ir_level, red_level, swing)
                self._target = (ir_level, red_level, swing)
                self._started_at = time.monotonic()
                self._matches = {}
                self.status.configure(text=t["running"], text_color=T.ACCENT)
            except (ValueError, RuntimeError) as exc:
                self.status.configure(text=str(exc), text_color=T.ERROR)
        self.periodic_update()

    def on_show(self):
        self.periodic_update()

    def on_hide(self):
        if self._spo2_run is not None:
            self._spo2_run.abort()
            self._spo2_finished()
        if self.engine.is_calibrating:
            self.engine.stop_simulation()

    # ---- receive-path SpO2 calibration ----
    def start_spo2_calibration(self):
        if self._spo2_run is not None:
            return
        try:
            if self.master.frames["Pathology"].is_recording:
                self.master.frames["Pathology"].toggle_recording()
        except (AttributeError, KeyError):
            pass
        if self.engine.is_calibrating:
            self.engine.stop_simulation()
        self._target, self._matches = None, {}
        self._spo2_run = rx_spo2_cal.CalibrationRun(self.engine, self.receiver)
        self._spo2_run.start(time.monotonic())
        self.spo2_btn.configure(state="disabled")
        self.periodic_update()

    def _spo2_progress(self, now):
        run = self._spo2_run
        run.tick(now)
        if run.done:
            self._spo2_finished()
            return
        t = COPY[self.language]
        text = t["spo2_progress"].format(i=run.index + 1, n=len(run.points), s=run.points[run.index],
                                         left=run.remaining_s(now))
        if self.status.cget("text") != text:
            self.status.configure(text=text, text_color=T.ACCENT)

    def _spo2_finished(self):
        run, self._spo2_run = self._spo2_run, None
        self.spo2_btn.configure(state="normal")
        t = COPY[self.language]
        if run.calibration is not None:
            cal = run.calibration
            text = t["spo2_done"].format(a=cal.a, b=cal.b, res=cal.max_residual, ir=cal.dc_ir_mv, red=cal.dc_red_mv)
            if not rx_spo2_cal.save(cal):
                text += t["spo2_unsaved"]
            self.status.configure(text=text, text_color=T.OK)
            return
        why, reasons = run.error or "", t["spo2_why"]
        if why.startswith("reason:"):
            from ui.rx_monitor import _SPO2
            code = why.split(":", 1)[1]
            why = _SPO2[self.language][1].get(code, code)
        elif why.startswith("residual:"):
            why = reasons["residual"].format(x=why.split(":", 1)[1])
        elif why in reasons:
            why = reasons[why]
        elif "R did not change" in why or "does not fall" in why:
            why = reasons["flat"]
        self.status.configure(text=t["spo2_failed"].format(why=why), text_color=T.ERROR)

    # ---- match dots ----
    def _update_matches(self, now):
        if now - self._match_at < MATCH_REFRESH_S:
            return
        self._match_at = now
        ir_level, red_level, swing = self._target
        tolerance = float(self.tolerance_slider.get())
        for name, channel in LANES:
            if now - self._started_at < SETTLE_S:
                self._matches[name] = None
                continue
            level = ir_level if name == "IR" else red_level
            samples = self.receiver.get_samples_since(channel, now - WINDOW_S)
            self._matches[name] = level_match([raw_to_millivolts(s.raw) for s in samples], level, swing, tolerance)

    def _paint_dots(self, running, now):
        t = COPY[self.language]
        blink_on = int(now / BLINK_S) % 2 == 0
        for name, _channel in LANES:
            match = self._matches.get(name) if running else None
            if match is None:
                color, text = T.FAINT, f"{name} {t['waiting']}" if running else name
            else:
                color = (T.OK if blink_on else T.PANEL) if match.ok else T.ERROR
                level = self._target[0 if name == "IR" else 1]
                if max(match.measured) < RX_OFFLINE_MV:
                    text = t["offline"].format(name=name)
                elif level - self._target[2] >= LIT_MIN_MV and max(match.measured) < DARK_MV:
                    text = t["dark"].format(name=name, v=max(match.measured))
                elif len(match.measured) == 1:
                    text = t["steady"].format(name=name, v=match.measured[0], e=match.error_mv)
                else:
                    text = t["wave"].format(name=name, hi=match.measured[0], lo=match.measured[1], e=match.error_mv)
            if self.dots[name].cget("text_color") != color:
                self.dots[name].configure(text_color=color)
            if self.dot_text[name].cget("text") != text:
                self.dot_text[name].configure(text=text, text_color=T.OK if match and match.ok else T.MUTED)

    def _paint_tx_range(self, running):
        """Show what the DACs really output: level ± amplitude, clipped to 0..full scale."""
        text = ""
        if running and self._target is not None:
            ir_level, red_level, swing = self._target
            def span(level):
                lo, hi = max(0.0, level - swing), min(DAC_FULLSCALE_MV, level + swing)
                return f"{lo:.0f}" if lo == hi else f"{lo:.0f}–{hi:.0f}"
            text = COPY[self.language]["tx_range"].format(ir=span(ir_level), red=span(red_level))
        if self.tx_range.cget("text") != text:
            self.tx_range.configure(text=text)

    def periodic_update(self):
        if not self.winfo_ismapped():
            return
        now = time.monotonic()
        if self._spo2_run is not None:
            self._spo2_progress(now)
        sweeping = self._spo2_run is not None
        running = self.engine.is_calibrating or sweeping
        if running != self._running_shown:
            self._running_shown = running
            t = COPY[self.language]
            K.set_running(self.run_btn, running, t["start"], t["stop"])
        output_ok = self.engine.dac_manager.output_ok
        if running and output_ok != self._output_ok_shown and not output_ok:
            self.status.configure(text=COPY[self.language]["no_output"], text_color=T.ERROR)
        self._output_ok_shown = output_ok if running else None
        if self.engine.is_calibrating and self._target is not None:
            self._update_matches(now)
        self._paint_dots(self.engine.is_calibrating, now)
        self._paint_tx_range(self.engine.is_calibrating)
        self.trace.update_samples(self.engine.get_display_history() if running else [])
        self.rx_panel.periodic_update()
