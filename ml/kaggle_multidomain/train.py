"""Run controlled data/architecture/loss ablations and benchmark AFTER selection."""
import argparse
import json
from pathlib import Path
import platform
import time

import numpy as np
import torch
from torch.nn import functional as F

from ml.kaggle_lsm.train_lsm import LENGTH, spectral_loss, prepare_discriminator_for_generator, save_json
from ml.kaggle_multidomain.data import balanced_indices, balanced_pool, digest, validate_pack
from ml.kaggle_multidomain.models import networks, diffusion_loss, distribution_loss
from ml.kaggle_multidomain.benchmark import Evaluator, sample, cpu_latency

ARMS = ("lsm_bidmc", "lsm_multi", "tcn_multi", "hybrid_multi", "diffusion_multi")


def train_one(arm, seed, pack, evaluator, output, steps, batch, interval, device):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    g, d = networks(arm)
    g.to(device)
    if d is not None:
        d.to(device)
    is_lsm, diffusion = arm.startswith("lsm"), d is None
    lr = 5e-4 if is_lsm else 2e-4
    optg = torch.optim.Adam(g.parameters(), lr=lr, betas=(.5, .999))
    optd = torch.optim.Adam(d.parameters(), lr=lr, betas=(.5, .999)) if d is not None else None
    run = output/f"{arm}_seed{seed}"
    run.mkdir()
    best, best_step, history = float("inf"), 0, []
    train_ids, weights = balanced_pool(pack, "train", ["bidmc"] if arm == "lsm_bidmc" else None)
    start = time.monotonic()
    for step in range(1, steps+1):
        g.train()
        ids = rng.choice(train_ids, batch, p=weights)
        real = torch.tensor(pack["signal"][ids, None], device=device)
        optg.zero_grad(set_to_none=True)
        ld, aux = real.new_zeros(()), real.new_zeros(())
        if diffusion:
            lg = diffusion_loss(g, real)
        else:
            d.train()
            for p in d.parameters():
                p.requires_grad_(True)
            fake = g(torch.randn(batch, LENGTH, device=device))
            optd.zero_grad(set_to_none=True)
            pr, pf = d(real), d(fake.detach())
            ld = (F.binary_cross_entropy(pr, torch.ones_like(pr))+F.binary_cross_entropy(pf, torch.zeros_like(pf))
                  if is_lsm else F.relu(1-pr).mean()+F.relu(1+pf).mean())
            ld.backward(); optd.step()
            prepare_discriminator_for_generator(d)
            pred = d(fake)
            lg = F.binary_cross_entropy(pred, torch.ones_like(pred)) if is_lsm else -pred.mean()
            if is_lsm:
                matching, consistency = spectral_loss(fake, real, pairing="all_pairs")
                aux = matching+consistency
            elif arm == "hybrid_multi":
                aux = distribution_loss(fake, real)
            lg = lg+aux
        if not torch.isfinite(lg+ld):
            raise RuntimeError(f"Nonfinite loss: {arm}, {seed}, {step}")
        lg.backward()
        torch.nn.utils.clip_grad_norm_(g.parameters(), 10, error_if_nonfinite=True)
        optg.step()
        if step == 1 or step % interval == 0 or step == steps:
            g.eval()
            generated = sample(g, seed+10000, device, evaluator.n, diffusion)
            value, per_domain = evaluator.validation(generated)
            row = dict(step=step, loss_g=float(lg.detach()), loss_d=float(ld.detach()),
                       auxiliary=float(aux.detach()), validation_score=value, per_domain=per_domain,
                       seconds=time.monotonic()-start)
            history.append(row)
            if value < best:
                best, best_step = value, step
                torch.save(dict(generator=g.state_dict(), arm=arm, seed=seed, step=step,
                                validation_score=value), run/"best.pt")
            save_json(run/"history.json", history)
            print(arm, seed, json.dumps(row), flush=True)
    torch.save(dict(generator=g.state_dict(), discriminator=d.state_dict() if d else None,
                    optimizer_g=optg.state_dict(), optimizer_d=optd.state_dict() if optd else None,
                    torch_rng=torch.get_rng_state(), cuda_rng=torch.cuda.get_rng_state_all() if device == "cuda" else [],
                    numpy_rng=rng.bit_generator.state, arm=arm, seed=seed, step=steps), run/"last_training_state.pt")
    return dict(arm=arm, seed=seed, best_step=best_step, validation_score=best,
                training_seconds=time.monotonic()-start, generator_parameters=sum(p.numel() for p in g.parameters()))


def load_input(root):
    matches = sorted(Path(root).rglob("windows.npz"))
    matches = [p for p in matches if (p.parent/"manifest.json").exists()
               and json.loads((p.parent/"manifest.json").read_text()).get("protocol") == "ppg_multidomain_v1"]
    if len(matches) != 1:
        raise ValueError(f"Expected one prepared multidomain pack, got {len(matches)}")
    path = matches[0]
    manifest = json.loads((path.parent/"manifest.json").read_text())
    if digest(path) != manifest["windows_sha256"]:
        raise ValueError("Prepared data checksum mismatch")
    with np.load(path, allow_pickle=False) as data:
        pack = {k: data[k] for k in data.files}
    validate_pack(pack)
    return pack, manifest


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--input-root", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--steps", type=int, default=2000)
    p.add_argument("--seeds", type=int, nargs="+", default=[42, 123, 2026])
    p.add_argument("--arms", choices=ARMS, nargs="+", default=list(ARMS))
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--interval", type=int, default=250)
    p.add_argument("--eval-samples", type=int, default=128)
    p.add_argument("--bootstrap", type=int, default=50)
    p.add_argument("--allow-cpu", action="store_true", help="Local smoke tests only")
    a = p.parse_args(argv)
    if min(a.steps, a.batch, a.interval, a.eval_samples) < 2 or a.bootstrap < 0:
        raise ValueError("Invalid experiment budget")
    if len(set(a.seeds)) != len(a.seeds) or len(set(a.arms)) != len(a.arms):
        raise ValueError("Duplicate seeds or arms")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu" and not a.allow_cpu:
        raise RuntimeError("GPU required for the research run; CPU only allowed for smoke checks")
    torch.set_num_threads(2)
    pack, manifest = load_input(a.input_root)
    expected_domains = {"bidmc", "perform_large", "perform_af", "perform_non_af"}
    for split in ("train", "validation", "test"):
        if set(pack["domain"][pack["split"] == split]) != expected_domains:
            raise ValueError(f"Missing or unexpected domains in {split}")
    if not a.allow_cpu and set(pack["domain"][pack["split"] == "external"]) != {"ptt_sit", "ptt_walk", "ptt_run"}:
        raise ValueError("Independent PTT domains are required for the full benchmark")
    output = Path(a.output); output.mkdir(parents=True, exist_ok=False)
    save_json(output/"data_manifest.json", manifest)
    evaluator = Evaluator(pack, a.eval_samples)
    configuration = dict(args=vars(a), device=device, python=platform.python_version(), torch=torch.__version__,
                         gpu=torch.cuda.get_device_name() if device == "cuda" else None,
                         selection="mean over validation domains of ACF + log-PSD + morphology RBF MMD2; no test selection",
                         bandwidths=evaluator.bandwidths, morphology_center=evaluator.center.tolist(),
                         morphology_scale=evaluator.scale.tolist(),
                         limitations=["Finite exploratory architecture search, not a globally best model claim",
                                      "Equal optimizer steps/batch; report wall time separately, not equal compute",
                                      "Unconditional mixture evaluated per domain; no controllable HR/AF/SpO2 claim",
                                      "Patient bootstrap is conditional on generated sample and fixed trained seed",
                                      "Independent PTT held out in full; no tuning after reading external scores",
                                      "Basic morphology descriptors and two-sample diagnostics are not clinical validation"])
    save_json(output/"configuration.json", configuration)
    selection = []
    for arm in a.arms:
        for seed in a.seeds:
            row = train_one(arm, seed, pack, evaluator, output, a.steps, a.batch, a.interval, device)
            selection.append(row)
            save_json(output/"selection_progress.json", selection)
    averages = {arm: float(np.mean([r["validation_score"] for r in selection if r["arm"] == arm])) for arm in a.arms}
    winner = min(averages, key=averages.get)
    save_json(output/"selection.json", dict(winner=winner, mean_validation=averages, runs=selection))
    results = []
    # Freeze all choices before evaluating any test or external domain.
    for row in selection:
        arm, seed = row["arm"], row["seed"]
        run = output/f"{arm}_seed{seed}"
        g, _ = networks(arm)
        ckpt = torch.load(run/"best.pt", map_location="cpu", weights_only=True)
        g.load_state_dict(ckpt["generator"]); g.to(device).eval()
        generated = sample(g, seed+20000, device, a.eval_samples, arm == "diffusion_multi")
        metrics = dict(**row, test=evaluator.evaluate(generated, "test", a.bootstrap),
                       external=evaluator.evaluate(generated, "external", a.bootstrap),
                       diagnostics=evaluator.diagnostics(generated), latency=cpu_latency(g, arm == "diffusion_multi"))
        if arm != "diffusion_multi":
            with torch.no_grad():
                example = torch.randn(2, LENGTH)
                traced = torch.jit.trace(g, example)
                torch.testing.assert_close(traced(example[:1]), g(example[:1]))
                traced.save(str(run/"generator_cpu.ts"))
        np.savez_compressed(run/"samples.npz", generated=generated)
        save_json(run/"metrics.json", metrics)
        results.append(metrics)
        save_json(output/"results.json", dict(winner_by_validation=winner, models=results))
    controls = {}
    replay = pack["signal"][balanced_indices(pack, "train", np.random.default_rng(2109), a.eval_samples)]
    controls["balanced_train_replay"] = dict(test=evaluator.evaluate(replay, "test", a.bootstrap),
                                            external=evaluator.evaluate(replay, "external", a.bootstrap))
    old = sorted(Path(a.input_root).rglob("lsm_repo_corrected/generator_cpu.ts"))
    if len(old) == 1:
        model = torch.jit.load(str(old[0]), map_location=device).eval()
        generated = sample(model, 20042, device, a.eval_samples)
        controls["frozen_previous_lsm"] = dict(artifact_sha256=digest(old[0]),
                                              test=evaluator.evaluate(generated, "test", a.bootstrap),
                                              external=evaluator.evaluate(generated, "external", a.bootstrap))
    else:
        controls["frozen_previous_lsm"] = {"status": "not_available", "matches": len(old)}
    save_json(output/"controls.json", controls)
    from ml.kaggle_multidomain.report import report
    report(output)
    save_json(output/"COMPLETE.json", dict(status="complete", winner_by_validation=winner,
                                          trained_runs=len(results), data_sha256=manifest["windows_sha256"],
                                          deployment="research_only_not_connected_to_DAC"))
    print("COMPLETE", winner, flush=True)


if __name__ == "__main__":
    main()
