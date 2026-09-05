import time
import customtkinter as ctk
from core.signal_engine import SignalEngine
from hw.opt101_rx import OPT101Receiver, raw_to_millivolts
from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED, DRY_RUN
from ui.trace_view import TraceView
from ui import theme as T


class CalibrationFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.engine, self.rx = SignalEngine.get_instance(), OPT101Receiver.get_instance()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        T.label(self, "Calibration & acquisition", 22, True).grid(row=0, column=0, sticky="w", pady=(0, 12))
        controls = ctk.CTkFrame(self)
        controls.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        T.label(controls, "Sine output", 14, True).pack(side="left", padx=16, pady=14)
        T.label(controls, "Frequency / Hz").pack(side="left", padx=8)
        self.frequency = ctk.CTkEntry(controls, width=75)
        self.frequency.insert(0, "1")
        self.frequency.pack(side="left")
        T.label(controls, "0 to peak / mV").pack(side="left", padx=8)
        self.amplitude = ctk.CTkEntry(controls, width=85)
        self.amplitude.insert(0, "1000")
        self.amplitude.pack(side="left")
        self.run_btn = ctk.CTkButton(controls, text="Start calibration", command=self.toggle, height=36)
        self.run_btn.pack(side="right", padx=16)
        self.trace = TraceView(self, height=200)
        self.trace.empty_text = "Calibration standby  /  output starts only on request"
        self.trace.grid(row=2, column=0, sticky="nsew")
        self.status = T.label(self, "Opening this page does not change the output. Leaving stops calibration output.",
                              12, text_color=T.MUTED, anchor="w")
        self.status.grid(row=3, column=0, sticky="ew", pady=8)
        rx_panel = ctk.CTkFrame(self)
        rx_panel.grid(row=4, column=0, sticky="ew")
        T.label(rx_panel, "OPT101 / RECEIVED SIGNAL", 12, True).pack(anchor="w", padx=16, pady=(12, 4))
        self.rx_label = T.label(rx_panel, "No samples", 15, anchor="w", justify="left")
        self.rx_label.pack(anchor="w", padx=16, pady=(0, 8))
        T.label(rx_panel, "Raw ADC readings • measured SpO₂ requires a validated optical calibration.",
                11, text_color=T.MUTED).pack(anchor="w", padx=16, pady=(0, 12))

    def toggle(self):
        if self.engine.is_calibrating:
            self.engine.stop_simulation()
        else:
            try:
                if self.master.frames["Pathology"].is_recording:
                    self.master.frames["Pathology"].toggle_recording()
                self.engine.start_calibration(float(self.frequency.get()), float(self.amplitude.get()))
                self.status.configure(text="Sine output running on both DAC channels • waveform units: mV", text_color=T.ACCENT)
            except ValueError as exc:
                self.status.configure(text=str(exc), text_color=T.ERROR)
        self.periodic_update()

    def on_show(self):
        self.periodic_update()

    def on_hide(self):
        if self.engine.is_calibrating:
            self.engine.stop_simulation()

    def periodic_update(self):
        self.run_btn.configure(text="Stop calibration" if self.engine.is_calibrating else "Start calibration",
                               fg_color=T.ERROR if self.engine.is_calibrating else T.INK)
        self.trace.update_samples(self.engine.get_display_history() if self.engine.is_calibrating else [])
        rows = []
        for channel, name in ((ADC_CHANNEL_IR, "IR  ·  A0"), (ADC_CHANNEL_RED, "RED  ·  A2")):
            sample = self.rx.get_latest(channel)
            status = self.rx.channel_status(channel)
            if DRY_RUN or self.rx.is_simulated:
                text = "—   simulation mode; no physical ADC samples"
            elif sample is None or self.rx.is_stale(channel):
                text = f"—   {status} / no fresh sample"
            else:
                text = f"{raw_to_millivolts(sample.raw):.1f} mV   ·   {status}"
            rows.append(f"{name}    {text}")
        self.rx_label.configure(text="\n".join(rows))
