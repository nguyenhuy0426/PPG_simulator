import time
import tkinter as tk
import customtkinter as ctk
from comm.logger import log
from config import DRY_RUN, FIRMWARE_VERSION
from core.signal_engine import SignalEngine
from ui import theme as T
from ui.frames.pathology_frame import PathologyFrame
from ui.frames.calibration_frame import CalibrationFrame
from ui.frames.playback_frame import PlaybackFrame
from ui.frames.advanced_frame import AdvancedFrame
from ui.responsive import profile_for_screen


class CTkApp(ctk.CTk):
    def __init__(self):
        T.install()
        super().__init__()
        self.layout = profile_for_screen(self.winfo_screenwidth(), self.winfo_screenheight())
        # CustomTkinter does not automatically scale widgets on Linux.  Scale
        # from the actual desktop resolution so 1024x600 touch panels stay
        # usable and Full-HD/QHD displays do not render tiny controls.
        ctk.set_widget_scaling(self.layout.widget_scale)
        self.title("PPG Simulator • Optical signal workstation")
        self.geometry(self.layout.geometry)
        self.minsize(*self.layout.minimum_size)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        # Recording is engine-owned (one CSVLogger shared by GUI, BLE and the
        # status echo); the engine creates it lazily on the first start.
        self.engine = SignalEngine.get_instance()
        self._closing = False
        header = ctk.CTkFrame(self, fg_color=T.DARK, corner_radius=0,
                              height=58 if self.layout.compact else 66)
        header.grid(row=0, column=0, sticky="ew")
        header_pad = 14 if self.layout.compact else 24
        T.label(header, "PPG", 24 if self.layout.compact else 27, True,
                text_color="white").pack(side="left", padx=(header_pad, 12), pady=10)
        if not self.layout.compact:
            T.label(header, "OPTICAL SIGNAL WORKSTATION", 13, True,
                    text_color="#C8D2D9").pack(side="left")
        self.mode_label = T.label(header, "SIMULATION / NO HARDWARE" if DRY_RUN else "HARDWARE MODE",
                                  12, True, text_color=T.IR)
        self.mode_label.pack(side="right", padx=header_pad)
        nav = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=0)
        nav.grid(row=1, column=0, sticky="ew")
        self.nav_buttons = {}
        for key, title in (("Pathology", "01   Monitor"),
                           ("Calibration", "02   Calibration / RX"),
                           ("Playback", "03   Recordings")):
            btn = ctk.CTkButton(nav, text=title, width=self.layout.nav_width, height=40, corner_radius=0,
                                command=lambda k=key: self._show_frame(k))
            btn.pack(side="left", padx=(8 if self.layout.compact else 12, 0),
                     pady=6 if self.layout.compact else 8)
            self.nav_buttons[key] = btn
        self.frames = {
            "Pathology": PathologyFrame(self, fg_color="transparent"),
            "Calibration": CalibrationFrame(self, fg_color="transparent"),
            "Playback": PlaybackFrame(self, fg_color="transparent"),
        }
        self.signal_setup_window = None
        self.signal_setup_panel = None
        bubble_size = 44 if self.layout.compact else 50
        self.signal_setup_bubble = ctk.CTkButton(
            nav, text="⚙", width=bubble_size, height=bubble_size,
            corner_radius=bubble_size // 2, fg_color=T.ACCENT,
            hover_color=T.HOVER, border_width=2, border_color=T.BG,
            font=ctk.CTkFont(family="DejaVu Sans", size=19, weight="bold"),
            command=self.toggle_signal_setup)
        self.signal_setup_bubble.pack(side="right", padx=14 if self.layout.compact else 22,
                                      pady=4 if self.layout.compact else 6)
        footer = ctk.CTkFrame(self, corner_radius=0, fg_color=T.PANEL)
        footer.grid(row=3, column=0, sticky="ew")
        self.status_label = T.label(footer, "Ready", 11, text_color=T.MUTED)
        self.status_label.pack(side="left", padx=20, pady=4)
        if not self.layout.compact:
            T.label(footer, f"Research simulator   •   v{FIRMWARE_VERSION}", 11,
                    text_color=T.MUTED).pack(side="right", padx=20)
        self.active_frame = None
        self._show_frame("Pathology")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        # Ask the window manager for the usable desktop area (excluding the
        # GNOME top bar).  The geometry above remains the fallback for minimal
        # window managers and Xvfb.
        self.after_idle(self._maximize_to_work_area)
        self._after_id = self.after(50, self.update_gui)

    def _maximize_to_work_area(self):
        try:
            self.attributes("-zoomed", True)
        except tk.TclError:
            self.geometry(self.layout.geometry)

    def _show_frame(self, name):
        if self.active_frame is self.frames[name]:
            return
        if self.active_frame is not None:
            if hasattr(self.active_frame, "on_hide"):
                self.active_frame.on_hide()
            self.active_frame.grid_forget()
        self.active_frame = self.frames[name]
        self.active_frame.grid(row=2, column=0, sticky="nsew",
                               padx=self.layout.outer_pad, pady=self.layout.outer_pady)
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
        self.open_signal_setup()

    def open_signal_setup(self):
        """Open the former Signal Setup page as a non-modal floating editor."""
        window = self.signal_setup_window
        if window is not None and window.winfo_exists():
            window.deiconify()
            window.lift()
            window.focus_set()
            return

        width, height = self.layout.setup_popup_size
        self.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - width) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - height) // 2)
        window = ctk.CTkToplevel(self)
        window.title("Signal setup")
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.minsize(min(620, width), min(380, height))
        window.configure(fg_color=T.BG)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(0, weight=1)
        window.transient(self)
        window.protocol("WM_DELETE_WINDOW", self.close_signal_setup)
        window.bind("<Escape>", lambda _event: self.close_signal_setup())
        panel = AdvancedFrame(window, fg_color="transparent")
        panel.grid(row=0, column=0, sticky="nsew",
                   padx=self.layout.outer_pad, pady=self.layout.outer_pady)
        self.signal_setup_window = window
        self.signal_setup_panel = panel
        self.signal_setup_bubble.configure(text="×", fg_color=T.ERROR)
        panel.on_show()
        window.after_idle(window.lift)

    def close_signal_setup(self):
        window = self.signal_setup_window
        if window is not None and window.winfo_exists():
            window.destroy()
        self.signal_setup_window = None
        self.signal_setup_panel = None
        self.signal_setup_bubble.configure(text="⚙", fg_color=T.ACCENT)

    def toggle_signal_setup(self):
        window = self.signal_setup_window
        if window is not None and window.winfo_exists():
            self.close_signal_setup()
        else:
            self.open_signal_setup()

    def update_gui(self):
        if self._closing:
            return
        monitor = self.frames["Pathology"]
        monitor.record_tick()
        # Phone-issued playback commands (protocol v2 "pb") are queued on the
        # engine by the bless thread and applied here on the Tk thread, even
        # while the Playback tab is hidden.
        request = self.engine.take_playback_request()
        if request is not None:
            self.frames["Playback"].handle_playback_request(*request)
        # BLE can mutate engine state while any tab is visible. Refresh every
        # frame, not only the active one, so returning to a tab never appears
        # to be the moment the command was received. This also advances a
        # phone-selected playback while the Pi is on another tab.
        for frame in self.frames.values():
            if hasattr(frame, "periodic_update"):
                frame.periodic_update()
        if self.signal_setup_panel is not None:
            self.signal_setup_panel.periodic_update()
        stats = self.engine.get_stats()
        if not DRY_RUN:
            dac = self.engine.dac_manager
            self.mode_label.configure(text="TX DAC READY" if dac.is_ready else "TX DAC UNAVAILABLE",
                                      text_color=T.IR if dac.is_ready else T.RED)

        running = "RUNNING" if self.engine._running else "STANDBY"
        if self.layout.compact:
            status = (f"{running}  •  Buffer {stats['buffer_fill']}  •  "
                      f"Lost {stats['dropped_samples']}  •  "
                      f"Clip {stats['clipped_samples']}  •  {time.strftime('%H:%M:%S')}")
        else:
            status = (f"{running}  /  TX model 100 Hz → DAC target 1 kHz   |   "
                      f"Buffer {stats['buffer_fill']}   Lost {stats['dropped_samples']}   "
                      f"Clipped {stats['clipped_samples']}   |   {time.strftime('%H:%M:%S')}")
        self.status_label.configure(text=status)
        self._after_id = self.after(40, self.update_gui)

    def on_closing(self):
        log.info("[CTkApp] Closing window")
        self._closing = True
        if hasattr(self, "_after_id"):
            self.after_cancel(self._after_id)
        if hasattr(self, "engine"):
            if getattr(self.engine, "recording", False):
                self.engine.stop_recording()
            self.engine.stop_simulation()
        if self.signal_setup_window is not None:
            self.close_signal_setup()
        self.destroy()
