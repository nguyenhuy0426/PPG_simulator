"""Tests that the model actually emits the configured artefact.

Covers the wiring between PPGParameters / PPGModel / SignalEngine and the
NoiseGenerator: the artefact must reach the generated waveform, must be
specified in absolute millivolts, and must be reproducible from a seed.
"""

import os
import random
import statistics
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.signal_engine import SignalEngine  # noqa: E402
from models.noise import (  # noqa: E402
    NOISE_NONE,
    NOISE_PROPORTIONAL,
    NOISE_SINE,
    NOISE_WHITE,
)
from models.ppg_model import COND_NORMAL, PPGModel, PPGParameters  # noqa: E402

DT = 0.01

# The model draws its beat-to-beat HR/PI variability from the *global* RNG.
# Seeding it identically before construction and before each run makes two
# model instances comparable sample-for-sample; the artefact stream is
# unaffected because NoiseGenerator owns a private random.Random.
PHYSIO_SEED = 20240607


def _model(**kwargs) -> PPGModel:
    random.seed(PHYSIO_SEED)
    model = PPGModel()
    params = PPGParameters()
    params.condition = COND_NORMAL
    params.heart_rate = 60.0
    params.perfusion_index = 3.0
    params.noise_level = 0.0
    for key, value in kwargs.items():
        setattr(params, key, value)
    model.set_parameters(params)
    return model


def _display_ir(model: PPGModel, n: int) -> list:
    random.seed(PHYSIO_SEED)
    out = []
    for _ in range(n):
        model.generate_both_samples(DT)
        out.append(model.last_display_ir)
    return out


def test_default_parameters_keep_the_legacy_noise_contract():
    params = PPGParameters()

    assert params.noise_kind == NOISE_PROPORTIONAL
    assert params.noise_level == 0.0
    assert params.noise_amplitude_mv == 0.0


def test_no_noise_configured_leaves_the_waveform_untouched():
    quiet = _model(noise_kind=NOISE_NONE)
    also_quiet = _model(noise_kind=NOISE_NONE)

    assert _display_ir(quiet, 500) == _display_ir(also_quiet, 500)


def test_white_noise_adds_the_requested_millivolts_to_the_output():
    clean = _model(noise_kind=NOISE_NONE)
    noisy = _model(noise_kind=NOISE_WHITE, noise_amplitude_mv=8.0, noise_seed=1)

    residual = [n - c for c, n in zip(_display_ir(clean, 20000),
                                      _display_ir(noisy, 20000))]

    assert statistics.pstdev(residual) * 1000.0 == pytest.approx(8.0, rel=0.10)


def test_artefact_amplitude_does_not_collapse_at_low_perfusion():
    """The whole point of absolute-mV artefacts: PI must not scale them."""
    strong = _model(noise_kind=NOISE_WHITE, noise_amplitude_mv=8.0,
                    noise_seed=1, perfusion_index=6.0)
    weak = _model(noise_kind=NOISE_WHITE, noise_amplitude_mv=8.0,
                  noise_seed=1, perfusion_index=0.6)
    clean_strong = _model(noise_kind=NOISE_NONE, perfusion_index=6.0)
    clean_weak = _model(noise_kind=NOISE_NONE, perfusion_index=0.6)

    res_strong = [n - c for c, n in zip(_display_ir(clean_strong, 20000),
                                        _display_ir(strong, 20000))]
    res_weak = [n - c for c, n in zip(_display_ir(clean_weak, 20000),
                                      _display_ir(weak, 20000))]

    assert (statistics.pstdev(res_weak)
            == pytest.approx(statistics.pstdev(res_strong), rel=0.10))


def test_noise_seed_makes_a_run_reproducible():
    a = _model(noise_kind=NOISE_WHITE, noise_amplitude_mv=8.0, noise_seed=99)
    b = _model(noise_kind=NOISE_WHITE, noise_amplitude_mv=8.0, noise_seed=99)

    assert _display_ir(a, 300) == _display_ir(b, 300)


def test_the_two_channels_get_independent_artefacts():
    model = _model(noise_kind=NOISE_WHITE, noise_amplitude_mv=8.0, noise_seed=1)

    random.seed(PHYSIO_SEED)
    ir, red = [], []
    for _ in range(300):
        model.generate_both_samples(DT)
        ir.append(model.last_display_ir)
        red.append(model.last_display_red)

    assert ir != red


def test_set_noise_rejects_a_frequency_above_the_model_bandwidth():
    model = _model()

    with pytest.raises(ValueError, match="Nyquist"):
        model.set_noise(NOISE_SINE, amplitude_mv=10.0, freq_hz=50.0)


def test_engine_update_noise_mirrors_into_params():
    engine = SignalEngine()
    try:
        engine.update_noise(NOISE_SINE, amplitude_mv=12.0, freq_hz=10.0)

        assert engine.ppg_params.noise_kind == NOISE_SINE
        assert engine.ppg_params.noise_amplitude_mv == pytest.approx(12.0)
        assert engine.ppg_params.noise_freq_hz == pytest.approx(10.0)
        assert engine.ppg_model.params.noise_kind == NOISE_SINE
    finally:
        engine._stop_thread()


def test_engine_noise_settings_survive_start_simulation():
    engine = SignalEngine()
    try:
        engine.update_noise(NOISE_WHITE, amplitude_mv=5.0)

        engine.start_simulation(COND_NORMAL)

        assert engine.ppg_model.params.noise_kind == NOISE_WHITE
        assert engine.ppg_model.params.noise_amplitude_mv == pytest.approx(5.0)
    finally:
        engine.stop_simulation()
        engine._stop_thread()
