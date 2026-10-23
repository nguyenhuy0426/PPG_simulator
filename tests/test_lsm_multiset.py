"""ml.kaggle_lsm.lsm_multiset: preprocessing, people split, AUC and detector shape (no data files, no training)."""
import numpy as np
import torch

from ml.kaggle_lsm import lsm_multiset as lm


def test_windows_follow_the_paper_view_and_drop_only_gapped_windows():
    t = np.arange(125*90)/125
    wave = np.sin(2*np.pi*1.2*t)
    wave[125*40] = np.nan                               # inside the second 30 s window
    out, rejected = lm.windows(wave, 125.)
    assert rejected == 1 and len(out) == 2
    assert all(w.shape == (lm.LENGTH,) and w.min() == 0 and abs(w.max()-1) < 1e-6 for w in out)


def test_people_split_is_disjoint_deterministic_and_keeps_two_held_people():
    people = [f"p{i:02d}" for i in range(16)]
    a, b = lm.split_people(people), lm.split_people(list(reversed(people)))
    assert a == b
    assert sum(map(len, a.values())) == 16 and len(set().union(*map(set, a.values()))) == 16
    assert len(a["validation"]) == len(a["test"]) == 2


def test_auc_matches_rank_definition():
    y = np.array([0, 0, 1, 1])
    assert lm.auc(y, np.array([.1, .4, .35, .8])) == .75
    assert lm.auc(y, np.array([.1, .2, .3, .4])) == 1.


def test_detector_scores_one_logit_per_window():
    assert lm.Detector()(torch.zeros(3, lm.LENGTH)).shape == (3,)
