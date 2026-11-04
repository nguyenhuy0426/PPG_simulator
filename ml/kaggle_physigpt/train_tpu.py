"""PPG-physiGPT pretraining on a Kaggle TPU v3-8 (PyTorch/XLA, 8 cores, bf16 autocast).

The same stage as train.py, on another device: the windows, the batch of every step (batch_index), the
warmup-stable-decay schedule, stable.pt / last.pt / release.pt, the stage id and the summary all come from train.py,
so a stage started here can be resumed on the T4s and the other way round (the TPU states carry no gradient scaler).
What differs is only what XLA needs:
- one process per core (xmp.spawn); gradients are all-reduced by xm.reduce_gradients before clipping;
- every tensor shape is fixed (the per-core batch, the evaluation chunks), so the step graph compiles once;
- the flow noise comes from the XLA generator, reseeded from (seed, step, core) at every step, so a resumed stage
  draws the same noise; it is a different stream from the CUDA one, so the two devices do not give equal weights;
- the time budget is measured on steps 20-70, after the graph has compiled;
- the release samples are drawn on the host CPU (the sampler takes a torch.Generator, which XLA does not provide).
Kaggle stops a TPU session at 9 h (assumed from Kaggle's notebook limits, not read from a document); --hours is set
below that.
"""
import argparse
import json
import os
from pathlib import Path
import queue
import threading
import time

import numpy as np
import torch

from ml.kaggle_lsm.train_lsm import save_json
from ml.kaggle_physigpt.model import CONFIGS, PhysiGPT, describe
from ml.kaggle_physigpt.train import (VALID_WINDOWS, Windows, batch_index, lr_at, plan_steps, release_samples,
                                      stage_identity, synthetic_shard)

EVAL_CHUNK = 256
MEASURE_FROM, MEASURE_STEPS = 20, 50


def xla():
    import torch_xla.core.xla_model as xm
    import torch_xla.runtime as xr
    return xm, xr


def evaluate(model, data, device, world, rank, amp):
    """Mean validation flow loss and NLL over the same fixed windows as train.py, split evenly over the cores."""
    xm, _ = xla()
    n = min(VALID_WINDOWS, len(data.valid))
    index = data.valid[np.linspace(0, len(data.valid)-1, n).astype(int)]
    per_core = (n//(world*EVAL_CHUNK))*EVAL_CHUNK or n//world   # equal on every core: one compiled chunk shape
    if not per_core:
        raise ValueError(f"{n} validation windows cannot be split over {world} cores")
    mine = index[rank*per_core:(rank+1)*per_core]
    xm.set_rng_state(20261027+rank, device=device)
    totals = torch.zeros(3, device=device)
    model.eval()
    with torch.no_grad():
        for lo in range(0, len(mine), EVAL_CHUNK):
            x = torch.from_numpy(data.rows(mine[lo:lo+EVAL_CHUNK]).astype(np.float32)/65535).to(device)
            with torch.autocast("xla", dtype=torch.bfloat16, enabled=amp):
                _, parts = model(x, torch.zeros(len(x), dtype=torch.long, device=device))
            totals += torch.stack([parts["flow"].float()*len(x), parts["laplace_nll"].float()*len(x),
                                   torch.tensor(float(len(x)), device=device)])
            xm.mark_step()
    model.train()
    totals = xm.all_reduce(xm.REDUCE_SUM, totals)
    flow, nll, count = totals.cpu().tolist()
    return dict(valid_flow=flow/max(count, 1), valid_laplace_nll=nll/max(count, 1))


def save_state(path, model, optimizer, step, plan, args, stage_id):
    """train.py's state layout; xm.save copies the XLA tensors to the host and writes from the master core only."""
    xm, _ = xla()
    tmp = Path(str(path)+".partial")
    xm.save(dict(model=model.state_dict(), optimizer=optimizer.state_dict(), scaler={}, step=step, plan=plan,
                 config=args.config, stage_id=stage_id, device="tpu"), str(tmp))
    if xm.is_master_ordinal(local=False):
        tmp.replace(path)
    xm.rendezvous(f"saved-{Path(path).name}-{step}")


def worker(index, args):
    try:
        run_core(args)
    except BaseException:
        import traceback
        print(f"core {index} failed:\n{traceback.format_exc()}", flush=True)
        raise


def run_core(args):
    xm, xr = xla()
    world, rank = xr.world_size(), xr.global_ordinal()
    device = xm.xla_device()
    master = rank == 0
    output = Path(args.output)
    begin = time.time()
    torch.manual_seed(args.seed)
    model = PhysiGPT(CONFIGS[args.config])
    data = Windows(args.data+args.replay)
    if not len(data.valid):
        raise ValueError(f"no held-out windows under {args.data+args.replay}: too few records for the 2% split")
    stage_id = stage_identity(data, args.seed, args.config)
    new_paths = {s["path"] for s in Windows(args.data).shards}
    shard_of = np.repeat(np.arange(len(data.shards), dtype=np.int16).repeat([len(s["chunks"]) for s in data.shards]),
                         np.diff(data.offsets))
    is_new = np.isin(shard_of, [i for i, s in enumerate(data.shards) if s["path"] in new_paths])
    new_rows, replay_rows = data.train[is_new[data.train]], data.train[~is_new[data.train]]
    total, decay_start = plan_steps(len(new_rows), args.epochs, args.batch, args.replay_share if len(replay_rows) else 0,
                                    args.decay_frac)
    if args.steps:
        total, decay_start = args.steps, args.steps-max(1, round(args.decay_frac*args.steps))
    step, warmup = 0, min(args.warmup, max(1, total//10))
    state = None
    if args.resume:
        state = torch.load(args.resume, map_location="cpu", weights_only=False)
        if state["config"] != args.config:
            raise ValueError(f"checkpoint config {state['config']} != {args.config}")
        model.load_state_dict(state["model"])
        if state["stage_id"] == stage_id:
            step, (total, decay_start) = state["step"], state["plan"]
        warmup = 0
    model = model.to(device)
    # On a v3-8 two cores share a process (a thread each) and its global RNG, so initial weights can differ between
    # cores; every core starts from the master's weights (a resumed state is the same on all of them anyway).
    xm.broadcast_master_param(model)
    decay, no_decay = [], []
    for name, p in model.named_parameters():
        (decay if p.dim() == 2 and "start" not in name else no_decay).append(p)
    optimizer = torch.optim.AdamW([dict(params=decay, weight_decay=args.weight_decay), dict(params=no_decay,
                                   weight_decay=0.)], lr=args.lr, betas=(.9, .95), eps=1e-8)
    if state is not None:
        optimizer.load_state_dict(state["optimizer"])   # moves the moments onto the XLA device with the parameters
    local = args.batch//world
    if args.batch % world:
        raise ValueError(f"batch {args.batch} must divide by the {world} cores")
    if master:
        output.mkdir(parents=True, exist_ok=True)
        save_json(output/"run_config.json", dict(vars(args), stage_id=stage_id, world=world, device="tpu",
                                                 xla_device=dict(type=xr.device_type(), str=str(device)),
                                                 model=describe(model), new_windows=int(len(new_rows)),
                                                 replay_windows=int(len(replay_rows)),
                                                 valid_windows=int(len(data.valid)), shards=data.shards,
                                                 plan=[total, decay_start], start_step=step))
    feed = queue.Queue(maxsize=4)

    def produce(first):
        for s in range(first, total):
            rows = batch_index(new_rows, replay_rows, s, args.batch, args.replay_share, args.seed)
            feed.put((s, data.rows(rows[rank*local:(rank+1)*local])))
        feed.put(None)

    threading.Thread(target=produce, args=(step,), daemon=True).start()
    log = (output/"metrics.jsonl").open("a") if master else None
    domain = torch.zeros(local, dtype=torch.long, device=device)
    # Saving is decided by step count, the same on every core (a per-core clock would split the collectives).
    tick, measured, save_every, started = None, None, 0, step
    while True:
        item = feed.get()
        if item is None:
            break
        s, rows = item
        if s >= total:
            continue
        for group in optimizer.param_groups:
            group["lr"] = lr_at(s, total, decay_start, args.lr, warmup)
        x = torch.from_numpy(rows.astype(np.float32)/65535).to(device)
        xm.set_rng_state(args.seed*1_000_003+s*world+rank, device=device)
        with torch.autocast("xla", dtype=torch.bfloat16, enabled=args.precision == "bf16"):
            loss, parts = model(x, domain, aux=args.aux, repeats=args.repeats)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        xm.reduce_gradients(optimizer)
        grad = torch.nn.utils.clip_grad_norm_(model.parameters(), args.clip)
        optimizer.step()
        xm.mark_step()
        step = s+1
        if step == decay_start:
            save_state(output/"stable.pt", model, optimizer, step, [total, decay_start], args, stage_id)
        if step-started == MEASURE_FROM:
            xm.wait_device_ops()
            tick = time.time()
        if measured is None and step-started == MEASURE_FROM+MEASURE_STEPS:
            # The kernel budget shortens the stage once, from the compiled step time, keeping the decay share.
            xm.wait_device_ops()
            seconds = float(xm.all_reduce(xm.REDUCE_MAX, torch.tensor((time.time()-tick)/MEASURE_STEPS,
                                                                     device=device)).cpu())
            left = args.hours*3600-(time.time()-begin)-args.reserve_minutes*60
            fit = int(xm.all_reduce(xm.REDUCE_MIN, torch.tensor(float(step+int(left/seconds)), device=device)).cpu())
            if fit < total:
                total = max(step+1, fit)
                decay_start = max(step, min(decay_start, total-max(1, round(args.decay_frac*total))))
            measured, save_every = seconds, max(1, int(args.save_minutes*60/seconds))
        if step % args.log_every == 0 or step == total:
            record = dict(step=step, lr=optimizer.param_groups[0]["lr"], loss=float(loss.detach().cpu()),
                          grad_norm=float(grad.detach().cpu()), plan=[total, decay_start],
                          hours=round((time.time()-begin)/3600, 4), step_seconds=measured,
                          **{k: float(v.cpu()) for k, v in parts.items()})
            if step % args.eval_every == 0 or step == total:
                record.update(evaluate(model, data, device, world, rank, args.precision == "bf16"))
            if master:
                log.write(json.dumps(record)+"\n")
                log.flush()
                print(json.dumps(record), flush=True)
        if save_every and (step-started) % save_every == 0:
            save_state(output/"last.pt", model, optimizer, step, [total, decay_start], args, stage_id)
        if step >= total or step == args.stop_at:
            break
    if step < total:
        save_state(output/"last.pt", model, optimizer, step, [total, decay_start], args, stage_id)
        if master:
            log.close()
        return
    if decay_start >= total:
        save_state(output/"stable.pt", model, optimizer, step, [total, decay_start], args, stage_id)
    save_state(output/"last.pt", model, optimizer, step, [total, decay_start], args, stage_id)
    final = evaluate(model, data, device, world, rank, args.precision == "bf16")
    if master:
        weights = {k: v.cpu() for k, v in model.state_dict().items()}
        torch.save(dict(model=weights, config=args.config, describe=describe(model), stage_id=stage_id, step=step,
                        device="tpu"), output/"release.pt")
        host = PhysiGPT(CONFIGS[args.config])
        host.load_state_dict(weights)
        summary = dict(stage_id=stage_id, steps=step, plan=[total, decay_start], hours=(time.time()-begin)/3600,
                       device="tpu", final=final, samples=release_samples(host, data, output, "cpu", args.sample_steps),
                       note="fit and sanity statistics only; realism is judged by the strict judge in a later round")
        save_json(output/"stage_summary.json", summary)
        log.close()


def smoke(root, config="base", steps=90):
    """Synthetic windows through the XLA path (compile, all-reduce, checkpoints, host sampling) before the real
    stage. Long enough to pass the step-time measurement. It proves the code runs on the TPU, nothing about the model."""
    root = Path(root)
    synthetic_shard(root/"shard")
    main(["--data", str(root/"shard"), "--output", str(root/"run"), "--config", config, "--steps", str(steps),
          "--log-every", "10", "--eval-every", "30", "--sample-steps", "4"])
    return json.loads((root/"run"/"stage_summary.json").read_text())


def versions():
    """Package versions only: touching the XLA runtime here would stop xmp.spawn (each core logs its device)."""
    import torch_xla
    return dict(torch=torch.__version__, torch_xla=torch_xla.__version__, pjrt_device=os.environ.get("PJRT_DEVICE"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", nargs="+", required=True, help="roots holding this stage's new shards")
    parser.add_argument("--replay", nargs="*", default=[], help="roots holding earlier shards")
    parser.add_argument("--replay-share", type=float, default=.25)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="base", choices=sorted(CONFIGS))
    parser.add_argument("--resume", default=None, help="stable.pt of the previous stage, or last.pt of this one")
    parser.add_argument("--epochs", type=float, default=4.)
    parser.add_argument("--steps", type=int, default=0, help="override the planned stage length")
    parser.add_argument("--batch", type=int, default=1024)
    parser.add_argument("--lr", type=float, default=6e-4)
    parser.add_argument("--warmup", type=int, default=1000)
    parser.add_argument("--decay-frac", type=float, default=.15)
    parser.add_argument("--weight-decay", type=float, default=.1)
    parser.add_argument("--clip", type=float, default=1.)
    parser.add_argument("--aux", type=float, default=.1, help="weight of the logit-Laplace NLL")
    parser.add_argument("--repeats", type=int, default=4, help="flow times per patch per step")
    parser.add_argument("--precision", default="bf16", choices=("bf16", "fp32"))
    parser.add_argument("--hours", type=float, default=8.3)
    parser.add_argument("--reserve-minutes", type=float, default=25.)
    parser.add_argument("--save-minutes", type=float, default=30.)
    parser.add_argument("--log-every", type=int, default=100)
    parser.add_argument("--eval-every", type=int, default=1000)
    parser.add_argument("--sample-steps", type=int, default=32)
    parser.add_argument("--stop-at", type=int, default=-1, help="end this run at that step, keeping the plan")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    import torch_xla.distributed.xla_multiprocessing as xmp
    xmp.spawn(worker, args=(args,))


if __name__ == "__main__":
    main()
