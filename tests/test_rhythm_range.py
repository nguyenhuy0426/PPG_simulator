"""core.rhythm_range: rate-range commands for the conditioned generators (R1c rhythm model, no retraining)."""
import io
import json
from contextlib import redirect_stdout

import numpy as np
import pytest

from core import rhythm_range as rr


def test_range_sigma_spans_the_range_and_rejects_bad_ranges():
    sigma = rr.range_sigma(70, 75)
    assert sigma == pytest.approx(np.log(75/70)/(2*rr.Z95))
    assert rr.range_sigma(72, 72) == rr.SIGMA_RANGE[0]
    for lo, hi in ((75, 70), (0, 70), (float("nan"), 70)):
        with pytest.raises(ValueError):
            rr.range_sigma(lo, hi)


def test_asset_covers_the_training_datasets_and_records_the_rule():
    asset = json.loads(rr.ASSET.read_text())
    assert {"bidmc", "gxu_finger", "perform_af", "perform_large", "perform_non_af", "wrist"} <= set(asset["domains"])
    assert asset["rule"].startswith("Rhythm rule 2")
    assert all(v["ok"] for v in asset["outcome"]["guard"].values())


@pytest.mark.parametrize("domain", ["gxu_finger", "perform_large", "unknown_dataset"])
def test_in_window_mean_rate_equals_the_range_centre(domain):
    for seed in range(5):
        u, sigma, mean, model = rr.interval_noise(domain, 60, 66, np.random.default_rng(seed))
        assert model == ("independent" if domain == "unknown_dataset" else "R1c")
        assert len(u) == rr.BEATS and mean == 63
        ibi = np.exp(sigma*u-.5*sigma**2)/(mean/60)
        if model == "R1c":
            k = int(np.searchsorted(np.cumsum(ibi), rr.DURATION+60/mean))+1
            assert np.mean(u[:k]) == pytest.approx(0, abs=1e-9)
            assert 60/np.exp(np.mean(np.log(ibi[:k]))) == pytest.approx(mean*np.exp(sigma**2/2), rel=1e-6)


def test_interval_noise_is_deterministic_and_correlated_where_real_rhythm_is():
    a = rr.interval_noise("gxu_finger", 70, 75, np.random.default_rng(1))[0]
    b = rr.interval_noise("gxu_finger", 70, 75, np.random.default_rng(1))[0]
    assert np.array_equal(a, b)
    lag1 = np.mean([np.corrcoef(u[:-1], u[1:])[0, 1] for u in
                    (rr.interval_noise("gxu_finger", 70, 75, np.random.default_rng(s))[0] for s in range(40))])
    assert lag1 > .2          # FINGER intervals are positively correlated (fitted AR lag-1 about 0.38)


def test_encode_writes_only_the_positions_each_generator_reads():
    z, u = np.zeros(1200, np.float32), np.arange(1, 161, dtype=np.float32)
    front, back = rr.encode(z, u, "physiomix"), rr.encode(z, u, "physioflow")
    assert np.array_equal(front[32:192], u) and not front[:32].any() and not front[192:].any()
    assert np.array_equal(back[-160:], u[::-1]) and not back[:-160].any()
    with pytest.raises(ValueError):
        rr.encode(z, u, "lsm")


def test_matches_the_ml_rhythm_model():
    from ml.kaggle_multidomain.rhythm import ar_simulate
    spec = json.loads(rr.ASSET.read_text())["domains"]["gxu_finger"]
    a = rr._ar(spec["coef"], spec["innovation_sd"], 160, np.random.default_rng(3))
    b = ar_simulate(np.asarray(spec["coef"]), spec["innovation_sd"], 160, np.random.default_rng(3))
    assert np.allclose(a, b)


@pytest.mark.parametrize("slot", ["physiomix", "physioflow"])
def test_generator_follows_a_range_command(slot):
    pytest.importorskip("torch")
    from core.neural_preview import PhysioMixGenerator
    from ml.kaggle_multidomain.flow import window_peaks
    g = PhysioMixGenerator(slot=slot)
    preview = g.generate(11, domain="gxu_finger", hr_range=(70, 75))
    values = np.array([s[1] for s in preview.samples])
    peaks = window_peaks((values-values.min())/np.ptp(values))
    assert 60*40/np.mean(np.diff(peaks)) == pytest.approx(72.5, abs=2.)
    assert preview.provenance["hr_range_bpm"] == [70., 75.] and preview.provenance["rhythm_model"] == "R1c"
    assert preview.provenance["requested_rate_bpm"] == 72.5
    with pytest.raises(ValueError):
        g.generate(11, domain="gxu_finger", hr_range=(30, 75))


def test_worker_accepts_a_range():
    pytest.importorskip("torch")
    from core import sequence_worker
    out = io.StringIO()
    with redirect_stdout(out):
        sequence_worker.main(["7", "--model", "physiomix", "--domain", "bidmc", "--hr-range", "60", "63"])
    assert json.loads(out.getvalue())["provenance"]["hr_range_bpm"] == [60., 63.]
