"""PPG-physiGPT pretraining on two T4s (DDP, fp16 autocast), in continual stages.

A stage trains on its new shards (mimic_wdb output) plus a replay share of the earlier shards, with a
warmup-stable-decay schedule (Hägele et al. 2024): the first stage warms up, every stage holds the peak learning rate
and ends with a short 1-sqrt decay to zero. stable.pt is the state right before the decay; the next stage starts from
it at the peak rate with no new warmup, so adding data never restarts training. release.pt is the decayed model a
stage hands to evaluation. last.pt (every --save-minutes) resumes the same stage after a kernel stops.
The batch of every step is a pure function of (seed, step), and so is the flow noise, so a resumed stage continues
exactly. The kernel time budget shortens a stage (measured step time) instead of cutting its decay; with --plateau,
a stage planned for many epochs over a small shard starts its decay once the held-out flow loss stops improving,
or, when that loss has risen above its best (overfitting, which a decay only deepens), ends at the best state.
best.pt is the state with the lowest held-out flow loss so far.
Validation is the held-out records of every mounted shard (fixed subset, fixed noise). Next-patch NLL and flow loss
measure fit only; best.pt and --plateau choose states on those records, so they are not a test set. Whether
samples are realistic is the strict judge's job in a later round, on people kept out of training and selection.
"""
import argparse
import contextlib
import functools
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import threading
import time

import numpy as np
import torch
import torch.distributed as dist

from ml.kaggle_lsm.train_lsm import FS, LENGTH, save_json
from ml.kaggle_physigpt.mimic_wdb import PROTOCOL, ShardWriter, rate_features
from ml.kaggle_physigpt.model import CONFIGS, PhysiGPT, describe

VALID_WINDOWS = 8192
SAMPLE_WINDOWS = 1024
# Step time is measured over steps MEASURE_FROM..MEASURE_FROM+MEASURE_STEPS (after compilation and allocator warmup),
# without the time rank 0 spends evaluating or saving.
MEASURE_FROM, MEASURE_STEPS = 10, 50
COMPILE_GAIN = .95   # --compile is kept only if the measured step is at least 5 % faster than eager


class Windows:
    """Memory-mapped windows of every shard found under the given roots, split by the shard's validation flag."""

    def __init__(self, roots):
        manifests = sorted({p for root in roots for p in Path(root).rglob("manifest.json")
                            if json.loads(p.read_text()).get("protocol") == PROTOCOL})
        if not manifests:
            raise FileNotFoundError(f"No {PROTOCOL} shard under {roots}")
        self.signal, self.shards, metas = [], [], []
        for path in manifests:
            manifest = json.loads(path.read_text())
            for chunk in manifest["chunks"]:
                self.signal.append(np.load(path.parent/f"{chunk['stem']}_signal.npy", mmap_mode="r"))
                metas.append(np.load(path.parent/f"{chunk['stem']}_meta.npy"))
            self.shards.append(dict(path=str(path.parent), record_range=manifest["record_range"],
                                    windows=manifest["windows"], chunks=[c["sha256"] for c in manifest["chunks"]]))
        spans = sorted(tuple(s["record_range"]) for s in self.shards if s["record_range"][0] < s["record_range"][1])
        for (a, b), (c, d) in zip(spans, spans[1:]):
            if c < b:   # the same record twice: duplicated windows, maybe on both sides of the held-out split
                raise ValueError(f"shards share records: record ranges [{a}, {b}) and [{c}, {d}) overlap")
        self.offsets = np.cumsum([0]+[len(s) for s in self.signal])
        valid = np.concatenate([m["valid"] for m in metas]).astype(bool)
        self.record = np.concatenate([m["record"] for m in metas])   # the person unit of the people-level split
        self.train, self.valid = np.flatnonzero(~valid), np.flatnonzero(valid)

    def rows(self, index):
        """uint16 [len(index), LENGTH] in the order of index."""
        index = np.asarray(index)
        out = np.empty((len(index), LENGTH), np.uint16)
        chunk = np.searchsorted(self.offsets, index, side="right")-1
        for c in np.unique(chunk):
            where = np.flatnonzero(chunk == c)
            local = index[where]-self.offsets[c]
            order = np.argsort(local)
            out[where[order]] = self.signal[c][local[order]]
        return out


@functools.lru_cache(maxsize=2)
def epoch_order(n, seed, epoch):
    """The permutation of one epoch; cached, because every step of the epoch slices the same one (a 5 M window
    permutation costs tens of milliseconds per step otherwise)."""
    order = np.random.default_rng([seed, epoch]).permutation(n)
    order.flags.writeable = False
    return order


def batch_index(new, replay, step, batch, replay_share, seed):
    """Global batch rows of `step`: an epoch-wise permutation of the new windows plus replay drawn with replacement."""
    n_replay = round(batch*replay_share) if len(replay) else 0
    n_new = batch-n_replay
    first, last = step*n_new, (step+1)*n_new
    parts = []
    for epoch in range(first//len(new), (last-1)//len(new)+1):
        perm = epoch_order(len(new), seed, epoch)
        lo, hi = max(first, epoch*len(new))-epoch*len(new), min(last, (epoch+1)*len(new))-epoch*len(new)
        parts.append(new[perm[lo:hi]])
    if n_replay:
        parts.append(replay[np.random.default_rng([seed, 1 << 20, step]).integers(len(replay), size=n_replay)])
    return np.concatenate(parts)


def lr_at(step, total, decay_start, peak, warmup):
    if step < warmup:
        return peak*(step+1)/warmup
    if step < decay_start:
        return peak
    return peak*(1-math.sqrt((step-decay_start)/max(1, total-decay_start)))


WARM_BLOCK = 1 << 26


def warm_cache(data):
    """Reads every signal chunk once, sequentially, into the page cache. A Kaggle input that is cold costs one slow
    page fault per random row (15.9 s/step measured against 0.36 s once warm), and the time budget sizes the stage
    from the step time of the first steps, so a cold start shrank a 10 h plan to one epoch. Returns the bytes read."""
    total = 0
    for signal in data.signal:
        with open(signal.filename, "rb") as f:
            while block := f.read(WARM_BLOCK):
                total += len(block)
    return total


def plan_steps(windows, epochs, batch, replay_share, decay_frac):
    total = max(1, math.ceil(epochs*windows/(batch-round(batch*replay_share))))
    return total, total-max(1, round(decay_frac*total))


def stage_identity(data, seed, config):
    """Same shards, seed and size give the same stage on any device, so last.pt resumes across devices."""
    return hashlib.sha256(json.dumps([s["chunks"] for s in data.shards]+[seed, config]).encode()).hexdigest()[:16]


def evaluate(model, data, device, amp):
    index = data.valid[np.linspace(0, len(data.valid)-1, min(VALID_WINDOWS, len(data.valid))).astype(int)]
    generator = torch.Generator(device).manual_seed(20261027)
    totals, count = dict(flow=0., laplace_nll=0.), 0
    model.eval()
    with torch.no_grad():
        for part in np.array_split(index, max(1, len(index)//512)):
            x = torch.from_numpy(data.rows(part).astype(np.float32)/65535).to(device)
            with torch.autocast("cuda", torch.float16, enabled=amp):
                _, parts = model(x, torch.zeros(len(x), dtype=torch.long, device=device), generator=generator)
            for k in totals:
                totals[k] += float(parts[k])*len(x)
            count += len(x)
    model.train()
    return {f"valid_{k}": v/max(count, 1) for k, v in totals.items()}


def release_samples(model, data, output, device, steps=32):
    x = model.generate(SAMPLE_WINDOWS, steps=steps, seed=0, device=device).float().cpu().numpy()
    real = data.rows(data.valid[:SAMPLE_WINDOWS]).astype(np.float32)/65535
    np.save(output/"release_samples.npy", x.astype(np.float16))
    stats = {}
    for name, w in (("generated", x), ("valid_real", real)):
        acf, rate = rate_features(w)
        stats[name] = dict(acf_peak_mean=float(acf.mean()), rate_bpm_quartiles=np.percentile(rate, [25, 50, 75]).tolist(),
                           diff_std=float(np.diff(w, axis=1).std()))
    return stats


def save_state(path, model, optimizer, scaler, step, plan, args, stage_id, **extra):
    tmp = Path(str(path)+".partial")
    torch.save(dict(model=model.state_dict(), optimizer=optimizer.state_dict(), scaler=scaler.state_dict(),
                    step=step, plan=plan, config=args.config, stage_id=stage_id, **extra), tmp)
    tmp.replace(path)


def worker(rank, world, args):
    cuda = torch.cuda.is_available() and not args.cpu
    if world > 1:
        dist.init_process_group("nccl" if cuda else "gloo", init_method=f"tcp://127.0.0.1:{args.port}", rank=rank,
                                world_size=world)
    device = torch.device(f"cuda:{rank}" if cuda else "cpu")
    if cuda:
        torch.cuda.set_device(device)
        torch.backends.cuda.matmul.allow_tf32 = True
    output = Path(args.output)
    begin = time.time()
    torch.manual_seed(args.seed)
    model = PhysiGPT(CONFIGS[args.config]).to(device)
    decay, no_decay = [], []
    for name, p in model.named_parameters():
        (decay if p.dim() == 2 and "start" not in name else no_decay).append(p)
    # fused: one CUDA kernel for the whole update instead of a few per parameter tensor
    optimizer = torch.optim.AdamW([dict(params=decay, weight_decay=args.weight_decay), dict(params=no_decay,
                                   weight_decay=0.)], lr=args.lr, betas=(.9, .95), eps=1e-8, fused=cuda or None)
    scaler = torch.amp.GradScaler("cuda", enabled=cuda)
    data = Windows(args.data+args.replay)
    if not len(data.valid):
        raise ValueError(f"no held-out windows under {args.data+args.replay}: too few records for the 2% split")
    stage_id = stage_identity(data, args.seed, args.config)
    # New rows are the train rows of the shards under --data; the rest of the union is the replay pool.
    new_paths = {s["path"] for s in Windows(args.data).shards}
    shard_of = np.repeat(np.arange(len(data.shards), dtype=np.int16).repeat([len(s["chunks"]) for s in data.shards]),
                         np.diff(data.offsets))
    is_new = np.isin(shard_of, [i for i, s in enumerate(data.shards) if s["path"] in new_paths])
    new_rows, replay_rows = data.train[is_new[data.train]], data.train[~is_new[data.train]]
    total, decay_start = plan_steps(len(new_rows), args.epochs, args.batch, args.replay_share if len(replay_rows) else 0,
                                    args.decay_frac)
    if args.steps:
        total, decay_start = args.steps, args.steps-max(1, round(args.decay_frac*args.steps))
    # A short stage (a small first shard) warms up over at most a tenth of its planned steps; the plan, not the
    # budget-shortened length, sets it, so a resumed stage gets the same warmup.
    step, warmup = 0, min(args.warmup, max(1, total//10))
    best_flow, best_step, best_path = math.inf, None, output/"best.pt"
    if args.resume:
        state = torch.load(args.resume, map_location=device, weights_only=False)
        if state["config"] != args.config:
            raise ValueError(f"checkpoint config {state['config']} != {args.config}")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        if state["scaler"]:   # a TPU (bf16) state has no gradient scaler; the T4 one then starts fresh
            scaler.load_state_dict(state["scaler"])
        if state["stage_id"] == stage_id:   # same stage after a stop: continue its step and plan
            step, (total, decay_start) = state["step"], state["plan"]
            kept = Path(args.resume).with_name("best.pt")   # and its best state so far
            if kept.exists():
                kept_state = torch.load(kept, map_location="cpu", weights_only=False)
                if kept_state["stage_id"] == stage_id:
                    best_flow, best_step, best_path = kept_state["valid_flow"], kept_state["step"], kept
                del kept_state
        if args.decay_steps:   # the decay a plateau stop skipped: the resumed state's own stage, from its step
            if state["stage_id"] != stage_id:
                raise ValueError(f"--decay-steps resumes its own stage {state['stage_id']}, not this data's {stage_id}")
            total, decay_start = step+args.hold_steps+args.decay_steps, step+args.hold_steps
        warmup = 0                          # a new stage from stable.pt stays at the peak rate
    if args.compile:
        # Per block, in place: the state_dict keys stay those of the eager model, and flow_loss's seeded noise
        # (a torch.Generator, which dynamo does not trace) stays outside the compiled graphs.
        for block in model.blocks:
            block.compile()
        model.flow.compile()
    net = (torch.nn.parallel.DistributedDataParallel(model, [rank] if cuda else None, gradient_as_bucket_view=True)
           if world > 1 else model)
    local = args.batch//world
    if args.batch % world:
        raise ValueError("batch must divide by the number of devices")
    if rank == 0:
        output.mkdir(parents=True, exist_ok=True)
        save_json(output/"run_config.json", dict(vars(args), stage_id=stage_id, world=world, model=describe(model),
                                                 new_windows=int(len(new_rows)), replay_windows=int(len(replay_rows)),
                                                 valid_windows=int(len(data.valid)), shards=data.shards,
                                                 plan=[total, decay_start], start_step=step))
    if rank == 0:
        warm = time.time()
        gigabytes = warm_cache(data)/2**30
        print(f"warm cache: {gigabytes:.2f} GB in {time.time()-warm:.0f} s", flush=True)
    if world > 1:
        dist.barrier()
    feed = queue.Queue(maxsize=4)

    def produce(first):
        # Gathering, scaling and pinning run here, off the training thread; a pinned batch copies to the GPU
        # asynchronously. The device is set first so that pinning does not open a context on cuda:0 from rank 1.
        if cuda:
            torch.cuda.set_device(device)
        for s in range(first, total):
            rows = batch_index(new_rows, replay_rows, s, args.batch, args.replay_share, args.seed)
            x = torch.from_numpy(data.rows(rows[rank*local:(rank+1)*local]).astype(np.float32)/65535)
            feed.put((s, x.pin_memory() if cuda else x))
        feed.put(None)

    threading.Thread(target=produce, args=(step,), daemon=True).start()
    last_save, log = time.time(), (output/"metrics.jsonl").open("a") if rank == 0 else None
    domain = torch.zeros(local, dtype=torch.long, device=device)
    measured, tick, paused, best, stale, first, rewind = None, None, 0., math.inf, 0, step, False
    while True:
        item = feed.get()
        if item is None:
            break
        s, x = item
        if s >= total:
            continue
        for group in optimizer.param_groups:
            group["lr"] = lr_at(s, total, decay_start, args.lr, warmup)
        x = x.to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        # --micro splits this rank's batch into gradient-accumulation chunks (one optimizer step per batch, so the
        # recipe's batch and rate stay). The first chunk's noise seed is the unsplit step's.
        chunks = x.split(args.micro) if args.micro else (x,)
        loss, parts = 0., {}
        for i, chunk in enumerate(chunks):
            generator = torch.Generator(device).manual_seed(args.seed*1_000_003+s*world+rank+i*(1 << 24))
            share = len(chunk)/len(x)
            with (net.no_sync() if world > 1 and i < len(chunks)-1 else contextlib.nullcontext()):
                with torch.autocast("cuda", torch.float16, enabled=cuda):
                    part_loss, part = net(chunk, domain[:len(chunk)], aux=args.aux, repeats=args.repeats,
                                          generator=generator, diff=args.diff_weight)
                scaler.scale(part_loss*share).backward()
            loss = loss+part_loss.detach()*share
            parts = {k: parts.get(k, 0.)+v*share for k, v in part.items()}
        scaler.unscale_(optimizer)
        grad = torch.nn.utils.clip_grad_norm_(model.parameters(), args.clip)
        scaler.step(optimizer)
        scaler.update()
        step = s+1
        if step-first in (MEASURE_FROM, MEASURE_FROM+MEASURE_STEPS) and measured is None:
            if cuda:
                torch.cuda.synchronize(device)
            if tick is None:
                tick, paused = time.time(), 0.
            else:
                # The time budget shortens the stage once, from the measured step time, keeping the decay share.
                seconds = (time.time()-tick-paused)/MEASURE_STEPS
                left = args.hours*3600-(time.time()-begin)-args.reserve_minutes*60
                fit = torch.tensor([step+int(left/seconds)], device=device)
                if world > 1:
                    dist.broadcast(fit, 0)
                if int(fit) < total:
                    total = max(step+1, int(fit))
                    decay_start = max(step, min(decay_start, total-max(1, round(args.decay_frac*total))))
                measured = seconds
        evaluating = step % args.eval_every == 0 or step == total
        if rank == 0 and (step % args.log_every == 0 or evaluating):
            held = time.time()
            record = dict(step=step, lr=optimizer.param_groups[0]["lr"], loss=float(loss.detach()),
                          grad_norm=float(grad), scale=float(scaler.get_scale()), plan=[total, decay_start],
                          hours=round((time.time()-begin)/3600, 4), step_seconds=measured,
                          **{k: float(v) for k, v in parts.items()})
            if evaluating:
                record.update(evaluate(model, data, device, cuda))
                if record["valid_flow"] < best_flow:
                    best_flow, best_step, best_path = record["valid_flow"], step, output/"best.pt"
                    save_state(best_path, model, optimizer, scaler, step, [total, decay_start], args, stage_id,
                               valid_flow=best_flow)
                if args.plateau and warmup <= step < decay_start:
                    # Stable phase until the held-out flow loss stops improving, then the decay. On a small shard
                    # this, not the time budget, ends the stage; a resumed stage restarts the patience count.
                    if record["valid_flow"] < best*(1-args.plateau_delta):
                        best, stale = record["valid_flow"], 0
                    else:
                        stale += 1
                    if stale >= args.plateau and record["valid_flow"] > best_flow*(1+args.plateau_delta):
                        # Held-out loss risen above its best while the train loss falls: overfitting, which the
                        # decay only deepens. The stage ends now and hands on best.pt instead.
                        total = decay_start = step
                        rewind = True
                        record.update(plateau="best", best_step=best_step, plan=[total, decay_start])
                    elif stale >= args.plateau:
                        total = min(total, step+max(1, round(step*args.decay_frac/(1-args.decay_frac))))
                        decay_start = step
                        record.update(plateau=True, plan=[total, decay_start])
            log.write(json.dumps(record)+"\n")
            log.flush()
            print(json.dumps(record), flush=True)
            paused += time.time()-held
        if args.plateau and evaluating and world > 1:
            plan = torch.tensor([total, decay_start], device=device)
            dist.broadcast(plan, 0)
            total, decay_start = (int(v) for v in plan)
        if step == decay_start and rank == 0 and not rewind:
            held = time.time()
            save_state(output/"stable.pt", model, optimizer, scaler, step, [total, decay_start], args, stage_id)
            paused += time.time()-held
        if rank == 0 and time.time()-last_save > args.save_minutes*60:
            held = time.time()
            save_state(output/"last.pt", model, optimizer, scaler, step, [total, decay_start], args, stage_id)
            last_save = time.time()
            paused += last_save-held
        if step >= total or step == args.stop_at:
            break
    if world > 1:
        dist.barrier()
    if step < total:   # stopped on request: keep the resumable state only
        if rank == 0:
            save_state(output/"last.pt", model, optimizer, scaler, step, [total, decay_start], args, stage_id)
            log.close()
        if world > 1:
            dist.destroy_process_group()
        return
    if rank == 0:
        if rewind:   # the stage's states and release are the best one, at the peak rate, not the last one
            state = torch.load(best_path, map_location=device, weights_only=False)
            model.load_state_dict(state["model"])
            optimizer.load_state_dict(state["optimizer"])
            if state["scaler"]:
                scaler.load_state_dict(state["scaler"])
            step = total = decay_start = state["step"]
        if decay_start >= total:   # a stage shortened past its decay start still leaves a stable state
            save_state(output/"stable.pt", model, optimizer, scaler, step, [total, decay_start], args, stage_id)
        save_state(output/"last.pt", model, optimizer, scaler, step, [total, decay_start], args, stage_id)
        torch.save(dict(model=model.state_dict(), config=args.config, describe=describe(model), stage_id=stage_id,
                        step=step), output/"release.pt")
        summary = dict(stage_id=stage_id, steps=step, plan=[total, decay_start], hours=(time.time()-begin)/3600,
                       step_seconds=measured, windows_per_second=measured and args.batch/measured,
                       max_memory_gb=torch.cuda.max_memory_allocated(device)/2**30 if cuda else None,
                       compile=args.compile, best=dict(step=best_step, valid_flow=best_flow), stopped_at_best=rewind,
                       final=evaluate(model, data, device, cuda),
                       samples=release_samples(model, data, output, device, args.sample_steps),
                       note="fit and sanity statistics only, on held-out records that also chose best.pt and the "
                            "plateau; realism is judged by the strict judge on separate people in a later round")
        save_json(output/"stage_summary.json", summary)
        log.close()
    if world > 1:
        dist.destroy_process_group()


def synthetic_shard(root, n=4096, seed=0):
    """Sine windows in the shard format, a sixteenth of them held out; for the device smoke run only."""
    rng = np.random.default_rng(seed)
    t = np.arange(LENGTH)/FS
    x = .5+.5*np.sin(2*np.pi*rng.uniform(.8, 2.5, (n, 1))*t+rng.uniform(0, 6, (n, 1)))
    writer = ShardWriter(root)
    for valid in (False, True):
        part = x[n//16:] if not valid else x[:n//16]
        writer.add(part, 3999999 if valid else 3000000, [("s", i) for i in range(len(part))], valid,
                   *rate_features(part))
    writer.flush()
    save_json(Path(root)/"manifest.json", dict(protocol=PROTOCOL, record_range=[0, 0], windows=n, synthetic=True,
                                               chunks=writer.chunks))


def smoke(root, config="base", steps=60, extra=()):
    """Minutes on synthetic windows through the real device path (DDP, fp16, stable/last/release, sampling) before
    a kernel spends hours fetching data. It proves the code runs on the GPUs, nothing about the model."""
    root = Path(root)
    if not (root/"shard"/"manifest.json").exists():
        synthetic_shard(root/"shard")
    run = f"run{'_'.join(['']+[a.strip('-') for a in extra])}"
    main(["--data", str(root/"shard"), "--output", str(root/run), "--config", config, "--steps", str(steps),
          "--log-every", "10", "--eval-every", "30", "--sample-steps", "4", "--port", "29519", *extra])
    return json.loads((root/run/"stage_summary.json").read_text())


def pick_compile(root, config="base", steps=MEASURE_FROM+MEASURE_STEPS, extra=()):
    """Smoke runs eager and with --compile on the kernel's own GPUs; --compile is used only if it ran and its
    measured step is COMPILE_GAIN faster. Whether inductor's kernels help on a T4 (sm_75) is measured, not assumed.
    extra goes to both runs (--micro: the large config does not fit a whole 512-window device batch on a T4)."""
    report = dict(eager=smoke(root, config, steps, list(extra)))
    try:
        report["compiled"] = smoke(root, config, steps, [*extra, "--compile"])
    except Exception as error:   # no Triton for this GPU, a dynamo failure...: train eager, and say why
        report["compiled"] = dict(error=f"{type(error).__name__}: {error}"[:500])
    eager, compiled = report["eager"]["step_seconds"], report["compiled"].get("step_seconds")
    report["use_compile"] = bool(eager and compiled and compiled < COMPILE_GAIN*eager)
    return report["use_compile"], report


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
    parser.add_argument("--micro", type=int, default=0,
                        help="gradient-accumulation chunk size per device (0: the whole per-device batch at once)")
    parser.add_argument("--lr", type=float, default=6e-4)
    parser.add_argument("--warmup", type=int, default=1000)
    parser.add_argument("--decay-frac", type=float, default=.15)
    parser.add_argument("--weight-decay", type=float, default=.1)
    parser.add_argument("--clip", type=float, default=1.)
    parser.add_argument("--aux", type=float, default=.1, help="weight of the logit-Laplace NLL")
    parser.add_argument("--repeats", type=int, default=4, help="flow times per patch per step")
    parser.add_argument("--hours", type=float, default=11.)
    parser.add_argument("--reserve-minutes", type=float, default=25.)
    parser.add_argument("--save-minutes", type=float, default=30.)
    parser.add_argument("--log-every", type=int, default=100)
    parser.add_argument("--eval-every", type=int, default=1000)
    parser.add_argument("--sample-steps", type=int, default=32)
    parser.add_argument("--stop-at", type=int, default=-1, help="end this run at that step, keeping the plan")
    parser.add_argument("--decay-steps", type=int, default=0,
                        help="with --resume of the same stage: continue it from the resumed step with this many "
                             "steps of the 1-sqrt decay to zero (the decay a plateau stop at best.pt left out)")
    parser.add_argument("--hold-steps", type=int, default=0,
                        help="with --decay-steps: first keep the peak rate for this many steps (more training)")
    parser.add_argument("--diff-weight", type=float, default=0.,
                        help="weight of the first/second difference error of the one-step estimate (0: off)")
    parser.add_argument("--plateau", type=int, default=0,
                        help="after this many evaluations without a better valid_flow, start the decay, or end at "
                             "best.pt if valid_flow has risen above its best (0: off)")
    parser.add_argument("--plateau-delta", type=float, default=.005, help="relative valid_flow gain that counts")
    parser.add_argument("--compile", action="store_true", help="torch.compile each block and the flow head")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--port", type=int, default=29517)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--cpu-world", type=int, default=1, help="CPU (gloo) processes; checks the DDP path")
    args = parser.parse_args(argv)
    world = args.cpu_world if args.cpu or not torch.cuda.is_available() else torch.cuda.device_count()
    if world > 1:
        torch.multiprocessing.spawn(worker, args=(world, args), nprocs=world, join=True)
    else:
        worker(0, 1, args)


if __name__ == "__main__":
    main()
