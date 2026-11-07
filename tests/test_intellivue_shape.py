"""The app's pulse shape is the IntelliVue fit and the run defaults are HR 75, SpO2 99, RR 16 (Normal)."""
import json
import math
from pathlib import Path

import config_store
from models import limits
from models.ppg_model import COND_NORMAL, PPGModel, PPGParameters
from models.waveform import PulseMorphology, PulseShaper, WAVE_PPG

ROOT = Path(__file__).resolve().parents[1]
FIT = json.loads((ROOT/"assets/gaussian/intellivue_fit.json").read_text())


def rmse(a, b):
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b))/len(a))


def app_beat(model):
    """One normalised beat of the shape the model plays (IR), on the fit's phase grid."""
    n = len(FIT["mean_beat"])
    return [model._compute_pulse_shape(min(i/(n-1), 1-1e-9)) for i in range(n)]


def test_defaults_are_the_reference_screen():
    p = PPGParameters()
    assert (p.condition, p.heart_rate, p.spo2, p.resp_rate) == (COND_NORMAL, 75.0, 99.0, 16.0)
    for channel in ("ir", "red"):
        assert [getattr(p, k+channel) for k in ("sp_ms_", "dn_ms_", "dp_ms_")] == [240, 257, 536]
    assert p.dicrotic_notch == 0.65 and abs(p.dicrotic_notch-FIT["morphology"]["dicrotic_depth"]) < .01
    assert limits.SPO2.default == 99.0 and limits.DICROTIC_NOTCH_DEPTH.default == p.dicrotic_notch


def test_played_shape_matches_the_fit_within_beat_spread():
    model = PPGModel()
    beat = app_beat(model)
    assert max(beat) > .999 and min(beat) == 0.0    # the 256-point grid need not hit the exact peak
    # The app rounds feature times to 1 ms and the notch depth to 0.01; it must still be within the spread
    # of the photographed beats and close to the unrounded fit.
    assert rmse(beat, FIT["mean_beat"]) < FIT["beat_to_beat_rms_sd"]
    assert rmse(beat, FIT["fitted_beat"]) < .005


def test_waveform_defaults_equal_the_model_preset():
    shaper, model = PulseShaper(PulseMorphology()), PPGModel()
    n = len(FIT["mean_beat"])
    default = [shaper.sample(WAVE_PPG, min(i/(n-1), 1-1e-9)) for i in range(n)]
    assert rmse(default, app_beat(model)) < 1e-9


def test_saved_config_and_fresh_config_load_the_defaults():
    for config in (config_store.load_config(), dict(config_store._DEFAULTS)):
        p = PPGParameters()
        config_store.apply_config_to_params(config, p)
        assert (p.condition, p.heart_rate, p.spo2, p.resp_rate) == (COND_NORMAL, 75.0, 99.0, 16.0)
        assert (p.sp_ms_ir, p.dn_ms_ir, p.dp_ms_ir) == (240, 257, 536)
        assert p.dicrotic_notch == 0.65
