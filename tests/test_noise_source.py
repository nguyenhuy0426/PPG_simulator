"""Tests for the PPG artefact/noise source.

The original noise was a single deterministic hash whose seed repeated every
997 samples (~9.97 s at the 100 Hz model rate), with an amplitude defined only
as a fraction of the AC component -- so at low perfusion the "noise" all but
vanished, and there was no way to ask for a specific interference frequency.

The replacement must be a real random source, must accept an amplitude in
absolute millivolts, and must refuse frequencies the 100 Hz model cannot
represent.
"""

import math
import os
import statistics
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.noise import (  # noqa: E402
    NOISE_KINDS,
    NOISE_MOTION,
    NOISE_NONE,
    NOISE_POWERLINE,
    NOISE_PROPORTIONAL,
    NOISE_SINE,
    NOISE_WHITE,
    NoiseGenerator,
)

FS = 100.0
DT = 1.0 / FS


def _collect(gen: NoiseGenerator, n: int, ac_v: float = 0.045) -> list:
    return [gen.sample(DT, ac_v) for _ in range(n)]


def test_none_produces_exactly_zero():
    gen = NoiseGenerator(FS, seed=1)
    gen.configure(NOISE_NONE, amplitude_mv=100.0)

    assert _collect(gen, 50) == [0.0] * 50


def test_white_noise_amplitude_is_absolute_and_independent_of_ac():
    """RMS must follow the requested mV, not the pulse amplitude."""
    gen = NoiseGenerator(FS, seed=7)
    gen.configure(NOISE_WHITE, amplitude_mv=10.0)

    weak = _collect(gen, 20000, ac_v=0.001)
    gen.configure(NOISE_WHITE, amplitude_mv=10.0)
    strong = _collect(gen, 20000, ac_v=0.500)

    rms_weak = statistics.pstdev(weak) * 1000.0
    rms_strong = statistics.pstdev(strong) * 1000.0
    assert rms_weak == pytest.approx(10.0, rel=0.10)
    assert rms_strong == pytest.approx(10.0, rel=0.10)


def test_white_noise_does_not_repeat_within_a_long_run():
    """The old hash repeated every 997 samples; a real source must not."""
    gen = NoiseGenerator(FS, seed=3)
    gen.configure(NOISE_WHITE, amplitude_mv=10.0)

    samples = _collect(gen, 4000)

    assert samples[:997] != samples[997:1994]
    assert len(set(samples)) > 3900


def test_same_seed_reproduces_the_same_sequence():
    """Reproducibility matters for regression runs and for reporting."""
    a = NoiseGenerator(FS, seed=42)
    a.configure(NOISE_WHITE, amplitude_mv=10.0)
    b = NoiseGenerator(FS, seed=42)
    b.configure(NOISE_WHITE, amplitude_mv=10.0)

    assert _collect(a, 200) == _collect(b, 200)


def test_different_seeds_decorrelate_the_two_channels():
    a = NoiseGenerator(FS, seed=1)
    a.configure(NOISE_WHITE, amplitude_mv=10.0)
    b = NoiseGenerator(FS, seed=2)
    b.configure(NOISE_WHITE, amplitude_mv=10.0)

    assert _collect(a, 200) != _collect(b, 200)


def test_sine_has_the_requested_peak_amplitude_and_frequency():
    gen = NoiseGenerator(FS, seed=1)
    gen.configure(NOISE_SINE, amplitude_mv=20.0, freq_hz=10.0)

    samples = _collect(gen, 1000)

    assert max(samples) * 1000.0 == pytest.approx(20.0, rel=0.05)
    assert min(samples) * 1000.0 == pytest.approx(-20.0, rel=0.05)
    # 10 Hz at 100 Hz sampling: 10 samples per cycle, 100 cycles in 1000.
    zero_crossings = sum(
        1 for x, y in zip(samples, samples[1:]) if x <= 0.0 < y)
    assert zero_crossings == pytest.approx(100, abs=2)


def test_powerline_defaults_to_fifty_hertz_is_rejected_at_nyquist():
    """50 Hz is exactly Nyquist for a 100 Hz model and cannot be represented."""
    gen = NoiseGenerator(FS, seed=1)

    with pytest.raises(ValueError, match="Nyquist"):
        gen.configure(NOISE_POWERLINE, amplitude_mv=10.0, freq_hz=50.0)


def test_frequency_above_nyquist_is_rejected():
    gen = NoiseGenerator(FS, seed=1)

    with pytest.raises(ValueError, match="Nyquist"):
        gen.configure(NOISE_SINE, amplitude_mv=10.0, freq_hz=60.0)


def test_max_frequency_is_reported_so_the_ui_can_bound_its_control():
    gen = NoiseGenerator(FS, seed=1)

    assert gen.nyquist_hz == pytest.approx(50.0)
    assert gen.max_frequency_hz < gen.nyquist_hz


def test_powerline_below_nyquist_is_accepted():
    gen = NoiseGenerator(FS, seed=1)
    gen.configure(NOISE_POWERLINE, amplitude_mv=10.0, freq_hz=25.0)

    samples = _collect(gen, 1000)

    assert max(abs(x) for x in samples) > 0.0


def test_motion_noise_is_low_frequency_and_bounded():
    """Motion artefact must be slow drift, not broadband hash."""
    gen = NoiseGenerator(FS, seed=5)
    gen.configure(NOISE_MOTION, amplitude_mv=50.0, freq_hz=0.5)

    samples = _collect(gen, 6000)

    white = NoiseGenerator(FS, seed=5)
    white.configure(NOISE_WHITE, amplitude_mv=50.0)
    white_samples = _collect(white, 6000)

    # Sample-to-sample roughness, normalised by the signal's own spread. A
    # 0.5 Hz-limited drift must be far smoother than broadband noise of the
    # same RMS (for white noise this ratio is ~1.13).
    def roughness(xs):
        return (statistics.mean(abs(b - a) for a, b in zip(xs, xs[1:]))
                / statistics.pstdev(xs))

    assert roughness(samples) < roughness(white_samples) / 4.0
    assert max(abs(x) for x in samples) * 1000.0 < 250.0


def test_proportional_mode_preserves_the_legacy_behaviour():
    """The legacy 0-1 'noise level' stays available and scales with AC."""
    gen = NoiseGenerator(FS, seed=11)
    gen.configure(NOISE_PROPORTIONAL, level=0.5)
    small = _collect(gen, 4000, ac_v=0.010)

    gen.configure(NOISE_PROPORTIONAL, level=0.5)
    big = _collect(gen, 4000, ac_v=0.100)

    assert statistics.pstdev(big) > 5.0 * statistics.pstdev(small)


def test_amplitude_must_not_be_negative():
    gen = NoiseGenerator(FS, seed=1)

    with pytest.raises(ValueError):
        gen.configure(NOISE_WHITE, amplitude_mv=-1.0)


def test_unknown_kind_is_rejected():
    gen = NoiseGenerator(FS, seed=1)

    with pytest.raises(ValueError):
        gen.configure("cosmic-rays", amplitude_mv=1.0)


def test_all_advertised_kinds_are_configurable():
    for kind in NOISE_KINDS:
        gen = NoiseGenerator(FS, seed=1)
        gen.configure(kind, amplitude_mv=5.0, freq_hz=10.0, level=0.2)
        _collect(gen, 10)
