import customtkinter as ctk
from core.signal_engine import SignalEngine
from models.ppg_model import CONDITION_NAMES
from models import limits
from calibration import r_target_from_spo2
from ui.trace_view import TraceView
from ui import theme as T


class PathologyFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.app, self.engine, self.logger = master, SignalEngine.get_instance(), master.csv_logger
        self.is_recording = False
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        T.label(toolbar, "Signal monitor", 22, True).pack(side="left")
        self.run_btn = ctk.CTkButton(toolbar, text="Run simulation", height=38,
                                    fg_color=T.ACCENT, command=self.toggle_simulation)
        self.run_btn.pack(side="right", padx=(8, 0))
        self.record_btn = ctk.CTkButton(toolbar, text="Record CSV", width=120, height=38,
                                       command=self.toggle_recording)
        self.record_btn.pack(side="right")
        monitor = ctk.CTkFrame(self, fg_color="transparent")
        monitor.grid(row=1, column=0, sticky="nsew")
        monitor.grid_columnconfigure(0, weight=4)
        monitor.grid_columnconfigure(1, weight=1, minsize=250)
        monitor.grid_rowconfigure(0, weight=1)
        waves = ctk.CTkFrame(monitor, fg_color=T.DARK)
        waves.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        waves.grid_rowconfigure(1, weight=1)
        waves.grid_columnconfigure(0, weight=1)
        T.label(waves, "TRANSMIT  /  AC + modulation     •     8 s window     •     Auto scale per channel",
                11, text_color="#C4CED5", anchor="w").grid(row=0, column=0, sticky="ew", padx=18, pady=(10, 0))
        self.trace = TraceView(waves, height=220)
        self.trace.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 6))
        self.canvas = self.trace
        vitals = ctk.CTkFrame(monitor, fg_color=T.PANEL)
        vitals.grid(row=0, column=1, sticky="nsew")
        vitals.grid_columnconfigure(0, weight=1)
        T.label(vitals, "SETPOINTS", 11, True, text_color=T.MUTED).grid(row=0, column=0, sticky="w", padx=18, pady=(10, 0))
        self.vital_labels = {}
        for i, (key, title, unit) in enumerate((("hr", "Heart rate", "bpm"), ("spo2", "SpO₂ target", "%"),
                                                ("rr", "Respiration", "brpm"), ("pi", "Perfusion index", "%"))):
            row = ctk.CTkFrame(vitals, fg_color=T.PANEL if i % 2 == 0 else "#F4F6F7", corner_radius=0)
            row.grid(row=i+1, column=0, sticky="nsew", padx=8, pady=2)
            vitals.grid_rowconfigure(i+1, weight=1)
            row.grid_columnconfigure(1, weight=1)
            row.grid_rowconfigure(0, weight=1)
            T.label(row, title + " / " + unit, 11, text_color=T.MUTED,
                    wraplength=92, justify="left", anchor="w").grid(row=0, column=0, padx=10, sticky="w")
            value = T.label(row, "—", 30, True, anchor="e")
            value.grid(row=0, column=1, padx=10, sticky="e")
            self.vital_labels[key] = value
        self.amp_label = T.label(self, "", 11, text_color=T.MUTED, anchor="w")
        self.amp_label.grid(row=2, column=0, sticky="ew", pady=(6, 4))
        controls = ctk.CTkFrame(self, fg_color=T.PANEL)
        controls.grid(row=3, column=0, sticky="ew")
        controls.grid_columnconfigure((0, 1), weight=1, uniform="controls")
        self.entries, self.sliders, self.slider_vars = {}, {}, {}
        self.fields = {
            "hr": ("Heart rate", "heart_rate", limits.HEART_RATE, "bpm"),
            "spo2": ("SpO₂ target", "spo2", limits.SPO2, "%"),
            "rr": ("Respiration", "resp_rate", limits.RESP_RATE, "brpm"),
            "pi": ("Perfusion index", "perfusion_index", limits.PERFUSION_INDEX, "%"),
        }
        for i, (key, (title, attr, span, unit)) in enumerate(self.fields.items()):
            box = ctk.CTkFrame(controls, fg_color="transparent")
            box.grid(row=i//2, column=i%2, sticky="ew", padx=16, pady=8)
            box.grid_columnconfigure(1, weight=1)
            T.label(box, title, 12, anchor="w", width=106).grid(row=0, column=0, sticky="w")
            var = ctk.DoubleVar(value=getattr(self.engine.ppg_params, attr))
            self.slider_vars[key] = var
            slider = ctk.CTkSlider(box, from_=span.minimum, to=span.maximum, variable=var,
                                  command=lambda value, k=key: self.update_param(k, value))
            slider.grid(row=0, column=1, sticky="ew", padx=10)
            self.sliders[key] = slider
            entry = ctk.CTkEntry(box, width=70, height=32)
            entry.grid(row=0, column=2)
            entry.bind("<Return>", lambda event, k=key: self.apply_entry(k))
            self.entries[key] = entry
            T.label(box, unit, 11, width=34, text_color=T.MUTED).grid(row=0, column=3)
        bottom = ctk.CTkFrame(controls, fg_color="transparent")
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(2, 10))
        T.label(bottom, "Condition", 12).pack(side="left", padx=(0, 12))
        self.condition_menu = ctk.CTkOptionMenu(bottom, values=CONDITION_NAMES, width=158,
                                               command=lambda name: self.set_condition(CONDITION_NAMES.index(name)))
        self.condition_menu.pack(side="left")
        self.message = T.label(bottom, "Enter a value, then press Enter to apply.", 11, text_color=T.MUTED)
        self.message.pack(side="left", padx=16)

    def on_show(self):
        p = self.engine.ppg_params
        self.entries["pi"].configure(state="normal")
        for key, (_, attr, _, _) in self.fields.items():
            value = getattr(p, attr)
            self.slider_vars[key].set(value)
            self.entries[key].delete(0, "end")
            self.entries[key].insert(0, f"{value:g}")
        self.condition_menu.set(CONDITION_NAMES[p.condition])
        self.sliders["pi"].configure(state="disabled" if self.engine.ac_dc_locked else "normal")
        self.entries["pi"].configure(state="disabled" if self.engine.ac_dc_locked else "normal")
        self.periodic_update()

    def apply_entry(self, key):
        try:
            value = float(self.entries[key].get())
            self.fields[key][2].validate(value)
            self.update_param(key, value)
        except ValueError as exc:
            self.message.configure(text=str(exc), text_color=T.ERROR)

    def update_param(self, key, value):
        span = self.fields[key][2]
        value = span.quantise(value)
        callbacks = {"hr": self.engine.update_heart_rate, "spo2": self.engine.update_spo2,
                     "rr": self.engine.update_resp_rate, "pi": self.engine.update_perfusion_index}
        try:
            callbacks[key](value)
            actual = getattr(self.engine.ppg_params, self.fields[key][1])
            self.slider_vars[key].set(actual)
            self.entries[key].delete(0, "end")
            self.entries[key].insert(0, f"{actual:g}")
            self.message.configure(text="Applied to generator", text_color=T.ACCENT)
        except ValueError as exc:
            self.message.configure(text=str(exc), text_color=T.ERROR)

    def set_condition(self, idx):
        self.engine.change_condition(idx)

    def toggle_simulation(self):
        if self.engine._running:
            self.engine.stop_simulation()
            if self.is_recording:
                self.toggle_recording()
        else:
            try:
                self.engine.start_simulation(self.engine.ppg_params.condition)
            except ValueError as exc:
                self.message.configure(text=str(exc), text_color=T.ERROR)
        self.periodic_update()

    def toggle_recording(self):
        if self.is_recording:
            self.engine.set_recording(False)
            self.record_tick()
            self.logger.stop(save=True)
            self.is_recording = False
            self.message.configure(text="CSV saved in dataset/", text_color=T.ACCENT)
        elif self.engine._running:
            self.logger.start()
            self.is_recording = self.logger.is_logging
            if self.is_recording:
                self.engine.set_recording(True)
        else:
            self.message.configure(text="Start simulation before recording.", text_color=T.MUTED)
        self.record_btn.configure(text="Save recording" if self.is_recording else "Record CSV",
                                  fg_color=T.ERROR if self.is_recording else T.INK)

    def record_tick(self):
        if self.is_recording:
            for sample in self.engine.drain_recording():
                self.logger.log_data(*sample)

    def periodic_update(self):
        p, m = self.engine.ppg_params, self.engine.ppg_model
        for key, (_, attr, _, _) in self.fields.items():
            self.vital_labels[key].cget("font").configure(size=44 if self.vital_labels[key].master.winfo_height() >= 75 else 30)
            self.vital_labels[key].configure(text=f"{getattr(p, attr):.2f}" if key == "pi" else f"{getattr(p, attr):.0f}")
        ac = p.perfusion_index / 100 * p.dc_ir_mv
        ratio = r_target_from_spo2(p.spo2, p.spo2_coeff_a, p.spo2_coeff_b)
        clamp = max(0.0, ratio)
        red = p.ac_red_mv if p.ac_red_mv is not None else clamp * ac * p.dc_red_mv / p.dc_ir_mv
        state = "RED AC manual • SpO₂ target uncoupled" if p.ac_red_mv is not None else ("Negative R • target outside calibration range" if ratio != clamp else "RED follows SpO₂ ratio")
        self.amp_label.configure(text=(f"NOMINAL  AC IR {ac:.2f} / RED {red:.2f} mV   ·   DC IR {p.dc_ir_mv:g} / RED {p.dc_red_mv:g} mV   ·   {state}"))
        self.trace.update_samples(self.engine.get_display_history())
        self.run_btn.configure(text="Stop output" if self.engine._running else "Run simulation",
                               fg_color=T.ERROR if self.engine._running else T.ACCENT)
