"""Tests for review provenance, label-preserving augmentation and independent evaluation."""
import copy
import json
import numpy as np
import pytest

pytest.importorskip("scipy")
pytest.importorskip("torch")
from ml import round2_review as review
from ml.independent_ppg_eval import landmarks, metrics
from ml.round2_finetune import warp_batch, relative_derivative_loss


def pulse(notch=True):
    t = np.linspace(0, 1, 256)
    y = np.exp(-.5*((t-.23)/.07)**2)
    if notch:
        y += .45*np.exp(-.5*((t-.61)/.07)**2)
    return ((y-y.min())/np.ptp(y)).astype(np.float32)


@pytest.fixture
def review_fixture(tmp_path, monkeypatch):
    x = np.stack([pulse(i % 2 == 1) for i in range(14)])
    c = np.tile([.375, .23, .45, .61, .1, .45, 1], (14, 1)).astype(np.float32)
    c[::2, 2:] = 0
    masks = {s: np.array([i in r for i in range(14)]) for s, r in
             (("train", range(6)), ("validation", range(6,12)), ("test", range(12,14)))}
    subjects = np.array(["train"]*6+["validation"]*6+["test"]*2)
    path = tmp_path/"prepared.npz"
    np.savez(path, subject=subjects, record=np.ones(14), start_sample=np.arange(14))
    monkeypatch.setattr(review, "load_prepared", lambda _: (x, c, masks))
    cases = [dict(id=i, split="train" if i<6 else "validation", subject=str(subjects[i]),
                  decision="accept", notch="present" if i%2 else "absent",
                  sp=.23, dn=.45 if i%2 else None, dp=.61 if i%2 else None) for i in range(12)]
    annotation = dict(schema=1, prepared_sha256=review.PREPARED_SHA256, reviewer="unit-test fixture",
                      reviewed_at="2026-09-28T00:00:00Z", cases=cases)
    return path, annotation


def load_fixture(tmp_path, source, value):
    file = tmp_path/"review.json"
    file.write_text(json.dumps(value))
    return review.curated_data(source, file, min_train=4, min_validation=4)


def test_review_excludes_uncertain_and_keeps_subject_split(review_fixture, tmp_path):
    source, value = review_fixture
    value["cases"][0]["decision"] = "uncertain"
    x, c, masks, subjects, provenance = load_fixture(tmp_path, source, value)
    assert len(x) == 11 and provenance["counts"]["uncertain"] == 1
    assert not (set(subjects[masks["train"]]) & set(subjects[masks["validation"]]))
    assert 0 not in provenance["source_indices"]


@pytest.mark.parametrize("change", ["reviewer", "pending", "test", "duplicate", "nan", "order", "hash", "subject"])
def test_invalid_reviews_cannot_train(review_fixture, tmp_path, change):
    source, value = review_fixture
    if change == "reviewer": value["reviewer"] = ""
    if change == "pending":
        for row in value["cases"]: row["decision"] = "pending"
    if change == "test": value["cases"][0].update(id=12, split="test", subject="test")
    if change == "duplicate": value["cases"].append(copy.deepcopy(value["cases"][0]))
    if change == "nan": value["cases"][0]["sp"] = float("nan")
    if change == "order": value["cases"][1]["dn"] = .8
    if change == "hash": value["prepared_sha256"] = "wrong"
    if change == "subject": value["cases"][0]["subject"] = "wrong"
    with pytest.raises(ValueError):
        load_fixture(tmp_path, source, value)


def test_review_pack_is_unlabelled_and_test_free(review_fixture, tmp_path):
    source, _ = review_fixture
    pack = review.build_pack(source, tmp_path/"pack", 3, 3)
    assert len(pack["cases"]) == 12
    assert not pack["reviewer"] and all(r["decision"] == "pending" for r in pack["cases"])
    assert all(r["sp"] is None and r["notch"] == "" and r["split"] != "test" for r in pack["cases"])


def test_warp_transforms_landmarks_and_retains_hr():
    x = np.stack([pulse(), pulse(False)])
    x[:, [0, -1]] = 0  # Match the zero-boundary pulse contract of prepared data.
    c = np.array([[.375, .23, .45, .61, .1, .45, 1], [.5, .23, 0, 0, 0, 0, 0]], np.float32)
    warped, labels = warp_batch(x, c, np.array([.01, -.01]))
    np.testing.assert_array_equal(labels[:, 0], c[:, 0])
    np.testing.assert_array_equal(labels[:, -1], c[:, -1])
    assert labels[0, 1] < c[0, 1] and labels[1, 1] > c[1, 1]
    assert labels[0, 1] < labels[0, 2] < labels[0, 3]
    assert np.isfinite(warped).all() and warped.min() >= 0 and warped.max() <= 1
    np.testing.assert_allclose(warped[:, [0,-1]], x[:, [0,-1]], atol=1e-6)
    with pytest.raises(ValueError):
        warp_batch(x, c, [.1, 0])


def test_independent_detector_and_metrics_respond_to_actual_shape():
    smooth, notched = pulse(False), pulse()
    assert not landmarks(smooth)["notch"]
    assert landmarks(notched)["notch"]
    x = np.stack([smooth, notched])
    c = np.array([[.375,.23,0,0,0,0,0],[.375,.23,.45,.61,.1,.45,1]])
    result = metrics(x, c, x)
    assert result["phase_log_psd_rmse"] == 0 and result["phase_acf_rmse"] == 0
    assert result["requested_notch_recall"] == result["requested_no_notch_specificity"] == 1
    jitter = x + .02*np.sin(np.arange(256)*2)[None]
    assert metrics(jitter, c, x)["roughness"] > result["roughness"]


def test_relative_derivative_loss_has_finite_nonzero_gradient():
    import torch
    real = torch.tensor(np.stack([pulse(), pulse(False)]))
    fake = (real+.01*torch.sin(torch.arange(256)*2)).requires_grad_(True)
    loss = relative_derivative_loss(fake, real)
    loss.backward()
    assert torch.isfinite(loss) and torch.isfinite(fake.grad).all() and fake.grad.abs().sum() > 0
