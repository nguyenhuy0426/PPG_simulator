"""Display rate estimate of preview strips and GXU preparation helpers; no hardware, no downloads."""
import zipfile

import pytest

np = pytest.importorskip("numpy")

from core.neural_preview import estimate_rate_bpm


def pulse_train(bpm, fs=40, seconds=30, notch=.35):
    t = np.arange(int(fs*seconds))/fs
    phase = 2*np.pi*bpm/60*t
    wave = np.sin(phase)+notch*np.sin(2*phase+.8)
    return (wave-wave.min())/np.ptp(wave)


@pytest.mark.parametrize("bpm", [45, 60, 75, 110, 150, 180])
def test_rate_estimate_tracks_periodic_strips_and_ignores_reflected_wave(bpm):
    assert estimate_rate_bpm(pulse_train(bpm), 40) == pytest.approx(bpm, abs=1.5)
    assert estimate_rate_bpm(pulse_train(bpm, notch=.9), 40) == pytest.approx(bpm, abs=1.5)


def test_rate_estimate_falls_back_to_beats_for_irregular_rhythm():
    rng = np.random.default_rng(3)
    ibi = 60/90*np.exp(.35*rng.normal(size=60)-.35**2/2)
    t, onsets = np.arange(1200)/40, np.cumsum(ibi)
    k = np.clip(np.searchsorted(onsets, t, side="right")-1, 0, len(ibi)-1)
    phase = 2*np.pi*(t-onsets[k])/ibi[k]
    wave = np.sin(phase-np.pi/2)+.3*np.sin(2*phase)
    strip = (wave-wave.min())/np.ptp(wave)
    span = onsets[k[-1]]-onsets[k[0]]
    expected = 60*(k[-1]-k[0])/span
    assert estimate_rate_bpm(strip, 40) == pytest.approx(expected, rel=.12)


def test_rate_estimate_rejects_flat_and_aperiodic_input():
    assert estimate_rate_bpm(np.zeros(1200), 40) is None
    assert estimate_rate_bpm(np.random.default_rng(1).normal(size=1200), 40) is None


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


@pytest.mark.parametrize("seed,bpm", [(69, 110), (103, 95), (148, 110), (159, 95), (259, 110)])
def test_irregular_strip_locked_on_two_beat_lag_reports_the_beat_rate(seed, bpm):
    """AF-like strips where the autocorrelation peaks at two beats (about half the rate, shown as e.g.
    46-53 bpm for 95 bpm AF in the app); the peak intervals do not alternate, so the beat rate is shown."""
    from core.neural_preview import _acf_rate_bpm
    rng = np.random.default_rng(seed)
    ibi = 60/bpm*np.exp(.25*rng.normal(size=60)-.25**2/2)
    t, onsets = np.arange(1200)/40, np.cumsum(ibi)
    k = np.clip(np.searchsorted(onsets, t, side="right")-1, 0, len(ibi)-1)
    phase = 2*np.pi*(t-onsets[k])/ibi[k]
    wave = np.sin(phase-np.pi/2)+.3*np.sin(2*phase)
    strip = (wave-wave.min())/np.ptp(wave)
    expected = 60*(k[-1]-k[0])/(onsets[k[-1]]-onsets[k[0]])
    assert _acf_rate_bpm(strip, 40) == pytest.approx(expected/2, rel=.12)
    assert estimate_rate_bpm(strip, 40) == pytest.approx(expected, rel=.05)
