"""GalaxyPPG fresh-test preparation: session cutting, Polar clock alignment, app prompts and the frozen rule."""
import io
import json
import zipfile

import numpy as np
import pytest

from ml.kaggle_multidomain import fresh_galaxy as fg

T0 = 1_710_000_000_000  # ms, UTC


def _zip(path, rate_bpm=72., polar_offset_ms=fg.POLAR_OFFSET_MS, events=True):
    """One participant: 4 min of a 64 Hz pulse-like BVP, a rest and a running session, 1 Hz Polar HR."""
    t = np.arange(0, 240, 1/fg.E4_FS)
    phase = 2*np.pi*rate_bpm/60*t
    bvp = np.sin(phase)+.35*np.sin(2*phase+.8)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Dataset/Meta.csv", "UID,AGE,GENDER,TSST,SSST,GalaxyWatch\nP01,25,M,5,6,R\n")
        z.writestr("Dataset/P01/E4/BVP.csv", "value,timestamp\n"+"".join(
            f"{v:.4f},{int((T0+1000*s)*1000)}\n" for v, s in zip(bvp, t)))
        z.writestr("Dataset/P01/PolarH10/HR.csv", "phoneTimestamp,hr,hrv\n"+"".join(
            f"{T0+polar_offset_ms+1000*s},{rate_bpm},1.0\n" for s in range(240)))
        if events:
            z.writestr("Dataset/P01/Event.csv", "timestamp,session,status\n"
                       f"{T0},baseline,ENTER\n{T0+120_000},baseline,EXIT\n"
                       f"{T0+120_000},running,ENTER\n{T0+240_000},running,EXIT\n")
    return path


def test_prepare_cuts_sessions_and_aligns_the_polar_clock(tmp_path):
    pack, manifest = fg.prepare(_zip(tmp_path/"g.zip"), tmp_path/"out", md5=None)
    assert manifest["per_group"]["rest"] == 4 and manifest["per_group"]["jogging_running"] == 4
    assert set(pack["subject"]) == {"galaxyppg:P01"}
    # The Korean-local Polar clock lines up only with the +9 h offset; at offset 0 nothing overlaps.
    assert np.allclose(pack["polar_hr"], 72.) and np.isnan(pack["polar_hr_utc"]).all()
    assert manifest["ppg_vs_polar_median_abs_bpm"]["polar_hr"] < 3
    assert manifest["ppg_vs_polar_median_abs_bpm"]["polar_hr_utc"] is None
    assert pack["signal"].shape[1] == 1200 and pack["signal"].min() >= 0 and pack["signal"].max() <= 1


def test_prepare_rejects_a_wrong_archive(tmp_path):
    with pytest.raises(ValueError, match="checksum"):
        fg.prepare(_zip(tmp_path/"g.zip"), tmp_path/"out")


def test_participant_without_events_is_kept_but_unlabeled(tmp_path):
    pack, manifest = fg.prepare(_zip(tmp_path/"g.zip", events=False), tmp_path/"out", md5=None)
    assert manifest["per_group"]["unlabeled"] == len(pack["signal"]) == 8


def test_wrist_prompts_follow_the_app_condition_contract():
    meta = json.loads(open("assets/neural/manifest.json").read())["physiomix"]
    t = np.arange(1200)/40
    signal = np.stack([.5+.5*np.sin(2*np.pi*r/60*t) for r in (60, 150)]).astype(np.float32)
    rows, rates = fg.wrist_prompts(meta, signal, np.array([65., np.nan]))
    domains = len(meta["domains"])
    assert rows.shape == (2, domains+5)
    assert (rows[:, :domains].argmax(1) == meta["domains"].index("wrist")).all()
    assert np.allclose(rows[:, domains:domains+2], 1)
    # Polar HR wins where present; otherwise the PPG consensus rate of the window.
    assert rates[0] == 65. and abs(rates[1]-150) < 3
    assert np.allclose(rows[:, -3]*meta["scale"][0]+meta["center"][0], rates, atol=1e-3)


def _summary(flow_ind, flow_q=.6, flow_rate=1., sd=2.):
    entry = lambda ind, q, rate: dict(indistinguishable=dict(mean=ind, sd=sd), Q=dict(mean=q, sd=0),
                                      rate_error_median_bpm=dict(mean=rate, sd=0))
    return dict(physiomix=entry(40., .6, 1.), physioflow=entry(flow_ind, flow_q, flow_rate))


@pytest.mark.parametrize("flow_ind,flow_q,flow_rate,app", [
    (45., .6, 1., "physioflow"),   # gap 5 > 2 x SD 2
    (43., .6, 1., "physiomix"),    # gap 3 within noise
    (60., .7, 1., "physiomix"),    # wrist Q worse by 0.1
    (60., .6, 4., "physiomix"),    # rate error worse by 3 bpm
])
def test_frozen_rule(flow_ind, flow_q, flow_rate, app):
    assert fg.decide(_summary(flow_ind, flow_q, flow_rate))["app_model"] == app


def test_person_split_is_fixed_and_disjoint():
    people = [f"galaxyppg:P{i:02d}" for i in range(1, 25)]
    split = fg.person_split(people)
    assert split == fg.person_split(list(reversed(people)))
    assert sum(v == "train" for v in split.values()) == 12 and set(split.values()) == {"train", "external"}


def test_step_b_rule_needs_fresh_gain_and_no_old_validation_regression():
    from ml.kaggle_multidomain.experiment_galaxy import decide_b
    entry = lambda ind, q, rate: dict(indistinguishable=dict(mean=ind, sd=1.), Q=dict(mean=q, sd=0),
                                      rate_error_median_bpm=dict(mean=rate, sd=0))
    summary = dict(physiomix=entry(1., .8, 1.5), physiomix_g=entry(30., .4, 1.5), physioflow_g=entry(30., .4, 1.5))
    ok, bad = dict(ok=True), dict(ok=False)
    decision = decide_b(summary, dict(physiomix_g=ok, physioflow_g=bad))
    assert decision["go"] == ["physiomix_g"]
    summary["physiomix_g"] = entry(2.5, .4, 1.5)  # gain 1.5 within 2 x SD
    assert decide_b(summary, dict(physiomix_g=ok, physioflow_g=ok))["go"] == ["physioflow_g"]


def test_unmeasurable_rate_is_saved_as_null_and_fails_the_rule():
    assert fg.median_or_none(np.array([np.nan, np.nan])) is None
    assert fg.median_or_none(np.array([np.nan, 2., 4.])) == 3.
    halving = dict(indistinguishable=1., Q=.5, fidelity=.5, coverage=.5, rate_error_median_bpm=None, rate_within_5bpm=0.)
    summary = fg.summarize([dict(physioflow=halving), dict(physioflow=dict(halving, rate_error_median_bpm=1.))])
    assert summary["physioflow"]["rate_error_median_bpm"] == dict(mean=None, sd=None)
    json.dumps(summary, allow_nan=False)
    flow_unmeasurable = _summary(60.)
    flow_unmeasurable["physioflow"]["rate_error_median_bpm"] = dict(mean=None, sd=None)
    assert fg.decide(flow_unmeasurable)["app_model"] == "physiomix"
