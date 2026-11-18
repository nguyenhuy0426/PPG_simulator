import bisect
import time
from pathlib import Path
import customtkinter as ctk
from comm.logger import log
from core.signal_engine import SignalEngine
from core.waveform_clip import WaveformClip
from ui.recordings import load_recording
from ui.rx_monitor import RXPanel
from ui.trace_view import TraceView
from models.ppg_model import CONDITION_NAMES
from ui import icons
from ui.i18n import condition_labels
from ui import page_kit as K
from ui import theme as T


COPY = {
    "vi": dict(title="Bản ghi", subtitle="Lệnh mô hình TX đã ghi ở 100 Hz. Phát lại đưa đúng các lệnh DAC đó ra LED, thay cho Classic.",
               upload="Lên DB", upload_confirm="Gửi lên DB?", in_db="Đã ở DB", uploading="Đang gửi…",
               upload_failed="Lỗi gửi DB", no_db="Chưa cấu hình DB",
               upload_requested="{name}: đã yêu cầu gửi lên database (chỉ file này).",
               delete="Xoá", confirm="Xoá thật?", deleted="Đã xoá {name}",
               delete_failed="Không xoá được {name}: {why}",
               leds="Đang phát {name} ra LED (output Classic đã dừng).",
               finished="Đã phát xong {name}; LED tắt. Bấm Phát ở Classic để chạy lại Classic.",
               screen_only="Chỉ phát trên màn hình, không ra LED: {why}",
               taken="Output đã chuyển sang trang khác; phát lại dừng.",
               sessions="Phiên đã ghi", select="Chọn một bản ghi", empty="Chưa có bản ghi.\nHãy Phát rồi bấm Ghi CSV.",
               play="Phát lại", pause="Tạm dừng", replay="Phát lại từ đầu", none="Chưa chọn bản ghi",
               hr="Nhịp tim", spo2="SpO₂ mục tiêu", rr="Nhịp thở", condition="Tình trạng",
               samples="{n:,} mẫu · {d:.2f} s · {timing}",
               scope="Bản ghi chỉ chứa lệnh mô hình TX. RX bên phải là ADC đọc lúc này, không thuộc bản ghi.",
               rx="RX trực tiếp · OPT101",
               missing="Không tìm thấy bản ghi: {name}"),
    "en": dict(title="Recordings", subtitle="TX model commands recorded at 100 Hz. Playback sends those DAC commands to the LEDs, in place of Classic.",
               upload="Upload to DB", upload_confirm="Upload it?", in_db="In the DB", uploading="Uploading…",
               upload_failed="DB upload error", no_db="No database set up",
               upload_requested="{name}: upload to the database requested (this file only).",
               delete="Delete", confirm="Delete it?", deleted="Deleted {name}",
               delete_failed="Could not delete {name}: {why}",
               leds="Playing {name} on the LEDs (Classic output stopped).",
               finished="Finished {name}; LEDs off. Start Classic to run Classic again.",
               screen_only="On screen only, not on the LEDs: {why}",
               taken="Another page took the output; playback stopped.",
               sessions="Recorded sessions", select="Select a recording", empty="No saved recordings.\nStart output, then Record CSV.",
               play="Play", pause="Pause", replay="Replay", none="No recording selected",
               hr="Heart rate", spo2="SpO₂ target", rr="Respiration", condition="Condition",
               samples="{n:,} samples · {d:.2f} s · {timing}",
               scope="Recordings hold TX model commands only. RX on the right is the live ADC, not part of the recording.",
               rx="Live RX · OPT101",
               missing="Recording not found: {name}"),
}
# PI is not shown (HR, SpO2, RR are the setpoints a user sets); the CSV keeps its PI_% column.
METRICS = (("hr", "bpm"), ("spo2", "%"), ("rr", "brpm"), ("condition", ""))
# Database copy (comm/record_sync.py) after each file name; nothing when sync is not configured.
# "local": kept on the Pi only; it goes to the database only after Upload to DB (comm/record_sync.py).
SYNC_MARKS = {"synced": "   ✓ DB", "pending": "   … DB", "error": "   ✗ DB"}
SYNC_CODES = {"synced": "s", "pending": "p", "error": "e", "local": "l"}


def sync_state(name):
    """'synced', 'pending', 'error', 'local' or None for a recording file name."""
    from comm import record_sync
    sync = record_sync.current()
    state = sync.state_of(name) if sync is not None else None
    return state[0] if state else None


def sync_available():
    from comm import record_sync
    return record_sync.current() is not None


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
        self.delete_btn = K.secondary_button(actions, command=self.delete_selected, width=112, icon="trash",
                                             state="disabled")
        self.delete_btn.pack(side="right", padx=(0, T.ui(8)))
        self._delete_armed = None      # Tk after-id while "Delete it?" waits for the second tap
        self.upload_btn = K.secondary_button(actions, command=self.upload_selected, width=136, icon="upload",
                                             state="disabled")
        self.upload_btn.pack(side="right", padx=(0, T.ui(8)))
        self._upload_armed = None      # the same two-tap confirmation: nothing leaves the Pi on one stray tap
        self._upload_shown = None

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure((1, 2), weight=1, uniform="signals")
        body.grid_rowconfigure(0, weight=1)
        # Session drawer: a narrow list that folds to one icon, like the rail,
        # so the TX and RX plots get the width once a recording is chosen.
        self.drawer = T.card(body)
        self.drawer.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, u(8)))
        self.drawer.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self.drawer, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=u(6), pady=(u(6), u(4)))
        self.drawer_btn = ctk.CTkButton(head, text="", width=u(36), height=u(36), corner_radius=u(6),
                                        fg_color="transparent", hover_color=T.SUBTLE,
                                        command=self.toggle_sessions)
        self.drawer_btn.pack(side="left")
        self.sessions_title = T.label(head, "", u(14), True, anchor="w")
        self.files = ctk.CTkScrollableFrame(self.drawer, width=u(176), fg_color="transparent")
        self._file_buttons = {}
        self.sessions_open = None
        self.set_sessions_open(True)

        view, self.title_label, tools = K.section(body)
        view.grid(row=0, column=1, sticky="nsew", padx=(0, u(4)))
        self.info = T.label(tools, "", u(12), text_color=T.MUTED)
        self.info.pack(side="right")
        self.trace = TraceView(K.plot_holder(view), height=200)
        self.trace.pack(fill="both", expand=True, padx=u(3), pady=u(3))
        # Live RX sits beside the recorded TX. It is the receiver right now,
        # never data from the file: recordings hold model commands only.
        rx, self.rx_title, _ = K.section(body)
        rx.grid(row=0, column=2, sticky="nsew", padx=(u(4), 0))
        self.rx_panel = RXPanel(K.plot_holder(rx), language=self.language, height=200)
        self.rx_panel.pack(fill="both", expand=True, padx=u(3), pady=u(3))
        tiles = ctk.CTkFrame(body, fg_color="transparent")
        tiles.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(u(8), 0))
        tiles.grid_columnconfigure(tuple(range(len(METRICS))), weight=1, uniform="tiles")
        self.metric_names, self.metric_values = {}, {}
        for column, (key, unit) in enumerate(METRICS):
            tile = ctk.CTkFrame(tiles, fg_color=T.SUBTLE, corner_radius=u(6))
            tile.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else u(6), 0))
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
        self._clip = None              # the WaveformClip this page put on the output, while it is there
        self._clip_offset = 0.0        # recording time at which that clip starts
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
        self.rx_title.configure(text=t["rx"])
        if self.status.cget("text_color") != T.ERROR:
            self.status.configure(text=t["scope"], text_color=T.MUTED)
        self.rx_panel.set_language(self.language)
        if not self.current_name:
            self.title_label.configure(text=t["select"])
        for key, name in self.metric_names.items():
            name.configure(text=t[key])
        self._paint_delete()
        self.trace.empty_text = t["none"]
        if self.samples:
            self.info.configure(text=t["samples"].format(n=len(self.samples), d=self.times[-1], timing=self._timing))
        self._paint_play()

    def _paint_play(self):
        t = COPY[self.language]
        at_end = bool(self.samples) and not self.is_playing and self.position >= self.times[-1]
        text = t["pause"] if self.is_playing else (t["replay"] if at_end else t["play"])
        self.play_btn.configure(text=text, image=icons.icon("pause" if self.is_playing else "play", T.WHITE, T.ui(14)))

    def set_sessions_open(self, opened):
        opened = bool(opened)
        if opened == self.sessions_open:
            return
        self.sessions_open = opened
        u = T.ui
        if opened:
            self.sessions_title.pack(side="left", padx=(u(6), u(4)))
            self.files.grid(row=1, column=0, sticky="nsew", padx=u(4), pady=(0, u(6)))
        else:
            self.sessions_title.pack_forget()
            self.files.grid_remove()
        self.drawer_btn.configure(image=icons.icon("collapse" if opened else "recordings",
                                                   T.MUTED if opened else T.INK, u(20)))

    def toggle_sessions(self):
        self.set_sessions_open(not self.sessions_open)

    def _pick(self, path):
        self.load_data(path)
        if self.samples and self.current_name == Path(path).name:
            self.set_sessions_open(False)

    def on_show(self):
        u = T.ui
        if not self.current_name:
            self.set_sessions_open(True)
        for child in self.files.winfo_children(): child.destroy()
        self._file_buttons = {}
        files = sorted(self.dataset_dir.glob("*.csv"), reverse=True)   # newest first
        files = [p for p in files if p.name != "temp_recording.csv"]
        if not files:
            T.label(self.files, COPY[self.language]["empty"], u(12), text_color=T.MUTED,
                    wraplength=u(170), justify="left").pack(anchor="w", padx=u(6), pady=u(12))
        for path in files:
            mark = SYNC_MARKS.get(sync_state(path.name), "")
            button = ctk.CTkButton(self.files, text=path.name + mark, anchor="w", height=u(36), corner_radius=u(6),
                                   font=T.font(u(12)), fg_color="transparent", text_color=T.INK,
                                   hover_color=T.SUBTLE, image=icons.icon("recordings", T.MUTED, u(16)),
                                   compound="left", command=lambda p=path: self._pick(p))
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
        self._disarm_delete()
        self._disarm_upload()
        self._paint_play()
        self._highlight()
        self._publish_state()
        self._render(0)

    # ─── Playback primitives (Tk thread; also driven by phone "pb" commands) ──
    # The recording goes to the LEDs as a WaveformClip through the engine's single DAC writer, which stops
    # whatever Classic was sending. When the DACs are missing (or a Classic CSV recording is running) it plays on
    # screen only and says why.
    def _owns_output(self):
        return self._clip is not None and self.engine.current_clip is self._clip and self.engine.is_running

    def _start_output(self, position):
        t = COPY[self.language]
        self._clip = None
        try:
            clip = WaveformClip.from_recording(self.samples, self.current_name, position)
            self.engine.start_waveform(clip)
        except (ValueError, RuntimeError) as exc:
            log.warning(f"[Playback] {self.current_name} not sent to the LEDs: {exc}")
            self.status.configure(text=t["screen_only"].format(why=exc), text_color=T.WARN)
            return
        self._clip, self._clip_offset = clip, position
        self.status.configure(text=t["leds"].format(name=self.current_name), text_color=T.OK)

    def play(self):
        if self.is_playing or not self.samples:
            return
        if self.position >= self.times[-1]: self.position = 0.0
        if not (self._owns_output() and self.engine.resume_simulation()):
            self._start_output(self.position)
        self._origin = time.monotonic() - self.position
        self.is_playing = True
        self._paint_play()
        self._publish_state()

    def pause_playback(self):
        if self.samples and self.is_playing:
            if self._owns_output():
                self.engine.pause_simulation()          # the LEDs hold the last level until Play or Stop
                self.position = self._output_position()
            else:
                self.position = min(self.times[-1], time.monotonic() - self._origin)
            self.is_playing = False
            self._paint_play()
        self._publish_state()

    def resume_playback(self):
        self.play()

    def _release_output(self):
        if self._owns_output():
            self.engine.stop_simulation()
        self._clip = None

    def stop_playback(self):
        self._release_output()
        self.is_playing = False
        self.position = 0.0
        if self.samples:
            self._paint_play()
            self._render(0)
        self._publish_state()

    def _output_position(self):
        return min(self.times[-1], self._clip_offset + self.engine.waveform_position_s)

    # ─── Database upload, only for the file the user picks (two taps) ───────
    def _upload_state(self):
        """(label key, enabled, colour) of the upload button for the selected file."""
        if not self.current_name:
            return "upload", False, T.INK
        if not sync_available():
            return "no_db", False, T.MUTED
        state = sync_state(self.current_name)
        if state == "synced":
            return "in_db", False, T.OK
        if state == "pending":
            return "uploading", False, T.MUTED
        if state == "error":
            return "upload_failed", False, T.ERROR      # approved already: the sync thread keeps retrying it
        if self._upload_armed is not None:
            return "upload_confirm", True, T.ACCENT
        return "upload", True, T.INK

    def _paint_upload(self):
        shown = self._upload_state()
        if shown == self._upload_shown:
            return
        self._upload_shown = shown
        key, enabled, color = shown
        self.upload_btn.configure(text=COPY[self.language][key], state="normal" if enabled else "disabled",
                                  text_color=color)

    def _disarm_upload(self):
        if self._upload_armed is not None:
            self.after_cancel(self._upload_armed)
            self._upload_armed = None
        self._paint_upload()

    def upload_selected(self):
        if not self.current_name:
            return
        if self._upload_armed is None:
            self._upload_armed = self.after(4000, self._disarm_upload)
            self._paint_upload()
            return
        self._disarm_upload()
        self.request_upload(self.current_name)

    def request_upload(self, name):
        """Consent for one recording to go to the database (comm/record_sync.py); the phone asks the same way."""
        from comm import record_sync
        sync = record_sync.current()
        name = Path(str(name)).name
        if sync is None or name not in self._recording_names() or not sync.request_upload(name):
            return False
        self.status.configure(text=COPY[self.language]["upload_requested"].format(name=name), text_color=T.MUTED)
        self.on_show()
        self._paint_upload()
        return True

    # ─── Deleting a recording (two taps: the button asks once) ───────────────
    def _paint_delete(self):
        t = COPY[self.language]
        armed = self._delete_armed is not None
        self.delete_btn.configure(text=t["confirm"] if armed else t["delete"],
                                  state="normal" if self.current_name else "disabled",
                                  text_color=T.ERROR if armed else T.INK)

    def _disarm_delete(self):
        if self._delete_armed is not None:
            self.after_cancel(self._delete_armed)
            self._delete_armed = None
        self._paint_delete()

    def delete_selected(self):
        if not self.current_name:
            return
        if self._delete_armed is None:
            self._delete_armed = self.after(4000, self._disarm_delete)
            self._paint_delete()
            return
        self._disarm_delete()
        self.delete_recording(self.current_name)

    def delete_recording(self, name):
        """Remove one saved recording from dataset/ (its database copy, if any, stays on the server)."""
        t = COPY[self.language]
        name = Path(str(name)).name
        path = self.dataset_dir / name
        if not name.lower().endswith(".csv") or name == "temp_recording.csv" or not path.is_file():
            return False
        if name == self.current_name:
            self._release_output()
            self.is_playing, self.position = False, 0.0
        try:
            path.unlink()
        except OSError as exc:
            self.status.configure(text=t["delete_failed"].format(name=name, why=exc), text_color=T.ERROR)
            return False
        log.info(f"[Playback] deleted recording {name}")
        if name == self.current_name:
            self.samples, self.parameters, self.times = [], [], []
            self.current_name, self._timing = "", ""
            self.title_label.configure(text=t["select"])
            self.info.configure(text="")
            self.play_btn.configure(state="disabled")
            self.trace.update_samples([])
            for label, _unit in self.metric_values.values():
                label.configure(text="—")
            self._paint_play()
        self._names_cache = None
        self.on_show()
        self._paint_delete()
        self.status.configure(text=t["deleted"].format(name=name), text_color=T.MUTED)
        self._publish_state()
        return True

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
            if value is None:
                text = "—"
            elif isinstance(value, str):
                text = (condition_labels(self.language)[CONDITION_NAMES.index(value)]
                        if value in CONDITION_NAMES else value)
            else:
                text = f"{value:g} {unit}"
            if label.cget("text") != text:
                label.configure(text=text)

    # ─── BLE protocol v3 (ui/remote.py) ──────────────────────────────────────
    def _recording_names(self):
        now = time.monotonic()
        cached = getattr(self, "_names_cache", None)
        if cached is None or now - cached[0] > 2.0:
            files = sorted(self.dataset_dir.glob("*.csv"), reverse=True)
            cached = (now, [p.name for p in files if p.name != "temp_recording.csv"])
            self._names_cache = cached
        return cached[1]

    def remote_parts(self):
        from comm.ble_remote import UI_PART_MAX_BYTES
        names = self._recording_names()
        chunks, chunk, size = [], [], 40
        for name in names[:60]:
            if chunk and size + len(name) + 3 > UI_PART_MAX_BYTES:
                chunks.append(chunk)
                chunk, size = [], 40
            chunk.append(name)
            size += len(name) + 3
        chunks.append(chunk)
        parts = [(f"ls{i}", {"k": "ls", "c": i, "m": len(chunks), "f": c}) for i, c in enumerate(chunks)]
        # Database copy of each listed file, one letter per name in list order: s synced, p pending, e error.
        parts.append(("sy", {"k": "sy", "s": "".join(SYNC_CODES.get(sync_state(n), "-") for n in names[:60])}))
        # Phone apps read "m" as [hr, spo2, rr, pi, condition] by index and skip index 3: keep it there, empty.
        metrics = [label.cget("text") for label, _unit in self.metric_values.values()]
        metrics.insert(3, "")
        duration = self.times[-1] if self.samples else 0.0
        parts.append(("rec", {"sel": self.current_name or "", "play": bool(self.is_playing),
                              "pos": round(float(self.position), 2), "dur": round(float(duration), 2),
                              "m": metrics, "i": self.info.cget("text") if self.samples else "",
                              "db": bool(sync_available())}))
        return parts

    def remote_apply(self, request):
        """Phone request: load (select) a recording; play/pause/stop arrive as protocol v2 "pb"."""
        name = request.get("sel")
        if isinstance(name, str):
            name = Path(name).name
            if name and name in self._recording_names():
                self._pick(self.dataset_dir / name)
        upload = request.get("up")          # the phone confirmed on its side
        if isinstance(upload, str) and upload:
            self.request_upload(upload)

    def remote_tx_rows(self):
        """The last second of the recording up to the playback position, (t, IR mV, RED mV); [] unless playing."""
        if not self.is_playing or not self.samples:
            return []
        idx = max(0, bisect.bisect_right(self.times, self.position) - 1)
        return [(t, ir * 1000.0, red * 1000.0) for t, ir, red in self.samples[max(0, idx - 100):idx + 1]]

    def periodic_update(self):
        self.rx_panel.periodic_update()
        self._paint_upload()
        if not self.is_playing: return
        ended = False
        if self._clip is None:
            self.position = min(self.times[-1], time.monotonic() - self._origin)     # screen only
        elif self.engine.current_clip is self._clip:
            self.position = self._output_position()     # follows what the DACs really sent
            ended = not self.engine.is_running          # the clip ran out, or Stop from the phone
        else:
            self._clip = None                           # Classic (or another page) started its own output
            self.is_playing = False
            self.status.configure(text=COPY[self.language]["taken"], text_color=T.WARN)
            self._paint_play()
            self._publish_state()
            return
        idx = max(0, bisect.bisect_right(self.times, self.position)-1)
        self._render(idx)
        if ended or self.position >= self.times[-1]:
            if ended:
                self._clip = None
                self.status.configure(text=COPY[self.language]["finished"].format(name=self.current_name),
                                      text_color=T.MUTED)
                if self.position < self.times[-1] - 0.05:
                    self.position = 0.0
            self.is_playing = False
            self._paint_play()
            self._publish_state()
