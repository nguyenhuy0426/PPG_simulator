"""Pulse tone plumbing: pitch from SpO2, WAV tone, and tones only for locked beats of a PPG output."""
import wave
from collections import namedtuple

import pytest

from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED
from hw import beeper as B
from tests.test_beat_detector import pulse_wave

Sample = namedtuple("Sample", "timestamp raw saturated")


def test_pitch_falls_with_spo2_and_is_neutral_without_it():
    assert B.pitch_hz(100) == pytest.approx(880.0)
    assert B.pitch_hz(76) == pytest.approx(880.0 / 2)            # 24 % = 12 semitones = one octave
    assert B.pitch_hz(50) == B.pitch_hz(B.MIN_SPO2_PITCH)
    assert B.pitch_hz(None) == B.NEUTRAL_HZ == B.pitch_hz(float("nan"))


def test_tone_file_is_short_mono_pcm(tmp_path):
    path = tmp_path / "t.wav"
    B.tone_wav(str(path), 880)
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, B.SAMPLE_RATE)
        assert w.getnframes() == int(B.TONE_S * B.SAMPLE_RATE)


class FakeProc:
    def __init__(self, busy):
        self.busy = busy

    def poll(self):
        return None if self.busy else 0


def test_player_never_stacks_processes(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(B.subprocess, "Popen", lambda cmd, **kw: started.append(cmd) or FakeProc(busy=True))
    player = B.TonePlayer(command="/usr/bin/pw-play", cache_dir=str(tmp_path))
    assert player.beep(880) is True
    assert player.beep(880) is False                             # previous tone still playing
    assert len(started) == 1 and started[0][-1].endswith("beep-880.wav")
    assert started[0][1:3] == ["--latency", "10ms"]                # default 100 ms split the tone on the Pi
    assert B.TonePlayer(command=None, cache_dir=str(tmp_path)).available in (True, False)


class FakeEngine:
    def __init__(self, running=True, calibrating=False):
        self.is_running, self.is_calibrating = running, calibrating


class FakeReceiver:
    def __init__(self, values):
        self.samples = [Sample(i / 100, round(v / B.MV_PER_CODE), False) for i, v in enumerate(values)]

    def get_samples_since(self, channel, since):
        upto = self.now
        lane = self.samples if channel == ADC_CHANNEL_IR else [s._replace(raw=5) for s in self.samples]
        return [s for s in lane if since <= s.timestamp <= upto]


class FakePlayer:
    available = True

    def __init__(self):
        self.tones = []

    def beep(self, hz):
        self.tones.append(hz)
        return True


def run(engine, enabled=True, spo2=None, seconds=20):
    values, _ = pulse_wave(90, seconds)
    receiver, player = FakeReceiver(values), FakePlayer()
    beeper = B.HeartBeeper(receiver=receiver, engine=engine, player=player)
    beeper.set_enabled(enabled)
    beeper.set_spo2(spo2)
    t = 0.0
    while t < seconds:
        receiver.now = t
        beeper.poll(t)
        t += B.POLL_S
    return player.tones


def test_tones_follow_the_received_beats_of_a_ppg_output():
    tones = run(FakeEngine(), spo2=97.0)
    assert 20 <= len(tones) <= 30                                # 90 bpm for 20 s, minus the lock-in beats
    assert all(hz == pytest.approx(B.pitch_hz(97.0)) for hz in tones)


@pytest.mark.parametrize("engine,enabled", ((FakeEngine(running=False), True),
                                            (FakeEngine(calibrating=True), True),
                                            (FakeEngine(), False)))
def test_silent_when_stopped_calibrating_or_muted(engine, enabled):
    assert run(engine, enabled=enabled) == []
