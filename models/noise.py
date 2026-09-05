"""noise.py — artefact / interference sources for the PPG simulator.

Why this module exists
----------------------
The original in-model noise was a single deterministic hash,
``sin(i·127.1 + 33.7)·43758.5453 mod 1``, seeded from
``beat_count·31 + int(simulated_time_ms) % 997``. That has three problems for
a bench signal source:

1. The seed repeats every 997 samples — ~9.97 s at the 100 Hz model rate — so
   the "random" artefact is a 0.1 Hz periodic pattern, not noise.
2. Its amplitude was defined purely as a fraction of the AC component, so at
   low perfusion (PI < 1 %) the artefact all but disappeared. Bench artefact
   levels are specified in absolute millivolts.
3. There was no way to ask for a specific interference frequency (mains hum,
   motion band), which is the whole point of an artefact injector.

Bandwidth limits — be explicit about them
-----------------------------------------
The noise is summed into the model output, which is generated at the model
tick rate (100 Hz today). Nothing at or above Nyquist (50 Hz) can be
represented at that rate, so this module REFUSES such a request rather than
silently aliasing it into a different, wrong frequency. Mains interference at
50/60 Hz, switching noise and broadband noise above 50 Hz therefore remain
out of reach until the model tick rate itself is raised — that is a separate
change, not something this module can fake.
"""

import math
import random

# ─── Artefact kinds ───
NOISE_NONE = "none"
NOISE_PROPORTIONAL = "proportional"  # legacy: amplitude = level × AC
NOISE_WHITE = "white"                # Gaussian broadband, amplitude_mv = RMS
NOISE_SINE = "sine"                  # single tone, amplitude_mv = peak
NOISE_POWERLINE = "powerline"        # tone + 3rd harmonic (mains-hum shape)
NOISE_MOTION = "motion"              # low-pass filtered noise (movement drift)

NOISE_KINDS = (
    NOISE_NONE,
    NOISE_PROPORTIONAL,
    NOISE_WHITE,
    NOISE_SINE,
    NOISE_POWERLINE,
    NOISE_MOTION,
)

# Highest frequency accepted, as a fraction of Nyquist. A tone exactly at
# Nyquist collapses to a phase-dependent constant when sampled, so leave
# headroom rather than accepting a request the output cannot honour.
MAX_FREQ_FRACTION_OF_NYQUIST = 0.8

# Mains hum is not a pure sine; the 3rd harmonic at this relative level gives
# the familiar flat-topped shape without pretending to model a real supply.
POWERLINE_THIRD_HARMONIC_RATIO = 0.15

# Legacy proportional mode: peak artefact = level × AC × this factor. Matches
# the (rand − 0.5) × 2.5 scaling of the original implementation.
PROPORTIONAL_GAIN = 1.25

# Peak/RMS headroom used to bound the motion-artefact output.
MOTION_PEAK_HEADROOM = 4.0


class NoiseGenerator:
    """A single-channel artefact source. Use one instance per channel."""

    def __init__(self, sample_rate_hz: float, seed=None) -> None:
        if sample_rate_hz <= 0.0:
            raise ValueError("sample_rate_hz must be > 0")
        self._fs = float(sample_rate_hz)
        self._rng = random.Random(seed)
        self._kind = NOISE_NONE
        self._amplitude_v = 0.0
        self._level = 0.0
        self._freq_hz = 0.0
        self._phase_rad = 0.0
        self._lp_state = 0.0

    # ─── Bandwidth ───
    @property
    def sample_rate_hz(self) -> float:
        return self._fs

    @property
    def nyquist_hz(self) -> float:
        return self._fs / 2.0

    @property
    def max_frequency_hz(self) -> float:
        """Highest frequency this source will accept at the current rate."""
        return self.nyquist_hz * MAX_FREQ_FRACTION_OF_NYQUIST

    # ─── Configuration ───
    def configure(self, kind: str, amplitude_mv: float = 0.0,
                  freq_hz: float = 0.0, level: float = 0.0) -> None:
        """Select the artefact kind and its parameters.

        Args:
            kind: one of NOISE_KINDS.
            amplitude_mv: RMS for NOISE_WHITE/NOISE_MOTION, peak for the tones.
            freq_hz: tone frequency, or the cutoff for NOISE_MOTION. Must stay
                below `max_frequency_hz`.
            level: legacy 0–1 fraction, only used by NOISE_PROPORTIONAL.

        Raises:
            ValueError: unknown kind, negative amplitude/level, or a frequency
                the current sample rate cannot represent.
        """
        if kind not in NOISE_KINDS:
            raise ValueError(
                f"unknown noise kind {kind!r}; expected one of {NOISE_KINDS}")
        if not math.isfinite(amplitude_mv) or amplitude_mv < 0.0:
            raise ValueError(f"amplitude_mv must be >= 0, got {amplitude_mv!r}")
        if not math.isfinite(level) or level < 0.0:
            raise ValueError(f"level must be >= 0, got {level!r}")
        if not math.isfinite(freq_hz) or freq_hz < 0.0:
            raise ValueError(f"freq_hz must be >= 0, got {freq_hz!r}")
        if kind in (NOISE_SINE, NOISE_POWERLINE, NOISE_MOTION):
            if freq_hz > self.max_frequency_hz:
                raise ValueError(
                    f"freq_hz={freq_hz} Hz exceeds the usable band "
                    f"(<= {self.max_frequency_hz:.1f} Hz) for a "
                    f"{self._fs:.0f} Hz model rate — Nyquist is "
                    f"{self.nyquist_hz:.1f} Hz; raise the model tick rate "
                    f"before asking for this frequency")

        self._kind = kind
        self._amplitude_v = amplitude_mv / 1000.0
        self._level = level
        self._freq_hz = freq_hz
        self._phase_rad = 0.0
        self._lp_state = 0.0

    # ─── Generation ───
    def sample(self, dt_s: float, ac_amplitude_v: float = 0.0) -> float:
        """Return one artefact sample in Volts.

        Args:
            dt_s: time step since the previous sample.
            ac_amplitude_v: current pulsatile amplitude — only NOISE_PROPORTIONAL
                uses it; every other kind is amplitude-absolute by design.
        """
        if self._kind == NOISE_NONE:
            return 0.0
        if self._kind == NOISE_PROPORTIONAL:
            return ((self._rng.random() - 0.5) * 2.0
                    * PROPORTIONAL_GAIN * self._level * ac_amplitude_v)
        if self._kind == NOISE_WHITE:
            return self._rng.gauss(0.0, self._amplitude_v)
        if self._kind == NOISE_SINE:
            return self._amplitude_v * math.sin(self._advance_phase(dt_s))
        if self._kind == NOISE_POWERLINE:
            phase = self._advance_phase(dt_s)
            return self._amplitude_v * (
                math.sin(phase)
                + POWERLINE_THIRD_HARMONIC_RATIO * math.sin(3.0 * phase))
        if self._kind == NOISE_MOTION:
            return self._motion_sample(dt_s)
        return 0.0

    def _advance_phase(self, dt_s: float) -> float:
        self._phase_rad = (self._phase_rad
                           + 2.0 * math.pi * self._freq_hz * dt_s) % (2.0 * math.pi)
        return self._phase_rad

    def _motion_sample(self, dt_s: float) -> float:
        """One-pole low-pass over white noise → slow movement-like drift."""
        if self._freq_hz <= 0.0 or dt_s <= 0.0:
            return 0.0
        # Standard one-pole RC coefficient for the requested cutoff.
        rc = 1.0 / (2.0 * math.pi * self._freq_hz)
        alpha = dt_s / (rc + dt_s)
        # Filtering removes power, so pre-compensate to keep the requested RMS.
        gain = math.sqrt(max(1e-9, (2.0 - alpha) / alpha))
        self._lp_state += alpha * (self._rng.gauss(0.0, self._amplitude_v) * gain
                                   - self._lp_state)
        limit = MOTION_PEAK_HEADROOM * self._amplitude_v
        return max(-limit, min(limit, self._lp_state))
