"""Regressions at the model/engine/persistence/UI-data boundaries."""
import math
import json
import pytest
from core.signal_engine import SignalEngine, SIG_RUNNING
from models.ppg_model import PPGParameters, PPGModel
from config_store import apply_config_to_params, config_from_ppg_params
from ui.recordings import load_recording
from core.csv_logger import CSVLogger


@pytest.fixture
def engine():
    result = SignalEngine()
    yield result
    result.shutdown()


def test_recording_uses_model_ticks_even_without_a_gui(engine, tmp_path):
    engine.set_recording(True)
    for _ in range(250): engine._generate_one_tick()
    engine.set_recording(False)
    rows = engine.drain_recording()
    assert len(rows) == 250
    assert rows[-1][-1] == pytest.approx(2.5)
    assert all(b[-1] - a[-1] == pytest.approx(.01) for a, b in zip(rows, rows[1:]))
    logger = CSVLogger(str(tmp_path))
    logger.start()
    for row in rows: logger.log_data(*row)
    logger.stop(save=True)
    samples, params, timing = load_recording(tmp_path / "data_1.csv")
    assert len(samples) == 250
    assert samples[-1][0] == pytest.approx(2.49)
    assert params[0][0] == engine.ppg_params.heart_rate
    assert "Recorded" in timing


def test_parameter_transaction_rejects_all_fields_if_shape_is_invalid(engine):
    values = config_from_ppg_params(engine.ppg_params)
    values.update(ac_ir_mv=25., ac_red_mv=10., dc_ir_mv=1100., sp_ms_red=500., dn_ms_red=300.)
    before = config_from_ppg_params(engine.ppg_params)
    with pytest.raises(ValueError): engine.update_signal_settings(values)
    assert config_from_ppg_params(engine.ppg_params) == before
    assert engine.ppg_model.dc_ir == 1.5


def test_manual_ac_and_respiration_survive_restart_and_config(engine):
    engine.update_ac_levels(20, 10)
    engine.update_respiration(engine.ppg_model.respiration.config.replace(rate_brpm=50, amplitude_enabled=False))
    params = PPGParameters()
    apply_config_to_params(config_from_ppg_params(engine.ppg_params), params)
    engine.load_parameters(params)
    engine.start_simulation()
    engine.stop_simulation()
    assert engine.ppg_model.params.ac_red_mv == 10
    assert engine.ppg_model.params.perfusion_index == pytest.approx(20/1500*100)
    assert engine.ppg_model.respiration.config.rate_brpm == 50
    assert not engine.ppg_model.respiration.config.amplitude_enabled


def test_legacy_coupling_setters_update_persisted_parameters():
    model = PPGModel()
    model.set_hr_amplitude_coupling(False)
    model.set_spo2_coupling(False)
    saved = config_from_ppg_params(model.params)
    assert saved["hr_amplitude_enabled"] is False
    assert saved["spo2_coupling_enabled"] is False


def test_calibration_ticks_are_independent_of_gui_and_stop_parks_outputs(engine):
    engine._calibration = (10., 1000.)
    for _ in range(100): engine._generate_one_tick()
    data = engine.get_display_history()
    assert data[-1][0] == pytest.approx(1.)
    # Spectral peak handles the two equal sampled maxima at 10 Hz / 100 Hz.
    energy = lambda f: abs(sum(complex(math.cos(2*math.pi*f*p[0]),
                                      -math.sin(2*math.pi*f*p[0])) * (p[1]-.5) for p in data))
    assert max(range(1, 21), key=energy) == 10
    assert all(0 <= p[1] <= 1 for p in data)
    engine.stop_simulation()
    assert engine.dac_manager.last_ir == engine.dac_manager.last_red == 0


@pytest.mark.parametrize("bad", [None, "wrong", float("nan"), -2])
def test_corrupt_noise_config_can_still_start(bad):
    params = PPGParameters()
    apply_config_to_params({"noise_kind":"white", "noise_amplitude_mv":bad}, params)
    model = PPGModel()
    model.set_parameters(params)
    assert all(math.isfinite(x) for x in model.generate_both_samples(.01))


def test_lock_ac_moves_dc_when_pi_is_changed():
    model = PPGModel()
    model.set_ac_levels(45)
    model.set_lock(lock_ac=True)
    model.set_perfusion_index(4.5)
    assert model.params.dc_ir_mv == pytest.approx(1000)
    assert model.params.ac_ir_mv == pytest.approx(45)
    model.set_lock(lock_dc=True)
    model.set_perfusion_index(9)
    assert model.params.perfusion_index == 4.5


def test_invalid_save_keeps_previous_config(tmp_path, monkeypatch):
    import config_store
    dest = tmp_path / "config.json"
    dest.write_text('{"heart_rate": 80}')
    monkeypatch.setattr(config_store, "CONFIG_JSON_PATH", str(dest))
    assert not config_store.save_config({"heart_rate":float("nan")})
    assert json.loads(dest.read_text()) == {"heart_rate":80}
    assert not list(tmp_path.glob(".ppg-config-*"))


def test_csv_rejects_nonmonotonic_timestamps(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("IR_Raw,RED_Raw,HR_BPM,SpO2_%,RR_BPM,PI_%,Condition,Time_s\n100,100,75,98,16,3,Normal,1\n100,100,75,98,16,3,Normal,0.5\n")
    with pytest.raises(ValueError, match="strictly increasing"): load_recording(path)


@pytest.mark.parametrize("spo2", [0., 40., 70., 98., 100.])
def test_full_spo2_target_changes_the_actual_red_ratio(spo2):
    from models.respiration import RespirationConfig
    model = PPGModel()
    model.set_heart_rate(60)
    model.hr_amplitude_enabled = False
    model.spo2_coupling_enabled = False
    model.cond_ranges.pi_cv = 0
    model.cond_ranges.hr_cv = 0
    model.set_respiration(RespirationConfig(baseline_enabled=False, amplitude_enabled=False, frequency_enabled=False))
    model.set_ac_levels(20)
    model.set_spo2(spo2)
    data = [model.generate_both_samples(.01) for _ in range(300)]
    ir = max(p[2] for p in data)-min(p[2] for p in data)
    red = max(p[3] for p in data)-min(p[3] for p in data)
    assert red/ir == pytest.approx((110-spo2)/25, rel=.001)
    assert model.clipped_samples == 0
