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

from models import limits
from models.waveform import PulseShaper, PulseMorphology, WAVE_PPG, validate_kind
from models.respiration import RespirationConfig, RespirationModulator

RESP_FIELDS = {
    "rate_brpm": "resp_rate", "inhale_exhale_ratio": "resp_ie_ratio",
    "baseline_enabled": "resp_mod_baseline", "amplitude_enabled": "resp_mod_amplitude",
    "frequency_enabled": "resp_mod_frequency", "variation_ir_pct": "resp_variation_ir_pct",
    "variation_red_pct": "resp_variation_red_pct", "apnea_enabled": "apnea_enabled",
    "apnea_duration_s": "apnea_duration_s", "apnea_cycle_min": "apnea_cycle_min",
}

from config import DAC_FULLSCALE_V, MODEL_SAMPLE_RATE_PPG
from models.noise import NOISE_PROPORTIONAL, NoiseGenerator
from calibration import (
    r_target_from_spo2,
    validate_coefficients,
    validate_ac_dc,
    ac_red_from_target,
    perfusion_index_from_ac_dc,
    SPO2_COEFF_A_DEFAULT,
    SPO2_COEFF_B_DEFAULT,
)

# ─── PPG Model Constants (Allen 2007, aligned with ppg_model.cpp) ───
# --- Temporal positions (fraction of RR cycle) ---
PPG_SYSTOLIC_POS    = 0.15    # Systolic peak: ~15% of cycle
PPG_NOTCH_POS       = 0.30    # Dicrotic notch: ~30% (aortic valve closure)
PPG_DIASTOLIC_POS   = 0.40    # Diastolic peak: ~40% (reflected wave)

# --- Gaussian widths (normalized std deviation) ---
PPG_SYSTOLIC_WIDTH  = 0.055   # σ systolic (sharp peak)
PPG_DIASTOLIC_WIDTH = 0.10    # σ diastolic (broader)
PPG_NOTCH_WIDTH     = 0.02    # σ notch (fast valvular event)

# --- Base normalized amplitudes ---
PPG_BASE_SYSTOLIC_AMPL   = 1.0    # Systolic amplitude (reference)
PPG_BASE_DIASTOLIC_RATIO = 0.4    # Diastolic/systolic ratio (Allen 2007)
PPG_BASE_DICROTIC_DEPTH  = 0.25   # Notch depth (≥20% for normal)

# --- Pulse-shape normalisation search (see PPGModel._find_raw_pulse_peak) ---
PULSE_PEAK_SCAN_STEPS   = 1000  # coarse scan resolution over one cycle
PULSE_PEAK_REFINE_ITERS = 40    # golden-section refinements around the coarse max

# --- AC/DC ownership (Phase 3) ---
# AC and DC are the master parameters; PI is DERIVED, not the driver:
#     PI = AC / DC × 100   ⇔   AC = PI × DC / 100   (strict clinical relation)
# There is no longer a fixed global "Volts-per-PI" scale. Each channel carries
# its own DC level (DC_ir, DC_red); the IR AC is set (directly, or via the PI
# convenience input as AC_ir = PI/100 · DC_ir) and the Red AC is DERIVED from
# the SpO2 target through the full ratio-of-ratios (see calibration.ac_red_from_
# target). Default DC_ir = DC_red = 1.5 V reproduces the legacy equal-DC model
# exactly: with DC = 1.5 V, AC_ir = PI/100 · 1.5 = PI × 0.015 V.

# -
# -- AC/DC polarity (Phase 1 §22 / E9) ---
# AECG100 supports the pulsatile AC riding ABOVE or BELOW the DC baseline.
# Default is ABOVE-DC, which preserves the existing (pulse-up) morphology
# required by Phase 3 §57; BELOW-DC is selectable (physically matches a
# transmission pulse oximeter, where systolic absorption dips the signal).
POLARITY_ABOVE_DC = 0    # signal = DC + AC·pulse  (legacy default, pulse-up)
POLARITY_BELOW_DC = 1    # signal = DC − AC·pulse  (pulse-down)

DEFAULT_DC_BASELINE_V = 1.5    # default per-channel DC (V); legacy shared baseline

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

    def __init__(self, hr_min=60, hr_max=100, hr_cv=0.02,
                 pi_min=2.9, pi_max=6.1, pi_cv=0.10,
                 systolic_ampl=1.0, diastolic_ampl=0.4, dicrotic_depth=0.25):
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
                 "resp_rate", "noise_level", "dicrotic_notch", "amplification",
                 "spo2_coeff_a", "spo2_coeff_b",
                 "dc_ir_mv", "dc_red_mv", "ac_polarity",
                 "noise_kind", "noise_amplitude_mv", "noise_freq_hz",
                 "noise_seed", "waveform", "ac_ir_mv", "ac_red_mv",
                 "output_dc_offset_mv", "lock_ac", "lock_dc",
                 "sp_ms_ir", "dn_ms_ir", "dp_ms_ir", "sp_ms_red", "dn_ms_red", "dp_ms_red",
                 "resp_ie_ratio", "resp_mod_baseline", "resp_mod_amplitude", "resp_mod_frequency",
                 "resp_variation_ir_pct", "resp_variation_red_pct", "apnea_enabled",
                 "apnea_duration_s", "apnea_cycle_min", "hr_amplitude_enabled",
                 "spo2_coupling_enabled", "variability_enabled")

    def __init__(self):
        self.condition = COND_NORMAL
        self.heart_rate = 75.0
        self.perfusion_index = 3.0
        self.spo2 = 98.0
        self.resp_rate = 16.0
        self.noise_level = 0.0
        self.dicrotic_notch = 0.25
        self.amplification = 1.0
        # SpO2 calibration coefficients (SpO2 = A - B*R). Configurable/persisted
        # (Phase 2); consumed by the R_target derivation below and, later, by the
        # measured-SpO2 path (Phase 6). Defaults reproduce SpO2 = 110 - 25*R.
        self.spo2_coeff_a = SPO2_COEFF_A_DEFAULT
        self.spo2_coeff_b = SPO2_COEFF_B_DEFAULT
        # AC/DC master state (Phase 3). Per-channel DC levels in mV (independent
        # Red/IR) and the AC polarity. Defaults keep DC_ir == DC_red == 1500 mV
        # (1.5 V) so the equal-DC legacy behavior is reproduced exactly. AC is
        # stored optionally: None derives IR AC from PI and Red AC from the
        # full ratio-of-ratios. Explicit Red AC disables SpO2 amplitude control.
        self.dc_ir_mv = DEFAULT_DC_BASELINE_V * 1000.0     # 1500.0 mV
        self.dc_red_mv = DEFAULT_DC_BASELINE_V * 1000.0    # 1500.0 mV
        self.ac_polarity = POLARITY_ABOVE_DC               # legacy pulse-up default
        # Artefact source (models.noise). The default reproduces the legacy
        # behaviour exactly: an AC-proportional artefact driven by noise_level,
        # which is 0.0, so a freshly constructed model is still noise-free.
        # The other kinds are amplitude-absolute (noise_amplitude_mv in mV) so
        # a 5 mV artefact stays 5 mV at PI 0.6 % and at PI 6 %.
        self.noise_kind = NOISE_PROPORTIONAL
        self.noise_amplitude_mv = 0.0
        self.noise_freq_hz = 0.0
        self.noise_seed = None    # None => OS entropy (non-reproducible)

        self.hr_amplitude_enabled = self.spo2_coupling_enabled = self.variability_enabled = True
        self.waveform = WAVE_PPG
        self.ac_ir_mv = None  # None: derive from PI, including legacy config files
        self.ac_red_mv = None  # None: derive from the SpO2 ratio
        self.output_dc_offset_mv = 0.0
        self.lock_ac = self.lock_dc = False
        for channel in ("ir", "red"):
            self.__setattr__("sp_ms_" + channel, 150.0)
            self.__setattr__("dn_ms_" + channel, 300.0)
            self.__setattr__("dp_ms_" + channel, 400.0)
        for source, target in RESP_FIELDS.items():
            setattr(self, target, getattr(RespirationConfig(), source))

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

        # Cached pulse-shape normalisation (invalidated when the shape changes)
        self._pulse_scale_key = None
        self._pulse_scale_cache = 1.0

        # Gaussian RNG state (Box-Muller)
        self._gauss_has_spare = False
        self._gauss_spare = 0.0

        # Physiological coupling options (can be toggled at runtime)
        self.hr_amplitude_enabled = True    # HR → pulse amplitude reduction
        self.spo2_coupling_enabled = True   # SpO2 → vasoconstriction (notch loss)

        # Independent artefact source per channel: IR and Red must not share a
        # stream, otherwise the artefact cancels out of the ratio-of-ratios and
        # SpO2 would be immune to noise — physically wrong.
        self._noise_ir = NoiseGenerator(MODEL_SAMPLE_RATE_PPG)
        self._noise_red = NoiseGenerator(MODEL_SAMPLE_RATE_PPG)

        self.respiration = RespirationModulator()
        self._shapers = {"ir": PulseShaper(), "red": PulseShaper()}
        self.clipped_samples = 0
        self.params = PPGParameters()
        self.cond_ranges = ConditionRanges()
        self._apply_noise_config()
        self.reset()

    # ─────────────────────────── RESET ───────────────────────────
    def reset(self):
        self.respiration.reset()
        self._resp_state = self.respiration.advance(0.0)
        self.clipped_samples = 0
        self.phase_in_cycle = 0.0
        self.current_rr = 60.0 / self.params.heart_rate
        self.beat_count = 0
        self.motion_noise = 0.0
        self.baseline_wander_phase = 0.0

        self._gauss_has_spare = False
        self._gauss_spare = 0.0

        self.current_hr = self.params.heart_rate
        self.current_pi = self.params.perfusion_index
        # Per-channel DC working state in Volts (Phase 3). Independent Red/IR.
        # dc_baseline is retained as a legacy alias equal to dc_ir (the primary
        # channel) for external readers (get_measured_pi, hw.dac_manager helper).
        self.dc_ir = DEFAULT_DC_BASELINE_V      # 1.5 V (clinical: PI = AC/DC × 100%)
        self.dc_red = DEFAULT_DC_BASELINE_V     # 1.5 V (independent Red DC)
        self.ac_polarity = POLARITY_ABOVE_DC    # pulse-up (legacy default)
        self.dc_baseline = self.dc_ir           # legacy alias == dc_ir

        self.last_sample_value = self.dc_baseline
        self.last_ac_value = 0.0
        self.last_ir_value = self.dc_baseline
        self.last_red_value = self.dc_baseline
        self.last_ac_ir = 0.0
        self.last_ac_red = 0.0
        self.last_display_red = 0.0
        self.last_display_ir = 0.0
        self.resp_phase_cycles = 0.0  # Respiratory phase in cycles (like HTML)
        self.simulated_time_s = 0.0   # Total simulated time in seconds (for slow BW)

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

        self._sync_ac_dc_from_params()
        self._apply_condition_modifiers()

    # ─────────────────────── CONDITION RANGES ───────────────────────
    def _init_condition_ranges(self):
        c = self.params.condition
        _MAP = {
            COND_NORMAL:           ConditionRanges(60, 100, 0.02, 2.9, 6.1, 0.10, 1.0, 0.4, 0.25),
            COND_ARRHYTHMIA:       ConditionRanges(60, 180, 0.15, 1.0, 5.0, 0.20, 1.0, 0.4, 0.20),
            COND_WEAK_PERFUSION:   ConditionRanges(70, 120, 0.02, 0.5, 2.1, 0.15, 1.0, 0.3, 0.05),
            COND_VASOCONSTRICTION: ConditionRanges(65, 110, 0.02, 0.7, 0.8, 0.10, 1.0, 0.25, 0.05),
            COND_STRONG_PERFUSION: ConditionRanges(60,  90, 0.02, 7.0, 20.0, 0.10, 1.0, 0.6, 0.35),
            COND_VASODILATION:     ConditionRanges(60,  90, 0.02, 5.0, 10.0, 0.10, 1.0, 0.5, 0.30),
        }
        self.cond_ranges = _MAP.get(c, _MAP[COND_NORMAL])

    # ─────────────────────── PARAMETER SETTING ───────────────────────
    def _sync_ac_dc_from_params(self):
        """Refresh the DC (Volts) / polarity working state from self.params.

        The persisted master state lives on PPGParameters in user-facing mV;
        the generator works in Volts. Kept defensive (getattr) so a params-like
        object without the Phase 3 fields falls back to the legacy 1.5 V shared
        DC and above-DC polarity.
        """
        self.dc_ir = getattr(self.params, "dc_ir_mv", DEFAULT_DC_BASELINE_V * 1000.0) / 1000.0
        self.dc_red = getattr(self.params, "dc_red_mv", DEFAULT_DC_BASELINE_V * 1000.0) / 1000.0
        self.ac_polarity = getattr(self.params, "ac_polarity", POLARITY_ABOVE_DC)
        self.dc_baseline = self.dc_ir    # keep legacy alias in sync

    def set_parameters(self, params: PPGParameters):
        self.params = params.copy()
        if self.params.ac_ir_mv is not None:
            self.params.perfusion_index = self.params.ac_ir_mv / self.params.dc_ir_mv * 100.0
        self._apply_noise_config()
        self.set_respiration(RespirationConfig(**{k: getattr(self.params, v) for k, v in RESP_FIELDS.items()}))
        self._sync_ac_dc_from_params()
        self.set_modelling_options(self.params.hr_amplitude_enabled, self.params.spo2_coupling_enabled, self.params.variability_enabled)
        self._apply_condition_modifiers()
        self.current_hr = limits.HEART_RATE.clamp(self.params.heart_rate)
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
        self.dicrotic_depth = self.params.dicrotic_notch
        self.systolic_width = PPG_SYSTOLIC_WIDTH
        self.diastolic_width = PPG_DIASTOLIC_WIDTH
        self.dicrotic_width = PPG_NOTCH_WIDTH
        self.motion_noise = 0.0

    # ─────────────────────── HEART RATE SETTER ───────────────────────
    def set_heart_rate(self, hr: float):
        hr = limits.HEART_RATE.clamp(hr)
        self.params.heart_rate = hr
        self.current_hr = hr
        self.current_rr = 60.0 / hr
        self.systole_fraction = self._calculate_systole_fraction(hr)
        self.systole_time = self.current_rr * 1000.0 * self.systole_fraction
        self.diastole_time = self.current_rr * 1000.0 * (1.0 - self.systole_fraction)

    def set_perfusion_index(self, pi: float):
        """PI convenience input (backward-compatible).

        PI is a derived quantity in the Phase 3 model, but the UI/BLE still
        expose a PI slider and the condition presets drive PI. Setting PI fixes
        the IR AC magnitude for the waveform via AC_ir = PI/100 · DC_ir (applied
        in generate_both_samples). With the default DC_ir = 1.5 V this reproduces
        the legacy AC_ir = PI × 0.015 V exactly. DC levels are unchanged here.
        """
        pi = limits.PERFUSION_INDEX.clamp(pi)
        if self.params.lock_ac:
            if self.params.lock_dc:
                return
            ac = self.params.ac_ir_mv
            if ac is None:
                ac = self.params.perfusion_index / 100 * self.params.dc_ir_mv
            dc = ac * 100 / pi
            limits.DC_LEVEL_MV.validate(dc)
            limits.validate_dc_with_offset(dc, self.params.output_dc_offset_mv)
            self.params.dc_ir_mv = dc
            self._sync_ac_dc_from_params()
        self.params.perfusion_index = pi
        self.params.ac_ir_mv = pi / 100.0 * self.params.dc_ir_mv
        self.current_pi = pi

    def _apply_noise_config(self):
        """Push the parameter block onto both channel generators.

        The two channels are seeded differently (seed, seed+1) so their
        artefacts are uncorrelated while the pair as a whole stays
        reproducible when params.noise_seed is set.

        Raises:
            ValueError: propagated from NoiseGenerator.configure for an unknown
                kind, a negative amplitude, or a frequency above the usable
                band of the model tick rate.
        """
        p = self.params
        seed_ir = p.noise_seed
        seed_red = None if p.noise_seed is None else p.noise_seed + 1
        self._noise_ir = NoiseGenerator(MODEL_SAMPLE_RATE_PPG, seed=seed_ir)
        self._noise_red = NoiseGenerator(MODEL_SAMPLE_RATE_PPG, seed=seed_red)
        for gen in (self._noise_ir, self._noise_red):
            gen.configure(p.noise_kind,
                          amplitude_mv=p.noise_amplitude_mv,
                          freq_hz=p.noise_freq_hz,
                          level=p.noise_level)

    def set_noise_level(self, noise: float):
        """Legacy 0–1 AC-proportional noise level."""
        self.params.noise_level = _clamp(noise, 0.0, 1.0)
        self._apply_noise_config()

    def set_noise(self, kind: str, amplitude_mv: float = 0.0,
                  freq_hz: float = 0.0, seed=None):
        """Select the artefact kind and its absolute parameters.

        Args:
            kind: one of models.noise.NOISE_KINDS.
            amplitude_mv: RMS (white/motion) or peak (sine/powerline), in mV.
            freq_hz: tone frequency, or the drift cutoff for the motion kind.
            seed: base seed for reproducible runs; None uses OS entropy.

        Raises:
            ValueError: if the kind is unknown, the amplitude is negative, or
                the frequency exceeds what the model tick rate can represent.
                The parameter block is left unchanged when this happens.
        """
        previous = (self.params.noise_kind, self.params.noise_amplitude_mv,
                    self.params.noise_freq_hz, self.params.noise_seed)
        self.params.noise_kind = kind
        self.params.noise_amplitude_mv = amplitude_mv
        self.params.noise_freq_hz = freq_hz
        self.params.noise_seed = seed
        try:
            self._apply_noise_config()
        except ValueError:
            (self.params.noise_kind, self.params.noise_amplitude_mv,
             self.params.noise_freq_hz, self.params.noise_seed) = previous
            self._apply_noise_config()
            raise

    def set_dc_levels(self, dc_ir_mv: float, dc_red_mv: float = None):
        dc_red_mv = dc_ir_mv if dc_red_mv is None else dc_red_mv
        for dc in (dc_ir_mv, dc_red_mv):
            limits.DC_LEVEL_MV.validate(dc)
            limits.validate_dc_with_offset(dc, self.params.output_dc_offset_mv)
        ac = self.params.ac_ir_mv
        if self.params.lock_ac and ac is not None:
            pi = ac / dc_ir_mv * 100.0
        else:
            pi = self.params.perfusion_index
            ac = pi / 100.0 * dc_ir_mv
        self.params.dc_ir_mv, self.params.dc_red_mv = dc_ir_mv, dc_red_mv
        self.params.ac_ir_mv, self.params.perfusion_index = ac, pi
        self.current_pi = pi
        self._sync_ac_dc_from_params()

    def set_ac_dc(self, ac_ir_mv: float, dc_ir_mv: float, dc_red_mv: float = None):
        dc_red_mv = dc_ir_mv if dc_red_mv is None else dc_red_mv
        validate_ac_dc(ac_ir_mv, dc_ir_mv)
        validate_ac_dc(ac_ir_mv, dc_red_mv)
        for dc in (dc_ir_mv, dc_red_mv):
            limits.DC_LEVEL_MV.validate(dc)
            limits.validate_dc_with_offset(dc, self.params.output_dc_offset_mv)
        self.params.dc_ir_mv, self.params.dc_red_mv = dc_ir_mv, dc_red_mv
        self.params.ac_ir_mv = ac_ir_mv
        self.params.perfusion_index = ac_ir_mv / dc_ir_mv * 100.0
        self.current_pi = self.params.perfusion_index
        self._sync_ac_dc_from_params()

    def set_ac_levels(self, ac_ir_mv, ac_red_mv=None):
        limits.AC_LEVEL_MV.validate(ac_ir_mv)
        if ac_red_mv is not None:
            limits.AC_LEVEL_MV.validate(ac_red_mv)
        self.params.ac_ir_mv, self.params.ac_red_mv = ac_ir_mv, ac_red_mv
        self.params.perfusion_index = ac_ir_mv / self.params.dc_ir_mv * 100.0
        self.current_pi = self.params.perfusion_index

    def set_lock(self, lock_ac=None, lock_dc=None):
        if lock_ac is not None:
            self.params.lock_ac = bool(lock_ac)
        if lock_dc is not None:
            self.params.lock_dc = bool(lock_dc)

    def set_output_dc_offset(self, offset_mv):
        limits.OUTPUT_DC_OFFSET_MV.validate(offset_mv)
        for dc in (self.params.dc_ir_mv, self.params.dc_red_mv):
            limits.validate_dc_with_offset(dc, offset_mv)
        self.params.output_dc_offset_mv = offset_mv

    def set_spo2(self, value):
        self.params.spo2 = limits.SPO2.validate(value)

    def set_resp_rate(self, value):
        self.set_respiration(self.respiration.config.replace(rate_brpm=value))

    def set_respiration(self, config):
        config.validate()
        self.respiration.config = config
        for source, target in RESP_FIELDS.items():
            setattr(self.params, target, getattr(config, source))

    def set_modelling_options(self, hr_amplitude, spo2_notch, variability):
        self.params.hr_amplitude_enabled = self.hr_amplitude_enabled = bool(hr_amplitude)
        self.params.spo2_coupling_enabled = self.spo2_coupling_enabled = bool(spo2_notch)
        self.params.variability_enabled = bool(variability)
        self._init_condition_ranges()
        if not variability:
            self.cond_ranges.hr_cv = self.cond_ranges.pi_cv = 0.0
        self.current_pi = self.params.perfusion_index

    def set_amplification(self, value):
        self.params.amplification = limits.AMPLIFICATION.validate(value)

    def set_dicrotic_notch(self, value):
        self.params.dicrotic_notch = limits.DICROTIC_NOTCH_DEPTH.validate(value)
        self.dicrotic_depth = self.params.dicrotic_notch

    def set_waveform(self, kind):
        self.params.waveform = validate_kind(kind)

    def set_feature_times(self, channel, sp_ms, dn_ms, dp_ms):
        if channel not in ("ir", "red"):
            raise ValueError("channel must be ir or red")
        for value in (sp_ms, dn_ms, dp_ms):
            limits.FEATURE_TIME_MS.validate(value)
        if not sp_ms < dn_ms < dp_ms:
            raise ValueError("Feature times must satisfy SP < DN < DP")
        for key, value in zip(("sp_ms_", "dn_ms_", "dp_ms_"), (sp_ms, dn_ms, dp_ms)):
            setattr(self.params, key + channel, value)

    def set_polarity(self, polarity: int):
        """Select AC-above-DC (0, default/legacy) or AC-below-DC (1)."""
        if polarity not in (POLARITY_ABOVE_DC, POLARITY_BELOW_DC):
            raise ValueError(
                f"ac_polarity must be {POLARITY_ABOVE_DC} (above) or "
                f"{POLARITY_BELOW_DC} (below), got {polarity!r}")
        self.ac_polarity = polarity
        self.params.ac_polarity = polarity

    def set_dc_baseline(self, dc: float):
        """Legacy single-DC setter: sets BOTH channels to the same DC (Volts).

        Preserved for backward compatibility; equivalent to
        set_dc_levels(dc*1000, dc*1000). Kept in Volts to match old callers.
        """
        self.set_dc_levels(dc * 1000.0, dc * 1000.0)

    def set_spo2_coefficients(self, a: float, b: float):
        """Set the SpO2 calibration coefficients (SpO2 = A - B*R).

        Validates that A/B are finite and B > 0 (via calibration.validate_
        coefficients); raises ValueError on invalid input rather than storing
        a broken mapping.
        """
        a, b = validate_coefficients(a, b)
        self.params.spo2_coeff_a = a
        self.params.spo2_coeff_b = b

    # ─────────────────────── DYNAMIC HR/PI ───────────────────────
    def _generate_dynamic_hr(self) -> float:
        cr = self.cond_ranges
        hr_base = cr.hr_min + random.random() * (cr.hr_max - cr.hr_min)
        sigma = hr_base * cr.hr_cv
        hr = hr_base + self._gaussian_random(0.0, sigma)
        return _clamp(hr, cr.hr_min, cr.hr_max)

    def _generate_dynamic_pi(self) -> float:
        """Generate beat-to-beat PI variability centered on user's set value.

        Matches HTML reference: piNow = PI * (1 + piCV * (rand - 0.5) * 1.2)
        This varies PI around the user's slider value, NOT uniformly across range.
        """
        cr = self.cond_ranges
        # Seeded random variation centered on user's PI value
        seed_val = self._seeded_rand(self.beat_count * 11 + int(self.phase_in_cycle * 17))
        pi_now = self.params.perfusion_index * (1.0 + cr.pi_cv * (seed_val - 0.5) * 1.2)
        return max(0.0, pi_now)

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
        """Generate next RR interval. Matches HTML reference logic:
        - Base from user HR
        - Arrhythmia: 15% ectopic (×0.7), 10% compensatory (×1.3)
        - HRV: hrCV-based variation
        - FM/RSA: 5% modulation by respiratory phase
        """
        self.current_hr = self.params.heart_rate
        rr_mean = 60.0 / self.current_hr

        # Arrhythmia: ectopic beats and compensatory pauses
        if self.params.condition == COND_ARRHYTHMIA and self.params.variability_enabled:
            r1 = self._seeded_rand(self.beat_count * 7 + 13)
            r2 = self._seeded_rand(self.beat_count * 3 + 7)
            if r1 < 0.15:
                rr_mean *= 0.70   # Ectopic (early beat)
            elif r1 < 0.25:
                rr_mean *= 1.30   # Compensatory pause
            rr_mean *= (1.0 + self.cond_ranges.hr_cv * (r2 - 0.5) * 2.0)
            rr_mean = _clamp(rr_mean, 0.2, 6.0)
        else:
            # Normal HRV
            rr_std = rr_mean * self.cond_ranges.hr_cv
            rr_mean += self._gaussian_random(0.0, rr_std)

        rr_mean *= self._resp_state.interval_factor
        rr = _clamp(rr_mean, 0.2, 6.0)

        self.systole_fraction = self._calculate_systole_fraction(self.current_hr)
        self.systole_time = rr * 1000.0 * self.systole_fraction
        self.diastole_time = rr * 1000.0 * (1.0 - self.systole_fraction)
        return rr

    # ─────────────────────── PULSE SHAPE ───────────────────────
    def _compute_pulse_shape(self, phase, dicrotic_factor=1.0, channel="ir"):
        p = self.params
        shaper = self._shapers[channel]
        shaper.morphology = PulseMorphology.from_times_ms(
            getattr(p, "sp_ms_" + channel), getattr(p, "dn_ms_" + channel),
            getattr(p, "dp_ms_" + channel),
            systolic_amplitude=self.systolic_amplitude,
            diastolic_amplitude=self.diastolic_amplitude,
            dicrotic_depth=self.dicrotic_depth,
            systolic_width=self.systolic_width, diastolic_width=self.diastolic_width,
            notch_width=self.dicrotic_width)
        return shaper.sample(p.waveform, phase, dicrotic_factor)

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

        Signal composition (Phase 3 — per-channel DC, full ratio-of-ratios):
            AC and DC are the master parameters; PI is DERIVED. Each channel
            carries its own DC (DC_ir, DC_red).
              AC_ir  = PI/100 · DC_ir          (PI drives IR AC magnitude)
              AC_red = R · AC_ir · (DC_red/DC_ir)   (calibration.ac_red_from_target)
            With the default equal DC (DC_ir = DC_red = 1.5 V) these reduce to the
            legacy model: AC_ir = PI × 0.015 V and AC_red = R × AC_ir.

        Ratio-of-ratios (A/B configurable, default 110/25):
            R = max(0, (A - SpO2) / B). Because AC_red carries the
            (DC_red/DC_ir) correction, the reconstructed
            R = (AC_red/DC_red)/(AC_ir/DC_ir) equals the target R for ANY DC pair.

        Polarity (Phase 1 §22 / E9):
            ABOVE_DC (default, legacy): signal = DC + AC·pulse (pulse rides up).
            BELOW_DC:                   signal = DC − AC·pulse (pulse dips down).

        Respiratory modulations (Charlton 2018) — per channel, scaled by that
        channel's DC:
            BW/AM: configurable per-channel depth relative to AC (default 4%).
            FM: configurable RSA via the shared RespirationModulator.
            Each modulation can be disabled; optional apnea gates respiration.

        Optional physiological couplings:
            HR → amplitude: -3.2% per 10 BPM above 60 (research-based)
            SpO2 → vasoconstriction: reduced dicrotic notch when SpO2 < 94%

        Args:
            delta_time: Time step in seconds (typically MODEL_DT_PPG = 0.01s).

        Returns:
            Tuple (signal_ir_V, signal_red_V, display_ir_V, display_red_V).
        """
        self._resp_state = self.respiration.advance(delta_time)
        self.resp_phase_cycles = self._resp_state.cycles
        # Advance phase
        self.phase_in_cycle += delta_time / self.current_rr
        self.simulated_time_s += delta_time
        if self.phase_in_cycle >= 1.0:
            self.phase_in_cycle = self.phase_in_cycle % 1.0
            self._detect_beat_and_apply_pending()

        # SpO2 → vasoconstriction coupling (optional)
        # Hypoxia (SpO2 < 94%) reduces dicrotic notch visibility
        # Ref: Li et al. 2022, K-value increases with vasoconstriction
        dicrotic_factor = 1.0
        if self.spo2_coupling_enabled and self.params.spo2 < 94.0:
            hypoxia = min(1.0, (94.0 - self.params.spo2) / 10.0)
            dicrotic_factor = 1.0 - 0.6 * hypoxia  # 0→no change, 1→60% reduction

        # Pulse shape (normalized [0, 1])
        pulse = self._compute_pulse_shape(self.phase_in_cycle, dicrotic_factor)
        pulse_red = self._compute_pulse_shape(self.phase_in_cycle, dicrotic_factor, "red")

        # Dual channel: full ratio-of-ratios.
        # Preserve the full nonnegative calibration ratio: 0–100% targets must
        # not all collapse to the old 70% floor (R=1.6 at default A/B).
        # A/B come from the configurable SpO2 calibration (default 110/25) — the
        # single source of truth in calibration.py (no longer hardcoded here).
        r_value = max(0.0, r_target_from_spo2(self.params.spo2,
                               self.params.spo2_coeff_a, self.params.spo2_coeff_b))
        # IR AC magnitude from the (possibly beat-varied) PI and the IR DC:
        #     AC_ir = PI/100 · DC_ir   (strict clinical PI = AC/DC × 100).
        ac_ir = self.current_pi / 100.0 * self.dc_ir
        # Red AC derived so the reconstructed ratio-of-ratios equals R_target for
        # any DC pair:  AC_red = R · AC_ir · (DC_red/DC_ir).
        ac_red = ac_red_from_target(r_value, ac_ir, self.dc_red, self.dc_ir)

        if self.params.ac_red_mv is not None:
            variation = self.current_pi / self.params.perfusion_index if self.params.perfusion_index else 1.0
            ac_red = self.params.ac_red_mv / 1000.0 * variation
        ac_ir *= self.params.amplification
        ac_red *= self.params.amplification

        # HR → amplitude coupling (optional)
        # Research: pulse amplitude decreases ~3.2% per 10 BPM above 60
        # Ref: effect of increasing heart rate on finger PPG (PMC6261569)
        if self.hr_amplitude_enabled:
            hr_amp_factor = 1.0 - 0.0032 * max(0.0, self.current_hr - 60.0)
            hr_amp_factor = max(0.7, hr_amp_factor)  # clamp to ≥70%
            ac_ir *= hr_amp_factor
            ac_red *= hr_amp_factor

        ac_val_ir = pulse * ac_ir
        ac_val_red = pulse_red * ac_red

        self.last_ac_ir = ac_val_ir
        self.last_ac_red = ac_val_red

        resp = self._resp_state
        wander_ir = resp.baseline_ir * ac_ir
        wander_red = resp.baseline_red * ac_red
        ac_val_ir *= resp.amplitude_ir
        ac_val_red *= resp.amplitude_red

        # Artefact — one real pseudo-random stream per channel (models.noise).
        # ac_ir/ac_red are passed for the legacy proportional kind only; every
        # other kind is amplitude-absolute and ignores them.
        noise_ir = self._noise_ir.sample(delta_time, ac_ir)
        noise_red = self._noise_red.sample(delta_time, ac_red)

        # Polarity: pulse rides ABOVE the DC (default/legacy) or BELOW it.
        # Only the pulsatile AC term carries the sign; the (slow) baseline wander
        # is a DC drift and stays additive.
        sign = 1.0 if self.ac_polarity == POLARITY_ABOVE_DC else -1.0

        # Display signals (AC + wander + noise, no DC) — for GUI rendering
        self.last_display_ir = sign * ac_val_ir + wander_ir + noise_ir
        self.last_display_red = sign * ac_val_red + wander_red + noise_red

        # Raw signals for DAC (per-channel DC + AC + wander + noise)
        signal_ir = self.dc_ir + self.params.output_dc_offset_mv / 1000.0 + self.last_display_ir
        signal_red = self.dc_red + self.params.output_dc_offset_mv / 1000.0 + self.last_display_red

        if not (0 <= signal_ir <= DAC_FULLSCALE_V and 0 <= signal_red <= DAC_FULLSCALE_V):
            self.clipped_samples += 1
        # Clamp to DAC voltage range [0, DAC_FULLSCALE_V] (3.28 V)
        signal_ir = _clamp(signal_ir, 0.0, DAC_FULLSCALE_V)
        signal_red = _clamp(signal_red, 0.0, DAC_FULLSCALE_V)

        # Measurement tracking
        dt_ms = delta_time * 1000.0
        self.simulated_time_ms += dt_ms
        self._update_measurements(signal_ir)

        self.last_ir_value = signal_ir
        self.last_red_value = signal_red
        self.last_ac_value = ac_val_ir

        return signal_ir, signal_red, self.last_display_ir, self.last_display_red

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

    # ─────────────────────── SEEDED RANDOM (matches HTML reference) ───────────────────────
    @staticmethod
    def _seeded_rand(i: int) -> float:
        """Deterministic pseudo-random in [0, 1), matching HTML seededRand().

        Uses the same hash function as the HTML reference:
            ((sin(i*127.1 + 33.7) * 43758.5453) % 1 + 1) % 1
        This ensures reproducible beat-to-beat variation patterns.
        """
        return ((math.sin(i * 127.1 + 33.7) * 43758.5453) % 1.0 + 1.0) % 1.0

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

    # ─────────────────────── DAC CONVERSION (Volts → 12-bit) ───────────────────────
    @staticmethod
    def ac_value_to_dac_12bit(ac_v: float) -> int:
        """Convert AC amplitude in Volts to 12-bit DAC value.

        With strict PI scaling (DC=1.5V):
            PI=3%  → AC=0.045V → DAC ≈  56
            PI=10% → AC=0.150V → DAC ≈ 186
            PI=20% → AC=0.300V → DAC ≈ 372
        """
        AC_MAX_V = 0.45   # 0.45 V max (PI~30% × 0.015, generous headroom)
        normalized = _clamp(ac_v / AC_MAX_V, 0.0, 1.0)
        return int(normalized * 4095.0)

    @staticmethod
    def ppg_sample_to_dac_value(sample_v: float, dc_baseline: float, max_ac: float) -> int:
        """Map a PPG sample (Volts) to a 12-bit DAC value."""
        min_v = dc_baseline - max_ac
        max_v = dc_baseline + max_ac
        if max_v <= min_v:
            return 2048
        normalized = _clamp((sample_v - min_v) / (max_v - min_v), 0.0, 1.0)
        return int(normalized * 4095.0)

    # ─────────────────────── GETTERS ───────────────────────
    def get_condition_name(self) -> str:
        if 0 <= self.params.condition < len(CONDITION_NAMES):
            return CONDITION_NAMES[self.params.condition]
        return "Unknown"

    def get_ac_amplitude(self) -> float:
        """IR AC amplitude (V) = PI/100 · DC_ir. Legacy 0.015·PI at DC_ir=1.5 V."""
        return self.current_pi / 100.0 * self.dc_ir

    def get_measured_hr(self) -> float:
        if self.measured_rr_ms > 0:
            return 60000.0 / self.measured_rr_ms
        return self.current_hr

    def is_in_systole(self) -> bool:
        return self.phase_in_cycle < self.systole_fraction

    # ─────────────────────── COUPLING CONTROLS ───────────────────────
    def set_hr_amplitude_coupling(self, enabled: bool):
        """Enable/disable HR → pulse amplitude reduction.
        When enabled, amplitude decreases ~3.2% per 10 BPM above 60.
        """
        value = bool(enabled)
        self.params.hr_amplitude_enabled = value
        self.hr_amplitude_enabled = value

    def set_spo2_coupling(self, enabled: bool):
        """Enable/disable SpO2 → vasoconstriction coupling.
        When enabled, dicrotic notch fades when SpO2 < 94%.
        """
        value = bool(enabled)
        self.params.spo2_coupling_enabled = value
        self.spo2_coupling_enabled = value

    def get_measured_pi(self) -> float:
        """Return measured PI = (AC / DC) × 100% from model output."""
        if self.dc_baseline > 0 and self.measured_peak > 0:
            ac = self.measured_peak - self.measured_valley
            return (ac / self.dc_baseline) * 100.0
        return self.current_pi
