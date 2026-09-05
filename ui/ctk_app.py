import time
import customtkinter as ctk
from comm.logger import log
from config import DRY_RUN, FIRMWARE_VERSION
from core.signal_engine import SignalEngine
from core.csv_logger import CSVLogger
from ui import theme as T
from ui.frames.pathology_frame import PathologyFrame
from ui.frames.calibration_frame import CalibrationFrame
from ui.frames.playback_frame import PlaybackFrame
from ui.frames.advanced_frame import AdvancedFrame


class CTkApp(ctk.CTk):
    def __init__(self):
        T.install()
        super().__init__()
        self.title("PPG Simulator • Optical signal workstation")
        self.geometry("1280x800")
        self.minsize(1024, 600)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.csv_logger = CSVLogger()
        self.engine = SignalEngine.get_instance()
        self._closing = False
        header = ctk.CTkFrame(self, fg_color=T.DARK, corner_radius=0, height=66)
        header.grid(row=0, column=0, sticky="ew")
        T.label(header, "PPG", 27, True, text_color="white").pack(side="left", padx=(24, 14), pady=12)
        T.label(header, "OPTICAL SIGNAL WORKSTATION", 13, True, text_color="#C8D2D9").pack(side="left")
        self.mode_label = T.label(header, "SIMULATION / NO HARDWARE" if DRY_RUN else "HARDWARE MODE",
                                  12, True, text_color=T.IR)
        self.mode_label.pack(side="right", padx=24)
        nav = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=0)
        nav.grid(row=1, column=0, sticky="ew")
        self.nav_buttons = {}
        for key, title in (("Pathology", "01   Monitor"), ("Advanced", "02   Signal setup"),
                           ("Calibration", "03   Calibration / RX"), ("Playback", "04   Recordings")):
            btn = ctk.CTkButton(nav, text=title, width=190, height=40, corner_radius=0,
                                command=lambda k=key: self._show_frame(k))
            btn.pack(side="left", padx=(12, 0), pady=8)
            self.nav_buttons[key] = btn
        self.frames = {
            "Pathology": PathologyFrame(self, fg_color="transparent"),
            "Advanced": AdvancedFrame(self, fg_color="transparent"),
            "Calibration": CalibrationFrame(self, fg_color="transparent"),
            "Playback": PlaybackFrame(self, fg_color="transparent"),
        }
        footer = ctk.CTkFrame(self, corner_radius=0, fg_color=T.PANEL)
        footer.grid(row=3, column=0, sticky="ew")
        self.status_label = T.label(footer, "Ready", 11, text_color=T.MUTED)
        self.status_label.pack(side="left", padx=20, pady=4)
        T.label(footer, f"Research simulator   •   v{FIRMWARE_VERSION}", 11,
                text_color=T.MUTED).pack(side="right", padx=20)
        self.active_frame = None
        self._show_frame("Pathology")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._after_id = self.after(50, self.update_gui)

    def _show_frame(self, name):
        if self.active_frame is self.frames[name]:
            return
        if self.active_frame is not None:
            if hasattr(self.active_frame, "on_hide"):
                self.active_frame.on_hide()
            self.active_frame.grid_forget()
        self.active_frame = self.frames[name]
        self.active_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=12)
        for key, button in self.nav_buttons.items():
            button.configure(fg_color=T.INK if key == name else T.PANEL,
                             text_color=T.PANEL if key == name else T.MUTED,
                             hover_color=T.ACCENT if key == name else T.BG)
        if hasattr(self.active_frame, "on_show"):
            self.active_frame.on_show()

    def select_pathology(self):
        self._show_frame("Pathology")

    def select_calibration(self):
        self._show_frame("Calibration")

    def select_playback(self):
        self._show_frame("Playback")

    def select_advanced(self):
        self._show_frame("Advanced")

    def update_gui(self):
        if self._closing:
            return
        if hasattr(self.active_frame, "periodic_update"):
            self.active_frame.periodic_update()
        monitor = self.frames["Pathology"]
        monitor.record_tick()
        stats = self.engine.get_stats()
        if not DRY_RUN:
            dac = self.engine.dac_manager
            self.mode_label.configure(text="TX DAC READY" if dac.is_ready else "TX DAC UNAVAILABLE",
                                      text_color=T.IR if dac.is_ready else T.RED)

        running = "RUNNING" if self.engine._running else "STANDBY"
        self.status_label.configure(text=(f"{running}  /  TX model 100 Hz → DAC target 1 kHz   |   "
            f"Buffer {stats['buffer_fill']}   Lost {stats['dropped_samples']}   "
            f"Clipped {stats['clipped_samples']}   |   {time.strftime('%H:%M:%S')}"))
        self._after_id = self.after(40, self.update_gui)

    def on_closing(self):
        log.info("[CTkApp] Closing window")
        self._closing = True
        if hasattr(self, "_after_id"):
            self.after_cancel(self._after_id)
        if hasattr(self, "csv_logger") and self.csv_logger.is_logging:
            self.engine.set_recording(False)
            self.frames["Pathology"].record_tick()
            self.csv_logger.stop(save=True)
        if hasattr(self, "engine"):
            self.engine.stop_simulation()
        self.destroy()
