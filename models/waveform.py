"""
waveform.py — output waveform shapes for the PPG simulator.

Scope
-----
This module owns the *shape* of one cycle, normalised to [0, 1] with the peak
at exactly 1.0. It knows nothing about amplitude in millivolts, DC level,
heart rate, respiration or hardware; models/ppg_model.py multiplies the shape
by the AC amplitude and adds the DC pedestal.

Four output waveforms, matching the AECG100 "Output Waveform" selector
(user_manual.pdf Table 7 / Table 10 — Sine, Triangle, Square, PPG; default PPG):

    WAVE_PPG       3-component Gaussian sum (Allen 2007): systolic peak +
                   diastolic peak - dicrotic notch.
    WAVE_SINE      raised sine, one cycle per beat.
    WAVE_TRIANGLE  symmetric rise/fall, peak at mid-cycle.
    WAVE_SQUARE    50 % duty, 0 or 1.

Why normalise to 1.0
--------------------
models/ppg_model.py computes AC_ir = PI/100 * DC_ir and multiplies it by the
shape. That identity only holds if the shape's true maximum is 1.0. A fixed
divisor cannot achieve this because the peak of a Gaussian *sum* moves when
the component amplitudes, widths or positions move, and all of those are
user-adjustable (AECG100 exposes SP/DN/DP amplitude AND time). PulseShaper
therefore searches for the peak numerically and caches the result until a
morphology field changes.

Feature times
-------------
The AECG100 specifies feature times in milliseconds *at 60 BPM*, i.e. against
a 1000 ms cycle (Table 7: SP 150 ms, DN 360 ms, DP 460 ms). They are stored
here as a fraction of the cardiac cycle so they scale with heart rate, which
is what the AECG100 does when BPM changes. REFERENCE_CYCLE_MS is that 1000 ms.

Stdlib only. No hardware access.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace as _dc_replace
from typing import Tuple

from models.limits import FEATURE_TIME_MS

__all__ = [
    "WAVE_PPG",
    "WAVE_SINE",
    "WAVE_TRIANGLE",
    "WAVE_SQUARE",
    "WAVEFORM_KINDS",
    "DEFAULT_WAVEFORM",
    "REFERENCE_CYCLE_MS",
    "PulseMorphology",
    "PulseShaper",
    "validate_kind",
]

WAVE_PPG = "ppg"
WAVE_SINE = "sine"
WAVE_TRIANGLE = "triangle"
WAVE_SQUARE = "square"

WAVEFORM_KINDS: Tuple[str, ...] = (WAVE_PPG, WAVE_SINE, WAVE_TRIANGLE, WAVE_SQUARE)
DEFAULT_WAVEFORM = WAVE_PPG

REFERENCE_CYCLE_MS = 1000.0
"""Cycle length the AECG100 quotes its feature times against (60 BPM)."""

# Peak search resolution. Preserved from the v4 implementation in
# models/ppg_model.py so the normalisation is bit-for-bit unchanged.
PULSE_PEAK_SCAN_STEPS = 1000
PULSE_PEAK_REFINE_ITERS = 40

# Below this the raw pulse is treated as degenerate (all amplitudes zero) and
# the scale falls back to 1.0 rather than dividing by ~0.
_DEGENERATE_PEAK = 1e-9


def validate_kind(kind: str) -> str:
    """Normalise and check an output-waveform name.

    Args:
        kind: Waveform name, any case.

    Returns:
        The canonical lowercase name.

    Raises:
        ValueError: If the name is not one of WAVEFORM_KINDS.
    """
    if not isinstance(kind, str):
        raise ValueError(f"waveform kind must be a string, got {type(kind).__name__}")
    canonical = kind.strip().lower()
    if canonical not in WAVEFORM_KINDS:
        raise ValueError(
            f"unknown waveform {kind!r}; expected one of {WAVEFORM_KINDS}"
        )
    return canonical


@dataclass(frozen=True)
class PulseMorphology:
    """Shape of one PPG cycle: three Gaussians on a normalised time axis.

    Positions and widths are fractions of the cardiac cycle (0-1); amplitudes
    are relative to the systolic peak amplitude, which is itself relative.
    Absolute millivolts are applied downstream by models/ppg_model.py.

    Defaults reproduce the v4 constants (Allen 2007) exactly, so an unchanged
    configuration produces an unchanged waveform.
    """

    systolic_pos: float = 0.15
    notch_pos: float = 0.30
    diastolic_pos: float = 0.40

    systolic_width: float = 0.055
    notch_width: float = 0.02
    diastolic_width: float = 0.10

    systolic_amplitude: float = 1.0
    diastolic_amplitude: float = 0.4
    dicrotic_depth: float = 0.25

    # ---- millisecond view (AECG100 units, quoted at 60 BPM) ----

    @property
    def systolic_time_ms(self) -> float:
        return self.systolic_pos * REFERENCE_CYCLE_MS

    @property
    def notch_time_ms(self) -> float:
        return self.notch_pos * REFERENCE_CYCLE_MS

    @property
    def diastolic_time_ms(self) -> float:
        return self.diastolic_pos * REFERENCE_CYCLE_MS

    @classmethod
    def from_times_ms(cls, systolic_ms: float, notch_ms: float,
                      diastolic_ms: float, **kwargs) -> "PulseMorphology":
        """Build a morphology from AECG100-style feature times in milliseconds.

        Args:
            systolic_ms: Systolic-peak time at 60 BPM, 0-1000 ms.
            notch_ms: Dicrotic-notch time at 60 BPM, 0-1000 ms.
            diastolic_ms: Diastolic-peak time at 60 BPM, 0-1000 ms.
            **kwargs: Any other PulseMorphology field (widths, amplitudes).

        Returns:
            A new PulseMorphology.

        Raises:
            ValueError: If any time falls outside FEATURE_TIME_MS.
        """
        return cls(
            systolic_pos=FEATURE_TIME_MS.validate(systolic_ms) / REFERENCE_CYCLE_MS,
            notch_pos=FEATURE_TIME_MS.validate(notch_ms) / REFERENCE_CYCLE_MS,
            diastolic_pos=FEATURE_TIME_MS.validate(diastolic_ms) / REFERENCE_CYCLE_MS,
            **kwargs,
        )

    def replace(self, **changes) -> "PulseMorphology":
        """Return a copy with the named fields changed (the object is frozen)."""
        return _dc_replace(self, **changes)

    def scale_key(self) -> tuple:
        """Fields the normalisation peak depends on. Used as a cache key."""
        return (self.systolic_pos, self.notch_pos, self.diastolic_pos,
                self.systolic_width, self.notch_width, self.diastolic_width,
                self.systolic_amplitude, self.diastolic_amplitude,
                self.dicrotic_depth)


def _gauss(phase: float, centre: float, width: float) -> float:
    """Unit-height Gaussian, guarded against a zero width."""
    if width <= 0.0:
        return 0.0
    return math.exp(-((phase - centre) ** 2) / (2.0 * width * width))


class PulseShaper:
    """Produces normalised cycle shapes, caching the PPG peak search.

    Not thread-safe on its own: models/ppg_model.py owns exactly one instance
    and only the generation thread touches it.
    """

    __slots__ = ("_morphology", "_scale_key", "_scale", "peak_search_count")

    def __init__(self, morphology: PulseMorphology = None):
        self._morphology = morphology or PulseMorphology()
        self._scale_key = None
        self._scale = 1.0
        self.peak_search_count = 0

    @property
    def morphology(self) -> PulseMorphology:
        return self._morphology

    @morphology.setter
    def morphology(self, value: PulseMorphology):
        if not isinstance(value, PulseMorphology):
            raise TypeError("morphology must be a PulseMorphology")
        self._morphology = value

    # ---- shapes ----

    def sample(self, kind: str, phase: float, dicrotic_factor: float = 1.0) -> float:
        """One normalised sample in [0, 1].

        Args:
            kind: One of WAVEFORM_KINDS (already canonical; not re-validated on
                the hot path — call validate_kind() at the setter instead).
            phase: Position in the cycle. Any real number; wrapped into [0, 1).
            dicrotic_factor: Notch-depth multiplier, PPG only. 1.0 = full notch,
                0.0 = no notch. Used by the SpO2 -> vasoconstriction coupling.

        Returns:
            The shape value, 0.0 at the cycle trough and 1.0 at its peak.
        """
        phase = phase % 1.0
        if kind == WAVE_PPG:
            return self._ppg(phase, dicrotic_factor)
        if kind == WAVE_SINE:
            return 0.5 * (1.0 - math.cos(2.0 * math.pi * phase))
        if kind == WAVE_TRIANGLE:
            return 2.0 * phase if phase < 0.5 else 2.0 * (1.0 - phase)
        if kind == WAVE_SQUARE:
            return 1.0 if phase < 0.5 else 0.0
        raise ValueError(f"unknown waveform {kind!r}")

    def _ppg(self, phase: float, dicrotic_factor: float) -> float:
        raw = self._raw_ppg(phase, dicrotic_factor)
        scaled = raw / self._peak_scale()
        return min(1.0, max(0.0, scaled))

    def _raw_ppg(self, phase: float, dicrotic_factor: float = 1.0) -> float:
        """Un-normalised 3-Gaussian sum."""
        m = self._morphology
        systolic = m.systolic_amplitude * _gauss(phase, m.systolic_pos, m.systolic_width)
        diastolic = m.diastolic_amplitude * _gauss(phase, m.diastolic_pos, m.diastolic_width)
        notch = (m.dicrotic_depth * dicrotic_factor * m.systolic_amplitude
                 * _gauss(phase, m.notch_pos, m.notch_width))
        return systolic + diastolic - notch

    def _peak_scale(self) -> float:
        """Peak of the raw pulse for the current morphology, cached.

        Evaluated at dicrotic_factor = 1.0 on purpose: the SpO2 coupling must
        reshape the notch, not rescale the whole waveform.
        """
        key = self._morphology.scale_key()
        if key != self._scale_key:
            self._scale_key = key
            self._scale = self._find_peak()
            self.peak_search_count += 1
        return self._scale

    def _find_peak(self) -> float:
        """Locate max(raw pulse) over one cycle: coarse scan then golden section."""
        steps = PULSE_PEAK_SCAN_STEPS
        best_phase = 0.0
        best_val = float("-inf")
        for i in range(steps):
            phase = i / float(steps)
            val = self._raw_ppg(phase)
            if val > best_val:
                best_val = val
                best_phase = phase

        lo = best_phase - 1.0 / steps
        hi = best_phase + 1.0 / steps
        for _ in range(PULSE_PEAK_REFINE_ITERS):
            m1 = lo + (hi - lo) / 3.0
            m2 = hi - (hi - lo) / 3.0
            if self._raw_ppg(m1) < self._raw_ppg(m2):
                lo = m1
            else:
                hi = m2
        best_val = max(best_val, self._raw_ppg(0.5 * (lo + hi)))
        return best_val if best_val > _DEGENERATE_PEAK else 1.0
