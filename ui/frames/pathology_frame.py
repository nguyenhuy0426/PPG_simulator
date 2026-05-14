import customtkinter as ctk
import tkinter as tk
from core.signal_engine import SignalEngine
from models.ppg_model import CONDITION_NAMES

class PathologyFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        
        self.app = master
        self.engine = SignalEngine.get_instance()
        self.logger = self.app.csv_logger
        
        self.grid_rowconfigure(0, weight=1)  # Waveform area
        self.grid_rowconfigure(1, weight=1)  # Controls area
        self.grid_columnconfigure(0, weight=1)
        
        # --- Waveform Area ---
        self.wf_frame = ctk.CTkFrame(self)
        self.wf_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.wf_frame.grid_rowconfigure(0, weight=1)
        self.wf_frame.grid_columnconfigure(0, weight=1)
        
        self.canvas = ctk.CTkCanvas(self.wf_frame, bg="black", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        
        # Canvas state
        self.canvas_width = 800
        self.canvas_height = 300
        self.sweep_x = 0
        self.last_y_ir = None
        self.last_y_red = None
        self.lines_ir = []
        self.lines_red = []
        
        # Draw grid
        self._draw_grid()

        # --- Controls Area ---
        self.ctrl_frame = ctk.CTkFrame(self)
        self.ctrl_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        
        # Sliders
        self.sliders = {}
        self.slider_vars = {}
        
        configs = [
            ("Heart Rate", "hr", 20, 300, 75, "{:.0f} BPM"),
            ("SpO2", "spo2", 70, 100, 98, "{:.0f} %"),
            ("Resp Rate", "rr", 4, 60, 16, "{:.0f} BPM"),
            ("Perf Index", "pi", 0.0, 20.0, 2.5, "{:.2f} %"),
            ("Noise Level", "noise", 0.0, 1.0, 0.0, "{:.2f}")
        ]
        
        for i, (label_text, key, vmin, vmax, vdefault, fmt) in enumerate(configs):
            frame = ctk.CTkFrame(self.ctrl_frame, fg_color="transparent")
            frame.grid(row=i//2, column=i%2, padx=20, pady=5, sticky="ew")
            self.ctrl_frame.grid_columnconfigure(i%2, weight=1)
            
            lbl = ctk.CTkLabel(frame, text=label_text, width=80, anchor="w")
            lbl.pack(side="left")
            
            var = ctk.DoubleVar(value=vdefault)
            self.slider_vars[key] = var
            
            val_lbl = ctk.CTkLabel(frame, text=fmt.format(vdefault), width=60, anchor="e")
            val_lbl.pack(side="right")
            
            def make_cmd(k=key, f=fmt, vl=val_lbl):
                def cmd(val):
                    vl.configure(text=f.format(val))
                    self.update_param(k, val)
                return cmd
                
            slider = ctk.CTkSlider(frame, from_=vmin, to=vmax, variable=var, command=make_cmd())
            slider.pack(side="left", fill="x", expand=True, padx=10)
            self.sliders[key] = slider

        # Condition Buttons
        self.cond_frame = ctk.CTkFrame(self.ctrl_frame, fg_color="transparent")
        self.cond_frame.grid(row=3, column=0, columnspan=2, pady=10, sticky="ew")
        
        self.cond_btns = []
        for i, name in enumerate(CONDITION_NAMES):
            btn = ctk.CTkButton(self.cond_frame, text=name[:12], width=80, 
                                command=lambda idx=i: self.set_condition(idx),
                                fg_color="gray25")
            btn.pack(side="left", padx=5, expand=True)
            self.cond_btns.append(btn)
            
        if self.cond_btns:
            self.cond_btns[0].configure(fg_color=["#3a7ebf", "#1f538d"]) # default active color
            
        # Record Button
        self.record_btn = ctk.CTkButton(self.ctrl_frame, text="Start Recording", 
                                        fg_color="darkred", hover_color="red",
                                        command=self.toggle_recording)
        self.record_btn.grid(row=4, column=0, columnspan=2, pady=10)
        self.is_recording = False

    def on_show(self):
        # Update UI to reflect current engine params
        p = self.engine.ppg_params
        self.slider_vars["hr"].set(p.heart_rate)
        self.slider_vars["spo2"].set(p.spo2)
        self.slider_vars["rr"].set(p.resp_rate)
        self.slider_vars["pi"].set(p.perfusion_index)
        self.slider_vars["noise"].set(p.noise_level)
        
        # trigger commands to update labels
        for k, v in self.slider_vars.items():
            self.sliders[k]._command(v.get())
            
        self.set_condition(p.condition)

    def update_param(self, key, val):
        if key == "hr": self.engine.update_heart_rate(val)
        elif key == "spo2": self.engine.update_spo2(val)
        elif key == "rr": self.engine.update_resp_rate(val)
        elif key == "pi": self.engine.update_perfusion_index(val)
        elif key == "noise": self.engine.update_noise_level(val)

    def set_condition(self, idx):
        for i, btn in enumerate(self.cond_btns):
            btn.configure(fg_color=["#3a7ebf", "#1f538d"] if i == idx else "gray25")
        self.engine.ppg_params.condition = idx

    def toggle_recording(self):
        if not self.is_recording:
            self.logger.start()
            self.record_btn.configure(text="Stop Recording", fg_color="red")
            self.is_recording = True
        else:
            self.record_btn.configure(text="Start Recording", fg_color="darkred")
            self.is_recording = False
            self.show_save_dialog()

    def show_save_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Save Recording")
        dialog.geometry("300x150")
        dialog.attributes("-topmost", True)
        dialog.transient(self.winfo_toplevel())
        
        lbl = ctk.CTkLabel(dialog, text="Do you want to save this data segment?")
        lbl.pack(pady=20)
        
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20)
        
        def save():
            self.logger.stop(save=True)
            dialog.destroy()
            
        def discard():
            self.logger.stop(save=False)
            dialog.destroy()
            
        ctk.CTkButton(btn_frame, text="Yes", command=save, width=100).pack(side="left", expand=True)
        ctk.CTkButton(btn_frame, text="No", command=discard, width=100, fg_color="gray").pack(side="right", expand=True)

    def on_canvas_resize(self, event):
        self.canvas_width = event.width
        self.canvas_height = event.height
        self._draw_grid()

    def _draw_grid(self):
        self.canvas.delete("grid")
        mid_y = self.canvas_height // 2
        self.canvas.create_line(0, mid_y, self.canvas_width, mid_y, fill="#004020", tags="grid")
        
        # time grid (every ~100px)
        for x in range(0, self.canvas_width, 100):
            self.canvas.create_line(x, 0, x, self.canvas_height, fill="#002010", tags="grid")

    def periodic_update(self):
        # Read from signal engine buffer
        if not self.engine._running:
            return
            
        # Get latest data points
        n_points = 5 # 50Hz update * 5 points = 250Hz draw rate equivalent approx
        
        ir_val = self.engine._curr_disp_ir
        red_val = self.engine._curr_disp_red
        
        # log to csv if recording
        if self.is_recording:
            p = self.engine.ppg_params
            self.logger.log_data(
                ir_val * 4095 / 3.3, # approximate raw conversion
                red_val * 4095 / 3.3,
                p.heart_rate, p.spo2, p.resp_rate, p.perfusion_index, CONDITION_NAMES[p.condition]
            )
            
        # Map values to y coordinates
        # Assume values are roughly -0.5 to 3.5
        v_min, v_max = -0.5, 3.5
        h = self.canvas_height
        
        def map_y(val):
            # inverted Y for canvas
            norm = (val - v_min) / (v_max - v_min)
            return h - (norm * h)
            
        y_ir = map_y(ir_val)
        y_red = map_y(red_val)
        
        x = self.sweep_x
        
        if self.last_y_ir is not None:
            l_ir = self.canvas.create_line(x-2, self.last_y_ir, x, y_ir, fill="#00ff80", width=2, tags="trace")
            l_red = self.canvas.create_line(x-2, self.last_y_red, x, y_red, fill="#ff4040", width=1, tags="trace")
            self.lines_ir.append(l_ir)
            self.lines_red.append(l_red)
            
        self.last_y_ir = y_ir
        self.last_y_red = y_red
        self.sweep_x += 2
        
        # Erase ahead
        if self.sweep_x >= self.canvas_width:
            self.sweep_x = 0
            self.last_y_ir = None
            self.last_y_red = None
            self.canvas.delete("trace")
            
        # Optional: remove old lines to save memory if doing continuous scrolling
        # Actually with sweep, deleting all at wrap is very efficient.

