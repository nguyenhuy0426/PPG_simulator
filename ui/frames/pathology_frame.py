import time

import customtkinter as ctk

from calibration import r_target_from_spo2
from config import DAC_ADDR_IR, DAC_ADDR_RED, DRY_RUN, FS_TIMER_HZ
from core.signal_engine import SignalEngine
from models import limits
from ui import icons
from ui import theme as T
from ui.i18n import condition_labels, text
from ui.rx_monitor import RXPanel
from ui.select_button import SelectButton
from ui.setpoint_card import SetpointCard
from ui.trace_view import Lane, LaneView

# Redraw budget for the TX plot. The DAC writer shares the GIL with Tk, so the
# plot refreshes at ~12 Hz instead of on every 40 ms UI tick.
TX_REFRESH_S = 0.08
MESSAGE_HOLD_S = 4.0


class PathologyFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.app, self.engine = master, SignalEngine.get_instance()
        self.layout = master.layout
        self.language = getattr(master, "language", "en")
        compact = self.layout.compact
        u = self.layout.ui
        gap = 8
        self._run_shown, self._rec_shown, self._status_shown = None, None, None
        self._message, self._message_until = None, 0.0
        self._last_tx_render = 0.0
        self._dac_error_base = (0, 0)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Status line and page actions ──
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, u(gap)))
        bar.grid_columnconfigure(2, weight=1)
        self.status_dot = ctk.CTkFrame(bar, width=u(8), height=u(8), corner_radius=u(4), fg_color=T.FAINT)
        self.status_dot.grid(row=0, column=0, padx=(u(4), u(8)))
        self.status_title = T.label(bar, "", u(13), True, anchor="w")
        self.status_title.grid(row=0, column=1, sticky="w")
        self.status_detail = T.label(bar, "", u(13), text_color=T.MUTED, anchor="w")
        self.status_detail.grid(row=0, column=2, sticky="ew", padx=(u(5), u(8)))
        button_h = u(36)
        self._icons = {
            "record": icons.icon("record", T.ERROR, u(14)), "save": icons.icon("save", T.ERROR, u(16)),
            "stop": icons.icon("stop", T.PANEL, u(14)), "play": icons.icon("play", T.PANEL, u(14)),
        }
        self.record_btn = T.outline_button(bar, "", height=button_h, width=u(116), compound="left",
                                           font=T.font(u(13), True), command=self.toggle_recording)
        self.record_btn.grid(row=0, column=3, padx=(0, u(8)))
        self.run_btn = ctk.CTkButton(bar, text="", height=button_h, width=u(128), compound="left",
                                     font=T.font(u(13), True), command=self.toggle_simulation)
        self.run_btn.grid(row=0, column=4)

        # ── TX and RX signal cards ──
        panels = ctk.CTkFrame(self, fg_color="transparent")
        panels.grid(row=1, column=0, sticky="nsew")
        panels.grid_columnconfigure((0, 1), weight=1, uniform="signals")
        panels.grid_rowconfigure(0, weight=1)
        plot_h = 200 if compact else self.layout.trace_height + 60
        header_h = u(34)

        tx = T.card(panels)
        tx.grid(row=0, column=0, sticky="nsew", padx=(0, u(gap) // 2))
        tx.grid_columnconfigure(0, weight=1)
        tx.grid_rowconfigure(1, weight=1)
        self.tx_title = T.label(tx, "", u(14), True, anchor="w", height=header_h)
        self.tx_title.grid(row=0, column=0, sticky="w", padx=u(10), pady=u(6))
        self.condition_menu = SelectButton(
            tx, condition_labels(self.language), command=self._condition_chosen, width=u(140),
            height=header_h, font=T.font(u(13)), dropdown_font=T.font(u(14)), icon_size=u(14), pad=u(10))
        self.condition_menu.grid(row=0, column=1, padx=(0, u(6)), pady=u(6))
        self.gaussian_btn = T.outline_button(tx, "3-Gaussian", height=header_h, width=u(100),
                                             font=T.font(u(13), True), command=self.select_gaussian)
        self.gaussian_btn.grid(row=0, column=2, padx=(0, u(8)), pady=u(6))
        holder = ctk.CTkFrame(tx, fg_color=T.DARK, corner_radius=u(6))
        holder.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=u(6), pady=(0, u(6)))
        self.trace = LaneView(holder, height=plot_h)
        self.trace.pack(fill="both", expand=True, padx=u(3), pady=u(3))
        self.canvas = self.trace

        rx = T.card(panels)
        rx.grid(row=0, column=1, sticky="nsew", padx=(u(gap) // 2, 0))
        rx.grid_columnconfigure(0, weight=1)
        rx.grid_rowconfigure(1, weight=1)
        self.rx_title = T.label(rx, "", u(14), True, anchor="w", height=header_h)
        self.rx_title.grid(row=0, column=0, sticky="w", padx=u(10), pady=u(6))
        rx_holder = ctk.CTkFrame(rx, fg_color=T.DARK, corner_radius=u(6))
        rx_holder.grid(row=1, column=0, sticky="nsew", padx=u(6), pady=(0, u(6)))
        self.rx_panel = RXPanel(rx_holder, language=self.language, height=plot_h)
        self.rx_panel.pack(fill="both", expand=True, padx=u(3), pady=u(3))

        # ── Setpoints ──
        self.fields = {
            "hr": ("heart_rate", limits.HEART_RATE, "bpm", 1, 0),
            "spo2": ("spo2", limits.SPO2, "%", 1, 0),
            "rr": ("resp_rate", limits.RESP_RATE, "brpm", 1, 0),
            "pi": ("perfusion_index", limits.PERFUSION_INDEX, "%", 0.01, 2),
        }
        setpoints = ctk.CTkFrame(self, fg_color="transparent")
        setpoints.grid(row=2, column=0, sticky="ew", pady=(u(gap), 0))
        setpoints.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="setpoints")
        self.cards, self.vital_labels, self.sliders = {}, {}, {}
        for column, (key, (attr, span, unit, step, decimals)) in enumerate(self.fields.items()):
            card = SetpointCard(setpoints, text(self.language, key), span, unit, step, decimals,
                                command=lambda value, k=key: self.update_param(k, value), ui=u)
            card.grid(row=0, column=column, sticky="nsew",
                      padx=(0 if column == 0 else u(gap) // 2, 0 if column == 3 else u(gap) // 2))
            self.cards[key] = card
            self.vital_labels[key] = card.value_label
            self.sliders[key] = card.slider
        self.set_language(self.language)

    # ── Language ──
    def set_language(self, language):
        self.language = language
        self.tx_title.configure(text=text(language, "tx_card"))
        self.rx_title.configure(text=text(language, "rx_card"))
        self.condition_menu.set_values(condition_labels(language))
        self.condition_menu.set(condition_labels(language)[self.engine.ppg_params.condition])
        for key, card in self.cards.items():
            card.set_title(text(language, key))
        self.rx_panel.set_language(language)
        self.trace.placeholder = (text(language, "tx_idle"), text(language, "tx_idle_sub"))
        self._run_shown = self._rec_shown = self._status_shown = None
        self._last_tx_render = 0.0
        if self.winfo_ismapped():
            self.periodic_update()

    def _say(self, key, color=None, raw=None):
        """Show feedback in the status line for a few seconds."""
        self._message = (raw if raw is not None else text(self.language, key), color or T.ACCENT)
        self._message_until = time.monotonic() + MESSAGE_HOLD_S
        self._status_shown = None

    # ── Actions ──
    def select_gaussian(self):
        self.engine.update_waveform("ppg")
        self._say("gaussian_selected")

    def on_show(self):
        p = self.engine.ppg_params
        for key, (attr, *_rest) in self.fields.items():
            self.cards[key].set(getattr(p, attr))
        self.condition_menu.set(condition_labels(self.language)[p.condition])
        self._last_tx_render = 0.0
        self.periodic_update()

    def update_param(self, key, value):
        attr, span = self.fields[key][:2]
        value = span.quantise(value)
        callbacks = {"hr": self.engine.update_heart_rate, "spo2": self.engine.update_spo2,
                     "rr": self.engine.update_resp_rate, "pi": self.engine.update_perfusion_index}
        try:
            callbacks[key](value)
            self.cards[key].set(getattr(self.engine.ppg_params, attr))
            self._say("applied")
        except ValueError as exc:
            self.cards[key].set(getattr(self.engine.ppg_params, attr))
            self._say(None, T.ERROR, raw=str(exc))

    def _condition_chosen(self, label):
        labels = condition_labels(self.language)
        if label in labels:
            self.set_condition(labels.index(label))

    def set_condition(self, idx):
        self.engine.change_condition(idx)

    @property
    def is_recording(self):
        """Recording state lives on the engine (shared with BLE + status)."""
        return bool(getattr(self.engine, "recording", False))

    def toggle_simulation(self):
        if self.engine._running:
            self.engine.stop_simulation()
            if self.is_recording:
                self.toggle_recording()
        else:
            try:
                self.engine.start_simulation(self.engine.ppg_params.condition)
            except ValueError as exc:
                self._say(None, T.ERROR, raw=str(exc))
        self._last_tx_render = 0.0
        self.periodic_update()

    def toggle_recording(self):
        if self.is_recording:
            self.engine.stop_recording()
            self._say("csv_saved")
        elif self.engine._running:
            if not self.engine.start_recording():
                self._say("record_failed", T.ERROR)
        else:
            self._say("record_needs_run", T.MUTED)
        self.periodic_update()

    def record_tick(self):
        if self.is_recording:
            self.engine.pump_recording()

    # ── Painting ──
    def sync_control_buttons(self):
        """Mirror engine run/record state onto the action buttons.

        Cheap (configure only on change) and frame-visibility independent, so
        a phone-side toggle is visible live even while another tab is shown.
        """
        run = bool(self.engine._running)
        if run != self._run_shown:
            self._run_shown = run
            self.run_btn.configure(text=text(self.language, "stop" if run else "start"),
                                   image=self._icons["stop" if run else "play"],
                                   fg_color=T.ERROR if run else T.ACCENT,
                                   hover_color=T.ERROR_HOVER if run else T.HOVER)
        recording = self.is_recording
        if recording != self._rec_shown:
            self._rec_shown = recording
            self.record_btn.configure(text=text(self.language, "save_record" if recording else "record"),
                                      image=self._icons["save" if recording else "record"],
                                      border_color=T.ERROR if recording else T.LINE,
                                      text_color=T.ERROR if recording else T.INK)

    def _status(self):
        """(dot colour, headline, detail) describing what the output really does."""
        lang, engine = self.language, self.engine
        dac = engine.dac_manager
        addresses = dict(ir=DAC_ADDR_IR, red=DAC_ADDR_RED)
        errors = (dac.error_count_ir, dac.error_count_red)
        if not engine._running:
            # Count write errors per run: one transient error at start-up must
            # not keep the status red for the rest of the session.
            self._dac_error_base = errors
            if not DRY_RUN and not dac.is_ready:
                return T.ERROR, text(lang, "status_stopped"), text(lang, "status_stopped_no_dac").format(**addresses)
            return T.FAINT, text(lang, "status_stopped"), text(lang, "status_stopped_detail")
        if engine.is_calibrating:
            headline = text(lang, "status_calibrating")
        elif getattr(engine, "is_waveform_playing", False):
            headline = text(lang, "status_clip")
        else:
            headline = None
        if DRY_RUN:
            return T.WARN, headline or text(lang, "status_dry"), text(lang, "status_dry_detail")
        if not dac.is_ready:
            return T.ERROR, headline or text(lang, "status_no_dac"), text(lang, "status_no_dac_detail").format(**addresses)
        ir_err, red_err = (now - base for now, base in zip(errors, self._dac_error_base))
        if ir_err or red_err:
            return (T.ERROR, text(lang, "status_dac_errors"),
                    text(lang, "status_dac_errors_detail").format(ir_err=ir_err, red_err=red_err))
        return (T.OK, headline or text(lang, "status_emitting"),
                text(lang, "status_emitting_detail").format(rate=FS_TIMER_HZ, **addresses))

    def _paint_status(self):
        dot, headline, detail = self._status()
        if self._message is not None and time.monotonic() < self._message_until:
            detail, detail_color = self._message
        else:
            self._message, detail_color = None, T.MUTED
        shown = (dot, headline, detail, detail_color)
        if shown != self._status_shown:
            self._status_shown = shown
            self.status_dot.configure(fg_color=dot)
            self.status_title.configure(text=headline)
            self.status_detail.configure(text=detail, text_color=detail_color)

    def _tx_lanes(self):
        lang, p = self.language, self.engine.ppg_params
        ac = p.perfusion_index / 100 * p.dc_ir_mv
        ratio = r_target_from_spo2(p.spo2, p.spo2_coeff_a, p.spo2_coeff_b)
        if p.ac_red_mv is not None:
            red, how = p.ac_red_mv, text(lang, "red_manual")
        else:
            red = max(0.0, ratio) * ac * p.dc_red_mv / p.dc_ir_mv
            how = text(lang, "red_negative") if ratio < 0 else text(lang, "red_follows")
        history = self.engine.get_display_history()
        return [
            Lane("IR", T.IR, f"AC {ac:.2f} mV    DC {p.dc_ir_mv:g} mV",
                 [(t, ir * 1000) for t, ir, _red in history]),
            Lane("RED", T.RED, f"AC {red:.2f} mV  {how}    DC {p.dc_red_mv:g} mV",
                 [(t, r * 1000) for t, _ir, r in history]),
        ]

    def periodic_update(self):
        # Widgets only. Recording is pumped by the engine; hidden canvases are
        # not redrawn while the DAC writer is active.
        if not self.winfo_ismapped():
            return
        p = self.engine.ppg_params
        for key, (attr, *_rest) in self.fields.items():
            self.cards[key].set(getattr(p, attr))
        self.cards["spo2"].set_badge(text(self.language, "badge_red_manual") if p.ac_red_mv is not None else None)
        locked = bool(self.engine.ac_dc_locked)
        self.cards["pi"].set_enabled(not locked)
        self.cards["pi"].set_badge(text(self.language, "badge_locked") if locked else None)
        condition = condition_labels(self.language)[p.condition]
        if self.condition_menu.get() != condition:
            self.condition_menu.set(condition)
        self._paint_status()
        self.sync_control_buttons()
        now = time.monotonic()
        if now - self._last_tx_render >= TX_REFRESH_S:
            self._last_tx_render = now
            self.trace.update_lanes(self._tx_lanes())
        self.rx_panel.periodic_update()

