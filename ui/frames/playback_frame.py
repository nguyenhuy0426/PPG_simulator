import bisect
import time
from pathlib import Path
import customtkinter as ctk
from ui.recordings import load_recording
from ui.trace_view import TraceView
from ui import theme as T


class PlaybackFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        T.label(self, "Recorded sessions", 22, True).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self.files = ctk.CTkScrollableFrame(self, width=215, label_text="TX model / DAC commands")
        self.files.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        body = ctk.CTkFrame(self)
        body.grid(row=1, column=1, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(2, weight=1)
        self.title_label = T.label(body, "Select a recording", 17, True, anchor="w")
        self.title_label.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        self.info = T.label(body, "CSV playback is a screen review; it does not drive the LEDs.", 11,
                            text_color=T.MUTED, anchor="w")
        self.info.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        self.trace = TraceView(body)
        self.trace.empty_text = "No recording selected"
        self.trace.grid(row=2, column=0, sticky="nsew", padx=12)
        self.metrics = T.label(body, "HR —   SpO₂ target —   RR —   PI —", 13, anchor="w")
        self.metrics.grid(row=3, column=0, sticky="ew", padx=16, pady=8)
        self.play_btn = ctk.CTkButton(body, text="Play", state="disabled", command=self.toggle_playback, height=36)
        self.play_btn.grid(row=4, column=0, sticky="e", padx=16, pady=(0, 12))
        self.status = T.label(self, "", 11, text_color=T.MUTED, anchor="w")
        self.status.grid(row=2, column=0, columnspan=2, sticky="ew", pady=8)
        self.dataset_dir = Path(__file__).resolve().parents[2] / "dataset"
        self.samples, self.parameters, self.times = [], [], []
        self.is_playing = False
        self.position = 0.0
        self._origin = 0.0

    def on_show(self):
        for child in self.files.winfo_children(): child.destroy()
        files = sorted(self.dataset_dir.glob("*.csv"))
        files = [p for p in files if p.name != "temp_recording.csv"]
        if not files:
            T.label(self.files, "No saved recordings.\nRun a simulation, then Record CSV.", 12,
                    text_color=T.MUTED, wraplength=190, justify="left").pack(padx=8, pady=20)
        for path in files:
            ctk.CTkButton(self.files, text=path.name, anchor="w", fg_color=T.BG,
                          text_color=T.INK, hover_color=T.LINE,
                          command=lambda p=path: self.load_data(p)).pack(fill="x", padx=4, pady=4)

    def on_hide(self):
        if self.is_playing: self.toggle_playback()

    def load_data(self, path):
        try:
            samples, parameters, timing = load_recording(path)
        except (OSError, ValueError) as exc:
            self.status.configure(text=str(exc), text_color=T.ERROR)
            return
        self.samples, self.parameters = samples, parameters
        self.times = [s[0] for s in samples]
        self.position, self.is_playing = 0.0, False
        self.title_label.configure(text=Path(path).name)
        self.info.configure(text=f"{len(samples):,} samples   ·   {self.times[-1]:.2f} s   ·   {timing}")
        self.status.configure(text="Model commands only; optical reproduction is not recorded here.", text_color=T.MUTED)
        self.play_btn.configure(text="Play", state="normal")
        self._render(0)

    def toggle_playback(self):
        if not self.samples: return
        if self.is_playing:
            self.position = min(self.times[-1], time.monotonic() - self._origin)
            self.is_playing = False
        else:
            if self.position >= self.times[-1]: self.position = 0.0
            self._origin = time.monotonic() - self.position
            self.is_playing = True
        self.play_btn.configure(text="Pause" if self.is_playing else "Play")

    def _render(self, idx):
        self.trace.update_samples(self.samples[max(0, idx-1200):idx+1])
        hr, spo2, rr, pi, condition = self.parameters[idx]
        self.metrics.configure(text=f"HR {hr:g} bpm   ·   SpO₂ target {spo2:g}%   ·   RR {rr:g} brpm   ·   PI {pi:g}%   ·   {condition}")

    def periodic_update(self):
        if not self.is_playing: return
        self.position = min(self.times[-1], time.monotonic() - self._origin)
        idx = max(0, bisect.bisect_right(self.times, self.position)-1)
        self._render(idx)
        if self.position >= self.times[-1]:
            self.is_playing = False
            self.play_btn.configure(text="Replay")
