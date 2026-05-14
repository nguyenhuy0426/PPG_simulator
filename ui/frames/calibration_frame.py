import customtkinter as ctk
import math
import time
from core.signal_engine import SignalEngine

class CalibrationFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        
        self.engine = SignalEngine.get_instance()
        
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # --- Waveform Area ---
        self.wf_frame = ctk.CTkFrame(self)
        self.wf_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.wf_frame.grid_rowconfigure(0, weight=1)
        self.wf_frame.grid_columnconfigure(0, weight=1)
        
        self.canvas = ctk.CTkCanvas(self.wf_frame, bg="black", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        
        self.canvas_width = 800
        self.canvas_height = 300
        self.sweep_x = 0
        self.last_y = None
        
        # --- Controls Area ---
        self.ctrl_frame = ctk.CTkFrame(self)
        self.ctrl_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.ctrl_frame.grid_columnconfigure(0, weight=1)
        self.ctrl_frame.grid_columnconfigure(1, weight=1)
        
        self.freq_var = ctk.DoubleVar(value=1.0)
        self.amp_var = ctk.DoubleVar(value=2000.0)
        
        # Freq Slider
        f_frame = ctk.CTkFrame(self.ctrl_frame, fg_color="transparent")
        f_frame.grid(row=0, column=0, padx=20, pady=20, sticky="ew")
        ctk.CTkLabel(f_frame, text="Frequency").pack(side="left")
        self.freq_lbl = ctk.CTkLabel(f_frame, text="1.0 Hz")
        self.freq_lbl.pack(side="right")
        def update_f(v): self.freq_lbl.configure(text=f"{v:.1f} Hz")
        ctk.CTkSlider(f_frame, from_=1.0, to=10.0, variable=self.freq_var, command=update_f).pack(side="left", fill="x", expand=True, padx=10)

        # Amp Slider
        a_frame = ctk.CTkFrame(self.ctrl_frame, fg_color="transparent")
        a_frame.grid(row=0, column=1, padx=20, pady=20, sticky="ew")
        ctk.CTkLabel(a_frame, text="Amplitude").pack(side="left")
        self.amp_lbl = ctk.CTkLabel(a_frame, text="2000 mV")
        self.amp_lbl.pack(side="right")
        def update_a(v): self.amp_lbl.configure(text=f"{v:.0f} mV")
        ctk.CTkSlider(a_frame, from_=100, to=3300, variable=self.amp_var, command=update_a).pack(side="left", fill="x", expand=True, padx=10)
        
        self.cal_phase = 0.0
        self.cal_last_time = time.time()

    def on_show(self):
        self.sweep_x = 0
        self.last_y = None
        self.canvas.delete("trace")
        self.cal_last_time = time.time()
        self.engine.stop_simulation() # Stop PPG model to let calibration run

    def on_canvas_resize(self, event):
        self.canvas_width = event.width
        self.canvas_height = event.height
        self._draw_grid()

    def _draw_grid(self):
        self.canvas.delete("grid")
        mid_y = self.canvas_height // 2
        self.canvas.create_line(0, mid_y, self.canvas_width, mid_y, fill="#004020", tags="grid")
        for x in range(0, self.canvas_width, 100):
            self.canvas.create_line(x, 0, x, self.canvas_height, fill="#002010", tags="grid")

    def periodic_update(self):
        # Generate Sine wave
        now = time.time()
        dt = now - self.cal_last_time
        self.cal_last_time = now
        
        freq = self.freq_var.get()
        amp = self.amp_var.get()
        
        self.cal_phase += dt * 2.0 * math.pi * freq
        self.cal_phase %= (2.0 * math.pi)
        
        val_mv = amp * math.sin(self.cal_phase)
        
        # Send to DAC if engine is accessible (direct write for calibration)
        # Assuming DAC is available
        dac_val = int((val_mv + 1650) / 3300.0 * 4095) # simple offset
        dac_val = max(0, min(4095, dac_val))
        self.engine.dac_manager.set_values(dac_val, dac_val)
        
        # Draw
        v_min, v_max = -3300, 3300
        h = self.canvas_height
        norm = (val_mv - v_min) / (v_max - v_min)
        y = h - (norm * h)
        
        x = self.sweep_x
        if self.last_y is not None:
            self.canvas.create_line(x-5, self.last_y, x, y, fill="#00ff80", width=2, tags="trace")
            
        self.last_y = y
        self.sweep_x += 5
        
        if self.sweep_x >= self.canvas_width:
            self.sweep_x = 0
            self.last_y = None
            self.canvas.delete("trace")
