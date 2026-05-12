"""
signal_engine.py — PPG signal generation engine with real-time DAC output.

Port of signal_engine.cpp. Replaces FreeRTOS task with Python threading.
Pipeline: PPGModel (100 Hz) → Linear interpolation (10×) → Ring buffer (1 kHz) → MCP4725 DACs
"""

import threading
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    MODEL_DT_PPG, MODEL_TICK_US_PPG, UPSAMPLE_RATIO_PPG,
    SIGNAL_BUFFER_SIZE, DAC_CENTER_VALUE, FS_TIMER_HZ,
)
from models.ppg_model import PPGModel, PPGParameters, COND_NORMAL
from hw.dac_manager import DACManager
from comm.logger import log

# Signal states
SIG_STOPPED = 0
SIG_RUNNING = 1
SIG_PAUSED  = 2


class SignalEngine:
    """Signal generation engine running PPG model in a background thread."""

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.ppg_model = PPGModel()
        self.dac_manager = DACManager()
        self.state = SIG_STOPPED
        self.ppg_params = PPGParameters()

        # Ring buffers
        self._buf_ir = [DAC_CENTER_VALUE] * SIGNAL_BUFFER_SIZE
        self._buf_red = [DAC_CENTER_VALUE] * SIGNAL_BUFFER_SIZE
        self._buf_display_ir = [0.0] * SIGNAL_BUFFER_SIZE
        self._buf_display_red = [0.0] * SIGNAL_BUFFER_SIZE
        self._read_idx = 0
        self._write_idx = 0

        # Interpolation state
        self._prev_ir = DAC_CENTER_VALUE
        self._prev_red = DAC_CENTER_VALUE
        self._curr_ir = DAC_CENTER_VALUE
        self._curr_red = DAC_CENTER_VALUE
        self._prev_disp_ir = 0.0
        self._curr_disp_ir = 0.0
        self._prev_disp_red = 0.0
        self._curr_disp_red = 0.0
        self._interp_counter = 0

        # Thread control
        self._thread = None
        self._lock = threading.Lock()
        self._running = False
        self._sample_count = 0

    def begin(self) -> bool:
        """Initialize the signal engine and DAC hardware."""
        dac_ok = self.dac_manager.begin()
        if not dac_ok:
            log.warning("[SignalEngine] DAC not available — continuing without analog output")
        self.dac_manager.set_values(DAC_CENTER_VALUE, DAC_CENTER_VALUE)
        log.info("[SignalEngine] Initialized")
        return True

    def start_simulation(self, condition: int = COND_NORMAL) -> bool:
        """Start PPG simulation with the given condition."""
        log.info(f"[SignalEngine] Starting PPG simulation, condition={condition}")

        with self._lock:
            if self.state == SIG_RUNNING:
                self._stop_thread()

            # Reset buffers
            self._read_idx = 0
            self._write_idx = 0
            self._interp_counter = 0
            self._prev_ir = self._curr_ir = DAC_CENTER_VALUE
            self._prev_red = self._curr_red = DAC_CENTER_VALUE
            self._prev_disp_ir = self._curr_disp_ir = 0.0
            self._prev_disp_red = self._curr_disp_red = 0.0
            self._sample_count = 0

            # Configure model
            self.ppg_model.reset()
            params = PPGParameters()
            params.condition = condition
            self.ppg_model.set_parameters(params)
            self.ppg_params = params

            # Pre-fill buffer
            dc = self.ppg_model.dc_baseline
            fill_val = DACManager.ppg_sample_to_dac_value(dc, dc, 150.0)
            for i in range(SIGNAL_BUFFER_SIZE // 2):
                self._buf_ir[i] = fill_val
                self._buf_red[i] = fill_val
                self._buf_display_ir[i] = 0.0
                self._buf_display_red[i] = 0.0
            self._write_idx = SIGNAL_BUFFER_SIZE // 2

            self.state = SIG_RUNNING

        # Start generation thread
        self._running = True
        self._thread = threading.Thread(target=self._generation_loop, daemon=True, name="SignalGen")
        self._thread.start()
        log.info(f"[SignalEngine] PPG running: {self.ppg_model.get_condition_name()}")
        return True

    def stop_simulation(self) -> bool:
        with self._lock:
            self.state = SIG_STOPPED
        self._stop_thread()
        self.dac_manager.set_values(DAC_CENTER_VALUE, DAC_CENTER_VALUE)
        log.info("[SignalEngine] Simulation stopped")
        return True

    def pause_simulation(self) -> bool:
        if self.state == SIG_RUNNING:
            self.state = SIG_PAUSED
            return True
        return False

    def resume_simulation(self) -> bool:
        if self.state == SIG_PAUSED:
            self.state = SIG_RUNNING
            return True
        return False

    def _stop_thread(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # ─── DAC Conversion ───
    @staticmethod
    def _mv_to_dac(signal_mv: float) -> int:
        """Convert signal in mV to 12-bit DAC value.

        Linear mapping: 0 mV → 0, 3300 mV → 4095.
        PPG signals typically center around dc_baseline (~1500 mV)
        with AC components of ±100 mV and wander of ±30 mV.
        """
        dac_val = int((signal_mv / 3300.0) * 4095.0)
        return max(0, min(4095, dac_val))

    # ─── Generation Loop (background thread) ───
    def _generation_loop(self):
        """Main generation loop — runs at ~1 kHz, generates model samples at 100 Hz."""
        model_tick_s = MODEL_TICK_US_PPG / 1_000_000.0
        dac_interval_s = 1.0 / FS_TIMER_HZ
        last_model_time = time.perf_counter()
        last_dac_time = time.perf_counter()

        while self._running:
            if self.state != SIG_RUNNING:
                time.sleep(0.01)
                continue

            now = time.perf_counter()

            # Generate new model sample at 100 Hz
            if now - last_model_time >= model_tick_s:
                last_model_time = now

                self._prev_ir = self._curr_ir
                self._prev_red = self._curr_red
                self._prev_disp_ir = self._curr_disp_ir
                self._prev_disp_red = self._curr_disp_red

                ir_mv, red_mv, disp_ir, disp_red = self.ppg_model.generate_both_samples(MODEL_DT_PPG)

                dc = self.ppg_model.dc_baseline
                # DAC voltage mapping: 0 mV → 0, 3300 mV → 4095 (12-bit)
                self._curr_ir = self._mv_to_dac(ir_mv)
                self._curr_red = self._mv_to_dac(red_mv)
                self._curr_disp_ir = disp_ir
                self._curr_disp_red = disp_red

                self._interp_counter = 0

            # Fill ring buffer with interpolated samples
            write_idx = self._write_idx
            read_idx = self._read_idx
            available = (read_idx - write_idx - 1 + SIGNAL_BUFFER_SIZE) % SIGNAL_BUFFER_SIZE

            while available > 0:
                t = self._interp_counter / UPSAMPLE_RATIO_PPG
                interp_ir = int(self._prev_ir + (self._curr_ir - self._prev_ir) * t)
                interp_red = int(self._prev_red + (self._curr_red - self._prev_red) * t)
                interp_disp_ir = self._prev_disp_ir + (self._curr_disp_ir - self._prev_disp_ir) * t
                interp_disp_red = self._prev_disp_red + (self._curr_disp_red - self._prev_disp_red) * t

                interp_ir = max(0, min(4095, interp_ir))
                interp_red = max(0, min(4095, interp_red))

                self._buf_ir[write_idx] = interp_ir
                self._buf_red[write_idx] = interp_red
                self._buf_display_ir[write_idx] = interp_disp_ir
                self._buf_display_red[write_idx] = interp_disp_red

                write_idx = (write_idx + 1) % SIGNAL_BUFFER_SIZE
                self._write_idx = write_idx
                available -= 1
                self._sample_count += 1

                self._interp_counter += 1
                if self._interp_counter >= UPSAMPLE_RATIO_PPG:
                    self._interp_counter = 0
                    self._prev_disp_ir = self._curr_disp_ir
                    self._prev_disp_red = self._curr_disp_red

            # Write to DACs at ~1 kHz
            if now - last_dac_time >= dac_interval_s:
                last_dac_time = now
                if self._read_idx != self._write_idx:
                    out_ir = self._buf_ir[self._read_idx]
                    out_red = self._buf_red[self._read_idx]
                    self._read_idx = (self._read_idx + 1) % SIGNAL_BUFFER_SIZE
                    self.dac_manager.set_values(out_ir, out_red)

            # Yield to other threads (aim for ~1 ms loop)
            time.sleep(0.0005)

    # ─── Parameter Updates ───
    def update_noise_level(self, noise: float):
        self.ppg_params.noise_level = max(0.0, min(0.10, noise))
        self.ppg_model.set_noise_level(noise)

    def update_heart_rate(self, hr: float):
        self.ppg_model.set_heart_rate(hr)
        self.ppg_params.heart_rate = hr

    def update_perfusion_index(self, pi: float):
        self.ppg_model.set_perfusion_index(pi)
        self.ppg_params.perfusion_index = pi

    def update_spo2(self, spo2: float):
        self.ppg_params.spo2 = spo2
        self.ppg_model.params.spo2 = spo2

    def update_resp_rate(self, rr: float):
        self.ppg_params.resp_rate = rr
        self.ppg_model.params.resp_rate = rr

    def change_condition(self, condition: int):
        if self.state in (SIG_RUNNING, SIG_PAUSED):
            self.start_simulation(condition)

    # ─── Getters ───
    def get_current_display_ir(self) -> float:
        idx = (self._read_idx - 1 + SIGNAL_BUFFER_SIZE) % SIGNAL_BUFFER_SIZE
        return self._buf_display_ir[idx]

    def get_current_display_red(self) -> float:
        idx = (self._read_idx - 1 + SIGNAL_BUFFER_SIZE) % SIGNAL_BUFFER_SIZE
        return self._buf_display_red[idx]

    def get_current_raw_ir(self) -> int:
        idx = (self._read_idx - 1 + SIGNAL_BUFFER_SIZE) % SIGNAL_BUFFER_SIZE
        return self._buf_ir[idx]

    def get_current_raw_red(self) -> int:
        idx = (self._read_idx - 1 + SIGNAL_BUFFER_SIZE) % SIGNAL_BUFFER_SIZE
        return self._buf_red[idx]

    def get_ppg_params(self) -> PPGParameters:
        return self.ppg_params

    def get_beat_count(self) -> int:
        return self.ppg_model.beat_count
