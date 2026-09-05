"""Tests for SignalEngine parameter ownership and state handling.

These cover two defects found in the audit:
  * start_simulation() replaced the live parameters with a fresh
    PPGParameters(), silently discarding everything the user had set.
  * update_noise_level() clamped its own copy to 0.10 while forwarding the
    unclamped value to the model, so the UI read-back disagreed with the
    signal that was actually generated.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.signal_engine import SignalEngine  # noqa: E402
from models.ppg_model import COND_NORMAL, COND_ARRHYTHMIA  # noqa: E402


@pytest.fixture
def engine():
    eng = SignalEngine()
    yield eng
    eng.stop_simulation()
    eng._stop_thread()


def test_start_simulation_preserves_user_settings(engine):
    """Settings made before pressing Run must survive the start."""
    engine.update_heart_rate(120.0)
    engine.update_perfusion_index(6.0)
    engine.update_resp_rate(25.0)
    engine.update_spo2(92.0)

    engine.start_simulation(COND_NORMAL)

    assert engine.ppg_params.heart_rate == pytest.approx(120.0)
    assert engine.ppg_params.perfusion_index == pytest.approx(6.0)
    assert engine.ppg_params.resp_rate == pytest.approx(25.0)
    assert engine.ppg_params.spo2 == pytest.approx(92.0)
    assert engine.ppg_model.params.heart_rate == pytest.approx(120.0)
    assert engine.ppg_model.params.perfusion_index == pytest.approx(6.0)


def test_start_simulation_preserves_dc_levels(engine):
    """Per-channel DC set through the AC/DC API must survive the start."""
    engine.update_dc_levels(1200.0, 1800.0)

    engine.start_simulation(COND_NORMAL)

    assert engine.ppg_model.dc_ir == pytest.approx(1.2)
    assert engine.ppg_model.dc_red == pytest.approx(1.8)


def test_start_simulation_applies_requested_condition(engine):
    """The condition argument must still take effect."""
    engine.start_simulation(COND_ARRHYTHMIA)

    assert engine.ppg_params.condition == COND_ARRHYTHMIA
    assert engine.ppg_model.params.condition == COND_ARRHYTHMIA


@pytest.mark.parametrize("requested", [0.0, 0.05, 0.30, 0.80, 1.0])
def test_noise_level_readback_matches_model(engine, requested):
    """What the UI reads back must be exactly what the model generates with."""
    engine.update_noise_level(requested)

    assert engine.ppg_params.noise_level == pytest.approx(
        engine.ppg_model.params.noise_level
    )
    assert engine.ppg_params.noise_level == pytest.approx(requested)


@pytest.mark.parametrize("requested,expected", [(-0.5, 0.0), (2.0, 1.0)])
def test_noise_level_out_of_range_clamps_consistently(engine, requested, expected):
    engine.update_noise_level(requested)

    assert engine.ppg_params.noise_level == pytest.approx(expected)
    assert engine.ppg_model.params.noise_level == pytest.approx(expected)


def test_heart_rate_readback_matches_model_after_clamping(engine):
    """The panel must show the HR the model really runs at, not the request.

    PPGModel.set_heart_rate now supports 10-300 BPM. Mirroring the raw request
    back onto ppg_params made the UI claim 300 BPM while the generator ran at
    180 -- a silent divergence between display and output.
    """
    engine.update_heart_rate(300.0)

    assert engine.ppg_params.heart_rate == pytest.approx(
        engine.ppg_model.params.heart_rate
    )
    assert engine.ppg_params.heart_rate == pytest.approx(300.0)


def test_perfusion_index_readback_matches_model_after_clamping(engine):
    engine.update_perfusion_index(99.0)

    assert engine.ppg_params.perfusion_index == pytest.approx(
        engine.ppg_model.params.perfusion_index
    )


def test_update_spo2_coefficients_applies_to_model_and_params(engine):
    engine.update_spo2_coefficients(104.0, 17.0)

    assert engine.ppg_params.spo2_coeff_a == pytest.approx(104.0)
    assert engine.ppg_params.spo2_coeff_b == pytest.approx(17.0)
    assert engine.ppg_model.params.spo2_coeff_a == pytest.approx(104.0)
    assert engine.ppg_model.params.spo2_coeff_b == pytest.approx(17.0)


def test_update_spo2_coefficients_rejects_non_invertible_b(engine):
    with pytest.raises(ValueError):
        engine.update_spo2_coefficients(110.0, 0.0)


def test_update_spo2_coefficients_survives_start_simulation(engine):
    engine.update_spo2_coefficients(104.0, 17.0)

    engine.start_simulation(COND_NORMAL)

    assert engine.ppg_model.params.spo2_coeff_a == pytest.approx(104.0)
    assert engine.ppg_model.params.spo2_coeff_b == pytest.approx(17.0)


# ─── AC/DC lock (B1): AC and DC are master, PI is a derived read-out ───

def test_ac_dc_lock_defaults_to_off(engine):
    assert engine.ac_dc_locked is False


def test_locking_ac_dc_makes_the_pi_slider_a_no_op(engine):
    engine.update_ac_dc(45.0, 1500.0, 1500.0)

    engine.set_ac_dc_lock(True)
    engine.update_perfusion_index(12.0)

    assert engine.ppg_params.perfusion_index == pytest.approx(3.0)
    assert engine.ppg_model.params.perfusion_index == pytest.approx(3.0)


def test_unlocking_restores_pi_control(engine):
    engine.set_ac_dc_lock(True)
    engine.set_ac_dc_lock(False)

    engine.update_perfusion_index(5.0)

    assert engine.ppg_params.perfusion_index == pytest.approx(5.0)


def test_the_lock_survives_start_simulation(engine):
    engine.set_ac_dc_lock(True)

    engine.start_simulation(COND_NORMAL)

    assert engine.ac_dc_locked is True
