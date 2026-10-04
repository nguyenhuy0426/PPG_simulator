import bisect
import time
from pathlib import Path
import customtkinter as ctk
from comm.logger import log
from core.signal_engine import SignalEngine
from ui.recordings import load_recording
from ui.trace_view import TraceView
from models.ppg_model import CONDITION_NAMES
from ui import icons
from ui.i18n import condition_labels
from ui import page_kit as K
from ui import theme as T


COPY = {
    "vi": dict(title="Bản ghi", subtitle="Lệnh mô hình TX đã ghi ở 100 Hz. Phát lại chỉ trên màn hình, không điều khiển LED.",
               sessions="Phiên đã ghi", select="Chọn một bản ghi", empty="Chưa có bản ghi.\nHãy Phát rồi bấm Ghi CSV.",
               play="Phát lại", pause="Tạm dừng", replay="Phát lại từ đầu", none="Chưa chọn bản ghi",
               hr="Nhịp tim", spo2="SpO₂ mục tiêu", rr="Nhịp thở", pi="PI", condition="Tình trạng",
               samples="{n:,} mẫu · {d:.2f} s · {timing}",
               scope="Chỉ có lệnh mô hình; tín hiệu quang thực tế không được ghi ở đây.",
               missing="Không tìm thấy bản ghi: {name}"),
    "en": dict(title="Recordings", subtitle="TX model commands recorded at 100 Hz. Playback is on screen only; it does not drive the LEDs.",
               sessions="Recorded sessions", select="Select a recording", empty="No saved recordings.\nStart output, then Record CSV.",
               play="Play", pause="Pause", replay="Replay", none="No recording selected",
               hr="Heart rate", spo2="SpO₂ target", rr="Respiration", pi="PI", condition="Condition",
               samples="{n:,} samples · {d:.2f} s · {timing}",
               scope="Model commands only; optical reproduction is not recorded here.",
               missing="Recording not found: {name}"),
}
METRICS = (("hr", "bpm"), ("spo2", "%"), ("rr", "brpm"), ("pi", "%"), ("condition", ""))


class PlaybackFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.engine = SignalEngine.get_instance()
        self.language = getattr(master, "language", "en")
        u = T.ui
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.page_title, self.subtitle, actions = K.page_header(self)
        self.play_btn = K.primary_button(actions, state="disabled", command=self.toggle_playback, width=132)
        self.play_btn.pack(side="right")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        sessions, self.sessions_title, _ = K.section(body)
        sessions.grid(row=0, column=0, sticky="nsew", padx=(0, u(8)))
        sessions.grid_rowconfigure(1, weight=1)
        self.files = ctk.CTkScrollableFrame(sessions, width=u(220), fg_color="transparent")
        self.files.grid(row=1, column=0, sticky="nsew", padx=u(4), pady=(0, u(6)))
        self._file_buttons = {}

        view, self.title_label, tools = K.section(body)
        view.grid(row=0, column=1, sticky="nsew")
        self.info = T.label(tools, "", u(12), text_color=T.MUTED)
        self.info.pack(side="right")
        self.trace = TraceView(K.plot_holder(view), height=220)
        self.trace.pack(fill="both", expand=True, padx=u(3), pady=u(3))
        tiles = ctk.CTkFrame(view, fg_color="transparent")
        tiles.grid(row=2, column=0, sticky="ew", padx=u(6), pady=(0, u(8)))
        tiles.grid_columnconfigure(tuple(range(len(METRICS))), weight=1, uniform="tiles")
        self.metric_names, self.metric_values = {}, {}
        for column, (key, unit) in enumerate(METRICS):
            tile = ctk.CTkFrame(tiles, fg_color=T.SUBTLE, corner_radius=u(6))
            tile.grid(row=0, column=column, sticky="ew", padx=u(3))
            name = T.label(tile, "", u(11), text_color=T.MUTED, anchor="w")
            name.pack(anchor="w", padx=u(8), pady=(u(5), 0))
            value = T.label(tile, "—", u(17), True, anchor="w")
            value.pack(anchor="w", padx=u(8), pady=(0, u(5)))
            self.metric_names[key], self.metric_values[key] = name, (value, unit)
        self.status = T.label(self, "", u(12), text_color=T.MUTED, anchor="w")
        self.status.grid(row=2, column=0, sticky="ew", pady=(u(6), 0))
        self.dataset_dir = Path(__file__).resolve().parents[2] / "dataset"
        self.samples, self.parameters, self.times = [], [], []
        self.is_playing = False
        self.position = 0.0
        self._origin = 0.0
        self.current_name = ""
        self._timing = ""
        self.engine.set_playback_state(False, "", "")
        self.set_language(self.language)
        self.trace.update_samples([])

    def set_language(self, language):
        self.language = language if language in COPY else "en"
        t = COPY[self.language]
        self.page_title.configure(text=t["title"])
        self.subtitle.configure(text=t["subtitle"])
        self.sessions_title.configure(text=t["sessions"])
        if not self.current_name:
            self.title_label.configure(text=t["select"])
        for key, name in self.metric_names.items():
            name.configure(text=t[key])
        self.trace.empty_text = t["none"]
        if self.samples:
            self.info.configure(text=t["samples"].format(n=len(self.samples), d=self.times[-1], timing=self._timing))
        self._paint_play()

    def _paint_play(self):
        t = COPY[self.language]
        at_end = bool(self.samples) and not self.is_playing and self.position >= self.times[-1]
        text = t["pause"] if self.is_playing else (t["replay"] if at_end else t["play"])
        self.play_btn.configure(text=text, image=icons.icon("pause" if self.is_playing else "play", T.WHITE, T.ui(14)))

    def on_show(self):
        u = T.ui
        for child in self.files.winfo_children(): child.destroy()
        self._file_buttons = {}
        files = sorted(self.dataset_dir.glob("*.csv"), reverse=True)   # newest first
        files = [p for p in files if p.name != "temp_recording.csv"]
        if not files:
            T.label(self.files, COPY[self.language]["empty"], u(12), text_color=T.MUTED,
                    wraplength=u(200), justify="left").pack(anchor="w", padx=u(6), pady=u(12))
        for path in files:
            button = ctk.CTkButton(self.files, text=path.name, anchor="w", height=u(36), corner_radius=u(6),
                                   font=T.font(u(12)), fg_color="transparent", text_color=T.INK,
                                   hover_color=T.SUBTLE, image=icons.icon("recordings", T.MUTED, u(16)),
                                   compound="left", command=lambda p=path: self.load_data(p))
            button.pack(fill="x", pady=u(1))
            self._file_buttons[path.name] = button
        self._highlight()

    def _highlight(self):
        for name, button in self._file_buttons.items():
            selected = name == self.current_name
            button.configure(fg_color=T.SUBTLE if selected else "transparent",
                             text_color=T.ACCENT if selected else T.INK)

    def on_hide(self):
        # Playback is a shared BLE state. Changing the Pi layout must not
        # pause a session that was started by the phone (or vice versa).
        pass

    def load_data(self, path):
        try:
            samples, parameters, timing = load_recording(path)
        except (OSError, ValueError) as exc:
            self.status.configure(text=str(exc), text_color=T.ERROR)
            return
        self.samples, self.parameters = samples, parameters
        self.times = [s[0] for s in samples]
        self.position, self.is_playing = 0.0, False
        self.current_name = Path(path).name
        self._timing = timing
        t = COPY[self.language]
        self.title_label.configure(text=Path(path).name)
        self.info.configure(text=t["samples"].format(n=len(samples), d=self.times[-1], timing=timing))
        self.status.configure(text=t["scope"], text_color=T.MUTED)
        self.play_btn.configure(state="normal")
        self._paint_play()
        self._highlight()
        self._publish_state()
        self._render(0)

    # ─── Playback primitives (Tk thread; also driven by phone "pb" commands) ──
    def play(self):
        if self.is_playing or not self.samples:
            return
        if self.position >= self.times[-1]: self.position = 0.0
        self._origin = time.monotonic() - self.position
        self.is_playing = True
        self._paint_play()
        self._publish_state()

    def pause_playback(self):
        if self.samples and self.is_playing:
            self.position = min(self.times[-1], time.monotonic() - self._origin)
            self.is_playing = False
            self._paint_play()
        self._publish_state()

    def resume_playback(self):
        self.play()

    def stop_playback(self):
        self.is_playing = False
        self.position = 0.0
        if self.samples:
            self._paint_play()
            self._render(0)
        self._publish_state()

    def start_named_playback(self, basename):
        """Phone-commanded playback of one saved recording by file name."""
        name = Path(str(basename)).name  # strip any caller-supplied directories
        if not name:
            log.warning("[Playback] pb start without a usable pb_file name")
            return False
        if not name.lower().endswith(".csv"):
            name += ".csv"
        path = self.dataset_dir / name
        if not path.is_file():
            log.warning(f"[Playback] pb_file not found: {name}")
            self.status.configure(text=COPY[self.language]["missing"].format(name=name), text_color=T.ERROR)
            return False
        self.load_data(path)
        if not self.samples:
            return False
        self.play()
        return True

    def handle_playback_request(self, action, filename=""):
        """Apply one queued phone 'pb' command (called from the Tk thread)."""
        if action == "start":
            if filename:
                self.start_named_playback(filename)
            elif self.samples:
                self.play()
            else:
                log.warning("[Playback] pb start with no pb_file and nothing loaded")
        elif action == "stop":
            self.stop_playback()
        elif action == "pause":
            self.pause_playback()
        elif action == "resume":
            self.resume_playback()

    def _publish_state(self):
        if self.is_playing:
            self.engine.set_playback_state(True, "playing", self.current_name)
        elif self.samples and self.current_name and 0.0 < self.position < self.times[-1]:
            self.engine.set_playback_state(True, "paused", self.current_name)
        else:
            self.engine.set_playback_state(False, "", self.current_name)

    def toggle_playback(self):
        if not self.samples: return
        if self.is_playing:
            self.pause_playback()
        else:
            self.play()

    def _render(self, idx):
        self.trace.update_samples(self.samples[max(0, idx-1200):idx+1])
        values = dict(zip(("hr", "spo2", "rr", "pi", "condition"), self.parameters[idx]))
        for key, (label, unit) in self.metric_values.items():
            value = values[key]
            if isinstance(value, str):
                text = (condition_labels(self.language)[CONDITION_NAMES.index(value)]
                        if value in CONDITION_NAMES else value)
            else:
                text = f"{value:g} {unit}"
            if label.cget("text") != text:
                label.configure(text=text)

    def periodic_update(self):
        if not self.is_playing: return
        self.position = min(self.times[-1], time.monotonic() - self._origin)
        idx = max(0, bisect.bisect_right(self.times, self.position)-1)
        self._render(idx)
        if self.position >= self.times[-1]:
            self.is_playing = False
            self._paint_play()
            self._publish_state()
