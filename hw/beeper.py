"""Pulse tone: a short beep on every received pulse peak, pitch falling with the received SpO2.

Like a bedside monitor's pulse-oximetry tone, the pitch drops as SpO2 drops (PITCH_AT_100_HZ at 100 %, one
semitone per SEMITONES_PER_PCT, clamped below MIN_SPO2_PITCH); without an SpO2 estimate it is NEUTRAL_HZ.
The tone only sounds while the generator plays a PPG output (Classic or playback, not the Calibration test
signal) and the received pulse is regular (core.beat_detector lock), so noise or a dark lane stays silent.

Audio goes through the desktop's sound server (pw-play, else paplay, else aplay) to its default output; on the
Pi 4 that is HDMI or the 3.5 mm jack, chosen in the desktop sound settings. A missing player only disables the
tone. One player process per beep (~70 ms tone, pw-play at 10 ms latency so the tone is not split); a beep
is skipped while the previous one still plays.
"""
import math
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import wave

from comm.logger import log
from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED
from core.beat_detector import BeatDetector
from hw.opt101_rx import raw_to_millivolts

MV_PER_CODE = raw_to_millivolts(1)

POLL_S = 0.02
TONE_S = 0.07
FADE_S = 0.006
SAMPLE_RATE = 48000
VOLUME = 0.45
PITCH_AT_100_HZ = 880.0
SEMITONES_PER_PCT = 0.5
MIN_SPO2_PITCH = 70.0
NEUTRAL_HZ = 660.0
PLAYERS = ("pw-play", "paplay", "aplay")
# pw-play's default 100 ms node latency splits a 70 ms tone into 45 + 30 ms with a 40 ms hole on the Pi 4
# (recorded from the HDMI sink monitor); 10 ms plays it whole even with the GUI running, 20 ms adds a 10 ms blip.
PLAYER_ARGS = {"pw-play": ("--latency", "10ms")}


def pitch_hz(spo2):
    if spo2 is None or not math.isfinite(spo2):
        return NEUTRAL_HZ
    spo2 = max(MIN_SPO2_PITCH, min(100.0, spo2))
    return PITCH_AT_100_HZ * 2 ** ((spo2 - 100.0) * SEMITONES_PER_PCT / 12.0)


def tone_wav(path, hz):
    """Mono 16-bit sine with short fades (no click)."""
    n, fade = int(TONE_S * SAMPLE_RATE), int(FADE_S * SAMPLE_RATE)
    frames = bytearray()
    for i in range(n):
        envelope = min(1.0, i / fade, (n - 1 - i) / fade)
        frames += struct.pack("<h", int(32767 * VOLUME * envelope * math.sin(2 * math.pi * hz * i / SAMPLE_RATE)))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(frames))


class TonePlayer:
    def __init__(self, command=None, cache_dir=None):
        self.command = command or next((shutil.which(p) for p in PLAYERS if shutil.which(p)), None)
        self._dir = cache_dir or tempfile.mkdtemp(prefix="ppg-beep-")
        self._proc = None
        self.played = 0

    @property
    def available(self):
        return self.command is not None

    def _file(self, hz):
        path = os.path.join(self._dir, f"beep-{round(hz)}.wav")
        if not os.path.exists(path):
            tone_wav(path, round(hz))
        return path

    def beep(self, hz):
        if not self.available:
            return False
        if self._proc is not None and self._proc.poll() is None:
            return False                      # previous tone still playing: never stack processes
        try:
            args = PLAYER_ARGS.get(os.path.basename(self.command), ())
            self._proc = subprocess.Popen([self.command, *args, self._file(hz)], stdin=subprocess.DEVNULL,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            log.error(f"[Beeper] {self.command} failed: {exc}")
            self.command = None
            return False
        self.played += 1
        return True


class HeartBeeper:
    """Background thread: new RX samples -> BeatDetector per lane -> one tone per beat of the locked lane."""

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, receiver=None, engine=None, player=None):
        self._receiver, self._engine, self._player = receiver, engine, player
        self.enabled = True
        self._spo2 = None
        self._detectors = {ADC_CHANNEL_IR: BeatDetector(), ADC_CHANNEL_RED: BeatDetector()}
        self._since = {}
        self._thread = None
        self._running = False
        self.last_beat = None                 # (monotonic time of the tone, lane, beat timestamp)

    # ---- wiring ----
    @property
    def player(self):
        if self._player is None:
            self._player = TonePlayer()
            if not self._player.available:
                log.warning("[Beeper] no pw-play/paplay/aplay: pulse tone disabled")
        return self._player

    def _sources(self):
        if self._receiver is None:
            from hw.opt101_rx import OPT101Receiver
            self._receiver = OPT101Receiver.get_instance()
        if self._engine is None:
            from core.signal_engine import SignalEngine
            self._engine = SignalEngine.get_instance()
        return self._receiver, self._engine

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)

    def set_spo2(self, spo2):
        self._spo2 = spo2

    # ---- thread ----
    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="PulseTone")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _loop(self):
        while self._running:
            try:
                self.poll(time.monotonic())
            except Exception:
                log.exception("[Beeper] poll failed")
            time.sleep(POLL_S)

    def _active(self, engine):
        return self.enabled and engine.is_running and not engine.is_calibrating

    def poll(self, now):
        """Feed the samples that arrived since the last poll; beep for a beat of the locked lane."""
        receiver, engine = self._sources()
        if not self._active(engine):
            for detector in self._detectors.values():
                detector.reset()
            self._since = {ch: now for ch in self._detectors}     # never replay old samples later
            return None
        beats = {}
        ir_locked = self._detectors[ADC_CHANNEL_IR].locked
        for channel, detector in self._detectors.items():
            since = self._since.setdefault(channel, now)     # first poll: start from now, never replay old samples
            if channel == ADC_CHANNEL_RED and ir_locked:
                # The tone follows IR while it is locked; the RED detector is only a fallback. Skipping it
                # halves this thread's share of the GIL-bound core on the Pi 4 (~0.23 ms a sample).
                detector.reset()
                self._since[channel] = now
                continue
            # Only the new samples: get_samples_since copies the whole 64 s buffer under the receiver lock, which
            # 100 times a second (2 lanes x 50 Hz) starved the acquisition thread on the Pi 4 (RX holes, DAC
            # "Lost" 661 in 2 min vs 26 with the tone off).
            newer = getattr(receiver, "get_samples_after", None)
            samples = newer(channel, since) if newer else receiver.get_samples_since(channel, since + 1e-6)
            for s in samples:
                beat = detector.feed(s.timestamp, s.raw * MV_PER_CODE)
                if beat is not None:
                    beats[channel] = beat
            if samples:
                self._since[channel] = samples[-1].timestamp
        lane = ADC_CHANNEL_IR if self._detectors[ADC_CHANNEL_IR].locked else ADC_CHANNEL_RED
        if lane in beats and self.player.beep(pitch_hz(self._spo2)):
            self.last_beat = (now, lane, beats[lane])
            return beats[lane]
        return None
