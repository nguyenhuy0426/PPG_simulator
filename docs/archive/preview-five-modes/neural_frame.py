"""Original Gaussian and three neural generators; screen preview only."""
import queue
import threading
from tkinter import filedialog

import customtkinter as ctk

from core.neural_preview import NeuralPreview, export_preview, gaussian_preview, PREVIEW_MODES, GAUSSIAN_PROFILES
from ui import theme as T
from ui.trace_view import TraceView


class NeuralFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.previews = {"Gaussian (original)": gaussian_preview()}
        try:
            self.previews["Gaussian (fitted)"] = gaussian_preview(profile="Balanced")
        except (OSError, ValueError, KeyError, TypeError):
            pass  # The original preview and Classic remain usable without the fit file.
        self.backend = None
        self.messages = queue.Queue(maxsize=1)
        self.busy = False
        self.selected = "Gaussian (fitted)"
        T.label(self, "Gaussian + Neural · preview only", 21, True, anchor="w").grid(row=0, column=0, sticky="ew")
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", pady=6)
        self.mode_menu = ctk.CTkOptionMenu(controls, values=list(PREVIEW_MODES), width=175, command=self.select_mode)
        self.mode_menu.set(self.selected)
        self.mode_menu.grid(row=0, column=0, padx=(0, 6), pady=3)
        self.switch_btn = ctk.CTkButton(controls, text="Next ⇄", width=70, command=self.switch)
        self.switch_btn.grid(row=0, column=1, padx=4)
        self.both = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(controls, text="Compare with", variable=self.both,
                        command=self.render).grid(row=0, column=2, padx=8)
        self.reference_menu = ctk.CTkOptionMenu(controls, values=list(PREVIEW_MODES), width=175, command=self.render)
        self.reference_menu.set("Gaussian (original)")
        self.reference_menu.grid(row=0, column=3, columnspan=2, padx=5)
        T.label(controls, "Seed", 12).grid(row=1, column=0, sticky="w")
        self.seed_entry = ctk.CTkEntry(controls, width=68)
        self.seed_entry.insert(0, "42")
        self.seed_entry.grid(row=1, column=0, sticky="e", padx=8)
        T.label(controls, "Pulse HR", 12).grid(row=1, column=1)
        self.hr_entry = ctk.CTkEntry(controls, width=60)
        self.hr_entry.insert(0, "75")
        self.hr_entry.grid(row=1, column=2, sticky="w", padx=8)
        self.morphology_menu = ctk.CTkOptionMenu(controls, values=["No notch", "With notch"], width=120)
        self.morphology_menu.grid(row=1, column=3, padx=5)
        self.gaussian_profile_menu = ctk.CTkOptionMenu(controls, values=list(GAUSSIAN_PROFILES), width=125)
        self.gaussian_profile_menu.set("Balanced")
        self.gaussian_profile_menu.grid(row=1, column=4, padx=5)
        T.label(controls, "Neural notch request", 10, text_color=T.MUTED).grid(row=2, column=3)
        T.label(controls, "Gaussian preset", 10, text_color=T.MUTED).grid(row=2, column=4)
        self.gaussian_btn = ctk.CTkButton(controls, text="Generate Gaussian", width=140, command=self.generate_gaussian)
        self.gaussian_btn.grid(row=0, column=5, padx=6)
        self.generate_btn = ctk.CTkButton(controls, text="Generate all", width=125, command=self.generate)
        self.generate_btn.grid(row=1, column=5, padx=6)
        self.info = T.label(self, "Fitted Gaussian: train-derived presets. Press Generate to apply. HR: pulse models. LSM: 40 Hz, no HR/notch control.",
                            11, text_color=T.MUTED, anchor="w")
        self.info.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        self.plots = ctk.CTkFrame(self, fg_color="transparent")
        self.plots.grid(row=3, column=0, sticky="nsew")
        self.plots.grid_columnconfigure((0, 1), weight=1, uniform="neural")
        self.plots.grid_rowconfigure(0, weight=1)
        self.cards, self.traces, self.labels = {}, {}, {}
        for name in PREVIEW_MODES:
            card = ctk.CTkFrame(self.plots)
            card.grid_columnconfigure(0, weight=1)
            card.grid_rowconfigure(1, weight=1)
            label = T.label(card, name, 15, True, anchor="w")
            label.grid(row=0, column=0, sticky="ew", padx=10, pady=6)
            trace = TraceView(card)
            trace.empty_text = "Press Generate all"
            trace.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
            self.cards[name], self.traces[name], self.labels[name] = card, trace, label
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=4, column=0, sticky="ew", pady=6)
        bottom.grid_columnconfigure(0, weight=1)
        self.position = ctk.CTkSlider(bottom, from_=0, to=22, number_of_steps=220, command=self.render)
        self.position.set(0)
        self.position.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.export_btn = ctk.CTkButton(bottom, text="Export selected CSV", width=165, command=self.export)
        self.export_btn.grid(row=0, column=1)
        self.status = T.label(self, "Screen preview · IR/RED share a shape with nominal AC/DC · no DAC/LED output.",
                              11, anchor="w", justify="left", wraplength=850)
        self.status.grid(row=5, column=0, sticky="ew")
        self.render()

    def switch(self):
        self.select_mode(PREVIEW_MODES[(PREVIEW_MODES.index(self.selected) + 1) % len(PREVIEW_MODES)])

    def select_mode(self, name):
        self.selected = name
        self.mode_menu.set(name)
        self.render()

    def generate_gaussian(self):
        try:
            hr = float(self.hr_entry.get())
            self.previews["Gaussian (original)"] = gaussian_preview(hr)
            self.previews["Gaussian (fitted)"] = gaussian_preview(hr, self.gaussian_profile_menu.get())
            self.select_mode("Gaussian (fitted)")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.configure(text=str(exc), text_color=T.ERROR)

    def generate(self):
        if self.busy:
            return
        try:
            seed, hr = int(self.seed_entry.get()), float(self.hr_entry.get())
            if not 0 <= seed < 2**32 or not 40 <= hr <= 180:
                raise ValueError()
        except ValueError:
            self.status.configure(text="Enter seed 0–4294967295 and pulse HR 40–180 bpm.", text_color=T.ERROR)
            return
        self.busy = True
        self.generate_btn.configure(state="disabled", text="Generating…")
        self.status.configure(text="Loading CPU models / generating five previews…", text_color=T.MUTED)
        morphology = self.morphology_menu.get()
        gaussian_profile = self.gaussian_profile_menu.get()

        def work():
            try:
                if self.backend is None:
                    self.backend = NeuralPreview()
                self.messages.put((self.backend.generate(seed, hr, morphology, gaussian_profile), None))
            except Exception as exc:
                self.messages.put((None, str(exc)))

        threading.Thread(target=work, daemon=True, name="NeuralPreview").start()

    def periodic_update(self):
        try:
            previews, error = self.messages.get_nowait()
        except queue.Empty:
            return
        self.busy = False
        self.generate_btn.configure(state="normal", text="Generate all")
        if error:
            self.status.configure(text=error, text_color=T.ERROR)
            return
        self.previews = previews
        self.export_btn.configure(state="normal")
        self.render()

    def render(self, _value=None):
        names = tuple(dict.fromkeys((self.selected, self.reference_menu.get()))) if self.both.get() else (self.selected,)
        self.export_btn.configure(state="normal" if self.selected in self.previews else "disabled")
        for card in self.cards.values():
            card.grid_forget()
        for column, name in enumerate(names):
            self.cards[name].grid(row=0, column=column, columnspan=1 if len(names) == 2 else 2,
                                  sticky="nsew", padx=3)
            self.labels[name].configure(text=name + (" · selected" if name == self.selected else ""),
                                        text_color=T.ACCENT if name == self.selected else T.INK)
            preview = self.previews.get(name)
            if preview:
                start = float(self.position.get())
                self.traces[name].update_samples([s for s in preview.samples if start <= s[0] <= start + 8])
        if self.selected in self.previews and not self.busy:
            current = self.previews[self.selected]
            score = current.discriminator_score
            diagnostic = ("No discriminator" if score is None else
                          f"{'Critic' if self.selected == 'TCN-FiLM' else 'D(fake)'} {score:.4f} (diagnostic only)")
            morphology = ("notch requested" if current.condition[-1] > .5 else "no notch requested") if current.condition else current.variant
            self.status.configure(text=f"Selected: {self.selected} · seed {current.seed} · native {current.native_fs} Hz · "
                                  f"HR {current.hr_target if current.hr_target else 'uncontrolled'} · {morphology}\n"
                                  f"{diagnostic}. Shared IR/RED shape, 1.5 V DC / 45 & 21.6 mV AC. No DAC output.",
                                  text_color=T.MUTED)
        elif not self.busy:
            self.status.configure(text=f"{self.selected}: press Generate all to create this preview.", text_color=T.MUTED)

    def export(self):
        preview = self.previews.get(self.selected)
        if preview is None:
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv",
                                           initialfile=f"{self.selected}-seed{preview.seed}.csv",
                                           filetypes=[("CSV", "*.csv")])
        if path:
            try:
                export_preview(preview, path)
                self.status.configure(text=f"Saved native-rate CSV and metadata: {path}", text_color=T.ACCENT)
            except OSError as exc:
                self.status.configure(text=str(exc), text_color=T.ERROR)
