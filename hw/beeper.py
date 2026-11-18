"""Pulse tone: a short beep on every received pulse peak, always at TONE_HZ.

The pitch used to follow the received SpO2 (880 Hz at 100 %, half a semitone lower per %, 660 Hz with no
estimate), so the tone changed while the estimate settled or moved; it is now one fixed pitch.
The tone only sounds while the generator plays a PPG output (Classic or playback, not the Calibration test
signal) and the received pulse is regular (core.beat_detector lock), so noise or a dark lane stays silent.

Audio goes to the desktop sound server's default output (on the Pi 4, HDMI or the 3.5 mm jack, chosen in the
desktop sound settings). StreamPlayer keeps one `aplay` stream open while the tone is active and writes silence
or tone into it, so a beep starts on an exact sample: each tone is placed at its beat's peak time plus a fixed
delay (longer than the detector needs to confirm a peak), so the beeps keep the spacing of the received beats.
One player process per beep (TonePlayer, the earlier way and the fallback) started each tone whenever the 20 ms
poll and the process start allowed: on the Pi the spacing moved in ~21 ms steps and 6 of 23 tones had a 4-5 ms
hole (recorded from the sink monitor, 18/11). A missing player only disables the tone.
"""
from collections import deque
import fcntl
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
TONE_HZ = 880.0
PLAYERS = ("pw-play", "paplay", "aplay")
# pw-play's default 100 ms node latency splits a 70 ms tone into 45 + 30 ms with a 40 ms hole on the Pi 4
# (recorded from the HDMI sink monitor); 10 ms plays it whole even with the GUI running, 20 ms adds a 10 ms blip.
PLAYER_ARGS = {"pw-play": ("--latency", "10ms")}

# StreamPlayer: raw S16 mono into aplay (through the sound server's ALSA plugin, so the default output).
STREAM_ARGS = ("-q", "-t", "raw", "-f", "S16_LE", "-c", "1", "-r", str(SAMPLE_RATE),
               "--buffer-time=100000", "--period-time=20000", "-")
CHUNK_S = 0.02            # audio written per wake-up
QUEUE_S = 0.12            # audio kept written ahead of now: a GUI stall shorter than this does not cut a tone
PIPE_BYTES = 16384        # pipe to aplay (170 ms) + aplay's 100 ms buffer > QUEUE_S, so writes rarely block
BLOCKED_S = 0.005         # a write that waited this long found the buffers full: re-anchor the audio clock
# Tone onset = beat peak + delay. The delay covers the slowest recent confirmation (the detector names a peak
# only after the pulse falls, 90-210 ms at 60-300 bpm), the poll, one chunk and the write-ahead.
LAG_BEATS = 8
DELAY_MARGIN_S = POLL_S + CHUNK_S + QUEUE_S + 0.01
MAX_DELAY_S = 1.2


def tone_pcm(hz):
    """Raw S16LE mono samples of one tone: sine with raised-cosine fades (no click)."""
    n, fade = int(TONE_S * SAMPLE_RATE), int(FADE_S * SAMPLE_RATE)
    out = bytearray()
    for i in range(n):
        edge = min(i, n - 1 - i)
        envelope = 1.0 if edge >= fade else 0.5 - 0.5 * math.cos(math.pi * edge / fade)
        out += struct.pack("<h", int(32767 * VOLUME * envelope * math.sin(2 * math.pi * hz * i / SAMPLE_RATE)))
    return bytes(out)



def tone_wav(path, hz):
    """The tone_pcm samples as a mono 16-bit WAV file."""
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(tone_pcm(hz))


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

    def stop(self):
        pass

    def beep(self, hz, at=None):
        """Plays at once (`at` is ignored: a process start cannot be timed to a few ms)."""
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


class StreamPlayer:
    """One open audio stream; tones are mixed in at the monotonic time they should be heard.

    A writer thread keeps QUEUE_S of audio written ahead of now, so the chunk being written is heard at the
    audio clock `base + written / SAMPLE_RATE`. A tone due inside that chunk starts on its exact sample; one
    already late starts at the chunk's start; one due while another tone plays follows it."""

    def __init__(self, command=None, clock=time.monotonic):
        self.argv = list(command) if command else ([shutil.which("aplay"), *STREAM_ARGS] if shutil.which("aplay")
                                                    else None)
        self._clock = clock
        self._lock = threading.Lock()
        self._pending = deque()               # (onset, pcm), onset in the clock's time
        self._tones = {}
        self._proc = self._thread = None
        self._running = False
        self.failed = False
        self.played = 0
        self._reset_clock()

    @property
    def available(self):
        return self.argv is not None and not self.failed

    def _reset_clock(self):
        self._current, self._cursor = None, 0
        self._written = 0                     # samples
        self._base = None                     # audio-clock time of sample 0

    def pcm(self, hz):
        hz = round(hz)
        if hz not in self._tones:
            self._tones[hz] = tone_pcm(hz)
        return self._tones[hz]

    def beep(self, hz, at=None):
        if not self.available or not self._ensure_running():
            return False
        self.schedule(hz, self._clock() if at is None else at)
        self.played += 1
        return True

    def prepare(self):
        """Open the stream ahead of the first tone; False when it cannot run."""
        return self.available and self._ensure_running()

    def schedule(self, hz, at):
        tone = self.pcm(hz)
        with self._lock:
            self._pending.append((at, tone))

    # ---- the audio clock and the samples of the next chunk (no I/O: tested directly) ----
    def chunk_start(self):
        return self._base + self._written / SAMPLE_RATE

    def compose(self, samples):
        """The next `samples` samples of the stream: silence, with each pending tone placed at its onset."""
        start, need = self.chunk_start(), 2 * samples
        out = bytearray()
        while len(out) < need:
            if self._current is None:
                with self._lock:
                    nxt = self._pending[0] if self._pending else None
                if nxt is None:
                    break
                at = max(len(out), 2 * max(0, round((nxt[0] - start) * SAMPLE_RATE)))
                if at >= need:
                    break
                out += bytes(at - len(out))
                with self._lock:
                    self._pending.popleft()
                self._current, self._cursor = nxt[1], 0
            take = min(need - len(out), len(self._current) - self._cursor)
            out += self._current[self._cursor:self._cursor + take]
            self._cursor += take
            if self._cursor >= len(self._current):
                self._current = None
        out += bytes(need - len(out))
        self._written += samples
        return bytes(out)

    # ---- process and writer thread ----
    def _ensure_running(self):
        if self._running and self._proc is not None and self._proc.poll() is None:
            return True
        self.stop()
        try:
            self._proc = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, bufsize=0)
        except OSError as exc:
            log.error(f"[Beeper] {self.argv[0]} failed: {exc}")
            self.failed = True
            return False
        try:
            fcntl.fcntl(self._proc.stdin.fileno(), fcntl.F_SETPIPE_SZ, PIPE_BYTES)
        except (AttributeError, OSError):
            pass                              # default 64 KiB pipe: more latency, still in time order
        self._reset_clock()
        self._base = self._clock()
        self._running = True
        self._thread = threading.Thread(target=self._write_loop, args=(self._proc,), daemon=True,
                                        name="PulseToneStream")
        self._thread.start()
        return True

    def _write_loop(self, proc):
        samples = int(CHUNK_S * SAMPLE_RATE)
        fd = proc.stdin.fileno()
        try:
            while self._running:
                data, began = self.compose(samples), self._clock()
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
                now = self._clock()
                ahead = self.chunk_start() - now
                if now - began >= BLOCKED_S:
                    self._base += QUEUE_S - ahead        # buffers full: what was just written is QUEUE_S away
                elif ahead < 0:
                    self._base -= ahead                  # fell behind (stall, underrun): play from now
                elif ahead > QUEUE_S:
                    time.sleep(ahead - QUEUE_S)
        except (OSError, ValueError):
            if self._running:
                log.error("[Beeper] audio stream closed; falling back to one player process per beep")
                self.failed = True
        finally:
            self._running = False

    def stop(self):
        """Close the stream (the tone is off); the next beep opens it again."""
        self._running = False
        proc, self._proc = self._proc, None
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.3)
            if thread.is_alive() and proc is not None:
                proc.kill()                   # a write stuck on a hung player: EPIPE ends it
                thread.join(timeout=0.5)
        if proc is not None:                  # closed only after the writer is gone: its fd is never reused under it
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=0.5)
        with self._lock:
            self._pending.clear()


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
        self._was_active = False
        self._detectors = {ADC_CHANNEL_IR: BeatDetector(), ADC_CHANNEL_RED: BeatDetector()}
        self._since = {}
        self._lags = deque(maxlen=LAG_BEATS)  # confirmation delays (poll time - peak time) of recent beats, s
        self._thread = None
        self._running = False
        self.last_beat = None                 # (monotonic time of the tone, lane, beat timestamp)

    # ---- wiring ----
    @property
    def player(self):
        """StreamPlayer (aplay) when it can run, else one player process per beep."""
        if self._player is None:
            self._player = StreamPlayer()
            if not self._player.available:
                self._player = None
        if self._player is None or (isinstance(self._player, StreamPlayer) and self._player.failed):
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
        if self._player is not None:
            self._player.stop()

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
            self._lags.clear()
            if self._player is not None:
                self._player.stop()                               # close the audio stream while silent
            self._was_active = False
            return None
        if not self._was_active:
            # Open the audio stream as the output starts, so the first tone (~2-3 beats later) is not held up
            # by starting the player process.
            self._was_active = True
            prepare = getattr(self.player, "prepare", None)
            if prepare is not None:
                prepare()
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
        if lane not in beats:
            return None
        beat = beats[lane]
        self._lags.append(max(0.0, now - beat))
        if self.player.beep(TONE_HZ, at=self.tone_time(beat)):
            self.last_beat = (now, lane, beat)
            return beat
        return None

    def tone_time(self, beat):
        """When the tone of a beat (peak time) is heard: a fixed delay after the peak, so the tones keep the beats'
        spacing; the delay follows the slowest recent confirmation."""
        return beat + min(MAX_DELAY_S, max(self._lags, default=0.0) + DELAY_MARGIN_S)
