import customtkinter as ctk
import os
import csv
import glob

class PlaybackFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)  # File list
        self.grid_columnconfigure(1, weight=3)  # Main display area
        
        # --- File List Area ---
        self.file_list_frame = ctk.CTkScrollableFrame(self, label_text="Recorded Datasets")
        self.file_list_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        self.dataset_dir = "dataset"
        
        # --- Display Area ---
        self.display_frame = ctk.CTkFrame(self)
        self.display_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.display_frame.grid_rowconfigure(1, weight=1)
        self.display_frame.grid_columnconfigure(0, weight=1)
        
        # Controls & Parameters
        self.control_frame = ctk.CTkFrame(self.display_frame, fg_color="transparent")
        self.control_frame.grid(row=0, column=0, sticky="ew", pady=10)
        
        self.play_btn = ctk.CTkButton(self.control_frame, text="Play", width=60, 
                                      command=self.toggle_playback, state="disabled")
        self.play_btn.pack(side="left", padx=10)
        
        self.lbl_hr = ctk.CTkLabel(self.control_frame, text="HR: --")
        self.lbl_hr.pack(side="left", expand=True)
        self.lbl_spo2 = ctk.CTkLabel(self.control_frame, text="SpO2: --")
        self.lbl_spo2.pack(side="left", expand=True)
        self.lbl_rr = ctk.CTkLabel(self.control_frame, text="RR: --")
        self.lbl_rr.pack(side="left", expand=True)
        self.lbl_pi = ctk.CTkLabel(self.control_frame, text="PI: --")
        self.lbl_pi.pack(side="left", expand=True)
        self.lbl_cond = ctk.CTkLabel(self.control_frame, text="Cond: --")
        self.lbl_cond.pack(side="left", expand=True)
        
        # Canvas
        self.canvas = ctk.CTkCanvas(self.display_frame, bg="black", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        
        self.canvas_width = 600
        self.canvas_height = 400
        
        # Playback State
        self.is_playing = False
        self.playback_ir = []
        self.playback_red = []
        self.playback_idx = 0
        self.sweep_x = 0
        self.last_y_ir = None
        self.last_y_red = None
        self.v_min = 0
        self.v_max = 4095
        self.v_range = 4095
        
        self._draw_grid()
        
    def on_show(self):
        self.refresh_file_list()

    def refresh_file_list(self):
        for widget in self.file_list_frame.winfo_children():
            widget.destroy()
            
        if not os.path.exists(self.dataset_dir):
            return
            
        files = sorted(glob.glob(os.path.join(self.dataset_dir, "*.csv")))
        
        for fpath in files:
            fname = os.path.basename(fpath)
            btn = ctk.CTkButton(self.file_list_frame, text=fname, 
                                command=lambda p=fpath: self.load_data(p),
                                fg_color="gray25", hover_color="gray40")
            btn.pack(fill="x", pady=2, padx=5)

    def toggle_playback(self):
        if not self.playback_ir:
            return
            
        if self.is_playing:
            self.is_playing = False
            self.play_btn.configure(text="Play", fg_color=["#3a7ebf", "#1f538d"])
        else:
            if self.playback_idx >= len(self.playback_ir):
                # restart from beginning
                self.playback_idx = 0
                self.sweep_x = 0
                self.last_y_ir = None
                self.last_y_red = None
                self.canvas.delete("trace")
            
            self.is_playing = True
            self.play_btn.configure(text="Pause", fg_color="darkorange")

    def load_data(self, filepath):
        ir_data = []
        red_data = []
        params = None
        
        try:
            with open(filepath, 'r') as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for row in reader:
                    if len(row) >= 7:
                        ir_data.append(float(row[0]))
                        red_data.append(float(row[1]))
                        if params is None:
                            params = {
                                "hr": row[2], "spo2": row[3], 
                                "rr": row[4], "pi": row[5], "cond": row[6]
                            }
        except Exception as e:
            print(f"Failed to load {filepath}: {e}")
            return
            
        if params:
            self.lbl_hr.configure(text=f"HR: {params['hr']} BPM")
            self.lbl_spo2.configure(text=f"SpO2: {params['spo2']} %")
            self.lbl_rr.configure(text=f"RR: {params['rr']} BPM")
            self.lbl_pi.configure(text=f"PI: {params['pi']} %")
            self.lbl_cond.configure(text=f"Cond: {params['cond']}")
            
        self.playback_ir = ir_data
        self.playback_red = red_data
        self.playback_idx = 0
        self.sweep_x = 0
        self.last_y_ir = None
        self.last_y_red = None
        
        self.is_playing = False
        self.play_btn.configure(text="Play", state="normal", fg_color=["#3a7ebf", "#1f538d"])
        self.canvas.delete("trace")
        
        if self.playback_ir:
            v_min = min(min(ir_data), min(red_data))
            v_max = max(max(ir_data), max(red_data))
            v_range = v_max - v_min if v_max > v_min else 1
            self.v_min = v_min - v_range * 0.1
            self.v_max = v_max + v_range * 0.1
            self.v_range = self.v_max - self.v_min

    def _draw_grid(self):
        self.canvas.delete("grid")
        mid_y = self.canvas_height // 2
        self.canvas.create_line(0, mid_y, self.canvas_width, mid_y, fill="#004020", tags="grid")
        for x in range(0, self.canvas_width, 100):
            self.canvas.create_line(x, 0, x, self.canvas_height, fill="#002010", tags="grid")

    def on_canvas_resize(self, event):
        self.canvas_width = event.width
        self.canvas_height = event.height
        self._draw_grid()

    def periodic_update(self):
        if not self.is_playing or not self.playback_ir:
            return
            
        if self.playback_idx >= len(self.playback_ir):
            self.is_playing = False
            self.play_btn.configure(text="Play", fg_color=["#3a7ebf", "#1f538d"])
            return
            
        h = self.canvas_height
        ir_val = self.playback_ir[self.playback_idx]
        red_val = self.playback_red[self.playback_idx]
        self.playback_idx += 1
        
        y_ir = h - ((ir_val - self.v_min) / self.v_range * h)
        y_red = h - ((red_val - self.v_min) / self.v_range * h)
        
        x = self.sweep_x
        
        if self.last_y_ir is not None:
            self.canvas.create_line(x-2, self.last_y_ir, x, y_ir, fill="#00ff80", width=2, tags="trace")
            self.canvas.create_line(x-2, self.last_y_red, x, y_red, fill="#ff4040", width=1, tags="trace")
            
        self.last_y_ir = y_ir
        self.last_y_red = y_red
        self.sweep_x += 2
        
        if self.sweep_x >= self.canvas_width:
            self.sweep_x = 0
            self.last_y_ir = None
            self.last_y_red = None
            self.canvas.delete("trace")
