"""
ppg_model.py — PPG waveform synthesis model (Raspberry Pi 4 port)

Faithful port of ppg_model.cpp (823 lines).
3-component Gaussian sum model (Allen 2007) with 6 clinical conditions,
dual-channel (IR/Red) generation, respiratory modulations (BW, AM, FM/RSA),
and beat-to-beat HR/PI variability.

References:
  - Allen J (2007): PPG base morphology
  - Sun X et al. (2024): PI beat-to-beat variability
  - Charlton et al. (2018): Respiratory modulations
"""

import math
import random

# ─── PPG Model Constants (Allen 2007) ───
PPG_SYSTOLIC_POS    = 0.15
PPG_NOTCH_POS       = 0.28
PPG_DIASTOLIC_POS   = 0.35

PPG_SYSTOLIC_WIDTH  = 0.055
PPG_DIASTOLIC_WIDTH = 0.10
PPG_NOTCH_WIDTH     = 0.02

PPG_BASE_SYSTOLIC_AMPL   = 1.0
PPG_BASE_DIASTOLIC_RATIO = 0.3
PPG_BASE_DICROTIC_DEPTH  = 0.18

PPG_AC_SCALE_PER_PI = 15.0   # AC = PI × 15 mV

PPG_SYSTOLE_BASE_MS = 300.0
PPG_SYSTOLE_MIN_MS  = 250.0
PPG_SYSTOLE_MAX_MS  = 350.0

# ─── PPG Condition Enum ───
COND_NORMAL           = 0
COND_ARRHYTHMIA       = 1
COND_WEAK_PERFUSION   = 2
COND_VASOCONSTRICTION = 3
COND_STRONG_PERFUSION = 4
COND_VASODILATION     = 5
COND_COUNT            = 6

CONDITION_NAMES = [
    "Normal", "Arrhythmia", "Weak Perf.",
    "Vasocnstr.", "Strong Perf.", "Vasodilat."
]


class ConditionRanges:
    """Per-condition dynamic ranges and waveform shape parameters."""
    __slots__ = (
        "hr_min", "hr_max", "hr_cv",
        "pi_min", "pi_max", "pi_cv",
        "systolic_ampl", "diastolic_ampl", "dicrotic_depth",
    )

    def __init__(self, hr_min=60, hr_max=120, hr_cv=0.02,
                 pi_min=2.9, pi_max=6.1, pi_cv=0.10,
                 systolic_ampl=1.0, diastolic_ampl=0.3, dicrotic_depth=0.18):
        self.hr_min = hr_min; self.hr_max = hr_max; self.hr_cv = hr_cv
        self.pi_min = pi_min; self.pi_max = pi_max; self.pi_cv = pi_cv
        self.systolic_ampl = systolic_ampl
        self.diastolic_ampl = diastolic_ampl
        self.dicrotic_depth = dicrotic_depth


# ─── Parameter Limits ───
class ParamRange:
    __slots__ = ("min", "max", "default")
    def __init__(self, mn, mx, df):
        self.min = mn; self.max = mx; self.default = df


class PPGLimits:
    __slots__ = ("heart_rate", "perfusion_index", "spo2", "resp_rate",
                 "noise_level", "dicrotic_notch", "amplification")
    def __init__(self, hr, pi, spo2, rr, noise, notch, amp):
        self.heart_rate = hr; self.perfusion_index = pi; self.spo2 = spo2
        self.resp_rate = rr; self.noise_level = noise
        self.dicrotic_notch = notch; self.amplification = amp


def get_ppg_limits(condition: int) -> PPGLimits:
    """Return parameter limits for a given PPG condition."""
    _LIMITS = {
        COND_NORMAL: PPGLimits(
            ParamRange(60, 100, 75), ParamRange(2.9, 6.1, 3.0),
            ParamRange(95, 100, 98), ParamRange(12, 20, 16),
            ParamRange(0, 0.10, 0), ParamRange(0.15, 0.35, 0.25),
            ParamRange(0.5, 2.0, 1.0)),
        COND_ARRHYTHMIA: PPGLimits(
            ParamRange(60, 180, 80), ParamRange(1.0, 5.0, 2.5),
            ParamRange(90, 98, 95), ParamRange(12, 24, 18),
            ParamRange(0, 0.10, 0), ParamRange(0.10, 0.30, 0.20),
            ParamRange(0.5, 2.0, 1.0)),
        COND_WEAK_PERFUSION: PPGLimits(
            ParamRange(70, 120, 90), ParamRange(0.5, 2.1, 1.0),
            ParamRange(85, 95, 90), ParamRange(14, 28, 20),
            ParamRange(0, 0.10, 0), ParamRange(0.0, 0.10, 0.05),
            ParamRange(0.5, 2.0, 1.0)),
        COND_VASOCONSTRICTION: PPGLimits(
            ParamRange(65, 110, 80), ParamRange(0.5, 0.8, 0.7),
            ParamRange(88, 96, 92), ParamRange(12, 22, 18),
            ParamRange(0, 0.10, 0), ParamRange(0.0, 0.10, 0.05),
            ParamRange(0.5, 2.0, 1.0)),
        COND_STRONG_PERFUSION: PPGLimits(
            ParamRange(60, 90, 70), ParamRange(7.0, 20.0, 10.0),
            ParamRange(96, 100, 99), ParamRange(10, 18, 14),
            ParamRange(0, 0.10, 0), ParamRange(0.25, 0.45, 0.35),
            ParamRange(0.5, 2.0, 1.0)),
        COND_VASODILATION: PPGLimits(
            ParamRange(60, 90, 65), ParamRange(5.0, 10.0, 7.0),
            ParamRange(94, 99, 97), ParamRange(10, 20, 15),
            ParamRange(0, 0.10, 0), ParamRange(0.20, 0.40, 0.30),
            ParamRange(0.5, 2.0, 1.0)),
    }
    return _LIMITS.get(condition, _LIMITS[COND_NORMAL])


class PPGParameters:
    """Mutable PPG parameter container."""
    __slots__ = ("condition", "heart_rate", "perfusion_index", "spo2",
                 "resp_rate", "noise_level", "dicrotic_notch", "amplification")

    def __init__(self):
        self.condition = COND_NORMAL
        self.heart_rate = 75.0
        self.perfusion_index = 3.0
        self.spo2 = 98.0
        self.resp_rate = 16.0
        self.noise_level = 0.0
        self.dicrotic_notch = 0.25
        self.amplification = 1.0

    def copy(self):
        p = PPGParameters()
        for attr in self.__slots__:
            setattr(p, attr, getattr(self, attr))
        return p


def _clamp(val, mn, mx):
    return max(mn, min(mx, val))


class PPGModel:
    """
    Physiological PPG waveform generator.
    3-component Gaussian sum (Allen 2007) with respiratory modulations.
    """

    def __init__(self):
        self._has_pending = False
        self._pending_params = None

        # Gaussian RNG state (Box-Muller)
        self._gauss_has_spare = False
        self._gauss_spare = 0.0

        self.params = PPGParameters()
        self.cond_ranges = ConditionRanges()
        self.reset()

    # ─────────────────────────── RESET ───────────────────────────
    def reset(self):
        self.phase_in_cycle = 0.0
        self.current_rr = 60.0 / 75.0
        self.beat_count = 0
        self.motion_noise = 0.0
        self.baseline_wander_phase = 0.0

        self._gauss_has_spare = False
        self._gauss_spare = 0.0

        self.current_hr = 75.0
        self.current_pi = 3.0
        self.dc_baseline = 1500.0

        self.last_sample_value = self.dc_baseline
        self.last_ac_value = 0.0
        self.last_ir_value = self.dc_baseline
        self.last_red_value = self.dc_baseline
        self.last_ac_ir = 0.0
        self.last_ac_red = 0.0
        self.last_display_ir = 0.0
        self.resp_phase = 0.0

        # Waveform shape
        self.systolic_amplitude = PPG_BASE_SYSTOLIC_AMPL
        self.systolic_width = PPG_SYSTOLIC_WIDTH
        self.diastolic_amplitude = PPG_BASE_DIASTOLIC_RATIO
        self.diastolic_width = PPG_DIASTOLIC_WIDTH
        self.dicrotic_depth = PPG_BASE_DICROTIC_DEPTH
        self.dicrotic_width = PPG_NOTCH_WIDTH

        # Phase times
        self.systole_fraction = self._calculate_systole_fraction(self.current_hr)
        self.systole_time = self.current_rr * 1000.0 * self.systole_fraction
        self.diastole_time = self.current_rr * 1000.0 * (1.0 - self.systole_fraction)

        # Measurement tracking
        self.measured_peak = self.dc_baseline
        self.measured_valley = self.dc_baseline
        self.measured_notch = self.dc_baseline
        self.current_cycle_peak = 0.0
        self.current_cycle_valley = 99999.0
        self.current_cycle_notch = 99999.0
        self.simulated_time_ms = 0.0
        self.last_peak_time_ms = 0.0
        self.last_valley_time_ms = 0.0
        self.cycle_start_time_ms = 0.0
        self.previous_phase = 0.0
        self.measured_rr_ms = self.current_rr * 1000.0
        self.measured_systole_ms = self.systole_time
        self.measured_diastole_ms = self.diastole_time

    # ─────────────────────── CONDITION RANGES ───────────────────────
    def _init_condition_ranges(self):
        c = self.params.condition
        _MAP = {
            COND_NORMAL:           ConditionRanges(60, 120, 0.02, 2.9, 6.1, 0.10, 1.0, 0.3, 0.18),
            COND_ARRHYTHMIA:       ConditionRanges(60, 180, 0.15, 1.0, 5.0, 0.20, 1.0, 0.4, 0.20),
            COND_WEAK_PERFUSION:   ConditionRanges(70, 120, 0.02, 0.5, 2.1, 0.15, 1.0, 0.3, 0.05),
            COND_VASOCONSTRICTION: ConditionRanges(65, 110, 0.02, 0.7, 0.8, 0.10, 1.0, 0.25, 0.05),
            COND_STRONG_PERFUSION: ConditionRanges(60,  90, 0.02, 7.0, 20.0, 0.10, 1.0, 0.5, 0.25),
            COND_VASODILATION:     ConditionRanges(60,  90, 0.02, 5.0, 10.0, 0.10, 1.0, 0.5, 0.25),
        }
        self.cond_ranges = _MAP.get(c, _MAP[COND_NORMAL])

    # ─────────────────────── PARAMETER SETTING ───────────────────────
    def set_parameters(self, params: PPGParameters):
        self.params = params.copy()
        self._init_condition_ranges()
        self._apply_condition_modifiers()
        self.current_hr = self._generate_dynamic_hr()
        self.current_rr = 60.0 / self.current_hr
        self.current_pi = self._generate_dynamic_pi()
        self.systole_fraction = self._calculate_systole_fraction(self.current_hr)
        self.systole_time = self.current_rr * 1000.0 * self.systole_fraction
        self.diastole_time = self.current_rr * 1000.0 * (1.0 - self.systole_fraction)
        self.measured_rr_ms = self.current_rr * 1000.0
        self.measured_systole_ms = self.systole_time
        self.measured_diastole_ms = self.diastole_time

    def set_pending_parameters(self, params: PPGParameters):
        self._pending_params = params.copy()
        self._has_pending = True

    def _apply_condition_modifiers(self):
        self.systolic_amplitude = self.cond_ranges.systolic_ampl
        self.diastolic_amplitude = self.cond_ranges.diastolic_ampl
        self.dicrotic_depth = self.cond_ranges.dicrotic_depth
        self.systolic_width = PPG_SYSTOLIC_WIDTH
        self.diastolic_width = PPG_DIASTOLIC_WIDTH
        self.dicrotic_width = PPG_NOTCH_WIDTH
        self.motion_noise = 0.0

    # ─────────────────────── HEART RATE SETTER ───────────────────────
    def set_heart_rate(self, hr: float):
        hr = _clamp(hr, 40.0, 180.0)
        self.params.heart_rate = hr
        self.current_hr = hr
        self.current_rr = 60.0 / hr
        self.systole_fraction = self._calculate_systole_fraction(hr)
        self.systole_time = self.current_rr * 1000.0 * self.systole_fraction
        self.diastole_time = self.current_rr * 1000.0 * (1.0 - self.systole_fraction)

    def set_perfusion_index(self, pi: float):
        pi = _clamp(pi, 0.5, 20.0)
        self.params.perfusion_index = pi
        self.current_pi = pi

    def set_noise_level(self, noise: float):
        self.params.noise_level = _clamp(noise, 0.0, 1.0)

    def set_dc_baseline(self, dc: float):
        self.dc_baseline = dc

    # ─────────────────────── DYNAMIC HR/PI ───────────────────────
    def _generate_dynamic_hr(self) -> float:
        cr = self.cond_ranges
        hr_base = cr.hr_min + random.random() * (cr.hr_max - cr.hr_min)
        sigma = hr_base * cr.hr_cv
        hr = hr_base + self._gaussian_random(0.0, sigma)
        return _clamp(hr, cr.hr_min, cr.hr_max)

    def _generate_dynamic_pi(self) -> float:
        cr = self.cond_ranges
        pi_base = cr.pi_min + random.random() * (cr.pi_max - cr.pi_min)
        sigma = pi_base * cr.pi_cv
        pi = pi_base + self._gaussian_random(0.0, sigma)
        return _clamp(pi, cr.pi_min, cr.pi_max)

    # ─────────────────────── SYSTOLE FRACTION ───────────────────────
    @staticmethod
    def _calculate_systole_fraction(hr: float) -> float:
        systole_ms = PPG_SYSTOLE_BASE_MS - 0.5 * (hr - 60.0)
        systole_ms = _clamp(systole_ms, PPG_SYSTOLE_MIN_MS, PPG_SYSTOLE_MAX_MS)
        rr_ms = 60000.0 / hr
        fraction = systole_ms / rr_ms
        return _clamp(fraction, 0.20, 0.60)

    # ─────────────────────── NEXT RR ───────────────────────
    def _generate_next_rr(self) -> float:
        self.current_hr = self.params.heart_rate
        rr_mean = 60.0 / self.current_hr
        rr_std = rr_mean * self.cond_ranges.hr_cv

        # Arrhythmia: occasional ectopic beats
        if self.params.condition == COND_ARRHYTHMIA:
            if random.randint(0, 99) < 15:
                rr_mean *= 0.7

        # FM (RSA)
        rsa = 0.05 * math.sin(self.resp_phase)
        rr_mean *= (1.0 + rsa)

        rr = rr_mean + self._gaussian_random(0.0, rr_std)
        rr = _clamp(rr, 0.3, 2.0)

        self.systole_fraction = self._calculate_systole_fraction(self.current_hr)
        self.systole_time = rr * 1000.0 * self.systole_fraction
        self.diastole_time = rr * 1000.0 * (1.0 - self.systole_fraction)
        return rr

    # ─────────────────────── PULSE SHAPE ───────────────────────
    def _compute_pulse_shape(self, phase: float) -> float:
        phase = phase % 1.0
        if phase < 0:
            phase += 1.0

        systolic = self.systolic_amplitude * math.exp(
            -(phase - PPG_SYSTOLIC_POS) ** 2 / (2.0 * self.systolic_width ** 2))
        diastolic = self.diastolic_amplitude * math.exp(
            -(phase - PPG_DIASTOLIC_POS) ** 2 / (2.0 * self.diastolic_width ** 2))
        notch = self.dicrotic_depth * self.systolic_amplitude * math.exp(
            -(phase - PPG_NOTCH_POS) ** 2 / (2.0 * self.dicrotic_width ** 2))

        pulse = systolic + diastolic - notch
        return self._normalize_pulse(pulse)

    @staticmethod
    def _normalize_pulse(raw: float) -> float:
        PULSE_MIN = 0.0
        PULSE_MAX = 1.4
        normalized = (raw - PULSE_MIN) / (PULSE_MAX - PULSE_MIN)
        return _clamp(normalized, 0.0, 1.0)

    # ─────────────────────── BEAT DETECTION ───────────────────────
    def _detect_beat_and_apply_pending(self):
        self.beat_count += 1
        if self._has_pending and self._pending_params is not None:
            self.set_parameters(self._pending_params)
            self._has_pending = False
        self.current_rr = self._generate_next_rr()
        self.current_pi = self._generate_dynamic_pi()
        self.measured_rr_ms = self.current_rr * 1000.0

    # ─────────────────────── DUAL CHANNEL GENERATION ───────────────────────
    def generate_both_samples(self, delta_time: float):
        """
        Generate dual-channel PPG samples (IR and Red).

        Args:
            delta_time: Time step in seconds (typically MODEL_DT_PPG = 0.01s).

        Returns:
            Tuple (signal_ir_mv, signal_red_mv, display_ir_mv).
        """
        # Advance phase
        self.phase_in_cycle += delta_time / self.current_rr
        if self.phase_in_cycle >= 1.0:
            self.phase_in_cycle = self.phase_in_cycle % 1.0
            self._detect_beat_and_apply_pending()

        # Pulse shape
        pulse = self._compute_pulse_shape(self.phase_in_cycle)

        # Dual channel: SpO2 → R → AC_red
        r_value = (110.0 - self.params.spo2) / 25.0
        ac_ir = self.current_pi * PPG_AC_SCALE_PER_PI
        ac_red = ac_ir * r_value

        ac_val_ir = pulse * ac_ir
        ac_val_red = pulse * ac_red

        self.last_ac_ir = ac_val_ir
        self.last_ac_red = ac_val_red

        # Respiratory modulations
        self.resp_phase += delta_time * (2.0 * math.pi * self.params.resp_rate / 60.0)
        self.resp_phase = self.resp_phase % (2.0 * math.pi)

        # Baseline wander (BW)
        self.baseline_wander_phase += delta_time * 0.3
        self.baseline_wander_phase = self.baseline_wander_phase % (2.0 * math.pi)
        wander_amp = 0.002 * self.dc_baseline if self.dc_baseline > 0 else 2.0
        wander = wander_amp * math.sin(self.baseline_wander_phase) + 4.0 * math.sin(self.resp_phase)

        # AM (amplitude modulation)
        am_factor = 1.0 + 0.25 * math.sin(self.resp_phase)
        ac_val_ir *= am_factor
        ac_val_red *= am_factor

        # Display signal (AC + wander, no DC)
        self.last_display_ir = ac_val_ir + wander

        signal_ir = self.dc_baseline + ac_val_ir + wander
        signal_red = self.dc_baseline + ac_val_red + wander

        # Noise
        noise_ir = self.params.noise_level * ac_ir
        noise_red = self.params.noise_level * ac_red
        signal_ir += self._gaussian_random(0.0, noise_ir)
        signal_red += self._gaussian_random(0.0, noise_red)

        if self.dc_baseline > 0:
            signal_ir = max(signal_ir, 0.0)
            signal_red = max(signal_red, 0.0)

        # Measurement tracking
        dt_ms = delta_time * 1000.0
        self.simulated_time_ms += dt_ms
        self._update_measurements(signal_ir)

        self.last_ir_value = signal_ir
        self.last_red_value = signal_red
        self.last_ac_value = ac_val_ir

        return signal_ir, signal_red, self.last_display_ir

    # ─────────────────────── MEASUREMENT TRACKING ───────────────────────
    def _update_measurements(self, signal_val: float):
        p = self.phase_in_cycle
        if 0.10 <= p <= 0.25:
            if signal_val > self.current_cycle_peak:
                self.current_cycle_peak = signal_val
        if p <= 0.08:
            if signal_val < self.current_cycle_valley:
                self.current_cycle_valley = signal_val
        if 0.28 <= p <= 0.35:
            if signal_val < self.current_cycle_notch:
                self.current_cycle_notch = signal_val
        if self.previous_phase <= 0.25 and p > 0.25:
            if self.current_cycle_peak > 0:
                self.measured_peak = self.current_cycle_peak
        if p < self.previous_phase and self.previous_phase > 0.5:
            if self.current_cycle_valley < 99999:
                self.measured_valley = self.current_cycle_valley
            if self.current_cycle_notch < 99999:
                self.measured_notch = self.current_cycle_notch
            if self.cycle_start_time_ms > 0:
                self.measured_rr_ms = self.simulated_time_ms - self.cycle_start_time_ms
            self.last_valley_time_ms = self.simulated_time_ms
            self.cycle_start_time_ms = self.simulated_time_ms
            self.current_cycle_peak = 0.0
            self.current_cycle_valley = 99999.0
            self.current_cycle_notch = 99999.0
        self.previous_phase = p

    # ─────────────────────── GAUSSIAN RNG (Box-Muller) ───────────────────────
    def _gaussian_random(self, mean: float, std: float) -> float:
        if std <= 0:
            return mean
        if self._gauss_has_spare:
            self._gauss_has_spare = False
            return mean + std * self._gauss_spare
        while True:
            u = random.random() * 2.0 - 1.0
            v = random.random() * 2.0 - 1.0
            s = u * u + v * v
            if 0 < s < 1.0:
                break
        s = math.sqrt(-2.0 * math.log(s) / s)
        self._gauss_spare = v * s
        self._gauss_has_spare = True
        return mean + std * u * s

    # ─────────────────────── DAC CONVERSION ───────────────────────
    @staticmethod
    def ac_value_to_dac_12bit(ac_mv: float) -> int:
        AC_MAX_MV = 150.0
        normalized = _clamp(ac_mv / AC_MAX_MV, 0.0, 1.0)
        return int(normalized * 4095.0)

    @staticmethod
    def ppg_sample_to_dac_value(sample_mv: float, dc_baseline: float, max_ac: float) -> int:
        min_v = dc_baseline - max_ac
        max_v = dc_baseline + max_ac
        if max_v <= min_v:
            return 2048
        normalized = _clamp((sample_mv - min_v) / (max_v - min_v), 0.0, 1.0)
        return int(normalized * 4095.0)

    # ─────────────────────── GETTERS ───────────────────────
    def get_condition_name(self) -> str:
        if 0 <= self.params.condition < len(CONDITION_NAMES):
            return CONDITION_NAMES[self.params.condition]
        return "Unknown"

    def get_ac_amplitude(self) -> float:
        return self.current_pi * PPG_AC_SCALE_PER_PI

    def get_measured_hr(self) -> float:
        if self.measured_rr_ms > 0:
            return 60000.0 / self.measured_rr_ms
        return self.current_hr

    def is_in_systole(self) -> bool:
        return self.phase_in_cycle < self.systole_fraction
