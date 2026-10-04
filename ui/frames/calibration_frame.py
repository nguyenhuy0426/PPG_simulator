import customtkinter as ctk

from config import DAC_FULLSCALE_MV
from core.signal_engine import SignalEngine
from ui import page_kit as K
from ui import theme as T
from ui.rx_monitor import RXPanel
from ui.touch_slider import TouchSlider
from ui.trace_view import TraceView

COPY = {
    "vi": dict(title="Hiệu chuẩn & thu tín hiệu",
               subtitle="Sine thử trên cả hai DAC. Mở trang không đổi đầu ra; rời trang sẽ dừng sine.",
               sine="Sine thử", frequency="Tần số / Hz", amplitude="0 tới đỉnh / mV",
               start="Bắt đầu", stop="Dừng sine", tx="Tín hiệu phát TX", rx="Tín hiệu thu RX",
               idle="Chưa phát sine", running="Đang phát sine trên cả hai kênh DAC · đơn vị mV",
               note="Số đọc ADC thô. SpO₂ đo được cần một hiệu chuẩn quang học đã kiểm chứng."),
    "en": dict(title="Calibration & acquisition",
               subtitle="Test sine on both DACs. Opening this page does not change the output; leaving stops it.",
               sine="Test sine", frequency="Frequency / Hz", amplitude="0 to peak / mV",
               start="Start", stop="Stop sine", tx="TX output signal", rx="RX received signal",
               idle="Calibration standby", running="Sine running on both DAC channels · units mV",
               note="Raw ADC readings. Measured SpO₂ requires a validated optical calibration."),
}


class CalibrationFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.engine = SignalEngine.get_instance()
        self.language = getattr(master, "language", "en")
        u = T.ui
        self._running_shown = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.title_label, self.subtitle, actions = K.page_header(self)
        self.run_btn = K.primary_button(actions, command=self.toggle, width=132)
        self.run_btn.pack(side="right")

        sine, self.sine_title, _tools = K.section(self, span=2)
        sine.grid(row=1, column=0, sticky="ew", pady=(0, u(8)))
        sine.grid_columnconfigure((0, 1), weight=1, uniform="sine")
        self.slider_labels = {}
        for column, (key, control) in enumerate((
                ("frequency", TouchSlider(sine, 1, 10, 0.1, value=1)),
                ("amplitude", TouchSlider(sine, 100, DAC_FULLSCALE_MV, 10, value=1000)))):
            label = T.label(sine, "", u(12), text_color=T.MUTED, anchor="w")
            label.grid(row=1, column=column, sticky="ew", padx=u(12))
            control.grid(row=2, column=column, sticky="ew", padx=u(12), pady=(0, u(10)))
            self.slider_labels[key] = label
            setattr(self, key, control)

        panels = ctk.CTkFrame(self, fg_color="transparent")
        panels.grid(row=2, column=0, sticky="nsew")
        panels.grid_columnconfigure((0, 1), weight=1, uniform="signals")
        panels.grid_rowconfigure(0, weight=1)
        tx, self.tx_title, _ = K.section(panels)
        tx.grid(row=0, column=0, sticky="nsew", padx=(0, u(4)))
        self.trace = TraceView(K.plot_holder(tx), height=220)
        self.trace.pack(fill="both", expand=True, padx=u(3), pady=u(3))
        rx, self.rx_title, _ = K.section(panels)
        rx.grid(row=0, column=1, sticky="nsew", padx=(u(4), 0))
        self.rx_panel = RXPanel(K.plot_holder(rx), language=self.language, height=220)
        self.rx_panel.pack(fill="both", expand=True, padx=u(3), pady=u(3))

        self.status = T.label(self, "", u(12), text_color=T.MUTED, anchor="w")
        self.status.grid(row=3, column=0, sticky="ew", pady=(u(6), 0))
        self.set_language(self.language)

    def set_language(self, language):
        self.language = language if language in COPY else "en"
        t = COPY[self.language]
        self.title_label.configure(text=t["title"])
        self.subtitle.configure(text=t["subtitle"])
        self.sine_title.configure(text=t["sine"])
        self.tx_title.configure(text=t["tx"])
        self.rx_title.configure(text=t["rx"])
        for key, label in self.slider_labels.items():
            label.configure(text=t[key])
        self.trace.empty_text = t["idle"]
        self.status.configure(text=t["note"], text_color=T.MUTED)
        self.rx_panel.set_language(self.language)
        self._running_shown = None

    def toggle(self):
        if self.engine.is_calibrating:
            self.engine.stop_simulation()
            self.status.configure(text=COPY[self.language]["note"], text_color=T.MUTED)
        else:
            try:
                if self.master.frames["Pathology"].is_recording:
                    self.master.frames["Pathology"].toggle_recording()
                self.engine.start_calibration(float(self.frequency.get()), float(self.amplitude.get()))
                self.status.configure(text=COPY[self.language]["running"], text_color=T.ACCENT)
            except ValueError as exc:
                self.status.configure(text=str(exc), text_color=T.ERROR)
        self.periodic_update()

    def on_show(self):
        self.periodic_update()

    def on_hide(self):
        if self.engine.is_calibrating:
            self.engine.stop_simulation()

    def periodic_update(self):
        if not self.winfo_ismapped():
            return
        running = self.engine.is_calibrating
        if running != self._running_shown:
            self._running_shown = running
            t = COPY[self.language]
            K.set_running(self.run_btn, running, t["start"], t["stop"])
        self.trace.update_samples(self.engine.get_display_history() if running else [])
        self.rx_panel.periodic_update()
