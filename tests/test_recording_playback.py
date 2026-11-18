"""Recordings page: a saved CSV plays to the LEDs (in place of Classic) and can be deleted."""
import os
import time
from unittest.mock import Mock

import pytest

os.environ.setdefault("PPG_DRY_RUN", "1")

from config import DAC_FULLSCALE_V, DAC_MAX_VALUE
from core.signal_engine import SignalEngine
from core.waveform_clip import MAX_SAMPLES, WaveformClip
from ui.frames.playback_frame import COPY, PlaybackFrame
from ui.recordings import load_recording

HEADER = "IR_Raw,RED_Raw,HR_BPM,SpO2_%,RR_BPM,PI_%,Condition,Time_s,Source\n"


def write_csv(path, codes, step=0.01, start=3.23, skip=()):
    rows = [f"{ir},{red},75.0,98.0,16.0,4.0,Normal,{start + i * step:.6f},TX model / DAC command\n"
            for i, (ir, red) in enumerate(codes) if i not in skip]
    path.write_text(HEADER + "".join(rows))
    return path


def volts(code):
    return code / DAC_MAX_VALUE * DAC_FULLSCALE_V


def test_recording_becomes_a_uniform_100hz_clip_from_any_point(tmp_path):
    codes = [(700 + i, 600 + 2 * i) for i in range(50)]
    samples, _, _ = load_recording(write_csv(tmp_path / "a.csv", codes, skip={10}))   # one dropped row
    clip = WaveformClip.from_recording(samples, "a.csv")
    assert clip.sample_rate == 100 and len(clip.samples) == 50
    assert [r[0] for r in clip.samples[:3]] == [0.0, 0.01, 0.02]
    assert clip.samples[10][1] == pytest.approx(volts(710))             # bridged between rows 9 and 11
    assert clip.samples[49][2] == pytest.approx(volts(698))
    late = WaveformClip.from_recording(samples, "a.csv", start_s=0.2)
    assert late.samples[0][1] == pytest.approx(volts(720)) and len(late.samples) == 30
    with pytest.raises(ValueError):
        WaveformClip.from_recording(samples, "a.csv", start_s=0.49)
    assert MAX_SAMPLES >= 100 * 60 * 30


def test_engine_sends_the_recorded_dac_codes(tmp_path):
    codes = [(800, 650)] * 20 + [(900, 700)] * 20
    samples, _, _ = load_recording(write_csv(tmp_path / "b.csv", codes))
    engine = SignalEngine()
    engine.dac_manager = Mock(is_ready=True)
    try:
        engine.start_simulation()                        # Classic running
        engine.start_waveform(WaveformClip.from_recording(samples, "b.csv"))
        deadline = time.monotonic() + 2.0
        while engine.is_running and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not engine.is_running and engine.waveform_position_s == pytest.approx(0.40)
        sent = [c.args for c in engine.dac_manager.set_values.call_args_list]
        sent = sent[next(i for i, v in enumerate(sent) if v == (800, 650)):]
        assert (900, 700) in sent and sent[-1] == (0, 0)  # recorded levels, then parked at 0 V
    finally:
        engine.stop_simulation()


class FakeEngine:
    def __init__(self, dac=True):
        self.dac, self.running, self.paused, self.current_clip, self.started = dac, True, False, None, []
        self.waveform_position_s = 0.0

    @property
    def is_running(self):
        return self.running

    def start_waveform(self, clip):
        if not self.dac:
            raise RuntimeError("MCP4725 output is unavailable")
        self.current_clip, self.running, self.paused, self.waveform_position_s = clip, True, False, 0.0
        self.started.append(clip)

    def start_classic(self):
        self.current_clip, self.running = None, True

    def pause_simulation(self):
        self.paused = True
        return True

    def resume_simulation(self):
        was, self.paused = self.paused, False
        return was

    def stop_simulation(self):
        self.running = False

    def set_playback_state(self, *args):
        self.pb = args


def page(tmp_path, engine):
    frame = PlaybackFrame.__new__(PlaybackFrame)
    frame.engine, frame.language, frame.dataset_dir = engine, "en", tmp_path
    for name in ("status", "play_btn", "delete_btn", "title_label", "info", "trace", "rx_panel"):
        setattr(frame, name, Mock())
    frame.metric_values, frame._delete_armed, frame._names_cache = {}, None, None
    frame.samples, frame.parameters, frame.times = [], [], []
    frame.is_playing, frame.position, frame._origin = False, 0.0, 0.0
    frame._clip, frame._clip_offset, frame.current_name, frame._timing = None, 0.0, "", ""
    frame._paint_play = frame._render = frame._highlight = frame.on_show = lambda *a: None
    frame.after, frame.after_cancel = Mock(return_value="id"), Mock()
    return frame


def loaded(tmp_path, engine, n=300):
    frame = page(tmp_path, engine)
    frame.load_data(write_csv(tmp_path / "data_1.csv", [(700 + i % 50, 600) for i in range(n)]))
    return frame


def last_status(frame):
    return frame.status.configure.call_args.kwargs["text"]


def test_play_takes_the_output_from_classic_and_follows_the_dacs(tmp_path):
    engine = FakeEngine()
    frame = loaded(tmp_path, engine)
    frame.play()
    assert engine.started and engine.current_clip.name == "data_1.csv"
    assert last_status(frame) == COPY["en"]["leds"].format(name="data_1.csv")
    engine.waveform_position_s = 1.25
    frame.periodic_update()
    assert frame.position == pytest.approx(1.25)
    frame.pause_playback()
    assert engine.paused and not frame.is_playing
    frame.play()                                         # resume the same clip, not a restart
    assert not engine.paused and len(engine.started) == 1
    engine.start_classic()                               # Classic Start while the recording plays
    frame.periodic_update()
    assert not frame.is_playing and last_status(frame) == COPY["en"]["taken"]
    frame.stop_playback()
    assert engine.running                                # Classic's output is not stopped by this page


def test_end_of_the_clip_ends_playback(tmp_path):
    engine = FakeEngine()
    frame = loaded(tmp_path, engine)
    frame.play()
    engine.waveform_position_s, engine.running = frame.times[-1], False
    frame.periodic_update()
    assert not frame.is_playing and frame.position == pytest.approx(frame.times[-1])
    assert last_status(frame) == COPY["en"]["finished"].format(name="data_1.csv")


def test_without_dacs_it_still_plays_on_screen_and_says_why(tmp_path):
    engine = FakeEngine(dac=False)
    frame = loaded(tmp_path, engine)
    frame.play()
    assert frame.is_playing and frame._clip is None
    assert "MCP4725" in last_status(frame)


def test_delete_needs_a_second_tap_and_removes_only_that_file(tmp_path):
    engine = FakeEngine()
    frame = loaded(tmp_path, engine)
    other = write_csv(tmp_path / "data_2.csv", [(700, 600)] * 5)
    frame.play()
    frame.delete_selected()
    assert (tmp_path / "data_1.csv").exists()            # first tap only asks
    frame.delete_selected()
    assert not (tmp_path / "data_1.csv").exists() and other.exists()
    assert not engine.running                            # its playback was on the LEDs: stopped
    assert frame.current_name == "" and frame.samples == [] and not frame.is_playing
    assert last_status(frame) == COPY["en"]["deleted"].format(name="data_1.csv")


def test_delete_refuses_paths_outside_and_the_live_temp_file(tmp_path):
    frame = page(tmp_path, FakeEngine())
    outside = tmp_path.parent / "keep.csv"
    outside.write_text(HEADER)
    temp = write_csv(tmp_path / "temp_recording.csv", [(700, 600)] * 3)
    assert not frame.delete_recording("../keep.csv") and outside.exists()
    assert not frame.delete_recording("temp_recording.csv") and temp.exists()
    assert not frame.delete_recording("missing.csv")
    outside.unlink()


def test_a_few_rows_written_out_of_order_are_put_back_in_time_order(tmp_path):
    """data_1.csv on the Pi: 3 of 46 511 rows written up to 0.08 s early (interleaved record batches)."""
    path = write_csv(tmp_path / "c.csv", [(700 + i, 600) for i in range(300)])
    lines = path.read_text().splitlines(keepends=True)
    lines.insert(101, lines.pop(109))                    # the row of 1.08 s now sits after the one of 0.99 s
    path.write_text("".join(lines))
    samples, _, timing = load_recording(path)
    assert [round(s[0], 2) for s in samples] == [round(i * 0.01, 2) for i in range(300)]
    assert samples[108][1] == pytest.approx(volts(808)) and "out of order at 1 places" in timing
    WaveformClip.from_recording(samples, "c.csv")


def test_many_or_large_backward_steps_are_still_refused(tmp_path):
    path = write_csv(tmp_path / "d.csv", [(700, 600)] * 200)
    lines = path.read_text().splitlines(keepends=True)
    lines.insert(150, lines.pop(10))                     # 1.4 s back
    path.write_text("".join(lines))
    with pytest.raises(ValueError, match="strictly increasing"):
        load_recording(path)


def test_two_threads_pumping_the_recording_keep_the_rows_in_order():
    import threading
    engine = SignalEngine()
    written, started, release = [], threading.Event(), threading.Event()

    class SlowLogger:
        is_logging = True

        def log_data(self, *row):
            written.append(row[-1])
            if len(written) == 1:
                started.set()
                release.wait(1.0)                        # the pump thread is still writing its batch

    engine._csv_logger = SlowLogger()
    engine._record_samples.extend((0, 0, 75, 98, 16, 4, "Normal", t / 100) for t in range(3))
    first = threading.Thread(target=engine.pump_recording)
    first.start()
    assert started.wait(1.0)
    engine._record_samples.extend((0, 0, 75, 98, 16, 4, "Normal", t / 100) for t in range(3, 6))
    second = threading.Thread(target=engine.pump_recording)  # the Classic page pumps meanwhile
    second.start()
    second.join(0.2)
    release.set()
    first.join(1.0)
    second.join(1.0)
    assert written == sorted(written) and len(written) == 6


def test_pi_is_not_shown_but_the_phone_still_finds_condition_at_index_4(tmp_path):
    from ui.frames.playback_frame import METRICS
    assert [k for k, _ in METRICS] == ["hr", "spo2", "rr", "condition"]
    assert all("pi" not in COPY[lang] for lang in COPY)
    frame = loaded(tmp_path, FakeEngine())
    frame.metric_values = {k: (Mock(cget=Mock(return_value=f"<{k}>")), u) for k, u in METRICS}
    rec = dict(frame.remote_parts())["rec"]
    assert rec["m"] == ["<hr>", "<spo2>", "<rr>", "", "<condition>"]
