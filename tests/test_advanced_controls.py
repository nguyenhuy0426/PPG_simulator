"""Tests for the parse/validate/dispatch layer behind the advanced panel.

Tk callbacks must never raise: a bad entry has to come back as a status
message, not an exception dialog. These tests pin that contract without
needing a display.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.signal_engine import SignalEngine  # noqa: E402
from models.noise import NOISE_SINE, NOISE_WHITE  # noqa: E402
from models.ppg_model import POLARITY_ABOVE_DC, POLARITY_BELOW_DC  # noqa: E402
from ui.advanced_controls import (  # noqa: E402
    ac_mv_from_pi,
    apply_ac_dc,
    apply_noise,
    apply_polarity,
    apply_spo2_coefficients,
    format_stats,
    pi_from_ac_dc,
)


@pytest.fixture
def engine():
    eng = SignalEngine()
    yield eng
    eng.stop_simulation()
    eng._stop_thread()


# ─── AC/DC ───

def test_apply_ac_dc_sets_the_model_and_derives_pi(engine):
    ok, msg = apply_ac_dc(engine, "45.0", "1500", "1500")

    assert ok, msg
    assert engine.ppg_params.dc_ir_mv == pytest.approx(1500.0)
    assert engine.ppg_params.perfusion_index == pytest.approx(3.0)


def test_apply_ac_dc_allows_independent_red_dc(engine):
    ok, msg = apply_ac_dc(engine, "45.0", "1500", "1800")

    assert ok, msg
    assert engine.ppg_params.dc_ir_mv == pytest.approx(1500.0)
    assert engine.ppg_params.dc_red_mv == pytest.approx(1800.0)


def test_apply_ac_dc_reports_a_non_numeric_entry_instead_of_raising(engine):
    ok, msg = apply_ac_dc(engine, "abc", "1500", "1500")

    assert not ok
    assert "number" in msg.lower()


def test_apply_ac_dc_reports_a_dac_headroom_violation(engine):
    # DC + AC must stay inside the 3280 mV full scale.
    ok, msg = apply_ac_dc(engine, "500", "3200", "3200")

    assert not ok
    assert msg


def test_apply_ac_dc_leaves_the_previous_setting_untouched_on_error(engine):
    apply_ac_dc(engine, "45.0", "1500", "1500")

    apply_ac_dc(engine, "500", "3200", "3200")

    assert engine.ppg_params.dc_ir_mv == pytest.approx(1500.0)


def test_blank_red_dc_mirrors_the_ir_channel(engine):
    ok, msg = apply_ac_dc(engine, "45.0", "1800", "")

    assert ok, msg
    assert engine.ppg_params.dc_red_mv == pytest.approx(1800.0)


# ─── PI <-> AC conversion (the Lock AC/DC path) ───

def test_ac_mv_from_pi_uses_the_clinical_definition():
    assert ac_mv_from_pi(3.0, 1500.0) == pytest.approx(45.0)


def test_pi_from_ac_dc_is_the_inverse():
    assert pi_from_ac_dc(45.0, 1500.0) == pytest.approx(3.0)


def test_pi_from_ac_dc_is_zero_for_a_non_positive_dc():
    assert pi_from_ac_dc(45.0, 0.0) == 0.0


# ─── Polarity ───

def test_apply_polarity_accepts_both_directions(engine):
    assert apply_polarity(engine, POLARITY_BELOW_DC)[0]
    assert engine.ppg_params.ac_polarity == POLARITY_BELOW_DC

    assert apply_polarity(engine, POLARITY_ABOVE_DC)[0]
    assert engine.ppg_params.ac_polarity == POLARITY_ABOVE_DC


def test_apply_polarity_rejects_an_unknown_value(engine):
    ok, msg = apply_polarity(engine, 7)

    assert not ok
    assert msg


# ─── SpO2 coefficients ───

def test_apply_spo2_coefficients_sets_both(engine):
    ok, msg = apply_spo2_coefficients(engine, "104.0", "17.0")

    assert ok, msg
    assert engine.ppg_params.spo2_coeff_a == pytest.approx(104.0)
    assert engine.ppg_params.spo2_coeff_b == pytest.approx(17.0)


def test_apply_spo2_coefficients_rejects_a_zero_slope(engine):
    ok, msg = apply_spo2_coefficients(engine, "110", "0")

    assert not ok
    assert msg


def test_apply_spo2_coefficients_reports_bad_text(engine):
    ok, msg = apply_spo2_coefficients(engine, "", "25")

    assert not ok
    assert "number" in msg.lower()


# ─── Noise ───

def test_apply_noise_sets_kind_and_absolute_amplitude(engine):
    ok, msg = apply_noise(engine, NOISE_WHITE, "8.0", "0")

    assert ok, msg
    assert engine.ppg_params.noise_kind == NOISE_WHITE
    assert engine.ppg_params.noise_amplitude_mv == pytest.approx(8.0)


def test_apply_noise_surfaces_the_nyquist_limit_as_a_message(engine):
    ok, msg = apply_noise(engine, NOISE_SINE, "10.0", "50")

    assert not ok
    assert "Nyquist" in msg


def test_apply_noise_reports_bad_text(engine):
    ok, msg = apply_noise(engine, NOISE_WHITE, "loud", "0")

    assert not ok
    assert "number" in msg.lower()


# ─── Buffer health ───

def test_format_stats_reports_every_counter():
    text = format_stats({"overruns": 2, "underruns": 3, "dropped_samples": 40,
                         "samples_generated": 1000, "buffer_fill": 7})

    for token in ("2", "3", "40", "7"):
        assert token in text


def test_format_stats_survives_a_missing_key():
    text = format_stats({})

    assert text
