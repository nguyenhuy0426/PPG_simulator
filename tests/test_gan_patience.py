"""--patience of the two fine-tuning scripts: the loops run for real on CPU, only the selection scores are scripted."""
import json

import numpy as np
import pytest
import torch

from ml.kaggle_multidomain import physio, rsr_flowgan as rf
from ml.kaggle_multidomain.flow import FlowGenerator
from ml.kaggle_physigpt import gan
from ml.kaggle_physigpt.train import synthetic_shard
from test_physiomix_v2 import v3_pack


def script_gan(scores):
    """select_score giving these scores in turn (the last one repeats)."""
    calls = iter(list(scores)+[scores[-1]]*1000)
    gan.select_score = lambda *a: dict(mean_similarity=next(calls), similarity={})


def run_gan(root, name, *extra):
    if not (root/"shard"/"manifest.json").exists():
        synthetic_shard(root/"shard")
    gan.main(["--data", str(root/"shard"), "--output", str(root/name), "--config", "tiny", "--batch", "4", "--anchor", "4",
              "--critic-warmup", "1", "--gen-steps", "2", "--eval-every", "2", "--cpu", "--port", "29541", *extra])
    lines = [json.loads(l) for l in (root/name/"metrics.jsonl").read_text().splitlines()]
    return json.loads((root/name/"gan_summary.json").read_text()), [l["step"] for l in lines if "select" in l]


@pytest.fixture
def restore_select_score():
    original = gan.select_score
    yield
    gan.select_score = original


def test_gan_stops_after_patience_evaluations_without_a_new_best_and_a_new_best_resets_the_count(tmp_path, restore_select_score):
    script_gan([.5, .4, .6, .5, .4, .9])   # .9 at step 10 must never be reached
    summary, selected = run_gan(tmp_path, "run", "--steps", "20", "--patience", "2", "--rt-gate", "-1")
    assert selected == [0, 2, 4, 6, 8]
    assert summary["stop_reason"] == "patience" and summary["steps"] == 8 and summary["planned"] == 20
    assert summary["best"]["step"] == 4 and summary["stale_evals"] == 2 and summary["patience"] == 2
    assert torch.load(tmp_path/"run"/"gan_release.pt", weights_only=False)["step"] == 4
    assert torch.load(tmp_path/"run"/"last.pt", weights_only=False)["step"] == 8


def test_gan_without_patience_runs_every_planned_step(tmp_path, restore_select_score):
    script_gan([.5, .4, .3, .2, .1])
    summary, selected = run_gan(tmp_path, "run", "--steps", "8", "--rt-gate", "-1")
    assert selected == [0, 2, 4, 6, 8]
    assert summary["stop_reason"] == "steps" and summary["steps"] == 8 and summary["patience"] == 0


def test_gan_patience_running_out_on_the_last_step_is_a_full_run(tmp_path, restore_select_score):
    script_gan([.5, .4, .3])
    summary, _ = run_gan(tmp_path, "run", "--steps", "4", "--patience", "2", "--rt-gate", "-1")
    assert summary["stop_reason"] == "steps" and summary["steps"] == 4 and summary["stale_evals"] == 2


def test_gan_evaluations_of_a_generator_that_did_not_move_do_not_count(tmp_path, restore_select_score):
    script_gan([.5])
    summary, selected = run_gan(tmp_path, "run", "--steps", "6", "--patience", "1", "--rt-gate", "2")
    assert summary["generator_updates"] == 0 and summary["stale_evals"] == 0
    assert summary["stop_reason"] == "steps" and selected == [0, 2, 4, 6]


def test_gan_resume_keeps_the_count_of_evaluations_without_a_new_best(tmp_path, restore_select_score):
    script_gan([.5, .6, .4])
    first, _ = run_gan(tmp_path, "run", "--steps", "4", "--patience", "2", "--rt-gate", "-1")
    assert first["stale_evals"] == 1
    script_gan([.4, .9])
    summary, _ = run_gan(tmp_path, "run", "--steps", "20", "--patience", "2", "--rt-gate", "-1",
                         "--resume", str(tmp_path/"run"/"last.pt"))
    assert summary["stop_reason"] == "patience" and summary["steps"] == 6 and summary["best"]["step"] == 2


def _scripted_worker(rank, world, args, scores):
    script_gan(scores)
    gan.worker(rank, world, args)


def test_gan_two_processes_stop_at_the_same_step(tmp_path, monkeypatch):
    # only rank 0 scores; a rank left in the training loop would hang the all-reduce instead of exiting
    spawn = torch.multiprocessing.spawn
    monkeypatch.setattr(torch.multiprocessing, "spawn", lambda fn, args, nprocs, join: spawn(
        _scripted_worker, args=(*args, [.5, .4, .3, .9]), nprocs=nprocs, join=join))
    summary, selected = run_gan(tmp_path, "run", "--steps", "20", "--patience", "2", "--rt-gate", "-1", "--cpu-world", "2",
                                "--port", "29542")
    assert summary["stop_reason"] == "patience" and summary["steps"] == 4 and selected == [0, 2, 4]


class TinyInputs:
    """The v3 test pack and an untrained two-step FlowGenerator in place of the pack on disk and the app bundle."""

    def __init__(self, root):
        pack = v3_pack()
        self.pack = {k: v[pack["split"] != "external"] for k, v in pack.items()}
        self.keep = np.flatnonzero(np.isin(self.pack["split"], ["train", "validation"]))
        self.view = {k: v[self.keep] for k, v in self.pack.items()}
        self.conditions = physio.Conditions(self.view, "v2")
        self.manifest = dict(windows_sha256="x")

    def generator(self):
        c = self.conditions
        return FlowGenerator(c.bank.shape[1], c.center, c.scale, sample_steps=2, flag_scaffold=True).train()


def run_rsr(monkeypatch, root, scores, *extra):
    calls = iter(list(scores)+[scores[-1]]*1000)
    monkeypatch.setattr(rf, "Inputs", TinyInputs)
    monkeypatch.setattr(rf, "SELECT_PER_DOMAIN", 2)
    monkeypatch.setattr(rf, "similarity", lambda *a: dict(score=next(calls)))
    rf.main(["--input-root", str(root), "--output", str(root/"run"), "--seeds", "7", "--batch", "4", "--anchor", "4",
             "--critic-warmup", "1", "--grad-steps", "1", "--eval-every", "2", "--skip-judge", "--cpu", *extra])
    lines = [json.loads(l) for l in (root/"run"/"seed7"/"metrics.jsonl").read_text().splitlines()]
    return json.loads((root/"run"/"seed7"/"train_summary.json").read_text()), [l["step"] for l in lines if "similarity" in l]


def test_rsr_flowgan_stops_a_seed_after_patience_evaluations_and_keeps_its_best(tmp_path, monkeypatch):
    summary, selected = run_rsr(monkeypatch, tmp_path, [.5, .4, .6, .5, .4, .9], "--steps", "20", "--patience", "2",
                                "--rt-gate", "-1")
    assert selected == [0, 2, 4, 6, 8]
    assert summary["stop_reason"] == "patience" and summary["steps"] == 8 and summary["best"]["step"] == 4
    assert summary["stale_evals"] == 2
    assert torch.load(tmp_path/"run"/"seed7"/"best.pt", weights_only=False)["step"] == 4


def test_rsr_flowgan_without_patience_runs_every_planned_step(tmp_path, monkeypatch):
    summary, selected = run_rsr(monkeypatch, tmp_path, [.5, .4, .3, .2], "--steps", "6", "--rt-gate", "-1")
    assert selected == [0, 2, 4, 6]
    assert summary["stop_reason"] == "steps" and summary["steps"] == 6 and summary["patience"] == 0


def test_rsr_flowgan_evaluations_of_a_generator_that_did_not_move_do_not_count(tmp_path, monkeypatch):
    summary, selected = run_rsr(monkeypatch, tmp_path, [.5], "--steps", "6", "--patience", "1", "--rt-gate", "2")
    assert summary["generator_updates"] == 0 and summary["stale_evals"] == 0
    assert summary["stop_reason"] == "steps" and selected == [0, 2, 4, 6]


def test_rsr_flowgan_time_limit_is_reported_as_the_reason(tmp_path, monkeypatch):
    summary, _ = run_rsr(monkeypatch, tmp_path, [.5], "--steps", "6", "--hours", "0", "--rt-gate", "-1")
    assert summary["stop_reason"] == "hours" and summary["steps"] == 0


@pytest.mark.parametrize("module, required", [(gan, ["--data", "x", "--output", "y"]), (rf, ["--input-root", "x", "--output", "y"])])
def test_negative_patience_is_refused(module, required):
    with pytest.raises(SystemExit):
        module.main([*required, "--patience", "-1"])
