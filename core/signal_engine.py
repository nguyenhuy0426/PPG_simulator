"""
signal_engine.py — PPG signal generation engine with real-time DAC output.

Port of signal_engine.cpp. Replaces FreeRTOS task with Python threading.
Pipeline: PPGModel (100 Hz) → Linear interpolation → Ring buffer → MCP4725 DACs
DAC rate: FS_TIMER_HZ (200 Hz by default on Pi, configurable).
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
    SIGNAL_BUFFER_SIZE, DAC_IDLE_VALUE, FS_TIMER_HZ, DAC_FULLSCALE_V, DRY_RUN, I2C_BUS, DAC_ADDR_RED,
    MAX30102_DC_MV, MAX30102_AC_MV, MAX30102_PEAK_MAX_MV, MAX30102_WRITE_HZ,
)
from models.ppg_model import PPGModel, PPGParameters, COND_NORMAL, CONDITION_NAMES, POLARITY_ABOVE_DC
from hw.dac_manager import DACManager
from hw.max30102_flicker import FlickerProcess, ThreadFlicker
from core.waveform_clip import pulse_span
from calibration import dac_voltage_to_code
from core.rate_scheduler import FixedRateTicker
from comm.logger import log

# Cooperative yield between deadline checks. Short enough that a 1 kHz DAC
# deadline is never missed by more than half a period, long enough that the
# two loops do not spin the CPU.
LOOP_YIELD_S = 0.0005
GENERATION_MAX_WAIT_S = 0.005

# Signal states
SIG_STOPPED = 0
SIG_RUNNING = 1
SIG_PAUSED  = 2

# Playback status codes published on the engine and echoed over BLE
# (protocol v2 status key "pb"). The engine holds them as the single source of
# truth: the bless thread reads them for the status frame, the Tk thread writes
# them from PlaybackFrame, and Tk polls the pending request.
PB_INACTIVE = 0
PB_PLAYING  = 1
PB_PAUSED   = 2

# How often the recording pump drains the sample buffer to the CSV sink.
# 6000 queued samples at 100 Hz is 60 s, so a slow pump can never lose rows.
RECORD_PUMP_INTERVAL_S = 0.25

# MAX30102 mode (config.MAX30102_*): amplitude settings the mode replaces with its preset and puts back on exit.
MAX30102_PRESET = {
    "dc_ir_mv": MAX30102_DC_MV, "dc_red_mv": MAX30102_DC_MV,
    "ac_ir_mv": MAX30102_AC_MV, "ac_red_mv": MAX30102_AC_MV,
    "output_dc_offset_mv": 0.0, "amplification": 1.0, "ac_polarity": POLARITY_ABOVE_DC,
    "lock_ac": False, "lock_dc": False,
}
MAX30102_SAVED_FIELDS = tuple(MAX30102_PRESET) + ("perfusion_index",)
MAX30102_MIN_CLIP_SPAN_V = 0.001   # a clip lane flatter than this carries no pulse: the LED holds the preset DC


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
        self._buf_ir = [DAC_IDLE_VALUE] * SIGNAL_BUFFER_SIZE
        self._buf_red = [DAC_IDLE_VALUE] * SIGNAL_BUFFER_SIZE
        self._buf_display_ir = [0.0] * SIGNAL_BUFFER_SIZE
        self._buf_display_red = [0.0] * SIGNAL_BUFFER_SIZE
        self._read_idx = 0
        self._write_idx = 0

        # Interpolation state; None until the first model sample of a run
        self._prev_ir = self._prev_red = self._curr_ir = self._curr_red = None
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
        self._waveform_clip = None
        self._clip_tick = 0
        # AC balance (core/ac_balance.py): factors on the AC part of the Classic output, (IR, RED). 1.0 = off.
        self._ac_comp = (1.0, 1.0)
        self._ac_comp_clipped = 0
        self._buf_lock = threading.Lock()
        self._running = False
        self._sample_count = 0

        # ─── Protocol v2 shared control state ───
        # Recording: the engine owns the CSV sink and its pump thread so BLE,
        # the Tk GUI and the status echo all read/write ONE source of truth.
        self._csv_logger = None
        self._record_ctl_lock = threading.Lock()
        self._record_write_lock = threading.Lock()   # one batch drained and written at a time, in order
        self._record_pump = None
        self._record_pump_stop = threading.Event()
        self._record_pump_stop.set()
        self._record_file = ""
        # Playback: plain thread-safe attributes (bless thread reads for the
        # status frame, Tk thread writes from PlaybackFrame) plus a bounded
        # command queue the Tk loop drains.
        self._playback_lock = threading.Lock()
        self._playback_requests = deque(maxlen=16)
        self.pb_active = False
        self.pb_state = ""   # "playing" | "paused" | ""
        self.pb_file = ""

        # Both persisted locks make PI read-only; single locks define which
        # amplitude parameter is held when PI changes.
        self.ac_dc_locked = False

        # MAX30102 mode: RED-only on/off output with the preset amplitude (set_max30102_mode).
        self._max30102 = False
        self._max30102_saved = None
        self._max30102_writes = 0
        self._max30102_clipped = 0
        self._clip_span = None   # (clip, lane, low V, high V) of the clip playing in MAX30102 mode
        self._rx_paused = False        # the MAX30102 output paused the OPT101 acquisition
        self._flick_ticker = None      # schedule of the in-thread writer (dry run)

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

    def start_simulation(self, condition: int = COND_NORMAL, *, calibration=None, waveform_clip=None) -> bool:
        """Start PPG simulation with the given condition."""
        if waveform_clip is not None:
            waveform_clip.validate()
            if calibration is not None:
                raise ValueError("Only one output source can run")
        log.info(f"[SignalEngine] Starting PPG simulation, condition={condition}")
        if not self.dac_manager.is_ready:
            self.dac_manager.begin()  # the DACs may have returned since the last attempt

        with self._lock:
            if self._running or any(t and t.is_alive() for t in (self._thread, self._dac_thread)):
                self._stop_thread()

            # Reset buffers
            self._read_idx = 0
            self._write_idx = 0
            self._interp_counter = 0
            # Unseeded: the first tick interpolates from its own sample. Seeding
            # from mid-scale (1.64 V) drove both LEDs to 1.64 V for one tick,
            # which overloads the IR receive path (see docs/hardware-validation).
            self._prev_ir = self._curr_ir = None
            self._prev_red = self._curr_red = None
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
                self._waveform_clip = waveform_clip
                self._clip_tick = 0
                self._cal_time = 0.0
                if waveform_clip is not None and self._max30102:   # sorts the clip once, before the 100 Hz ticks
                    self._clip_span = (waveform_clip, *pulse_span(waveform_clip))
                self.ppg_params.condition = condition
                self.ppg_model.set_parameters(self.ppg_params)
                self.ppg_model.reset()

            if waveform_clip is not None:
                ir, red = waveform_clip.at(0)
                if self._max30102:
                    with self._model_lock:
                        red = self._max30102_clip_level(ir, red)
                self._prev_ir = self._curr_ir = dac_voltage_to_code(ir)
                self._prev_red = self._curr_red = dac_voltage_to_code(red)

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
                if thread.is_alive():
                    raise RuntimeError("Output worker did not stop; refusing a second writer")

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
            "clipped_samples": self.ppg_model.clipped_samples + self._ac_comp_clipped,
            "overruns": self._overrun_count,
            "underruns": self._underrun_count,
            "dropped_samples": self._dropped_samples,
            "samples_generated": self._sample_count,
            "buffer_fill": (self._write_idx - self._read_idx) % SIGNAL_BUFFER_SIZE,
            "max30102_writes": self._max30102_writes,
            "max30102_clipped": self._max30102_clipped,
        }

    def reset_stats(self) -> None:
        self._overrun_count = 0
        self._underrun_count = 0
        self._dropped_samples = 0
        self._ac_comp_clipped = 0
        self._max30102_writes = 0
        self._max30102_clipped = 0

    # ─── Generation Loop (background thread) ───
    def _generate_one_tick(self) -> None:
        """Advance the model by one 100 Hz tick and upsample into the ring."""
        self._prev_ir = self._curr_ir
        self._prev_red = self._curr_red
        self._prev_disp_ir = self._curr_disp_ir
        self._prev_disp_red = self._curr_disp_red

        with self._model_lock:
            if self._waveform_clip is not None:
                stamp = self._clip_tick * MODEL_DT_PPG
                if stamp >= self._waveform_clip.duration:
                    self.state = SIG_STOPPED
                    self._running = False
                    return
                ir_v, red_v = self._waveform_clip.at(stamp)
                disp_ir, disp_red = ir_v, red_v
                if self._max30102:   # the clip's pulse at the preset DC/AC on the RED on-level
                    red_v = disp_red = self._max30102_clip_level(ir_v, red_v)
                self._clip_tick += 1
            elif self._calibration is None:
                ir_v, red_v, disp_ir, disp_red = self.ppg_model.generate_both_samples(MODEL_DT_PPG)
                stamp = self.ppg_model.simulated_time_s
                if not self._max30102:   # AC balance trims the OPT101 receive path, not the sensor's
                    ir_v, red_v = self._compensate(ir_v, red_v, disp_ir, disp_red)
            else:
                frequency, ir_level_mv, red_level_mv, swing_mv = self._calibration
                self._cal_time += MODEL_DT_PPG
                wave = swing_mv * math.sin(2 * math.pi * frequency * self._cal_time)
                ir_v, red_v = (ir_level_mv + wave) / 1000, (red_level_mv + wave) / 1000
                disp_ir, disp_red, stamp = ir_v, red_v, self._cal_time
            ir_code, red_code = dac_voltage_to_code(ir_v), dac_voltage_to_code(red_v)
            self._display_history.append((stamp, disp_ir, disp_red))
            if self._recording:
                p = self.ppg_params
                if len(self._record_samples) == self._record_samples.maxlen:
                    self._record_dropped += 1
                self._record_samples.append((ir_code, red_code,
                    p.heart_rate, p.spo2, p.resp_rate, p.perfusion_index,
                    self._waveform_clip.name if self._waveform_clip is not None else CONDITION_NAMES[p.condition], stamp))

        # DAC voltage mapping: 0 V → 0, 3.28 V → 4095 (12-bit)
        self._curr_ir, self._curr_red = ir_code, red_code
        if self._prev_ir is None:
            self._prev_ir, self._prev_red = self._curr_ir, self._curr_red
            self._prev_disp_ir, self._prev_disp_red = disp_ir, disp_red
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
                if not self._running:
                    break
                self._generate_one_tick()

            # Sleep to the next 10 ms model deadline (not a 0.5 ms poll, which
            # woke this thread 2000×/s on the Pi); capped so stop() stays prompt.
            time.sleep(ticker.wait_seconds(time.perf_counter(), GENERATION_MAX_WAIT_S))

    def _dac_loop(self):
        """DAC thread — drains the ring to the MCP4725 pair at FS_TIMER_HZ.

        In MAX30102 mode (Classic, Model and Recording clips; not the calibration output) the ring sets the RED on-level at FS_TIMER_HZ and a flicker
        writer (hw/max30102_flicker.py) writes RED at MAX30102_WRITE_HZ alternating 0 and that level; IR is
        held at 0 and the OPT101 acquisition is paused, its I2C reads would make the write times irregular."""
        ticker = FixedRateTicker(1.0 / FS_TIMER_HZ, time.perf_counter())
        peak = dac_voltage_to_code(MAX30102_PEAK_MAX_MV / 1000.0)
        writer = None
        try:
            while self._running:
                flicker = self.state == SIG_RUNNING and self._max30102 and self._calibration is None
                if flicker and writer is None:
                    writer = self._flicker_start(peak)
                elif not flicker and writer is not None:
                    writer = self._flicker_stop(writer)

                if self.state != SIG_RUNNING:
                    time.sleep(0.01)
                    ticker.reset(time.perf_counter())
                    continue

                for _ in range(ticker.due(time.perf_counter())):
                    with self._buf_lock:
                        sample = self._pop_dac_sample()
                    if sample is None:
                        break
                    if writer is not None:
                        if sample[1] > peak:
                            self._max30102_clipped += 1
                        writer.set_level(min(sample[1], peak))
                    else:
                        self.dac_manager.set_values(sample[0], sample[1])

                if isinstance(writer, ThreadFlicker):
                    writer.service()
                    now = time.perf_counter()
                    time.sleep(min(self._flick_ticker.wait_seconds(now, LOOP_YIELD_S),
                                   ticker.wait_seconds(now, LOOP_YIELD_S)))
                    continue

                # Two I2C writes already consume much of a 1 ms tick on Pi 4.
                # A fixed extra 0.5 ms sleep here caused sustained buffer growth.
                time.sleep(ticker.wait_seconds(time.perf_counter(), LOOP_YIELD_S))
        finally:
            self._flicker_stop(writer)
            self.dac_manager.set_values(DAC_IDLE_VALUE, DAC_IDLE_VALUE)

    def _flicker_start(self, peak):
        """Begin the MAX30102 output: IR to 0, OPT101 reads paused, RED writer started."""
        self.dac_manager.set_values(DAC_IDLE_VALUE, DAC_IDLE_VALUE)
        self._rx_paused = False
        try:
            from hw.opt101_rx import OPT101Receiver
            rx = OPT101Receiver.get_instance()
            if rx.is_running:
                rx.stop()
                self._rx_paused = True
        except Exception:
            log.exception("[SignalEngine] Could not pause the OPT101 acquisition")
        if DRY_RUN or not self.dac_manager.is_ready:
            self._flick_ticker = FixedRateTicker(1.0 / MAX30102_WRITE_HZ, time.perf_counter())
            return ThreadFlicker(self.dac_manager, MAX30102_WRITE_HZ, peak, self._flick_ticker)
        log.info(f"[SignalEngine] MAX30102 output: RED at {MAX30102_WRITE_HZ} writes/s in its own process")
        return FlickerProcess(I2C_BUS, DAC_ADDR_RED, MAX30102_WRITE_HZ, peak)

    def _flicker_stop(self, writer):
        """End the MAX30102 output: writer stopped, RED parked, OPT101 reads resumed. Returns None."""
        if writer is None:
            return None
        writes, errors, status = writer.stop()
        self._max30102_writes += writes
        if errors or status:
            log.error(f"[SignalEngine] MAX30102 writer: {errors} I2C errors, exit status {status}")
        self.dac_manager.set_values(DAC_IDLE_VALUE, DAC_IDLE_VALUE)
        if self._rx_paused:
            self._rx_paused = False
            try:
                from hw.opt101_rx import OPT101Receiver
                OPT101Receiver.get_instance().start()
            except Exception:
                log.exception("[SignalEngine] Could not resume the OPT101 acquisition")
        return None

    def start_waveform(self, clip):
        """Play one finite clip through the same single DAC writer as Classic."""
        if not self.dac_manager.is_ready:
            raise RuntimeError("MCP4725 output is unavailable")
        if self.recording:
            raise RuntimeError("Stop the Classic recording before playing a waveform clip")
        return self.start_simulation(self.ppg_params.condition, waveform_clip=clip)

    @property
    def is_waveform_playing(self):
        return self._running and self._waveform_clip is not None

    @property
    def current_clip(self):
        """The clip of the latest start (kept after it runs out), or None when the latest start was not a clip."""
        return self._waveform_clip

    @property
    def waveform_position_s(self):
        """Seconds of the clip already sent to the output; it does not advance while paused."""
        with self._model_lock:
            return self._clip_tick * MODEL_DT_PPG

    def _max30102_clip_level(self, ir_v, red_v):
        """With the model lock held: RED on-level (V) for a clip sample in MAX30102 mode.

        A Model or Recording clip carries its own DC/AC (the Model page sliders, or whatever was recorded). Its
        pulse lane (pulse_span) is mapped linearly so its 2nd-98th percentile span runs from the preset DC to
        DC + AC; the shape, beat timing and respiration of the clip are kept."""
        clip = self._waveform_clip
        if self._clip_span is None or self._clip_span[0] is not clip:
            self._clip_span = (clip, *pulse_span(clip))
        _, lane, low, high = self._clip_span
        if high - low < MAX30102_MIN_CLIP_SPAN_V:
            return MAX30102_DC_MV / 1000.0
        value = ir_v if lane == 1 else red_v
        level = (MAX30102_DC_MV + (value - low) / (high - low) * MAX30102_AC_MV) / 1000.0
        return max(0.0, min(DAC_FULLSCALE_V, level))

    # Model mutations and generation share one lock, so a tick sees complete settings.
    def _update_model(self, method, *args, **kwargs):
        with self._model_lock:
            getattr(self.ppg_model, method)(*args, **kwargs)
            self.ppg_params = self.ppg_model.params.copy()
            self._enforce_max30102_preset()

    def load_parameters(self, params):
        with self._model_lock:
            self.ppg_model.set_parameters(params)
            self.ppg_params = self.ppg_model.params.copy()
            self.ac_dc_locked = self.ppg_params.lock_ac and self.ppg_params.lock_dc
            self._enforce_max30102_preset()

    # ─── MAX30102 sensor mode (config.MAX30102_*) ───
    @property
    def max30102_mode(self) -> bool:
        return self._max30102

    def set_max30102_mode(self, enabled) -> None:
        """RED-only on/off output with the preset DC/AC for a MAX30102; HR, SpO2, RR and noise stay the user's.

        The amplitude settings in force before are kept and put back when the mode is switched off. While the
        mode is on, every parameter change (panel, phone) is followed by the preset again."""
        enabled = bool(enabled)
        with self._model_lock:
            if enabled == self._max30102:
                return
            params = self.ppg_model.params.copy()
            if enabled:
                self._max30102_saved = {k: getattr(params, k) for k in MAX30102_SAVED_FIELDS}
                self._max30102 = True
                self._enforce_max30102_preset()
            else:
                for key, value in (self._max30102_saved or {}).items():
                    setattr(params, key, value)
                self._max30102, self._max30102_saved = False, None
                self.ppg_model.set_parameters(params)
                self.ppg_params = self.ppg_model.params.copy()
                self.ac_dc_locked = params.lock_ac and params.lock_dc
        log.info(f"[SignalEngine] MAX30102 mode {'on' if enabled else 'off'}")

    def _enforce_max30102_preset(self):
        """With the model lock held: put the preset amplitude back if a change moved it."""
        if not self._max30102:
            return
        params = self.ppg_model.params
        if all(getattr(params, key) == value for key, value in MAX30102_PRESET.items()):
            return
        params = params.copy()
        for key, value in MAX30102_PRESET.items():
            setattr(params, key, value)
        self.ppg_model.set_parameters(params)
        self.ppg_params = self.ppg_model.params.copy()
        self.ac_dc_locked = False

    def params_for_save(self):
        """Parameters to persist: in MAX30102 mode, the amplitude settings from before the mode, not the preset."""
        with self._model_lock:
            params = self.ppg_params.copy()
            for key, value in (self._max30102_saved or {}).items():
                setattr(params, key, value)
            return params

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

    def update_spo2_target(self, spo2):
        self._update_model("set_spo2_target", spo2)

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

    def start_calibration(self, frequency_hz, ir_level_mv, red_level_mv=None, swing_mv=0.0):
        """Calibration output: level + swing * sin(2*pi*f*t) per channel, in mV.

        Levels are DAC output millivolts. IR and RED take separate levels
        because each LED -> OPT101 path has its own gain and range; swing 0
        holds a steady level."""
        from config import DAC_FULLSCALE_MV
        if red_level_mv is None:
            red_level_mv = ir_level_mv
        if not math.isfinite(frequency_hz) or not 1 <= frequency_hz <= 10:
            raise ValueError("Calibration frequency must be 1–10 Hz")
        if not math.isfinite(swing_mv) or swing_mv < 0:
            raise ValueError("Calibration swing must be ≥ 0 mV")
        for level in (ir_level_mv, red_level_mv):
            if not math.isfinite(level) or level - swing_mv < 0 or level + swing_mv > DAC_FULLSCALE_MV:
                raise ValueError(f"Calibration level ± swing must stay within 0–{DAC_FULLSCALE_MV:g} mV")
        self.start_simulation(self.ppg_params.condition,
                              calibration=(frequency_hz, ir_level_mv, red_level_mv, swing_mv))

    def set_ac_compensation(self, ir_factor, red_factor):
        """Scale the AC part of the Classic output written to the DACs (core/ac_balance.py); 1.0, 1.0 is off.

        The display history keeps the set waveform, so the TX plot shows what the receiver should get."""
        factors = (float(ir_factor), float(red_factor))
        if not all(math.isfinite(f) and 0.1 <= f <= 4.0 for f in factors):
            raise ValueError(f"AC compensation out of range: {factors}")
        self._ac_comp = factors

    @property
    def ac_compensation(self):
        return self._ac_comp

    @property
    def ac_balance_active(self):
        return self._ac_comp != (1.0, 1.0)

    def _compensate(self, ir_v, red_v, disp_ir, disp_red):
        """ir_v = DC + offset + disp: scale only disp. The model clamped the uncompensated value; clamp again."""
        k_ir, k_red = self._ac_comp
        if k_ir == 1.0 and k_red == 1.0:
            return ir_v, red_v
        ir_v, red_v = ir_v + (k_ir - 1.0) * disp_ir, red_v + (k_red - 1.0) * disp_red
        if not (0.0 <= ir_v <= DAC_FULLSCALE_V and 0.0 <= red_v <= DAC_FULLSCALE_V):
            self._ac_comp_clipped += 1
        return min(max(ir_v, 0.0), DAC_FULLSCALE_V), min(max(red_v, 0.0), DAC_FULLSCALE_V)

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

    @property
    def recording(self) -> bool:
        """Recording state shared by the Tk GUI, BLE commands and status echo."""
        return self._recording

    @property
    def record_file(self) -> str:
        """Short shared basename for the current engine recording."""
        return self._record_file if self._recording else ""

    def set_csv_logger(self, logger):
        """Replace the CSV sink (tests/headless runs). Stops any live recording."""
        if logger is self._csv_logger:
            return
        if self._recording:
            self.stop_recording()
        self._csv_logger = logger

    def start_recording(self, filename=None) -> bool:
        """Start CSV recording from the engine. Idempotent — returns the state.

        Requires a running simulation: the sample pump is fed by the 100 Hz
        model tick, so recording a stopped engine would write an empty file.
        """
        if self._recording:
            return True
        if self.is_waveform_playing:
            log.warning("[SignalEngine] Use waveform CSV export for clips; Classic setpoints do not describe GAN output")
            return False
        if not self._running:
            log.warning("[SignalEngine] start_recording ignored — simulation is stopped")
            return False
        with self._record_ctl_lock:
            if self._recording:
                return True
            if self._csv_logger is None:
                from core.csv_logger import CSVLogger
                self._csv_logger = CSVLogger()
            logger = self._csv_logger
            logger.start(filename)
            if not logger.is_logging:
                return False
            self._record_file = str(getattr(logger, "active_filename", "") or "")
            self.set_recording(True)
            self._record_pump_stop.clear()
            self._record_pump = threading.Thread(
                target=self._record_pump_loop, daemon=True, name="RecordPump")
            self._record_pump.start()
            log.info("[SignalEngine] Recording started (engine-owned sink)")
            return True

    def stop_recording(self, save: bool = True) -> bool:
        """Stop CSV recording and flush/discard the buffered tail. Idempotent."""
        with self._record_ctl_lock:
            if not self._recording and (self._csv_logger is None
                                        or not self._csv_logger.is_logging):
                return False
            self.set_recording(False)
            self._record_pump_stop.set()
            pump, self._record_pump = self._record_pump, None
            if pump is not None:
                pump.join(timeout=2.0)
            self.pump_recording()
            logger = self._csv_logger
            if logger is not None:
                logger.stop(save=save)
            log.info("[SignalEngine] Recording stopped")
            return True

    def pump_recording(self) -> int:
        """Drain buffered model rows into the CSV sink. Returns rows written.

        Safe from any thread. The drain and the writes of one batch hold one lock: the record pump thread and the
        Classic page both pump, and with only the drain locked their batches were written interleaved (a row
        from the later batch landed among the earlier one's, and the file was refused for its timestamps).
        """
        logger = self._csv_logger
        if logger is None or not logger.is_logging:
            return 0
        rows = 0
        with self._record_write_lock:
            for sample in self.drain_recording():
                logger.log_data(*sample)
                rows += 1
        return rows

    def _record_pump_loop(self):
        while not self._record_pump_stop.wait(RECORD_PUMP_INTERVAL_S):
            self.pump_recording()

    # ─── Playback shared state (protocol v2 "pb") ───
    def set_playback_state(self, active: bool, state: str = "", filename: str = ""):
        with self._playback_lock:
            self.pb_active = bool(active)
            self.pb_state = str(state) if self.pb_active else ""
            self.pb_file = str(filename) if self.pb_active else ""

    def get_playback_state(self):
        with self._playback_lock:
            return self.pb_active, self.pb_state, self.pb_file

    def request_playback(self, action: str, filename: str = "") -> bool:
        """Queue a programmatic playback action for the Tk thread to apply."""
        with self._playback_lock:
            if len(self._playback_requests) == self._playback_requests.maxlen:
                return False
            self._playback_requests.append((str(action), str(filename)))
            return True

    def take_playback_request(self):
        with self._playback_lock:
            return self._playback_requests.popleft() if self._playback_requests else None

    @property
    def is_running(self) -> bool:
        return bool(self._running)

    @property
    def pb_code(self) -> int:
        """Playback state as the protocol v2 enum (0 inactive, 1 playing, 2 paused)."""
        with self._playback_lock:
            if not self.pb_active:
                return PB_INACTIVE
            return PB_PAUSED if self.pb_state == "paused" else PB_PLAYING

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
            self._enforce_max30102_preset()

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
