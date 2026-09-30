"""Finite clip output, source isolation and missing-sensor behavior."""
import time
from unittest.mock import Mock
import pytest
from core.neural_preview import gaussian_preview
from core.waveform_clip import WaveformClip
from core.signal_engine import SignalEngine, SIG_STOPPED
from config_store import config_from_ppg_params
from hw.opt101_rx import OPT101Receiver


def test_native_sequence_interpolation_and_end():
    clip=WaveformClip(((0.,1.,2.),(.025,2.,1.)),40.,'test')
    clip.validate()
    assert clip.at(.01)==pytest.approx((1.4,1.6))
    assert clip.at(.04)==pytest.approx((2,1))
    assert clip.duration==.05
    with pytest.raises(ValueError): clip.at(.05)


@pytest.mark.parametrize('rows,fs',[
    (((0,1,1),(.03,1,1)),40),
    (((0,float('nan'),1),(.025,1,1)),40),
    (((0,3.5,1),(.025,1,1)),40),
    (((0,1,1),(.025,1,1)),float('nan')),
])
def test_invalid_clip_rejected(rows,fs):
    with pytest.raises(ValueError): WaveformClip(rows,fs,'bad').validate()


def test_clip_scale_preserves_shape_and_parameters():
    preview=gaussian_preview(75,'With notch')
    clip=WaveformClip.from_preview(preview,1000,100)
    assert clip.samples[25][1]==pytest.approx(1+.1*(preview.samples[25][1]-1.5)/.045)
    assert clip.samples[25][2]==pytest.approx(1+.1*(preview.samples[25][2]-1.5)/.045)
    assert clip.samples[-1][0]==29.99


def engine_with_dac():
    engine=SignalEngine()
    engine.dac_manager=Mock(is_ready=True)
    return engine


def test_finite_playback_parks_outputs_and_classic_restart_clears_source():
    engine=engine_with_dac()
    clip=WaveformClip(tuple((i/40,1+i/1000,1) for i in range(4)),40,'fixture')
    original=config_from_ppg_params(engine.ppg_params)
    try:
        engine.start_waveform(clip)
        assert not engine.start_recording()
        time.sleep(.16)
        engine._stop_thread()
        assert engine.state==SIG_STOPPED
        assert not engine.is_waveform_playing
        assert engine.dac_manager.set_values.call_args.args==(0,0)
        history=engine.get_display_history()
        assert len(history)==10
        assert history[1][1]==pytest.approx(1.0004)
        assert config_from_ppg_params(engine.ppg_params)==original
        engine.start_simulation()
        assert engine._waveform_clip is None
    finally:
        engine.stop_simulation()


def test_invalid_clip_does_not_interrupt_active_output():
    engine=engine_with_dac()
    try:
        engine.start_simulation()
        with pytest.raises(ValueError):
            engine.start_waveform(WaveformClip(((0,9,0),(.01,1,0)),100,'bad'))
        assert engine.is_running
        assert engine._waveform_clip is None
    finally: engine.stop_simulation()


def test_a0_only_never_reads_floating_a2_or_fabricates_red():
    adc=Mock()
    adc.read_raw.return_value=1234
    rx=OPT101Receiver(adc=adc,dry_run=False,enabled_channels=(0,))
    assert rx.begin()
    for _ in range(3): rx._acquire_once()
    assert [c.args for c in adc.read_raw.call_args_list]==[(0,)]*4
    assert rx.sample_count(0)==3
    assert rx.sample_count(2)==0
    assert rx.get_latest(2) is None
    assert rx.channel_status(2)=='disabled'
    assert rx.is_stale(2)


def test_a0_dry_run_keeps_a2_disabled():
    rx=OPT101Receiver(dry_run=True,enabled_channels=(0,))
    rx.begin()
    assert rx.channel_status(0)=='dry-run'
    assert rx.channel_status(2)=='disabled'


def test_real_sequence_retains_native_timing_and_train_provenance():
    from core.neural_preview import sequence_reference_preview
    preview=sequence_reference_preview()
    assert preview.native_fs==40 and preview.hr_target is None
    assert len(preview.samples)==1200
    assert preview.samples[-1][0]==29.975
    assert preview.provenance['split']=='train'
    assert preview.provenance['paired_ir_red'] is False
    WaveformClip.from_preview(preview).validate()
