"""scripts/build_gan_report.py: the aggregation behind Table I/II and the helpers of Fig. 2 and 9."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_gan_report", ROOT/"scripts/build_gan_report.py")
gr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gr)


def judge_row(source, seed, auc, domains=None, bal=60.):
    return dict(judge="strict", source=source, seed=seed, auc=auc, balanced_accuracy=bal,
                per_domain={d: dict(auc=v) for d, v in (domains or {}).items()},
                history=[dict(step=250, inner_auc=auc-.1), dict(step=500, inner_auc=auc)])


def test_split_source_and_labels():
    assert gr.split_source("G1_flowgan_seed42") == ("G1_flowgan", 42)
    assert gr.split_source("physiomix_app") == ("physiomix_app", None)
    assert gr.label_of("G1_flowgan").startswith("PhysioFlow-GAN")
    assert gr.label_of("unknown_source") == "unknown_source"


def test_summarise_pools_judge_and_training_seeds():
    rows = [judge_row("physiomix_app", s, .9, {"bidmc": .95}) for s in (10, 11, 12)]
    rows += [judge_row(f"G1_flowgan_seed{g}", s, a+.01*(s-10), {"bidmc": a}) for g, a in ((42, .6), (123, .7))
             for s in (10, 11, 12)]
    rows += [dict(judge_row("real_other_people", s, .5), judge="probe") for s in (10, 11)]
    out = gr.summarise(rows, "strict")
    assert set(out) == {"physiomix_app", "G1_flowgan"}
    arm = out["G1_flowgan"]
    assert arm["kind"] == "arm" and arm["n"] == 6
    assert arm["auc"] == pytest.approx(np.mean([.6, .61, .62, .7, .71, .72]), abs=1e-4)
    assert arm["seeds"] == {"42": pytest.approx(.61, abs=1e-4), "123": pytest.approx(.71, abs=1e-4)}
    assert arm["seed_sd"] == pytest.approx(np.std([.61, .71], ddof=1), abs=1e-4)
    assert arm["indistinguishable"] == pytest.approx(100*(1-abs(2*arm["auc"]-1)), abs=.01)
    assert arm["per_domain"]["bidmc"]["auc"] == pytest.approx(.65, abs=1e-4)
    assert [p[0] for p in arm["curve"]] == [250, 500]
    assert out["physiomix_app"]["kind"] == "app" and out["physiomix_app"]["seed_sd"] is None
    assert set(gr.summarise(rows, "probe")) == {"real_other_people"}


def test_dataset_table_counts_people_and_windows_per_split():
    pack = dict(domain=np.array(["bidmc"]*5+["wrist"]*3), split=np.array(["train"]*3+["test"]*2+["train"]*3),
                subject=np.array(["a", "a", "b", "c", "c", "w1", "w2", "w2"]),
                reference_hr_bpm=np.array([np.nan]*5+[80., 90., 100.], np.float32),
                rhythm_label=np.array([-1]*8))
    table = gr.dataset_table(pack, ("bidmc", "wrist"))
    bidmc, wrist = table["rows"]
    assert bidmc["train"] == dict(people=2, windows=3, share=50.) and bidmc["test"]["people"] == 1
    assert wrist["hr_median"] == 90. and bidmc["hr_median"] is None and bidmc["af_share"] is None
    assert table["total"]["train"] == 6


def test_mask_spans_and_features():
    mask = np.zeros(1200, bool)
    mask[40:80] = mask[1180:] = True
    assert gr.mask_spans(mask, 40) == [[1.0, 2.0], [29.5, 30.0]]
    x = np.random.default_rng(0).random((4, 1200)).astype(np.float32)
    assert gr.features(x, "amplitude", 40).shape == (4, 1200)
    spectral = gr.features(x, "spectral", 40)
    assert spectral.shape[0] == 4 and np.allclose(spectral[:, -81], 1.)   # ACF at lag 0 is 1
