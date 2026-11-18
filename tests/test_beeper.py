"""Pulse tone plumbing: one fixed pitch, WAV tone, and tones only for locked beats of a PPG output."""
import time
import wave
from collections import namedtuple

import pytest

from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED
from hw import beeper as B
from test_beat_detector import pulse_wave

Sample = namedtuple("Sample", "timestamp raw saturated")


def test_one_fixed_pitch():
    """The pitch used to follow the received SpO2 (660 Hz with no estimate): several tones were heard."""
    assert B.TONE_HZ == 880.0
    assert not hasattr(B, "pitch_hz") and not hasattr(B.HeartBeeper, "set_spo2")


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
        self.tones, self.at, self.stops = [], [], 0

    def beep(self, hz, at=None):
        self.tones.append(hz)
        self.at.append(at)
        return True

    def stop(self):
        self.stops += 1

    def prepare(self):
        self.prepared = getattr(self, "prepared", 0) + 1
        return True


def run(engine, enabled=True, seconds=20, player=None, log=None):
    values, _ = pulse_wave(90, seconds)
    receiver, player = FakeReceiver(values), player or FakePlayer()
    beeper = B.HeartBeeper(receiver=receiver, engine=engine, player=player)
    beeper.set_enabled(enabled)
    t = 0.0
    while t < seconds:
        receiver.now = t
        beat = beeper.poll(t)
        if beat is not None and log is not None:
            log.append((t, beat))
        t += B.POLL_S
    return player.tones


def test_tones_are_timed_from_the_beat_peaks_not_the_poll():
    """On the Pi the tones started at poll time + a process start: spacing in ~21 ms steps. Each tone is now due
    a fixed delay after its peak, late enough to be written ahead of the speaker."""
    player, log = FakePlayer(), []
    run(FakeEngine(), player=player, log=log)
    assert len(log) >= 20
    for (detected, beat), at in zip(log, player.at):
        assert at - detected >= B.POLL_S + B.CHUNK_S + B.QUEUE_S       # never already late when written
        assert at - beat <= B.MAX_DELAY_S
    delays = [at - beat for (_, beat), at in zip(log, player.at)][B.LAG_BEATS:]
    assert max(delays) - min(delays) <= B.POLL_S + 1e-9                  # spacing = the peaks' spacing
    tone_gaps = [b - a for a, b in zip(player.at[B.LAG_BEATS:], player.at[B.LAG_BEATS + 1:])]
    beat_gaps = [b - a for (_, a), (_, b) in zip(log[B.LAG_BEATS:], log[B.LAG_BEATS + 1:])]
    assert sum(abs(x - y) < 1e-9 for x, y in zip(tone_gaps, beat_gaps)) >= 0.8 * len(beat_gaps)


def test_stream_opens_as_the_output_starts_not_at_the_first_beat():
    player = FakePlayer()
    run(FakeEngine(), player=player, seconds=1)
    assert player.prepared == 1 and player.tones == []


def test_stream_is_closed_when_the_output_stops():
    player = FakePlayer()
    run(FakeEngine(running=False), player=player, seconds=1)
    assert player.stops > 0 and player.tones == []


def stream_at(base):
    clock = [base]
    player = B.StreamPlayer(command=["true"], clock=lambda: clock[0])
    player._base = base
    return player


def first_sound(pcm):
    """Index of the first non-zero sample."""
    return next(i for i in range(0, len(pcm), 2) if pcm[i:i + 2] != b"\0\0") // 2


def test_stream_places_a_tone_on_its_exact_sample_across_chunks():
    player = stream_at(10.0)
    n = int(B.CHUNK_S * B.SAMPLE_RATE)
    player.schedule(880, 10.0 + 1.5 * B.CHUNK_S + 0.001)
    pcm = b"".join(player.compose(n) for _ in range(8))
    tone = player.pcm(880)
    at = round((1.5 * B.CHUNK_S + 0.001) * B.SAMPLE_RATE)
    assert pcm[2 * at:2 * at + len(tone)] == tone                     # whole tone, unbroken over chunk edges
    assert first_sound(pcm) == at + first_sound(tone)
    assert len(pcm) == 2 * 8 * n and pcm[2 * at + len(tone):] == bytes(len(pcm) - 2 * at - len(tone))


def test_a_late_tone_starts_at_once_and_a_close_one_follows_the_first():
    player = stream_at(10.0)
    n = int(B.CHUNK_S * B.SAMPLE_RATE)
    tone = player.pcm(660)
    player.schedule(660, 9.0)                                          # already late
    player.schedule(660, 10.001)                                       # due while the first still plays
    pcm = b"".join(player.compose(n) for _ in range(10))
    assert pcm[:2 * len(tone)] == tone + tone


def test_tone_has_soft_edges():
    tone = B.tone_pcm(880)
    head = [int.from_bytes(tone[i:i + 2], "little", signed=True) for i in range(0, 40, 2)]
    tail = [int.from_bytes(tone[i:i + 2], "little", signed=True) for i in range(len(tone) - 40, len(tone), 2)]
    limit = 0.1 * 32767 * B.VOLUME
    assert max(map(abs, head)) < limit and max(map(abs, tail)) < limit


def test_stream_writes_the_tone_to_the_player_process_in_real_time(tmp_path):
    out = tmp_path / "pcm.raw"
    player = B.StreamPlayer(command=["sh", "-c", f"cat > '{out}'"])
    t0 = time.monotonic()
    assert player.beep(880, at=t0 + 0.25)
    base = player._base
    time.sleep(0.6)
    player.stop()
    pcm = out.read_bytes()
    tone = player.pcm(880)
    at = round((t0 + 0.25 - base) * B.SAMPLE_RATE)                     # base never moved: cat does not block
    assert pcm[2 * at:2 * at + len(tone)] == tone
    assert len(pcm) / 2 / B.SAMPLE_RATE <= 0.6 + B.QUEUE_S + 3 * B.CHUNK_S   # paced, not flooded


class NewOnlyReceiver(FakeReceiver):
    """Has the cheap get_samples_after; get_samples_since (whole-buffer copy) must not be used by the poller."""

    def get_samples_since(self, channel, since):
        raise AssertionError("the pulse tone must poll get_samples_after")

    def get_samples_after(self, channel, after):
        return [s for s in FakeReceiver.get_samples_since(self, channel, -1.0) if s.timestamp > after]


def test_poller_reads_only_new_samples_when_the_receiver_offers_it():
    values, _ = pulse_wave(90, 20)
    receiver, player = NewOnlyReceiver(values), FakePlayer()
    beeper = B.HeartBeeper(receiver=receiver, engine=FakeEngine(), player=player)
    t = 0.0
    while t < 20:
        receiver.now = t
        beeper.poll(t)
        t += B.POLL_S
    assert 20 <= len(player.tones) <= 30


def test_tones_follow_the_received_beats_of_a_ppg_output():
    tones = run(FakeEngine())
    assert 20 <= len(tones) <= 30                                # 90 bpm for 20 s, minus the lock-in beats
    assert set(tones) == {B.TONE_HZ}


@pytest.mark.parametrize("engine,enabled", ((FakeEngine(running=False), True),
                                            (FakeEngine(calibrating=True), True),
                                            (FakeEngine(), False)))
def test_silent_when_stopped_calibrating_or_muted(engine, enabled):
    assert run(engine, enabled=enabled) == []
