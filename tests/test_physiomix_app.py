"""PhysioMix bundle, worker and GXU preparation helpers; no hardware, no downloads."""
import io
import json
import math
import subprocess
import sys
import zipfile

import pytest

np = pytest.importorskip("numpy")

from core.neural_preview import DEFAULT_BUNDLE, estimate_rate_bpm, physiomix_metadata


def pulse_train(bpm, fs=40, seconds=30, notch=.35):
    t = np.arange(int(fs*seconds))/fs
    phase = 2*np.pi*bpm/60*t
    wave = np.sin(phase)+notch*np.sin(2*phase+.8)
    return (wave-wave.min())/np.ptp(wave)


@pytest.mark.parametrize("bpm", [45, 60, 75, 110, 150, 180])
def test_rate_estimate_tracks_periodic_strips_and_ignores_reflected_wave(bpm):
    assert estimate_rate_bpm(pulse_train(bpm), 40) == pytest.approx(bpm, abs=1.5)
    assert estimate_rate_bpm(pulse_train(bpm, notch=.9), 40) == pytest.approx(bpm, abs=1.5)


def test_rate_estimate_rejects_flat_and_aperiodic_input():
    assert estimate_rate_bpm(np.zeros(1200), 40) is None
    assert estimate_rate_bpm(np.random.default_rng(1).normal(size=1200), 40) is None


def test_metadata_does_not_import_torch():
    subprocess.run([sys.executable, "-c", "import sys, core.neural_preview as n; n.physiomix_metadata(); "
                    "assert 'torch' not in sys.modules"], check=True)


@pytest.fixture(scope="module")
def generator():
    pytest.importorskip("torch")
    if physiomix_metadata() is None:
        pytest.skip("Run scripts/prepare_physiomix_bundle.py to install the PhysioMix artifact")
    from core.neural_preview import PhysioMixGenerator
    return PhysioMixGenerator()


def test_generator_is_repeatable_bounded_and_rate_controlled(generator):
    lo, hi = generator.meta["hr_support_bpm"]
    first, again = generator.generate(9, 80, "bidmc"), generator.generate(9, 80, "bidmc")
    assert first.samples == again.samples and first.native_fs == 40 and len(first.samples) == 1200
    assert all(math.isfinite(v) for row in first.samples for v in row)
    assert first.provenance["measured_rate_bpm"] == pytest.approx(80, abs=4)
    with pytest.raises(ValueError):
        generator.generate(9, lo-1, "bidmc")
    with pytest.raises(ValueError):
        generator.generate(9, hi+1, "bidmc")
    with pytest.raises(ValueError):
        generator.generate(9, 80, "not_a_domain")
    with pytest.raises(ValueError):
        generator.generate(True, 80, "bidmc")


def test_worker_emits_one_physiomix_json(generator):
    out = subprocess.run([sys.executable, "-m", "core.sequence_worker", "11", "--model", "physiomix",
                          "--hr", "90", "--domain", generator.meta["domains"][0]],
                         check=True, capture_output=True, text=True).stdout
    preview = json.loads(out)
    assert preview["name"] == "PhysioMix" and preview["hr_target"] == 90
    assert len(preview["samples"]) == 1200 and preview["provenance"]["paired_ir_red"] is False


def test_reference_strips_are_train_only(generator):
    from core.neural_preview import physiomix_reference_preview
    for domain in generator.meta["domains"]:
        preview = physiomix_reference_preview(domain)
        assert preview.provenance["split"] == "train" and len(preview.samples) == 1200


gxu = pytest.importorskip("ml.kaggle_multidomain.data_gxu")


def synthetic_gxu_csv(seconds=40, fs=250, invert=True, lag=.25):
    t = np.arange(int(seconds*fs))/fs
    beats = np.arange(.5, seconds, .8)
    ecg = sum(np.exp(-((t-b)/.01)**2) for b in beats)*5000+300000
    pulse = sum(np.exp(-((t-b-lag)/.08)**2) for b in beats)
    ir = 400000+(-1 if invert else 1)*3000*pulse
    rows = "\n".join(f"{int(e)},{int(r)},{int(i)}," for e, r, i in zip(ecg, ir-20000, ir))
    return ("ECG_I,PPG_RED,PPG_IR,{'Hz': 250}\n"+rows+"\n").encode()


def test_gxu_csv_parse_polarity_and_reference_rate():
    ecg, red, ir = gxu.read_record(synthetic_gxu_csv())
    assert len(ecg) == len(red) == len(ir) == 10000
    peaks = gxu.r_peaks(ecg)
    assert len(peaks) >= 45
    assert gxu.polarity_lag(ir, peaks) == pytest.approx(.25, abs=.03)
    # An upright (non-inverted) raw signal fails the 0.1-0.6 s negated-peak rule.
    _, _, upright = gxu.read_record(synthetic_gxu_csv(invert=False))
    lag = gxu.polarity_lag(upright, peaks)
    assert lag is None or not .1 <= lag <= .6
    assert gxu.reference_rate(peaks, 250, 0) == pytest.approx(75, abs=1)


def test_gxu_rejects_wrong_header_and_rate():
    with pytest.raises(ValueError):
        gxu.read_record(b"A,B,C\n1,2,3\n")
    with pytest.raises(ValueError):
        gxu.read_record(synthetic_gxu_csv().replace(b"'Hz': 250", b"'Hz': 500"))


def test_edge_excess_flags_record_start_transient_only():
    clean = pulse_train(75)[None]
    spiked = clean.copy()
    spiked[0, :20] = np.linspace(-6, 0, 20)
    assert gxu.edge_excess(clean)[0] < gxu.EDGE_EXCESS_MAX < gxu.edge_excess(spiked)[0]


def test_gxu_archive_listing_requires_all_records(tmp_path):
    archive = tmp_path/"gxu.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("x/Raw_data/001_1.csv", synthetic_gxu_csv())
    with pytest.raises(ValueError, match="444"):
        list(gxu.gxu_records(archive))
