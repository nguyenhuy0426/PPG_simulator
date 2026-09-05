import customtkinter as ctk
from core.signal_engine import SignalEngine
from models.respiration import RespirationConfig
from models.waveform import WAVEFORM_KINDS
from models.noise import NOISE_KINDS
from ui import theme as T


class AdvancedFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.engine = SignalEngine.get_instance()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        T.label(self, "Signal setup", 22, True, anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.tabs = ctk.CTkTabview(self, fg_color=T.PANEL)
        self.tabs.grid(row=1, column=0, sticky="nsew")
        self.entries, self.vars = {}, {}
        for name in ("Amplitude & shape", "Respiration", "Noise & calibration"):
            tab = self.tabs.add(name)
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)
            body = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
            body.grid(row=0, column=0, sticky="nsew")
            body.grid_columnconfigure((0, 1), weight=1, uniform="forms")
            if name == "Amplitude & shape": self._amplitude(body)
            elif name == "Respiration": self._respiration(body)
            else: self._noise(body)
        self.status = T.label(self, "Changes apply only when you press Apply.", 12, text_color=T.MUTED, anchor="w")
        self.status.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _entry(self, body, row, column, key, title, hint=""):
        box = ctk.CTkFrame(body, fg_color="transparent")
        box.grid(row=row, column=column, sticky="ew", padx=12, pady=5)
        box.grid_columnconfigure(0, weight=1)
        T.label(box, title, 12, anchor="w").grid(row=0, column=0, sticky="w")
        entry = ctk.CTkEntry(box, width=120, height=34)
        entry.grid(row=0, column=1)
        if hint: T.label(box, hint, 10, text_color=T.MUTED, anchor="w").grid(row=1, column=0, columnspan=2, sticky="w")
        self.entries[key] = entry

    def _check(self, body, row, column, key, title):
        var = ctk.BooleanVar(value=False)
        self.vars[key] = var
        ctk.CTkCheckBox(body, text=title, variable=var).grid(row=row, column=column, sticky="w", padx=12, pady=10)

    def _note(self, body, row, text):
        T.label(body, text, 11, text_color=T.MUTED, anchor="w", justify="left").grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=12, pady=8)

    def _amplitude(self, b):
        for row, fields in enumerate((
            (("ac_ir_mv", "AC · IR", "0.1–300 mV"), ("ac_red_mv", "AC · RED", "Blank = derive from SpO₂")),
            (("dc_ir_mv", "DC · IR", "100–3000 mV"), ("dc_red_mv", "DC · RED", "100–3000 mV")),
            (("output_dc_offset_mv", "Output DC offset", "0–2000 mV; DC + offset ≤ 3000"), ("amplification", "AC gain", "0.1–5.0 ×")),
            (("dicrotic_notch", "Notch depth", "0–1, normalized"), ("spo2", "SpO₂ target", "0–100 %, calibration dependent")),
        )):
            for col, (key, title, hint) in enumerate(fields): self._entry(b, row, col, key, title, hint)
        self.waveform_menu = ctk.CTkOptionMenu(b, values=list(WAVEFORM_KINDS))
        self.waveform_menu.grid(row=4, column=0, sticky="ew", padx=12, pady=8)
        self.polarity_menu = ctk.CTkOptionMenu(b, values=["AC above DC", "AC below DC"])
        self.polarity_menu.grid(row=4, column=1, sticky="ew", padx=12, pady=8)
        self._check(b, 5, 0, "lock_ac", "Hold AC when DC changes")
        self._check(b, 5, 1, "lock_dc", "Hold DC when PI changes")
        self._note(b, 6, "Feature timing at 60 bpm  ·  SP < DN < DP  ·  scales with the cardiac cycle")
        for row, kind, title in ((7, "sp", "Systolic peak"), (8, "dn", "Dicrotic notch"), (9, "dp", "Diastolic peak")):
            for col, ch in enumerate(("ir", "red")):
                self._entry(b, row, col, kind + "_ms_" + ch, title + " · " + ch.upper(), "ms / 0–1000")
        ctk.CTkButton(b, text="Apply amplitude & shape", height=38, command=self.on_apply_signal).grid(
            row=10, column=0, columnspan=2, sticky="ew", padx=12, pady=12)

    def _respiration(self, b):
        for row, fields in enumerate((
            (("resp_rate", "Respiration rate", "1–150 breaths/min"), ("resp_ie_ratio", "Inhale : exhale", "Enter N for 1:N, N = 1…5")),
            (("resp_variation_ir_pct", "Variation · IR", "1–16 % of AC"), ("resp_variation_red_pct", "Variation · RED", "1–16 % of AC")),
            (("apnea_duration_s", "Apnea duration", "1–60 s"), ("apnea_cycle_min", "Apnea cycle", "1–10 min; duration < cycle")),
        )):
            for col, field in enumerate(fields): self._entry(b, row, col, *field)
        self._check(b, 3, 0, "resp_mod_baseline", "Baseline modulation")
        self._check(b, 3, 1, "resp_mod_amplitude", "Amplitude modulation")
        self._check(b, 4, 0, "resp_mod_frequency", "Frequency modulation / RSA")
        self._check(b, 4, 1, "apnea_enabled", "Enable periodic apnea")
        self._note(b, 5, "Apnea suppresses respiratory modulation. Cardiac pulses continue.\nVariation changes the model waveform; it is not a measured respiratory value.")
        ctk.CTkButton(b, text="Apply respiration", height=38, command=self.on_apply_respiration).grid(
            row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=12)

        self._note(b, 7, "Physiological dynamics / switch off for repeatable nominal AC and HR tests")
        self._check(b, 8, 0, "hr_amplitude_enabled", "HR changes pulse amplitude")
        self._check(b, 8, 1, "spo2_coupling_enabled", "SpO₂ changes notch shape")
        self._check(b, 9, 0, "variability_enabled", "Beat variability / arrhythmia")
        ctk.CTkButton(b, text="Apply dynamics", height=36, command=self.on_apply_dynamics).grid(
            row=9, column=1, sticky="ew", padx=12, pady=12)

    def on_apply_dynamics(self):
        self._apply(lambda: self.engine.update_modelling_options(
            self.vars["hr_amplitude_enabled"].get(), self.vars["spo2_coupling_enabled"].get(),
            self.vars["variability_enabled"].get()))

    def _noise(self, b):
        self._note(b, 0, "Artefact injection  /  independent random streams for IR and RED")
        self.noise_menu = ctk.CTkOptionMenu(b, values=list(NOISE_KINDS))
        self.noise_menu.grid(row=1, column=0, sticky="ew", padx=12, pady=8)
        self._entry(b, 1, 1, "noise_amplitude_mv", "Amplitude", "mV; white/motion RMS, sine peak")
        self._entry(b, 2, 0, "noise_freq_hz", "Frequency", "Hz; model Nyquist limit < 50 Hz")
        self._entry(b, 2, 1, "noise_seed", "Random seed", "Integer, or blank for random")
        self._entry(b, 3, 0, "noise_level", "Proportional noise", "0–1; only used by proportional kind")
        ctk.CTkButton(b, text="Apply noise", height=36, command=self.on_apply_noise).grid(
            row=3, column=1, sticky="ew", padx=12, pady=8)
        self._note(b, 4, "50/60 Hz mains injection is rejected at the 100 Hz model rate; interpolation adds no bandwidth.")
        self._note(b, 5, "SpO₂ calibration  /  SpO₂ = A − B × R  /  coefficients belong to your optical assembly")
        self._entry(b, 6, 0, "spo2_coeff_a", "Coefficient A")
        self._entry(b, 6, 1, "spo2_coeff_b", "Coefficient B", "Must be > 0")
        ctk.CTkButton(b, text="Apply coefficients", height=36, command=self.on_apply_coefficients).grid(
            row=7, column=0, columnspan=2, sticky="ew", padx=12, pady=12)

    def _number(self, key, optional=False):
        text = self.entries[key].get().strip()
        if optional and not text: return None
        try: return float(text)
        except ValueError: raise ValueError(f"{key}: enter a number")

    def _apply(self, callback):
        try:
            callback()
            self.status.configure(text="Applied. Settings will be saved on exit.", text_color=T.ACCENT)
        except (ValueError, TypeError) as exc:
            self.status.configure(text=str(exc), text_color=T.ERROR)

    def on_apply_signal(self):
        def apply():
            keys = ("dc_ir_mv", "dc_red_mv", "ac_ir_mv", "output_dc_offset_mv", "amplification", "dicrotic_notch", "spo2")
            values = {k: self._number(k) for k in keys}
            values["ac_red_mv"] = self._number("ac_red_mv", True)
            values["waveform"] = self.waveform_menu.get()
            values["ac_polarity"] = 0 if self.polarity_menu.get() == "AC above DC" else 1
            values.update({k: self.vars[k].get() for k in ("lock_ac", "lock_dc")})
            for ch in ("ir", "red"):
                for kind in ("sp", "dn", "dp"):
                    key = kind + "_ms_" + ch
                    values[key] = self._number(key)
            self.engine.update_signal_settings(values)
        self._apply(apply)

    def on_apply_respiration(self):
        def apply():
            ratio = self._number("resp_ie_ratio")
            if not ratio.is_integer(): raise ValueError("Inhale : exhale requires an integer from 1 to 5")
            self.engine.update_respiration(RespirationConfig(
                rate_brpm=self._number("resp_rate"), inhale_exhale_ratio=int(ratio),
                variation_ir_pct=self._number("resp_variation_ir_pct"),
                variation_red_pct=self._number("resp_variation_red_pct"),
                baseline_enabled=self.vars["resp_mod_baseline"].get(),
                amplitude_enabled=self.vars["resp_mod_amplitude"].get(),
                frequency_enabled=self.vars["resp_mod_frequency"].get(),
                apnea_enabled=self.vars["apnea_enabled"].get(),
                apnea_duration_s=self._number("apnea_duration_s"), apnea_cycle_min=self._number("apnea_cycle_min")))
        self._apply(apply)

    def on_apply_noise(self):
        def apply():
            seed = self._number("noise_seed", True)
            if seed is not None and not seed.is_integer(): raise ValueError("Seed must be an integer")
            self.engine.update_noise_settings(self.noise_menu.get(), self._number("noise_amplitude_mv"),
                self._number("noise_freq_hz"), None if seed is None else int(seed), self._number("noise_level"))
        self._apply(apply)

    def on_apply_coefficients(self):
        self._apply(lambda: self.engine.update_spo2_coefficients(self._number("spo2_coeff_a"), self._number("spo2_coeff_b")))

    def on_show(self):
        p = self.engine.ppg_params
        for key, entry in self.entries.items():
            value = getattr(p, key)
            if key == "ac_ir_mv" and value is None: value = p.perfusion_index * p.dc_ir_mv / 100
            entry.delete(0, "end")
            entry.insert(0, "" if value is None else f"{value:g}")
        for key, var in self.vars.items(): var.set(getattr(p, key))
        self.waveform_menu.set(p.waveform)
        self.noise_menu.set(p.noise_kind)
        self.polarity_menu.set("AC above DC" if p.ac_polarity == 0 else "AC below DC")
