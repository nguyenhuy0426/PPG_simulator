"""Model page CSV: a window saved as a recording, and the text the phone rebuilds from UI parts."""
import json
import os
from types import SimpleNamespace

os.environ.setdefault("PPG_DRY_RUN", "1")

from comm.ble_remote import UI_PART_MAX_BYTES, fit_part
from core import model_export as me
from core.waveform_clip import WaveformClip
from ui.recordings import load_recording


def clip(n=1200, rate=40.0):
    return WaveformClip(tuple((i / rate, 0.6 + 0.04 * ((i % 32) / 32), 0.6 + 0.02 * ((i % 32) / 32))
                              for i in range(n)), rate, "APFT-GAN")


PREVIEW = SimpleNamespace(seed=1234, hr_target=75.0, provenance={"hr_measured_bpm": 78.2})


def test_a_window_saved_to_recordings_loads_and_plays_like_a_recording(tmp_path):
    path = me.save_recording(tmp_path, me.file_stem("APFT-GAN", PREVIEW), me.recording_csv(clip(), PREVIEW, "APFT-GAN"))
    assert path.name == "APFT-GAN_1234.csv"
    samples, params, timing = load_recording(path)
    assert len(samples) == 1200 and samples[-1][0] == 1199 / 40
    assert params[0] == (78.2, None, None, None, "APFT-GAN")        # measured HR; no SpO2/RR/PI for a window
    assert abs(samples[0][1] - 0.6) < 0.001                          # DAC codes back to volts
    WaveformClip.from_recording(samples, path.name)
    again = me.save_recording(tmp_path, "APFT-GAN_1234", "x")
    assert again.name == "APFT-GAN_1234_2.csv" and not list(tmp_path.glob("*.part"))


def test_csv_for_the_phone_fits_ble_parts_and_rebuilds_exactly():
    text = me.waveform_csv(clip())
    parts = me.transfer_parts(text, 77, "APFT-GAN_1234.csv")
    assert text.startswith("time_s,ir_v,red_v\n") and len(parts) > 10
    rebuilt = []
    for name, fields in parts:
        data = fit_part(name, fields)
        assert len(data) <= UI_PART_MAX_BYTES
        obj = json.loads(data)
        assert obj["k"] == "nnx" and obj["id"] == 77 and obj["m"] == len(parts)
        rebuilt.append(obj["d"])                                     # never shortened by fit_part
    assert "".join(rebuilt) == text and parts[0][1]["n"] == "APFT-GAN_1234.csv"


def test_names_are_safe_file_names():
    assert me.file_stem("Gaussian (fitted)", SimpleNamespace(seed=None), "With notch") == "Gaussian-fitted-_With-notch"
    assert "/" not in me.file_stem("../x", SimpleNamespace(seed="../../etc"))
