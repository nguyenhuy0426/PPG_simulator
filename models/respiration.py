"""
respiration.py — respiratory modulation of the PPG, with apnea.

What this module produces
-------------------------
One RespirationState per model tick, carrying the three respiratory-induced
variations described in Charlton et al. 2018 ("Breathing Rate Estimation from
the Electrocardiogram and Photoplethysmogram: A Review"):

    baseline   RIIV  respiratory-induced intensity variation  -> a slow offset
                     added to the channel, proportional to that channel's AC
                     amplitude.
    amplitude  RIAV  respiratory-induced amplitude variation  -> a multiplier
                     on the pulse amplitude.
    interval   RIFV  respiratory-induced frequency variation, a.k.a. RSA
                     -> a multiplier on the beat-to-beat interval.

AECG100 parity (docs/whale_device/user_manual.pdf, Table 7 "Respiration"
and "Apnea"):

    Rate                    1-150 BrPM        -> RespirationConfig.rate_brpm
    Inhale-Exhale Ratio     1:1 .. 1:5        -> inhale_exhale_ratio
    Wave Modulation         Baseline /        -> baseline_enabled,
                            Amplitude /          amplitude_enabled,
                            Frequency            frequency_enabled
                            (multi-select)       (independently selectable)
    Variation R / IR        1-16 %, step 1    -> variation_red_pct,
                                                 variation_ir_pct
    Apnea duration          1-60 s            -> apnea_duration_s
    Apnea cycle             1-10 min          -> apnea_cycle_min

Change from v4 [BEHAVIOUR CHANGE]
---------------------------------
v4 hardcoded three depths inside models/ppg_model.generate_both_samples():
baseline 0.2 % (0.3 Hz) + 0.4 % of DC, amplitude +/-25 %, RSA +/-5 %, identical
on both channels and all three permanently on. They are now one adjustable
per-channel depth, as the AECG100 exposes it, and the depth is referenced to
the channel's AC amplitude rather than its DC level (the convention used when
RIIV/RIAV are quoted as a percentage in the literature). At the default 4 %
the respiratory modulation is therefore *weaker* than v4's; set Variation to
16 % for a v4-like depth. Nothing here is validated against a bench recording.

Stdlib only. No hardware access.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace as _dc_replace
from typing import Tuple

from models.limits import (
    APNEA_CYCLE_MIN,
    APNEA_DURATION_S,
    RESP_RATE,
    RESP_VARIATION_PCT,
    INHALE_EXHALE_RATIOS,
    inhale_fraction,
)

__all__ = [
    "MOD_BASELINE",
    "MOD_AMPLITUDE",
    "MOD_FREQUENCY",
    "MODULATION_KINDS",
    "RespirationConfig",
    "RespirationState",
    "RespirationModulator",
]

MOD_BASELINE = "baseline"
MOD_AMPLITUDE = "amplitude"
MOD_FREQUENCY = "frequency"
MODULATION_KINDS: Tuple[str, ...] = (MOD_BASELINE, MOD_AMPLITUDE, MOD_FREQUENCY)

# ---------------------------------------------------------------------------
# Shape constants
# ---------------------------------------------------------------------------

FREQUENCY_WEIGHT = 0.4
"""RSA depth relative to the configured variation. Respiratory sinus
arrhythmia is smaller than the amplitude modulation it accompanies; v4 used
+/-5 % RSA against +/-25 % AM, a ratio of 0.2. 0.4 is used here so RSA stays
visible at the AECG100's lower default variation. [ENGINEERING-INFERENCE]"""

SLOW_DRIFT_HZ = 0.3
"""Non-respiratory baseline drift retained from v4 (vasomotor/Mayer-wave band,
0.1-0.4 Hz). Independent of the respiratory rate on purpose."""

SLOW_DRIFT_RATIO = 0.5
"""Slow-drift depth relative to the respiratory baseline depth. Preserves the
v4 ratio (0.002 vs 0.004 of DC)."""

APNEA_BLEND_S = 1.0
"""Cross-fade time into and out of apnea. A hard cut to zero modulation would
put a step into the DAC output; the 0.5 mV-scale step that produces is a
visible artefact on a DUT, not a physiological event."""

_TWO_PI = 2.0 * math.pi


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


@dataclass(frozen=True)
class RespirationConfig:
    """User-facing respiration settings. Immutable; use replace() to change one."""

    rate_brpm: float = 16.0
    inhale_exhale_ratio: int = 1

    baseline_enabled: bool = True
    amplitude_enabled: bool = True
    frequency_enabled: bool = True

    variation_ir_pct: float = 4.0
    variation_red_pct: float = 4.0

    apnea_enabled: bool = False
    apnea_duration_s: float = 10.0
    apnea_cycle_min: float = 1.0

    def enabled_modulations(self) -> Tuple[str, ...]:
        """The selected Wave Modulation set, in MODULATION_KINDS order."""
        selected = []
        if self.baseline_enabled:
            selected.append(MOD_BASELINE)
        if self.amplitude_enabled:
            selected.append(MOD_AMPLITUDE)
        if self.frequency_enabled:
            selected.append(MOD_FREQUENCY)
        return tuple(selected)

    def replace(self, **changes) -> "RespirationConfig":
        """Return a copy with the named fields changed."""
        return _dc_replace(self, **changes)

    def validate(self) -> "RespirationConfig":
        """Check every field against its AECG100 range.

        Returns:
            self, so the call can be chained.

        Raises:
            ValueError: On the first field that is out of range, or when the
                apnea duration does not fit inside its own cycle.
        """
        RESP_RATE.validate(self.rate_brpm)
        if self.inhale_exhale_ratio not in INHALE_EXHALE_RATIOS:
            raise ValueError(
                f"inhale:exhale ratio 1:{self.inhale_exhale_ratio} not supported; "
                f"expected one of {INHALE_EXHALE_RATIOS}"
            )
        RESP_VARIATION_PCT.validate(self.variation_ir_pct)
        RESP_VARIATION_PCT.validate(self.variation_red_pct)
        if self.apnea_enabled:
            APNEA_DURATION_S.validate(self.apnea_duration_s)
            APNEA_CYCLE_MIN.validate(self.apnea_cycle_min)
            if self.apnea_duration_s >= self.apnea_cycle_min * 60.0:
                raise ValueError(
                    f"apnea duration {self.apnea_duration_s} s does not fit in a "
                    f"{self.apnea_cycle_min} min cycle"
                )
        return self


@dataclass(frozen=True)
class RespirationState:
    """One tick of respiratory modulation.

    Attributes:
        cycles: Total breaths elapsed since reset (monotonic, unwrapped).
        phase: Position in the current breath, 0-1.
        drive: The respiratory waveform itself, -1..+1, warped by the
            inhale-exhale ratio. +1 at end of inhalation.
        baseline_ir: Additive baseline offset for IR, as a FRACTION of that
            channel's AC amplitude.
        baseline_red: Same, for Red.
        amplitude_ir: Multiplier on the IR pulse amplitude (1.0 = unmodulated).
        amplitude_red: Same, for Red.
        interval_factor: Multiplier on the beat-to-beat interval (RSA).
        in_apnea: True while the apnea window is active.
    """

    cycles: float
    phase: float
    drive: float
    baseline_ir: float
    baseline_red: float
    amplitude_ir: float
    amplitude_red: float
    interval_factor: float
    in_apnea: bool


_NEUTRAL = RespirationState(
    cycles=0.0, phase=0.0, drive=0.0,
    baseline_ir=0.0, baseline_red=0.0,
    amplitude_ir=1.0, amplitude_red=1.0,
    interval_factor=1.0, in_apnea=False,
)


class RespirationModulator:
    """Stateful respiratory modulator, advanced one model tick at a time.

    Not thread-safe. models/ppg_model.py owns one instance and only the
    generation thread advances it; the UI thread only replaces `config`,
    which is a single atomic attribute assignment of an immutable object.
    """

    __slots__ = ("_config", "_cycles", "_elapsed_s", "_slow_phase")

    def __init__(self, config: RespirationConfig = None):
        self._config = (config or RespirationConfig()).validate()
        self._cycles = 0.0
        self._elapsed_s = 0.0
        self._slow_phase = 0.0

    @property
    def config(self) -> RespirationConfig:
        return self._config

    @config.setter
    def config(self, value: RespirationConfig):
        """Swap the settings without disturbing the running phase.

        The phase is deliberately preserved across a rate change: restarting it
        would put a discontinuity into the baseline and amplitude modulation.
        """
        self._config = value.validate()

    @property
    def phase(self) -> float:
        """Position in the current breath, 0-1."""
        return self._cycles % 1.0

    def reset(self):
        """Return to the start of a breath with no elapsed time."""
        self._cycles = 0.0
        self._elapsed_s = 0.0
        self._slow_phase = 0.0

    def advance(self, dt_s: float) -> RespirationState:
        """Advance by one model tick and return the resulting modulation.

        Args:
            dt_s: Tick length in seconds (MODEL_DT_PPG on the live path).

        Returns:
            The RespirationState for this tick.
        """
        cfg = self._config
        self._elapsed_s += dt_s
        self._slow_phase += dt_s * SLOW_DRIFT_HZ

        gate = self._apnea_gate()
        in_apnea = gate < 1.0

        # The breath keeps advancing during apnea so the phase does not jump
        # when breathing resumes; only its depth is gated.
        self._cycles += dt_s * (cfg.rate_brpm / 60.0) * gate

        if gate <= 0.0:
            return RespirationState(
                cycles=self._cycles, phase=self.phase, drive=0.0,
                baseline_ir=0.0, baseline_red=0.0,
                amplitude_ir=1.0, amplitude_red=1.0,
                interval_factor=1.0, in_apnea=True,
            )

        drive = self._drive(self.phase) * gate
        slow = math.sin(_TWO_PI * self._slow_phase) * gate

        ir_depth = cfg.variation_ir_pct / 100.0
        red_depth = cfg.variation_red_pct / 100.0

        if cfg.baseline_enabled:
            baseline_ir = ir_depth * (drive + SLOW_DRIFT_RATIO * slow)
            baseline_red = red_depth * (drive + SLOW_DRIFT_RATIO * slow)
        else:
            baseline_ir = baseline_red = 0.0

        if cfg.amplitude_enabled:
            amplitude_ir = 1.0 + ir_depth * drive
            amplitude_red = 1.0 + red_depth * drive
        else:
            amplitude_ir = amplitude_red = 1.0

        if cfg.frequency_enabled:
            # RSA is a whole-body effect, not a per-wavelength one, so it uses
            # the IR variation as the single physiological depth.
            interval_factor = 1.0 + FREQUENCY_WEIGHT * ir_depth * drive
        else:
            interval_factor = 1.0

        return RespirationState(
            cycles=self._cycles, phase=self.phase, drive=drive,
            baseline_ir=baseline_ir, baseline_red=baseline_red,
            amplitude_ir=amplitude_ir, amplitude_red=amplitude_red,
            interval_factor=interval_factor, in_apnea=in_apnea,
        )

    # ---- internals ----

    def _drive(self, phase: float) -> float:
        """Respiratory waveform in [-1, +1], warped by the inhale-exhale ratio.

        Inhalation is a rising half-cosine over the first 1/(1+N) of the breath
        and exhalation a falling half-cosine over the rest, so at 1:4 the drive
        spends 20 % of the breath rising and 80 % falling, which is what the
        ratio means. Both halves have zero slope at the joins, so the waveform
        is continuous in value and in slope; a plain phase-warped sine would
        instead put a slope step at the turning points.
        """
        f_in = inhale_fraction(self._config.inhale_exhale_ratio)
        if phase < f_in:
            return -math.cos(math.pi * (phase / f_in))
        return math.cos(math.pi * ((phase - f_in) / (1.0 - f_in)))

    def _apnea_gate(self) -> float:
        """Modulation depth multiplier, 1.0 breathing .. 0.0 fully apnoeic."""
        cfg = self._config
        if not cfg.apnea_enabled:
            return 1.0

        period_s = cfg.apnea_cycle_min * 60.0
        if period_s <= 0.0:
            return 1.0

        # Apnea sits at the END of each cycle so a run starts with normal
        # breathing, matching how the AECG100 presents "cycle" as the interval
        # between apnea events.
        into_cycle = self._elapsed_s % period_s
        apnea_start = period_s - cfg.apnea_duration_s
        blend = min(APNEA_BLEND_S, cfg.apnea_duration_s * 0.5)
        if blend <= 0.0:
            return 0.0 if into_cycle >= apnea_start else 1.0

        if into_cycle < apnea_start - blend:
            return 1.0
        if into_cycle < apnea_start:
            # Fading out over the last `blend` seconds before the apnea.
            return _clamp((apnea_start - into_cycle) / blend, 0.0, 1.0)
        if into_cycle < period_s - blend:
            return 0.0
        # Fading back in over the last `blend` seconds of the apnea.
        return _clamp(1.0 - (period_s - into_cycle) / blend, 0.0, 1.0)
