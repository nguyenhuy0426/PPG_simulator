import customtkinter as ctk
import os
import sys

from comm.logger import log
from core.signal_engine import SignalEngine
from core.state_machine import StateMachine
from core.csv_logger import CSVLogger

# Import frames
from ui.frames.pathology_frame import PathologyFrame
from ui.frames.calibration_frame import CalibrationFrame
from ui.frames.playback_frame import PlaybackFrame

class CTkApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("PPG Signal Simulator")
        self.geometry("1024x600") # Base resolution, can be resized

        # set grid layout 1x2
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.csv_logger = CSVLogger()

        # create sidebar frame with widgets
        self.sidebar_frame = ctk.CTkFrame(self, width=140, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(4, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="PPG Simulator", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.btn_pathology = ctk.CTkButton(self.sidebar_frame, text="Pathology Mode", command=self.select_pathology)
        self.btn_pathology.grid(row=1, column=0, padx=20, pady=10)

        self.btn_calibration = ctk.CTkButton(self.sidebar_frame, text="Calibration", command=self.select_calibration)
        self.btn_calibration.grid(row=2, column=0, padx=20, pady=10)

        self.btn_playback = ctk.CTkButton(self.sidebar_frame, text="Playback Data", command=self.select_playback)
        self.btn_playback.grid(row=3, column=0, padx=20, pady=10)

        self.appearance_mode_label = ctk.CTkLabel(self.sidebar_frame, text="Appearance Mode:", anchor="w")
        self.appearance_mode_label.grid(row=5, column=0, padx=20, pady=(10, 0))
        self.appearance_mode_optionemenu = ctk.CTkOptionMenu(self.sidebar_frame, values=["Light", "Dark", "System"],
                                                                       command=self.change_appearance_mode_event)
        self.appearance_mode_optionemenu.grid(row=6, column=0, padx=20, pady=(10, 20))

        # create frames
        self.frames = {}
        
        self.frames["Pathology"] = PathologyFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["Calibration"] = CalibrationFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["Playback"] = PlaybackFrame(self, corner_radius=0, fg_color="transparent")

        # default frame
        self.appearance_mode_optionemenu.set("Dark")
        self.change_appearance_mode_event("Dark")
        
        self.active_frame = None
        self.select_pathology()

        # Start periodic GUI updates
        self.after(50, self.update_gui)

    def change_appearance_mode_event(self, new_appearance_mode: str):
        ctk.set_appearance_mode(new_appearance_mode)

    def _show_frame(self, name):
        if self.active_frame is not None:
            self.active_frame.grid_forget()
        
        self.active_frame = self.frames[name]
        self.active_frame.grid(row=0, column=1, sticky="nsew")

        # Update button colors
        self.btn_pathology.configure(fg_color=("gray75", "gray25") if name == "Pathology" else "transparent")
        self.btn_calibration.configure(fg_color=("gray75", "gray25") if name == "Calibration" else "transparent")
        self.btn_playback.configure(fg_color=("gray75", "gray25") if name == "Playback" else "transparent")
        
        if hasattr(self.active_frame, "on_show"):
            self.active_frame.on_show()

    def select_pathology(self):
        self._show_frame("Pathology")

    def select_calibration(self):
        self._show_frame("Calibration")

    def select_playback(self):
        self._show_frame("Playback")

    def update_gui(self):
        # Update active frame
        if hasattr(self.active_frame, "periodic_update"):
            self.active_frame.periodic_update()
            
        self.after(20, self.update_gui) # 50Hz update rate for waveforms

    def on_closing(self):
        log.info("[CTkApp] Closing window")
        self.destroy()
        
