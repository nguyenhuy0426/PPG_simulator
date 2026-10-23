"""ml.kaggle_multidomain.strict_judge: controls, people split, network shapes, training and the selection rule."""
import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain import strict_judge as sj


def test_phase_randomized_keeps_the_power_spectrum_and_changes_the_shape():
    t = np.arange(LENGTH)/FS
    x = sj.normalise(np.sin(2*np.pi*1.2*t)+.4*np.sin(2*np.pi*2.4*t+1)+.2*np.sin(2*np.pi*3.6*t+2))[None]
    y = sj.phase_randomized(x, np.random.default_rng(0))
    a, b = np.abs(np.fft.rfft(x-x.mean())), np.abs(np.fft.rfft(y-y.mean()))
    peaks = a[0] > .1*a.max()
    ratio = b[0, peaks]/a[0, peaks]
    assert np.allclose(ratio, ratio[0], rtol=1e-6)
    assert np.corrcoef(x[0], y[0])[0, 1] < .9


def test_people_split_is_disjoint_complete_and_deterministic():
    domains = np.repeat(sj.DOMAINS, 40)
    subjects = np.array([f"{d}_{i % 8}" for d, i in zip(domains, range(len(domains)))])
    pack = dict(domain=domains, subject=subjects)
    ids = np.arange(len(domains))
    a, b = sj.people_split(pack, ids), sj.people_split(pack, ids)
    assert a == b
    every = [p for part in a.values() for p in part]
    assert len(every) == len(set(every)) == len(set(subjects))
    assert all(len(part) >= len(sj.DOMAINS) for part in a.values())


def test_judges_score_one_logit_per_window_at_crop_and_full_length():
    for kind in ("strict", "strict_time"):
        judge = sj.make_judge(kind).eval()
        for length in (sj.CROP, LENGTH):
            assert judge(torch.rand(3, 1, length)).shape == (3,)
    assert sj.parameters("strict") > 100*sj.parameters("probe")


def test_strict_judge_learns_a_plainly_separable_pair(monkeypatch):
    monkeypatch.setitem(sj.JUDGES, "strict_time", dict(sj.JUDGES["strict_time"], steps=30, batch=8, lr=1e-3))
    monkeypatch.setattr(sj, "EVAL_EVERY", 10)
    rng = np.random.default_rng(0)
    t = np.arange(LENGTH)/FS
    smooth = lambda n: sj.normalise(np.sin(2*np.pi*rng.uniform(1, 2, (n, 1))*t+rng.uniform(0, 6, (n, 1))))
    rough = lambda n: sj.normalise(rng.standard_normal((n, LENGTH)))
    model, history = sj.fit("strict_time", smooth(64), rough(64), smooth(16), rough(16), "cpu", 0)
    assert len(history) == 3
    result, _ = sj.judge_scores(model, "strict_time", smooth(32), np.array(["bidmc"]*32), rough(32),
                                np.array(["bidmc"]*32), torch.device("cpu"))
    assert result["auc"] > .9 and result["per_domain"]["bidmc"]["real"] == 32


def test_selection_requires_a_null_control_near_half_and_prefers_the_smaller_judge_on_ties(monkeypatch):
    monkeypatch.setattr(sj, "parameters", lambda kind: dict(probe=1, strict=3, strict_time=2)[kind])
    def rows(kind, null, hard):
        return [dict(judge=kind, source=s, seed=0, auc=null if s == "real_other_people" else hard)
                for s in sj.MODELS+sj.CONTROLS]
    picked = sj.select(rows("probe", .5, .7)+rows("strict", .5, .905)+rows("strict_time", .52, .9))
    assert picked["best"] == "strict_time"
    picked = sj.select(rows("probe", .5, .7)+rows("strict", .7, .99))
    assert picked["best"] == "probe" and not picked["table"]["strict"]["eligible"]


def test_control_inner_windows_are_disjoint_from_control_training_windows():
    domains = np.repeat(sj.DOMAINS, 60)
    subjects = np.array([f"{d}_{i % 10}" for d, i in zip(domains, range(len(domains)))])
    n = len(domains)
    pack = dict(domain=domains, subject=subjects, split=np.where(np.arange(n) % 6 == 5, "validation", "train"),
                signal=np.arange(n, dtype=np.float32)[:, None]*np.ones((1, 4), np.float32))
    arrays, _ = sj.build_sets(pack, None, {}, "validation", seed=1, controls=("real_other_people",))
    train, inner = (set(arrays[f"real_other_people_{k}"][:, 0].astype(int)) for k in ("train", "inner"))
    assert train and inner and not train & inner
