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
        
        # Parameters readout
        self.param_frame = ctk.CTkFrame(self.display_frame, fg_color="transparent")
        self.param_frame.grid(row=0, column=0, sticky="ew", pady=10)
        
        self.lbl_hr = ctk.CTkLabel(self.param_frame, text="HR: --")
        self.lbl_hr.pack(side="left", expand=True)
        self.lbl_spo2 = ctk.CTkLabel(self.param_frame, text="SpO2: --")
        self.lbl_spo2.pack(side="left", expand=True)
        self.lbl_rr = ctk.CTkLabel(self.param_frame, text="RR: --")
        self.lbl_rr.pack(side="left", expand=True)
        self.lbl_pi = ctk.CTkLabel(self.param_frame, text="PI: --")
        self.lbl_pi.pack(side="left", expand=True)
        self.lbl_cond = ctk.CTkLabel(self.param_frame, text="Cond: --")
        self.lbl_cond.pack(side="left", expand=True)
        
        # Canvas
        self.canvas = ctk.CTkCanvas(self.display_frame, bg="black", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        
        self.canvas_width = 600
        self.canvas_height = 400
        
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
            
        self.plot_data(ir_data, red_data)

    def on_canvas_resize(self, event):
        self.canvas_width = event.width
        self.canvas_height = event.height

    def plot_data(self, ir_data, red_data):
        self.canvas.delete("all")
        if not ir_data:
            return
            
        n = len(ir_data)
        if n < 2: return
        
        # Determine min/max
        v_min = min(min(ir_data), min(red_data))
        v_max = max(max(ir_data), max(red_data))
        v_range = v_max - v_min if v_max > v_min else 1
        
        # Add 10% padding
        v_min -= v_range * 0.1
        v_max += v_range * 0.1
        v_range = v_max - v_min
        
        w = self.canvas_width
        h = self.canvas_height
        
        # Downsample if too many points to avoid Canvas lag
        step = max(1, n // w)
        
        ir_coords = []
        red_coords = []
        
        for i in range(0, n, step):
            x = (i / (n-1)) * w
            
            y_ir = h - ((ir_data[i] - v_min) / v_range * h)
            ir_coords.extend([x, y_ir])
            
            y_red = h - ((red_data[i] - v_min) / v_range * h)
            red_coords.extend([x, y_red])
            
        if len(ir_coords) >= 4:
            self.canvas.create_line(*ir_coords, fill="#00ff80", width=2)
            self.canvas.create_line(*red_coords, fill="#ff4040", width=1)
