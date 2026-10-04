import time
import tkinter as tk
import customtkinter as ctk
from comm.logger import log
from config import DRY_RUN, FIRMWARE_VERSION, FS_TIMER_HZ, MODEL_SAMPLE_RATE_PPG
from core.signal_engine import SignalEngine
from ui import icons
from ui import theme as T
from ui.frames.pathology_frame import PathologyFrame
from ui.frames.calibration_frame import CalibrationFrame
from ui.frames.playback_frame import PlaybackFrame
from ui.frames.advanced_frame import AdvancedFrame
from ui.frames.neural_frame import NeuralFrame
from ui.responsive import profile_for_screen
from ui.i18n import LANGUAGES, normalise_language, text
from ui.rx_monitor import RXMonitor


class NavTab(ctk.CTkFrame):
    """Underlined page tab: muted index, label, accent bar when active."""

    def __init__(self, master, index, label, command, ui=round):
        super().__init__(master, fg_color="transparent", corner_radius=0)
        self.command, self.active = command, False
        self.bar = ctk.CTkFrame(self, height=ui(3), corner_radius=0, fg_color=T.PANEL)
        self.bar.pack(side="bottom", fill="x")
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(expand=True, padx=ui(8))
        self.index = T.label(row, index, ui(11), text_color=T.FAINT)
        self.index.pack(side="left", padx=(0, ui(6)))
        self.text = T.label(row, label, ui(14), text_color=T.MUTED)
        self.text.pack(side="left")
        for widget in (self, row, self.index, self.text):
            widget.bind("<Button-1>", lambda _event: self.command())
            widget.bind("<Enter>", lambda _event: self._hover(True))
            widget.bind("<Leave>", lambda _event: self._hover(False))
        for label_widget in (self.index, self.text):
            label_widget.configure(cursor="hand2")

    def _hover(self, inside):
        if not self.active:
            self.text.configure(text_color=T.INK if inside else T.MUTED)

    def set_active(self, active):
        self.active = active
        self.text.configure(text_color=T.INK, font=T.font(self.text.cget("font").cget("size"), active))
        if not active:
            self.text.configure(text_color=T.MUTED)
        self.bar.configure(fg_color=T.ACCENT if active else T.PANEL)
        self.index.configure(text_color=T.ACCENT if active else T.FAINT)

    def set_text(self, label):
        self.text.configure(text=label)

    def invoke(self):
        self.command()


class CTkApp(ctk.CTk):
    def __init__(self, language="en"):
        T.install()
        # Match packaging/linux/ppg-simulator.desktop.in so GNOME associates
        # the running Tk window with the dashboard icon that launched it.
        super().__init__(className="PPGSimulator")
        self.layout = profile_for_screen(self.winfo_screenwidth(), self.winfo_screenheight())
        # CustomTkinter does not automatically scale widgets on Linux.  Scale
        # from the actual desktop resolution so 1024x600 touch panels stay
        # usable and Full-HD/QHD displays do not render tiny controls.
        ctk.set_widget_scaling(self.layout.widget_scale)
        self.language = normalise_language(language)
        self.title(text(self.language, "title"))
        self.geometry(self.layout.geometry)
        self.minsize(*self.layout.minimum_size)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        # Recording is engine-owned (one CSVLogger shared by GUI, BLE and the
        # status echo); the engine creates it lazily on the first start.
        self.engine = SignalEngine.get_instance()
        self._closing = False
        self._shutdown_requested = False
        compact = self.layout.compact
        u = self.layout.ui
        # ── Header: brand, page tabs, settings ──
        header = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=0, height=u(50))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(2, weight=1)
        header.grid_rowconfigure(0, weight=1)
        ctk.CTkFrame(self, fg_color=T.LINE, corner_radius=0, height=T.hairline()).grid(row=0, column=0, sticky="sew")
        header_pad = u(14)
        T.label(header, "PPG", u(21), True).grid(row=0, column=0, padx=(header_pad, u(16)))
        tabs = ctk.CTkFrame(header, fg_color="transparent")
        tabs.grid(row=0, column=1, sticky="nsw")
        self.nav_buttons = {}
        self.nav_keys = (("Pathology", "classic"), ("Calibration", "calibration"),
                         ("Playback", "recordings"), ("Neural", "neural"))
        for index, (key, text_key) in enumerate(self.nav_keys, start=1):
            tab = NavTab(tabs, f"{index:02d}", text(self.language, text_key),
                         command=lambda k=key: self._show_frame(k), ui=u)
            tab.pack(side="left", fill="y", padx=(0, u(6)))
            self.nav_buttons[key] = tab
        self.signal_setup_bubble = T.outline_button(
            header, text(self.language, "settings_short"), height=u(36), width=u(116),
            image=icons.icon("sliders", T.INK, u(16)), compound="left", font=T.font(u(13), True),
            command=self.toggle_signal_setup)
        self.signal_setup_bubble.grid(row=0, column=3, padx=header_pad)

        # ── Page area ──
        # Compact panels scroll long pages while the header, RX dock and footer
        # stay fixed. The Classic page is laid out to fit 1024x600 without
        # scrolling, so it lives in a plain host that stretches its plots.
        self.page_host = ctk.CTkScrollableFrame(self, fg_color="transparent") if compact else ctk.CTkFrame(self, fg_color="transparent")
        self.page_host.grid(row=2, column=0, sticky="nsew")
        self.page_host.grid_columnconfigure(0, weight=1)
        if compact:
            self.page_host._scrollbar.configure(width=28)
            self.fixed_host = ctk.CTkFrame(self, fg_color="transparent")
            self.fixed_host.grid_columnconfigure(0, weight=1)
            self.fixed_host.grid_rowconfigure(0, weight=1)
        else:
            self.page_host.grid_rowconfigure(0, weight=1)
            self.fixed_host = self.page_host
        for host in {self.page_host, self.fixed_host}:
            host.layout = self.layout
            host.language = self.language
        self.frames = {
            "Pathology": PathologyFrame(self.fixed_host, fg_color="transparent"),
            "Calibration": CalibrationFrame(self.page_host, fg_color="transparent"),
            "Playback": PlaybackFrame(self.page_host, fg_color="transparent"),
            "Neural": NeuralFrame(self.page_host, fg_color="transparent"),
        }
        for host in {self.page_host, self.fixed_host}:
            host.frames = self.frames
        self.signal_setup_window = None
        self.signal_setup_panel = None
        # The persistent RX dock serves every page except Classic, which has
        # its own RX card next to the TX plot.
        self.rx_monitor = RXMonitor(self, language=self.language)
        self.rx_monitor.grid(row=3, column=0, sticky="ew", padx=self.layout.outer_pad)

        # ── Footer: output health and build ──
        footer = ctk.CTkFrame(self, corner_radius=0, fg_color=T.PANEL)
        footer.grid(row=4, column=0, sticky="ew")
        ctk.CTkFrame(self, fg_color=T.LINE, corner_radius=0, height=T.hairline()).grid(row=4, column=0, sticky="new")
        self.mode_label = T.label(footer, "", u(11), True, corner_radius=u(4), height=u(18))
        self.mode_label.pack(side="left", padx=(header_pad - u(4), u(12)), pady=u(4))
        self.footer_values = {}
        for key in ("tx_model", "dac_target", "buffer", "lost", "clipped"):
            name = T.label(footer, text(self.language, key), u(12), text_color=T.MUTED)
            name.pack(side="left", padx=(0, u(4)))
            value = T.label(footer, "", u(12), True)
            value.pack(side="left", padx=(0, u(14)))
            self.footer_values[key] = (name, value)
        self.footer_values["tx_model"][1].configure(text=f"{MODEL_SAMPLE_RATE_PPG} Hz")
        self.footer_values["dac_target"][1].configure(text=f"{FS_TIMER_HZ} Hz")
        self.clock_label = T.label(footer, "", u(12), True)
        self.clock_label.pack(side="right", padx=(0, header_pad))
        T.label(footer, f"v{FIRMWARE_VERSION}", u(12), text_color=T.MUTED).pack(side="right", padx=(0, u(14)))
        self.research_label = T.label(footer, text(self.language, "research"), u(12), text_color=T.MUTED)
        self.research_label.pack(side="right", padx=(0, u(14)))
        self._mode_shown = None
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
        self.active_frame.grid(row=0, column=0, sticky="nsew",
                               padx=self.layout.outer_pad, pady=self.layout.outer_pady)
        host = self.active_frame.master
        if host is not self.page_host:
            self.page_host.grid_remove()
            host.grid(row=2, column=0, sticky="nsew")
        else:
            if self.fixed_host is not self.page_host:
                self.fixed_host.grid_remove()
            self.page_host.grid()
        if self.layout.compact and host is self.page_host:
            self.page_host._parent_canvas.yview_moveto(0)
        if name == "Pathology":
            self.rx_monitor.grid_remove()
        else:
            self.rx_monitor.grid()
        for key, tab in self.nav_buttons.items():
            tab.set_active(key == name)
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
        window.title(text(self.language, "settings"))
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.minsize(min(620, width), min(380, height))
        window.configure(fg_color=T.BG)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(1, weight=1)
        window.transient(self)
        window.protocol("WM_DELETE_WINDOW", self.close_signal_setup)
        window.bind("<Escape>", lambda _event: self.close_signal_setup())
        language_bar = ctk.CTkFrame(window, fg_color=T.PANEL)
        language_bar.grid(row=0, column=0, sticky="ew", padx=self.layout.outer_pad, pady=(self.layout.outer_pady, 0))
        language_bar.grid_columnconfigure(2, weight=1)
        self.language_label = T.label(language_bar, text(self.language, "language"), 12, True)
        self.language_label.grid(row=0, column=0, padx=(12, 8), pady=8)
        self.language_menu = ctk.CTkOptionMenu(language_bar, values=list(LANGUAGES.values()), width=125,
                                                command=self._set_language_from_label)
        self.language_menu.set(LANGUAGES[self.language])
        self.language_menu.grid(row=0, column=1, padx=(0, 10), pady=8)
        self.language_hint = T.label(language_bar, text(self.language, "language_hint"), 10, text_color=T.MUTED, anchor="w")
        self.language_hint.grid(row=0, column=2, sticky="ew", padx=(0, 12), pady=8)
        panel = AdvancedFrame(window, fg_color="transparent")
        panel.grid(row=1, column=0, sticky="nsew",
                   padx=self.layout.outer_pad, pady=self.layout.outer_pady)
        self.signal_setup_window = window
        self.signal_setup_panel = panel
        self.settings_rx_monitor = RXMonitor(window, language=self.language)
        self.settings_rx_monitor.grid(row=2, column=0, sticky="ew", padx=self.layout.outer_pad)
        self.signal_setup_bubble.configure(fg_color=T.SUBTLE, border_color=T.ACCENT)
        panel.on_show()
        window.after_idle(window.lift)

    def _set_language_from_label(self, label):
        code = next((key for key, value in LANGUAGES.items() if value == label), "en")
        self.set_language(code)

    def set_language(self, language):
        """Apply and persist a shell language without touching signal parameters."""
        language = normalise_language(language)
        if language == self.language:
            return
        self.language = language
        self.title(text(language, "title"))
        for host in {self.page_host, self.fixed_host}:
            host.language = language
        for key, text_key in self.nav_keys:
            self.nav_buttons[key].set_text(text(language, text_key))
        self.signal_setup_bubble.configure(text=text(language, "settings_short"))
        for key, (name, _value) in self.footer_values.items():
            name.configure(text=text(language, key))
        self.research_label.configure(text=text(language, "research"))
        self._mode_shown = None
        self.frames["Neural"].set_language(language)
        self.frames["Pathology"].set_language(language)
        self.rx_monitor.set_language(language)
        window = self.signal_setup_window
        if window is not None and window.winfo_exists():
            self.settings_rx_monitor.set_language(language)
            window.title(text(language, "settings"))
            self.language_label.configure(text=text(language, "language"))
            self.language_menu.set(LANGUAGES[language])
            self.language_hint.configure(text=text(language, "language_hint"))
            self.signal_setup_panel.status.configure(text=text(language, "language_applied"), text_color=T.ACCENT)
        self._save_language()

    def _save_language(self):
        try:
            from config_store import load_config, save_config
            config = load_config()
            config["language"] = self.language
            save_config(config)
        except OSError:
            log.exception("Could not save UI language")

    def close_signal_setup(self):
        window = self.signal_setup_window
        if window is not None and window.winfo_exists():
            window.destroy()
        self.signal_setup_window = None
        self.signal_setup_panel = None
        self.signal_setup_bubble.configure(fg_color=T.PANEL, border_color=T.LINE)

    def toggle_signal_setup(self):
        window = self.signal_setup_window
        if window is not None and window.winfo_exists():
            self.close_signal_setup()
        else:
            self.open_signal_setup()

    def update_gui(self):
        if self._shutdown_requested:
            self.on_closing()
            return
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
            self.settings_rx_monitor.periodic_update()
        self.rx_monitor.periodic_update()
        stats = self.engine.get_stats()
        self._paint_mode()
        values = (("buffer", stats["buffer_fill"]), ("lost", stats["dropped_samples"]),
                  ("clipped", stats["clipped_samples"]))
        for key, value in values:
            label = self.footer_values[key][1]
            if label.cget("text") != str(value):
                label.configure(text=str(value), text_color=T.ERROR if key != "buffer" and value else T.INK)
        clock = time.strftime("%H:%M:%S")
        if self.clock_label.cget("text") != clock:
            self.clock_label.configure(text=clock)
        self._after_id = self.after(40, self.update_gui)

    def _paint_mode(self):
        """Footer chip: what the TX side is physically connected to."""
        if DRY_RUN:
            mode = ("mode_dry_run", T.WARN_INK, T.WARN_BG)
        elif self.engine.dac_manager.is_ready:
            mode = ("mode_hardware", T.OK, T.OK_BG)
        else:
            mode = ("mode_no_dac", T.ERROR, T.ERROR_BG)
        if mode != self._mode_shown:
            self._mode_shown = mode
            key, ink, fill = mode
            self.mode_label.configure(text=f"  {text(self.language, key)}  ", text_color=ink, fg_color=fill)

    def on_closing(self):
        if self._closing:
            return
        log.info("[CTkApp] Closing window")
        self._closing = True
        if hasattr(self, "_after_id"):
            self.after_cancel(self._after_id)
        if hasattr(self, "engine"):
            if getattr(self.engine, "recording", False):
                self.engine.stop_recording()
            self.engine.stop_simulation()
        self.frames["Neural"].shutdown()
        if self.signal_setup_window is not None:
            self.close_signal_setup()
        self.destroy()

    def request_shutdown(self):
        """Ask the Tk event loop to close safely on its next scheduled tick."""
        self._shutdown_requested = True
