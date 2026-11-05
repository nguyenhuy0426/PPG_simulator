"""Exactness and bookkeeping of the training-set copy check (ml/kaggle_physigpt/copy_check.py)."""
import json

import numpy as np
import pytest
from scipy import fft

from ml.kaggle_lsm.train_lsm import LENGTH
from ml.kaggle_multidomain.realism import nearest_train_correlation
from ml.kaggle_physigpt import copy_check as cc
from ml.kaggle_physigpt.mimic_wdb import PROTOCOL
from ml.kaggle_physigpt.train import Windows


def pulses(rng, n):
    """Pulse-like windows: heart rates and harmonics near each other, the case where the bound is loosest."""
    t = np.arange(LENGTH)/40
    rate = rng.uniform(1, 1.6, (n, 1))
    phase = rng.uniform(0, 6.3, (n, 1))
    x = np.sin(2*np.pi*rate*t+phase)+.4*np.sin(4*np.pi*rate*t+2*phase+rng.uniform(0, 3, (n, 1)))
    x = x+.15*rng.normal(size=x.shape)
    low, high = x.min(1, keepdims=True), x.max(1, keepdims=True)
    return ((x-low)/(high-low)).astype(np.float32)


def shard(root, signal, record, valid):
    root.mkdir(parents=True)
    signal = np.round(signal*65535).astype(np.uint16)
    meta = np.zeros(len(signal), dtype=[("record", "<i4"), ("start", "<i4"), ("valid", "u1"), ("acf", "<f2"), ("rate", "<f2")])
    meta["record"], meta["valid"] = record, valid
    np.save(root/"chunk_0000_signal.npy", signal)
    np.save(root/"chunk_0000_meta.npy", meta)
    (root/"manifest.json").write_text(json.dumps(dict(
        protocol=PROTOCOL, record_range=[0, int(record.max())+1], windows=len(signal),
        chunks=[dict(stem="chunk_0000", windows=len(signal), sha256="x")])))


def test_bound_never_below_any_shift():
    rng = np.random.default_rng(0)
    x, y = cc.unit(pulses(rng, 12)), cc.unit(pulses(rng, 40))
    X, Y = fft.rfft(x, axis=1), fft.rfft(y, axis=1)
    bound = cc.upper_bound(np.abs(X), np.abs(Y))
    exact = fft.irfft(X[:, None]*np.conj(Y)[None], n=LENGTH, axis=2).max(axis=2)
    assert np.all(bound >= exact-1e-4)
    assert np.all(exact <= 1+1e-4)


def test_pruned_search_equals_the_brute_statistic():
    rng = np.random.default_rng(1)
    x, train = pulses(rng, 24), pulses(rng, 600)
    search = cc.Nearest(x, threads=2)
    for start in range(0, len(train), 128):
        search.update(train[start:start+128], np.arange(start, min(start+128, len(train))))
    assert search.best == pytest.approx(nearest_train_correlation(x, train), abs=1e-4)
    assert search.exact_pairs < search.bound_pairs   # the bound really pruned


def test_shifted_copy_is_found_with_row_and_shift():
    rng = np.random.default_rng(2)
    train = pulses(rng, 200)
    x = np.stack([np.roll(train[17], 333), np.roll(train[150], 5)])
    search = cc.Nearest(x, threads=1)
    search.update(train[:100], np.arange(100))
    search.update(train[100:], np.arange(100, 200))
    assert search.row.tolist() == [17, 150]
    assert search.best == pytest.approx([1, 1], abs=1e-4)
    assert np.allclose(np.roll(train[17], search.shift[0]), x[0])


def test_flat_window_scores_zero_not_nan():
    rng = np.random.default_rng(3)
    train = pulses(rng, 8)
    search = cc.Nearest(np.vstack([np.full((1, LENGTH), .5, np.float32), train[:1]]), threads=1)
    search.update(train, np.arange(8))
    assert search.best[0] <= cc.MARGIN
    assert search.best[1] == pytest.approx(1, abs=1e-4)


@pytest.fixture
def mounted(tmp_path):
    rng = np.random.default_rng(4)
    signal = pulses(rng, 300)
    record = np.repeat(np.arange(30), 10)
    valid = (record >= 27).astype(int)
    shard(tmp_path/"shard", signal, record, valid)
    return Windows([tmp_path/"shard"]), signal, tmp_path


def test_run_reports_coverage_copies_and_never_compares_held_out(mounted):
    data, signal, tmp_path = mounted
    rng = np.random.default_rng(5)
    held = data.valid[:12]
    copied = np.vstack([signal[data.train[:4]], pulses(rng, 4)]).astype(np.float32)
    report = cc.run(data, dict(copier=copied), tmp_path/"out", held, expect_train=len(data.train), block=64,
                    threads=2, log=lambda text: None)
    assert report["whole_train_set"] and report["train_fraction"] == 1
    assert report["train_compared"] == len(data.train) == 270
    assert report["control_found"] == report["control_planted"] == cc.CONTROLS
    arrays = np.load(tmp_path/"out"/"copy_check.npz")
    assert np.isin(arrays["held_out_people/row"], data.train).all()   # nearest rows are training rows only
    assert arrays["copier/row"][:4].tolist() == data.train[:4].tolist()
    assert report["sources"]["copier"]["above_0_99_count"] >= 4
    assert report["top"]["copier"][0]["record"] in data.record
    # The saved train window, rolled by the saved shift, lies on the saved query.
    assert np.corrcoef(arrays["copier/top_window"][0], arrays["copier/top_train"][0])[0, 1] > .99
    cc.figure(tmp_path/"out")
    assert (tmp_path/"out"/"top_windows.png").stat().st_size > 0


def test_a_limited_run_does_not_claim_the_whole_set(mounted):
    data, signal, tmp_path = mounted
    report = cc.run(data, dict(m=signal[:4]), tmp_path/"out", data.valid[:4], limit=100, block=64, threads=1,
                    log=lambda text: None)
    assert not report["whole_train_set"]
    assert report["train_compared"] == 100
    assert report["train_fraction"] == pytest.approx(100/270)


def test_wrong_training_count_fails_before_scoring(mounted):
    data, signal, tmp_path = mounted
    with pytest.raises(ValueError, match="training windows mounted"):
        cc.run(data, dict(m=signal[:4]), tmp_path/"out", data.valid[:4], expect_train=999, log=lambda text: None)


def test_held_out_rows_among_training_rows_fail(mounted):
    data, signal, tmp_path = mounted
    with pytest.raises(ValueError, match="among the training rows"):
        cc.run(data, dict(m=signal[:4]), tmp_path/"out", data.train[:4], log=lambda text: None)


def test_eval_part_takes_the_final_set(tmp_path):
    generated = np.arange(9000*LENGTH, dtype=np.float32).reshape(9000, LENGTH)
    np.save(tmp_path/"generated.npy", generated)
    windows, digest = cc.eval_part(tmp_path/"generated.npy")
    assert windows.shape == (2000, LENGTH) and windows[0, 0] == generated[7000, 0] and len(digest) == 64
    np.save(tmp_path/"short.npy", generated[:10])
    with pytest.raises(ValueError, match="expected"):
        cc.eval_part(tmp_path/"short.npy")


def test_package_writes_a_private_cpu_kernel_with_the_module(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "claude/model-benchmark-x\n")
    out = cc.package(tmp_path/"k", "owner", ["ppg-physigpt-mimic3-shard1-v1"], ["ppg-physigpt-shard0-data-v1"],
                     dict(a=("gen-a", "dataset"), b=("gen-b", "kernel")), extra=["--queries", "8"])
    meta = json.loads((out/"kernel-metadata.json").read_text())
    assert meta["is_private"] and not meta["enable_gpu"] and not meta["enable_internet"]
    assert meta["dataset_sources"] == ["owner/ppg-physigpt-shard0-data-v1", "owner/gen-a"]
    assert meta["kernel_sources"] == ["owner/ppg-physigpt-mimic3-shard1-v1", "owner/gen-b"]
    manifest = json.loads((out/"source_manifest.json").read_text())
    assert "ml/kaggle_physigpt/copy_check.py" in manifest["files"]
    assert "'--queries', '8'" in (out/"run.py").read_text()
