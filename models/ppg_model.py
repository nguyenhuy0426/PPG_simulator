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

from config import DAC_FULLSCALE_V
from calibration import (
    r_target_from_spo2,
    validate_coefficients,
    validate_ac_dc,
    ac_red_from_target,
    perfusion_index_from_ac_dc,
    R_CLAMP_MIN,
    R_CLAMP_MAX,
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
                 "dc_ir_mv", "dc_red_mv", "ac_polarity")

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
        # not stored here: IR AC follows the PI convenience input (AC_ir =
        # PI/100 · DC_ir) and Red AC is derived via the ratio-of-ratios.
        self.dc_ir_mv = DEFAULT_DC_BASELINE_V * 1000.0     # 1500.0 mV
        self.dc_red_mv = DEFAULT_DC_BASELINE_V * 1000.0    # 1500.0 mV
        self.ac_polarity = POLARITY_ABOVE_DC               # legacy pulse-up default

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

        # Physiological coupling options (can be toggled at runtime)
        self.hr_amplitude_enabled = True    # HR → pulse amplitude reduction
        self.spo2_coupling_enabled = True   # SpO2 → vasoconstriction (notch loss)

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
        self._sync_ac_dc_from_params()
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
        """PI convenience input (backward-compatible).

        PI is a derived quantity in the Phase 3 model, but the UI/BLE still
        expose a PI slider and the condition presets drive PI. Setting PI fixes
        the IR AC magnitude for the waveform via AC_ir = PI/100 · DC_ir (applied
        in generate_both_samples). With the default DC_ir = 1.5 V this reproduces
        the legacy AC_ir = PI × 0.015 V exactly. DC levels are unchanged here.
        """
        pi = _clamp(pi, 0.5, 20.0)
        self.params.perfusion_index = pi
        self.current_pi = pi

    def set_noise_level(self, noise: float):
        self.params.noise_level = _clamp(noise, 0.0, 1.0)

    def set_dc_levels(self, dc_ir_mv: float, dc_red_mv: float = None):
        """Set independent per-channel DC levels (mV). Red defaults to IR.

        Validates each channel against the DAC headroom (DC > 0, DC <= full-scale)
        by reusing calibration.validate_ac_dc with AC = 0. Updates both the
        persisted params (mV) and the Volts working state.
        """
        if dc_red_mv is None:
            dc_red_mv = dc_ir_mv
        # AC=0 here → validate_ac_dc only checks the DC constraints (0 < DC <= FS).
        _, dc_ir_mv = validate_ac_dc(0.0, dc_ir_mv)
        _, dc_red_mv = validate_ac_dc(0.0, dc_red_mv)
        self.params.dc_ir_mv = dc_ir_mv
        self.params.dc_red_mv = dc_red_mv
        self.dc_ir = dc_ir_mv / 1000.0
        self.dc_red = dc_red_mv / 1000.0
        self.dc_baseline = self.dc_ir

    def set_ac_dc(self, ac_ir_mv: float, dc_ir_mv: float, dc_red_mv: float = None):
        """Master AC/DC entry point (Phase 3): set IR AC amplitude and per-channel DC.

        AC and DC are the master parameters; PI is DERIVED here as
        PI = AC_ir / DC_ir × 100 and stored on params so the existing PI-driven
        generator (presets, beat-to-beat variability, HR coupling) uses it. The
        Red AC is derived downstream from the SpO2 target via the ratio-of-ratios.

        Both channels are validated against the DAC headroom (envelope
        [DC-AC, DC+AC] within [0, full-scale]) via calibration.validate_ac_dc.

        Args:
            ac_ir_mv:  IR AC amplitude in mV (peak, one-sided).
            dc_ir_mv:  IR DC level in mV.
            dc_red_mv: Red DC level in mV (defaults to dc_ir_mv → equal-DC).
        """
        if dc_red_mv is None:
            dc_red_mv = dc_ir_mv
        ac_ir_mv, dc_ir_mv = validate_ac_dc(ac_ir_mv, dc_ir_mv)
        # Red channel uses the same AC envelope check for headroom safety.
        validate_ac_dc(ac_ir_mv, dc_red_mv)
        self.params.dc_ir_mv = dc_ir_mv
        self.params.dc_red_mv = dc_red_mv
        self.dc_ir = dc_ir_mv / 1000.0
        self.dc_red = dc_red_mv / 1000.0
        self.dc_baseline = self.dc_ir
        # PI derived from AC/DC (units cancel; mV/mV). Clamped to the same PI
        # slider range so the derived value stays consistent with set_perfusion_index.
        pi = _clamp(perfusion_index_from_ac_dc(ac_ir_mv, dc_ir_mv), 0.5, 20.0)
        self.params.perfusion_index = pi
        self.current_pi = pi

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
        return _clamp(pi_now, cr.pi_min * 0.8, cr.pi_max * 1.2)

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
        if self.params.condition == COND_ARRHYTHMIA:
            r1 = self._seeded_rand(self.beat_count * 7 + 13)
            r2 = self._seeded_rand(self.beat_count * 3 + 7)
            if r1 < 0.15:
                rr_mean *= 0.70   # Ectopic (early beat)
            elif r1 < 0.25:
                rr_mean *= 1.30   # Compensatory pause
            rr_mean *= (1.0 + self.cond_ranges.hr_cv * (r2 - 0.5) * 2.0)
            rr_mean = _clamp(rr_mean, 0.30, 1.50)
        else:
            # Normal HRV
            rr_std = rr_mean * self.cond_ranges.hr_cv
            rr_mean += self._gaussian_random(0.0, rr_std)

        # FM (RSA) — 5% modulation by respiratory phase
        resp_rad = self.resp_phase_cycles * 2.0 * math.pi
        rsa = 0.05 * math.sin(resp_rad)
        rr_mean *= (1.0 + rsa)

        rr = _clamp(rr_mean, 0.3, 2.0)

        self.systole_fraction = self._calculate_systole_fraction(self.current_hr)
        self.systole_time = rr * 1000.0 * self.systole_fraction
        self.diastole_time = rr * 1000.0 * (1.0 - self.systole_fraction)
        return rr

    # ─────────────────────── PULSE SHAPE ───────────────────────
    def _compute_pulse_shape(self, phase: float, dicrotic_factor: float = 1.0) -> float:
        """Compute normalized pulse shape [0, 1].

        Args:
            phase: Current phase in cardiac cycle (0-1).
            dicrotic_factor: Multiplier for dicrotic notch depth (1.0 = normal,
                <1.0 = reduced notch e.g. due to hypoxia/vasoconstriction).
        """
        phase = phase % 1.0
        if phase < 0:
            phase += 1.0

        systolic = self.systolic_amplitude * math.exp(
            -(phase - PPG_SYSTOLIC_POS) ** 2 / (2.0 * self.systolic_width ** 2))
        diastolic = self.diastolic_amplitude * math.exp(
            -(phase - PPG_DIASTOLIC_POS) ** 2 / (2.0 * self.diastolic_width ** 2))
        notch = self.dicrotic_depth * dicrotic_factor * self.systolic_amplitude * math.exp(
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

        Signal composition (Phase 3 — per-channel DC, full ratio-of-ratios):
            AC and DC are the master parameters; PI is DERIVED. Each channel
            carries its own DC (DC_ir, DC_red).
              AC_ir  = PI/100 · DC_ir          (PI drives IR AC magnitude)
              AC_red = R · AC_ir · (DC_red/DC_ir)   (calibration.ac_red_from_target)
            With the default equal DC (DC_ir = DC_red = 1.5 V) these reduce to the
            legacy model: AC_ir = PI × 0.015 V and AC_red = R × AC_ir.

        Ratio-of-ratios (A/B configurable, default 110/25):
            R = (A - SpO2) / B, clamped to [0.4, 1.6]. Because AC_red carries the
            (DC_red/DC_ir) correction, the reconstructed
            R = (AC_red/DC_red)/(AC_ir/DC_ir) equals the target R for ANY DC pair.

        Polarity (Phase 1 §22 / E9):
            ABOVE_DC (default, legacy): signal = DC + AC·pulse (pulse rides up).
            BELOW_DC:                   signal = DC − AC·pulse (pulse dips down).

        Respiratory modulations (Charlton 2018) — per channel, scaled by that
        channel's DC:
            BW: Baseline wander ≈ 0.2% (slow) + 0.4% (resp) of DC × sin(phase)
            AM: Amplitude modulation = 1 + 0.25 × sin(resp_phase)
            FM: RSA applied in _generate_next_rr() (±5%)

        Optional physiological couplings:
            HR → amplitude: -3.2% per 10 BPM above 60 (research-based)
            SpO2 → vasoconstriction: reduced dicrotic notch when SpO2 < 94%

        Args:
            delta_time: Time step in seconds (typically MODEL_DT_PPG = 0.01s).

        Returns:
            Tuple (signal_ir_V, signal_red_V, display_ir_V, display_red_V).
        """
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

        # Dual channel: full ratio-of-ratios.
        # R_target = (A - SpO2) / B, clamped to physiological range [0.4, 1.6].
        # A/B come from the configurable SpO2 calibration (default 110/25) — the
        # single source of truth in calibration.py (no longer hardcoded here).
        r_value = _clamp(
            r_target_from_spo2(self.params.spo2,
                               self.params.spo2_coeff_a,
                               self.params.spo2_coeff_b),
            R_CLAMP_MIN, R_CLAMP_MAX)
        # IR AC magnitude from the (possibly beat-varied) PI and the IR DC:
        #     AC_ir = PI/100 · DC_ir   (strict clinical PI = AC/DC × 100).
        ac_ir = self.current_pi / 100.0 * self.dc_ir
        # Red AC derived so the reconstructed ratio-of-ratios equals R_target for
        # any DC pair:  AC_red = R · AC_ir · (DC_red/DC_ir).
        ac_red = ac_red_from_target(r_value, ac_ir, self.dc_red, self.dc_ir)

        # HR → amplitude coupling (optional)
        # Research: pulse amplitude decreases ~3.2% per 10 BPM above 60
        # Ref: effect of increasing heart rate on finger PPG (PMC6261569)
        if self.hr_amplitude_enabled:
            hr_amp_factor = 1.0 - 0.0032 * max(0.0, self.current_hr - 60.0)
            hr_amp_factor = max(0.7, hr_amp_factor)  # clamp to ≥70%
            ac_ir *= hr_amp_factor
            ac_red *= hr_amp_factor

        ac_val_ir = pulse * ac_ir
        ac_val_red = pulse * ac_red

        self.last_ac_ir = ac_val_ir
        self.last_ac_red = ac_val_red

        # Respiratory modulations (Charlton 2018)
        # simRespPh += dt * (RR / 60)  → phase in cycles
        # respRad = simRespPh * 2π     → convert to radians
        self.resp_phase_cycles += delta_time * (self.params.resp_rate / 60.0)
        resp_rad = self.resp_phase_cycles * 2.0 * math.pi

        # Baseline wander (BW) — proportional to EACH channel's DC.
        # ~0.2% DC slow drift + ~0.4% DC respiratory component. Both channels
        # share the same phases; only the DC scale differs (independent DC).
        bw_slow_phase = math.sin(self.simulated_time_s * 0.3 * 2.0 * math.pi)
        bw_resp_phase = math.sin(resp_rad)
        wander_ir = 0.002 * self.dc_ir * bw_slow_phase + 0.004 * self.dc_ir * bw_resp_phase
        wander_red = 0.002 * self.dc_red * bw_slow_phase + 0.004 * self.dc_red * bw_resp_phase

        # AM (amplitude modulation by respiration) — multiplies both channels
        # equally, so the ratio-of-ratios is preserved.
        am_factor = 1.0 + 0.25 * math.sin(resp_rad)
        ac_val_ir *= am_factor
        ac_val_red *= am_factor

        # Noise — proportional to AC amplitude
        noise_ir = 0.0
        noise_red = 0.0
        if self.params.noise_level > 0:
            noise_seed_ir = self._seeded_rand(
                self.beat_count * 31 + int(self.simulated_time_ms) % 997)
            noise_seed_red = self._seeded_rand(
                self.beat_count * 53 + int(self.simulated_time_ms) % 991)
            noise_ir = (noise_seed_ir - 0.5) * 2.5 * self.params.noise_level * ac_ir
            noise_red = (noise_seed_red - 0.5) * 2.5 * self.params.noise_level * ac_red

        # Polarity: pulse rides ABOVE the DC (default/legacy) or BELOW it.
        # Only the pulsatile AC term carries the sign; the (slow) baseline wander
        # is a DC drift and stays additive.
        sign = 1.0 if self.ac_polarity == POLARITY_ABOVE_DC else -1.0

        # Display signals (AC + wander + noise, no DC) — for GUI rendering
        self.last_display_ir = sign * ac_val_ir + wander_ir + noise_ir
        self.last_display_red = sign * ac_val_red + wander_red + noise_red

        # Raw signals for DAC (per-channel DC + AC + wander + noise)
        signal_ir = self.dc_ir + self.last_display_ir
        signal_red = self.dc_red + self.last_display_red

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
        self.hr_amplitude_enabled = enabled

    def set_spo2_coupling(self, enabled: bool):
        """Enable/disable SpO2 → vasoconstriction coupling.
        When enabled, dicrotic notch fades when SpO2 < 94%.
        """
        self.spo2_coupling_enabled = enabled

    def get_measured_pi(self) -> float:
        """Return measured PI = (AC / DC) × 100% from model output."""
        if self.dc_baseline > 0 and self.measured_peak > 0:
            ac = self.measured_peak - self.measured_valley
            return (ac / self.dc_baseline) * 100.0
        return self.current_pi
