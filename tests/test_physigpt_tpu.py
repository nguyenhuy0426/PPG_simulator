"""train_tpu.py on PyTorch/XLA's CPU backend (PJRT_DEVICE=CPU). Skipped where torch_xla is not installed; these
check the XLA code path and the checkpoint format, not TPU speed or bf16 numerics on a real TPU."""
import json
import os

import numpy as np
import pytest

os.environ.setdefault("PJRT_DEVICE", "CPU")
pytest.importorskip("torch_xla")
import torch

from ml.kaggle_physigpt import train as tr
from ml.kaggle_physigpt import train_tpu as tt

COMMON = ["--config", "tiny", "--batch", "8", "--warmup", "2", "--decay-frac", ".34", "--log-every", "1",
          "--eval-every", "3", "--sample-steps", "2", "--precision", "fp32"]


def run_in_process(argv):
    """worker() in this process (one XLA CPU device), so the XLA metrics of the run are readable here."""
    seen = {}

    def capture(fn, args):
        seen["args"] = args[0]

    import torch_xla.distributed.xla_multiprocessing as xmp
    spawn = xmp.spawn
    xmp.spawn = capture
    try:
        tt.main(argv)
    finally:
        xmp.spawn = spawn
    tt.worker(0, seen["args"])


def test_tpu_stage_releases_and_its_state_resumes_on_the_gpu_trainer(tmp_path):
    tr.synthetic_shard(tmp_path/"shard", n=256)
    run_in_process(["--data", str(tmp_path/"shard"), "--output", str(tmp_path/"tpu"), "--steps", "6", *COMMON])
    summary = json.loads((tmp_path/"tpu"/"stage_summary.json").read_text())
    assert summary["device"] == "tpu" and summary["steps"] == 6 and np.isfinite(summary["final"]["valid_flow"])
    state = torch.load(tmp_path/"tpu"/"stable.pt", weights_only=False)
    assert state["scaler"] == {} and state["plan"] == [6, 4] and state["step"] == 4
    assert all(v.device.type == "cpu" for v in state["model"].values())
    # The T4 trainer continues the same stage from the TPU state (same stage id), without a gradient scaler.
    tr.main(["--data", str(tmp_path/"shard"), "--output", str(tmp_path/"gpu"), "--steps", "6", "--cpu",
             "--resume", str(tmp_path/"tpu"/"stable.pt"), *COMMON[:-2]])
    lines = [json.loads(l) for l in (tmp_path/"gpu"/"metrics.jsonl").read_text().splitlines()]
    assert [l["step"] for l in lines] == [5, 6]


def test_tpu_stage_resumes_exactly_and_compiles_the_step_once(tmp_path):
    import torch_xla.debug.metrics as met
    tr.synthetic_shard(tmp_path/"shard", n=256)
    argv = ["--data", str(tmp_path/"shard"), "--steps", "8", *COMMON]
    run_in_process(argv+["--output", str(tmp_path/"full")])
    run_in_process(argv+["--output", str(tmp_path/"part"), "--stop-at", "3"])
    before = met.metric_data("CompileTime")[0]
    run_in_process(argv+["--output", str(tmp_path/"part"), "--resume", str(tmp_path/"part"/"last.pt")])
    compiles = met.metric_data("CompileTime")[0]-before
    a = torch.load(tmp_path/"full"/"release.pt", weights_only=False)["model"]
    b = torch.load(tmp_path/"part"/"release.pt", weights_only=False)["model"]
    assert all(torch.allclose(a[k], b[k], atol=1e-5) for k in a)
    # 5 steps with a changing learning rate, 2 evaluations and 3 saves: a graph per step would compile >= 5 times
    # for the step alone. The bound leaves room for the distinct evaluation/save/first-step graphs.
    assert compiles <= 12, compiles

