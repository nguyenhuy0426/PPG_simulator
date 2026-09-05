"""
signal_engine.py — PPG signal generation engine with real-time DAC output.

Port of signal_engine.cpp. Replaces FreeRTOS task with Python threading.
Pipeline: PPGModel (100 Hz) → Linear interpolation (10×) → Ring buffer (1 kHz) → MCP4725 DACs
"""

import copy
import math
from collections import deque
import threading
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    MODEL_DT_PPG, MODEL_TICK_US_PPG, UPSAMPLE_RATIO_PPG,
    SIGNAL_BUFFER_SIZE, DAC_CENTER_VALUE, DAC_IDLE_VALUE, FS_TIMER_HZ,
)
from models.ppg_model import PPGModel, PPGParameters, COND_NORMAL, CONDITION_NAMES
from hw.dac_manager import DACManager
from calibration import dac_voltage_to_code
from core.rate_scheduler import FixedRateTicker
from comm.logger import log

# Cooperative yield between deadline checks. Short enough that a 1 kHz DAC
# deadline is never missed by more than half a period, long enough that the
# two loops do not spin the CPU.
LOOP_YIELD_S = 0.0005

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

        # Thread control. The model and the DAC writer run in separate
        # threads: an I2C write that blocks for hundreds of microseconds must
        # not delay the 100 Hz model tick (that was a direct contributor to
        # the playback running slow).
        self._thread = None
        self._dac_thread = None
        self._lock = threading.Lock()
        self._model_lock = threading.RLock()
        self._display_history = deque(maxlen=1200)
        self._record_samples = deque(maxlen=6000)
        self._recording = False
        self._record_dropped = 0
        self._calibration = None
        self._cal_time = 0.0
        self._buf_lock = threading.Lock()
        self._running = False
        self._sample_count = 0

        # Both persisted locks make PI read-only; single locks define which
        # amplitude parameter is held when PI changes.
        self.ac_dc_locked = False

        # Ring-buffer health counters (see get_stats())
        self._overrun_count = 0
        self._underrun_count = 0
        self._dropped_samples = 0

    def begin(self) -> bool:
        """Initialize the signal engine and DAC hardware."""
        dac_ok = self.dac_manager.begin()
        if not dac_ok:
            log.warning("[SignalEngine] DAC not available — continuing without analog output")
        # Park outputs at the safe idle level (0 V → LEDs off) until a
        # simulation starts; never idle at mid-scale (would half-drive LEDs).
        self.dac_manager.set_values(DAC_IDLE_VALUE, DAC_IDLE_VALUE)
        log.info("[SignalEngine] Initialized")
        return True

    def start_simulation(self, condition: int = COND_NORMAL, *, calibration=None) -> bool:
        """Start PPG simulation with the given condition."""
        log.info(f"[SignalEngine] Starting PPG simulation, condition={condition}")

        with self._lock:
            if self._running:
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

            # Configure model.
            # reset() clears the runtime/measurement state only; the user's
            # parameters (HR, PI, SpO2, RR, noise, per-channel DC, polarity)
            # live on self.ppg_params and are re-applied here so pressing Run
            # never silently discards what was set on the panel.
            with self._model_lock:
                self._display_history.clear()
                self._calibration = calibration
                self._cal_time = 0.0
                self.ppg_params.condition = condition
                self.ppg_model.set_parameters(self.ppg_params)
                self.ppg_model.reset()

            # Do not pre-fill buffer with DC baseline; start generating immediately
            self._write_idx = 0

            self.state = SIG_RUNNING

        # Start generation + DAC output threads
        self.reset_stats()
        self._running = True
        self._thread = threading.Thread(target=self._generation_loop, daemon=True, name="SignalGen")
        self._thread.start()
        self._dac_thread = threading.Thread(target=self._dac_loop, daemon=True, name="SignalDAC")
        self._dac_thread.start()
        log.info(f"[SignalEngine] PPG running: {self.ppg_model.get_condition_name()}")
        return True

    def stop_simulation(self) -> bool:
        with self._lock:
            self.state = SIG_STOPPED
        self._stop_thread()
        # Safe stop: 0 V on both channels (LEDs off in the driver concept).
        self.dac_manager.set_values(DAC_IDLE_VALUE, DAC_IDLE_VALUE)
        log.info("[SignalEngine] Simulation stopped")
        return True

    def shutdown(self):
        """Final shutdown at process exit: stop generation, park both DACs at
        the safe idle level (0 V → LEDs off), and refuse further HW writes."""
        self.stop_simulation()
        self.dac_manager.shutdown()

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
        for thread in (self._thread, self._dac_thread):
            if thread and thread.is_alive():
                thread.join(timeout=2.0)

    # ─── DAC Conversion (Volts → 12-bit) ───
    @staticmethod
    def _v_to_dac(signal_v: float) -> int:
        """Convert signal in Volts to 12-bit DAC value.

        Delegates to calibration.dac_voltage_to_code, the single source of truth
        for DAC scaling. Linear mapping: 0 V → 0, DAC_FULLSCALE_V (3.28 V) → 4095.
        PPG signals (strict clinical PI = AC/DC × 100%), at 3.28 V full-scale:
            DC baseline = 1.5 V → DAC = 1872
            PI=3%:  AC=45mV  → signal 1.5±0.045 V → DAC 1816–1928
            PI=10%: AC=150mV → signal 1.5±0.15 V  → DAC 1685–2059
            PI=20%: AC=300mV → signal 1.5±0.30 V  → DAC 1498–2247
        """
        return dac_voltage_to_code(signal_v)

    # ─── Ring buffer accounting ───
    def _reserve_write_space(self, n: int) -> None:
        """Make room for `n` samples, dropping the oldest if the ring is full.

        The producer (100 Hz x 10 interpolated samples) and the consumer (DAC
        writer) are nominally rate-matched, but the consumer is the one bound
        by the I2C bus. When it cannot keep up, dropping the OLDEST unread
        samples keeps the output in real time (a stale sample is worse than a
        dropped one for a live waveform) and the counters make it visible.
        """
        free = (self._read_idx - self._write_idx - 1) % SIGNAL_BUFFER_SIZE
        if free >= n:
            return
        shortfall = n - free
        self._read_idx = (self._read_idx + shortfall) % SIGNAL_BUFFER_SIZE
        self._overrun_count += 1
        self._dropped_samples += shortfall

    def _pop_dac_sample(self):
        """Return the next (ir, red) DAC pair, or None if the ring is empty."""
        if self._read_idx == self._write_idx:
            self._underrun_count += 1
            return None
        out_ir = self._buf_ir[self._read_idx]
        out_red = self._buf_red[self._read_idx]
        self._read_idx = (self._read_idx + 1) % SIGNAL_BUFFER_SIZE
        return out_ir, out_red

    def get_stats(self) -> dict:
        """Ring-buffer health, for the UI and for bring-up measurements."""
        return {
            "record_dropped": self._record_dropped,
            "clipped_samples": self.ppg_model.clipped_samples,
            "overruns": self._overrun_count,
            "underruns": self._underrun_count,
            "dropped_samples": self._dropped_samples,
            "samples_generated": self._sample_count,
            "buffer_fill": (self._write_idx - self._read_idx) % SIGNAL_BUFFER_SIZE,
        }

    def reset_stats(self) -> None:
        self._overrun_count = 0
        self._underrun_count = 0
        self._dropped_samples = 0

    # ─── Generation Loop (background thread) ───
    def _generate_one_tick(self) -> None:
        """Advance the model by one 100 Hz tick and upsample into the ring."""
        self._prev_ir = self._curr_ir
        self._prev_red = self._curr_red
        self._prev_disp_ir = self._curr_disp_ir
        self._prev_disp_red = self._curr_disp_red

        with self._model_lock:
            if self._calibration is None:
                ir_v, red_v, disp_ir, disp_red = self.ppg_model.generate_both_samples(MODEL_DT_PPG)
                stamp = self.ppg_model.simulated_time_s
            else:
                frequency, amplitude_mv = self._calibration
                self._cal_time += MODEL_DT_PPG
                ir_v = red_v = amplitude_mv / 2000 * (1 + math.sin(2 * math.pi * frequency * self._cal_time))
                disp_ir, disp_red, stamp = ir_v, red_v, self._cal_time
            self._display_history.append((stamp, disp_ir, disp_red))
            if self._recording:
                p = self.ppg_params
                if len(self._record_samples) == self._record_samples.maxlen:
                    self._record_dropped += 1
                self._record_samples.append((self._v_to_dac(ir_v), self._v_to_dac(red_v),
                    p.heart_rate, p.spo2, p.resp_rate, p.perfusion_index, CONDITION_NAMES[p.condition], stamp))

        # DAC voltage mapping: 0 V → 0, 3.28 V → 4095 (12-bit)
        self._curr_ir = self._v_to_dac(ir_v)
        self._curr_red = self._v_to_dac(red_v)
        self._curr_disp_ir = disp_ir
        self._curr_disp_red = disp_red

        with self._buf_lock:
            self._reserve_write_space(UPSAMPLE_RATIO_PPG)
            write_idx = self._write_idx
            for i in range(UPSAMPLE_RATIO_PPG):
                t = i / float(UPSAMPLE_RATIO_PPG)
                interp_ir = int(self._prev_ir + (self._curr_ir - self._prev_ir) * t)
                interp_red = int(self._prev_red + (self._curr_red - self._prev_red) * t)

                self._buf_ir[write_idx] = max(0, min(4095, interp_ir))
                self._buf_red[write_idx] = max(0, min(4095, interp_red))
                self._buf_display_ir[write_idx] = (
                    self._prev_disp_ir + (self._curr_disp_ir - self._prev_disp_ir) * t)
                self._buf_display_red[write_idx] = (
                    self._prev_disp_red + (self._curr_disp_red - self._prev_disp_red) * t)

                write_idx = (write_idx + 1) % SIGNAL_BUFFER_SIZE

            self._write_idx = write_idx
            self._sample_count += UPSAMPLE_RATIO_PPG

    def _generation_loop(self):
        """Model thread — advances the PPG model at exactly 100 Hz."""
        ticker = FixedRateTicker(MODEL_TICK_US_PPG / 1_000_000.0, time.perf_counter())

        while self._running:
            if self.state != SIG_RUNNING:
                time.sleep(0.01)
                ticker.reset(time.perf_counter())
                continue

            for _ in range(ticker.due(time.perf_counter())):
                self._generate_one_tick()

            time.sleep(LOOP_YIELD_S)

    def _dac_loop(self):
        """DAC thread — drains the ring to the MCP4725 pair at FS_TIMER_HZ."""
        ticker = FixedRateTicker(1.0 / FS_TIMER_HZ, time.perf_counter())

        while self._running:
            if self.state != SIG_RUNNING:
                time.sleep(0.01)
                ticker.reset(time.perf_counter())
                continue

            for _ in range(ticker.due(time.perf_counter())):
                with self._buf_lock:
                    sample = self._pop_dac_sample()
                if sample is None:
                    break
                self.dac_manager.set_values(sample[0], sample[1])

            time.sleep(LOOP_YIELD_S)

    # Model mutations and generation share one lock, so a tick sees complete settings.
    def _update_model(self, method, *args, **kwargs):
        with self._model_lock:
            getattr(self.ppg_model, method)(*args, **kwargs)
            self.ppg_params = self.ppg_model.params.copy()

    def load_parameters(self, params):
        with self._model_lock:
            self.ppg_model.set_parameters(params)
            self.ppg_params = self.ppg_model.params.copy()
            self.ac_dc_locked = self.ppg_params.lock_ac and self.ppg_params.lock_dc

    def update_noise_level(self, noise):
        self._update_model("set_noise_level", noise)

    def update_noise(self, kind, amplitude_mv=0.0, freq_hz=0.0, seed=None):
        self._update_model("set_noise", kind, amplitude_mv, freq_hz, seed)

    def update_heart_rate(self, hr):
        self._update_model("set_heart_rate", hr)

    def set_ac_dc_lock(self, locked):
        self.ac_dc_locked = bool(locked)
        self._update_model("set_lock", lock_ac=locked, lock_dc=locked)

    def update_lock(self, lock_ac, lock_dc):
        self.ac_dc_locked = bool(lock_ac and lock_dc)
        self._update_model("set_lock", lock_ac=lock_ac, lock_dc=lock_dc)

    def update_perfusion_index(self, pi):
        if not self.ac_dc_locked:
            self._update_model("set_perfusion_index", pi)

    def update_spo2_coefficients(self, coeff_a, coeff_b):
        self._update_model("set_spo2_coefficients", coeff_a, coeff_b)

    def update_dc_levels(self, dc_ir_mv, dc_red_mv=None):
        self._update_model("set_dc_levels", dc_ir_mv, dc_red_mv)

    def update_ac_dc(self, ac_ir_mv, dc_ir_mv, dc_red_mv=None):
        self._update_model("set_ac_dc", ac_ir_mv, dc_ir_mv, dc_red_mv)

    def update_ac_levels(self, ac_ir_mv, ac_red_mv=None):
        self._update_model("set_ac_levels", ac_ir_mv, ac_red_mv)

    def update_output_dc_offset(self, value):
        self._update_model("set_output_dc_offset", value)

    def update_polarity(self, polarity):
        self._update_model("set_polarity", polarity)

    def update_spo2(self, spo2):
        self._update_model("set_spo2", spo2)

    def update_resp_rate(self, rr):
        self._update_model("set_resp_rate", rr)

    def update_respiration(self, config):
        self._update_model("set_respiration", config)

    def update_modelling_options(self, hr_amplitude, spo2_notch, variability):
        self._update_model("set_modelling_options", hr_amplitude, spo2_notch, variability)

    def update_waveform(self, kind):
        self._update_model("set_waveform", kind)

    def update_feature_times(self, channel, sp, dn, dp):
        self._update_model("set_feature_times", channel, sp, dn, dp)

    def update_amplification(self, value):
        self._update_model("set_amplification", value)

    def update_dicrotic_notch(self, value):
        self._update_model("set_dicrotic_notch", value)

    def change_condition(self, condition):
        with self._model_lock:
            self.ppg_params.condition = condition
            self.ppg_model.set_parameters(self.ppg_params)

    def get_display_history(self):
        with self._model_lock:
            return list(self._display_history)

    def start_calibration(self, frequency_hz, amplitude_mv):
        from config import DAC_FULLSCALE_MV
        if not math.isfinite(frequency_hz) or not 1 <= frequency_hz <= 10:
            raise ValueError("Calibration frequency must be 1–10 Hz")
        if not math.isfinite(amplitude_mv) or not 100 <= amplitude_mv <= DAC_FULLSCALE_MV:
            raise ValueError(f"Calibration amplitude must be 100–{DAC_FULLSCALE_MV:g} mV")
        self.start_simulation(self.ppg_params.condition, calibration=(frequency_hz, amplitude_mv))

    @property
    def is_calibrating(self):
        return self._running and self._calibration is not None

    def set_recording(self, enabled):
        with self._model_lock:
            if enabled:
                self._record_samples.clear()
                self._record_dropped = 0
            self._recording = bool(enabled)

    def drain_recording(self):
        with self._model_lock:
            batch = list(self._record_samples)
            self._record_samples.clear()
            return batch

    def update_signal_settings(self, values):
        # Validate the complete form on a private copy before touching a live tick.
        with self._model_lock:
            candidate = copy.deepcopy(self.ppg_model)
            candidate.set_output_dc_offset(0)
            candidate.set_dc_levels(values["dc_ir_mv"], values["dc_red_mv"])
            candidate.set_ac_levels(values["ac_ir_mv"], values["ac_red_mv"])
            candidate.set_output_dc_offset(values["output_dc_offset_mv"])
            candidate.set_amplification(values["amplification"])
            candidate.set_dicrotic_notch(values["dicrotic_notch"])
            candidate.set_spo2(values["spo2"])
            candidate.set_waveform(values["waveform"])
            candidate.set_polarity(values["ac_polarity"])
            candidate.set_lock(values["lock_ac"], values["lock_dc"])
            for ch in ("ir", "red"):
                candidate.set_feature_times(ch, *(values[k + "_ms_" + ch] for k in ("sp", "dn", "dp")))
            self.ppg_model = candidate
            self.ppg_params = candidate.params.copy()
            self.ac_dc_locked = values["lock_ac"] and values["lock_dc"]

    def update_noise_settings(self, kind, amplitude, frequency, seed, level):
        from models.limits import NOISE_LEVEL
        NOISE_LEVEL.validate(level)
        with self._model_lock:
            candidate = copy.deepcopy(self.ppg_model)
            candidate.set_noise(kind, amplitude, frequency, seed)
            candidate.set_noise_level(level)
            self.ppg_model = candidate
            self.ppg_params = candidate.params.copy()

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
