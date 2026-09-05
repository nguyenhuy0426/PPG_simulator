"""Tests for end-to-end AC/DC (perfusion index) amplitude accuracy.

The PPG model advertises a *clinical* perfusion index: PI = AC/DC x 100 %.
A user that commands PI = 3 % on a 1.5 V DC baseline must actually get an
AC swing of ~45 mV on the DAC output. These tests measure what the model
really produces and assert it matches the command.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.ppg_model import PPGModel, PPGParameters, COND_NORMAL  # noqa: E402

MODEL_DT = 0.01  # 100 Hz model tick, same as config.MODEL_DT_PPG


def _run_model(model: PPGModel, seconds: float) -> None:
    for _ in range(int(seconds / MODEL_DT)):
        model.generate_both_samples(MODEL_DT)


def _mean_measured_pi(model: PPGModel, seconds: float = 30.0) -> float:
    """Average the per-beat measured PI over a whole number of beats.

    Averaging removes the respiratory amplitude modulation (+/-25 %) and the
    beat-to-beat PI variability, leaving the systematic scale error.
    """
    _run_model(model, 5.0)  # settle: fill the first measurement window
    samples = []
    last_beat = model.beat_count
    for _ in range(int(seconds / MODEL_DT)):
        model.generate_both_samples(MODEL_DT)
        if model.beat_count != last_beat:
            last_beat = model.beat_count
            samples.append(model.get_measured_pi())
    assert samples, "no beats completed during the measurement window"
    return sum(samples) / len(samples)


def _fresh_model(pi: float, hr: float = 60.0) -> PPGModel:
    model = PPGModel()
    params = PPGParameters()
    params.condition = COND_NORMAL
    params.heart_rate = hr
    params.perfusion_index = pi
    params.spo2 = 98.0
    params.noise_level = 0.0
    model.set_parameters(params)
    return model


@pytest.mark.parametrize("commanded_pi", [3.0, 5.0, 6.0])
def test_measured_pi_matches_commanded_pi(commanded_pi):
    """Measured PI must track the commanded PI within 5 % relative error."""
    model = _fresh_model(commanded_pi)

    measured = _mean_measured_pi(model)

    rel_err = abs(measured - commanded_pi) / commanded_pi
    assert rel_err < 0.05, (
        f"commanded PI={commanded_pi:.2f} % but measured {measured:.3f} % "
        f"({rel_err * 100:.1f} % error)"
    )


def test_ac_amplitude_in_millivolts_matches_datasheet_claim():
    """PI=3 % on a 1.5 V DC baseline must give ~45 mV of AC, not ~30 mV."""
    model = _fresh_model(3.0)

    measured_pi = _mean_measured_pi(model)
    ac_mv = measured_pi / 100.0 * model.dc_baseline * 1000.0

    assert 42.0 <= ac_mv <= 48.0, f"AC = {ac_mv:.1f} mV, expected ~45 mV"


def test_pulse_shape_peaks_at_unity():
    """The normalised pulse shape must reach 1.0 at the systolic peak.

    Anything less scales every downstream AC amplitude by the same factor.
    """
    model = _fresh_model(3.0)

    peak = max(model._compute_pulse_shape(i / 2000.0) for i in range(2000))

    assert peak == pytest.approx(1.0, abs=0.01)
