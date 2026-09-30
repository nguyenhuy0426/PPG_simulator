"""Conditional PPG architecture sweep on frozen BIDMC pulse splits.

This is an engineering comparison, not a clinical model.  The test split is
never used for checkpoint or architecture selection.  No hardware I/O occurs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import time
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks
from scipy.spatial.distance import cdist

POINTS = 256
LATENT_DIM = 32
N_CONDITIONS = 7
PREPARED_SHA256 = "25c830dc1613a0dbf9c3775fc87b95b966492fc0962a828c84543422fa278dcf"
CONDITION_NAMES = ["hr_div_200", "sp_phase", "dn_phase", "dp_phase",
                   "dn_over_sp", "dp_over_sp", "has_notch"]
ARCHITECTURES = (
    "upsample_projection",
    "resnet_film_projection",
    "tcn_film_projection",
    "multiscale_film_projection",
    "resnet_film_concat",
)


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def measure(pulse):
    """Measure project-defined SP, resolvable DN and DP on one normalized pulse."""
    y = np.asarray(pulse, dtype=float)
    if y.ndim != 1 or len(y) < 16 or not np.isfinite(y).all() or np.ptp(y) < 1e-8:
        raise ValueError("Pulse must be finite, one-dimensional and non-flat")
    y = (y-y.min())/np.ptp(y)
    sp, n = int(y.argmax()), len(y)-1
    result = dict(sp_phase=sp/n, dn_phase=None, dp_phase=None,
                  dn_level=None, dp_level=None, has_notch=False)
    peaks, _ = find_peaks(y, prominence=.02, distance=max(1, round(.03*n)))
    for dp in peaks:
        if not sp+.06*n < dp < .90*n:
            continue
        dn = sp+int(np.argmin(y[sp:dp+1]))
        if sp < dn < dp and y[dp]-y[dn] >= .02:
            result.update(dn_phase=dn/n, dp_phase=int(dp)/n,
                          dn_level=float(y[dn]), dp_level=float(y[dp]), has_notch=True)
            break
    return result


def measured_conditions(samples, requested):
    rows = []
    for y, c in zip(samples, requested):
        m = measure(y)
        rows.append([c[0], m["sp_phase"], m["dn_phase"] or 0,
                     m["dp_phase"] or 0, m["dn_level"] or 0,
                     m["dp_level"] or 0, float(m["has_notch"])])
    return np.asarray(rows, np.float32)


def log_spectrum(samples):
    window = np.hanning(POINTS)[None]
    power = np.abs(np.fft.rfft(samples*window, axis=1))[:, 1:]**2
    power /= np.maximum(power.sum(1, keepdims=True), 1e-12)
    return np.log(np.maximum(power, 1e-8))


def morphology_metrics(samples, requested, reference, train_bank):
    observed = measured_conditions(samples, requested)
    target_notch = requested[:, -1] > .5
    found_notch = observed[:, -1] > .5
    positive = target_notch
    negative = ~target_notch
    sensitivity = float(found_notch[positive].mean()) if positive.any() else None
    specificity = float((~found_notch[negative]).mean()) if negative.any() else None
    balanced_accuracy = float((sensitivity+specificity)/2)
    matched = positive & found_notch
    sp_mae = float(np.abs(observed[:, 1]-requested[:, 1]).mean())
    penalized = {}
    for index, name in ((2, "dn_phase"), (3, "dp_phase"),
                        (4, "dn_level"), (5, "dp_level")):
        error = np.ones(positive.sum(), dtype=float)
        error[found_notch[positive]] = np.abs(observed[matched, index]-requested[matched, index])
        penalized[name] = float(error.mean()) if len(error) else None
    score = (sp_mae + .5*(1-balanced_accuracy) +
             .25*penalized["dn_phase"] + .25*penalized["dp_phase"] +
             .1*penalized["dn_level"] + .1*penalized["dp_level"])
    spectrum_rmse = float(np.sqrt(np.mean((log_spectrum(samples).mean(0)-
                                           log_spectrum(reference).mean(0))**2)))
    nearest = np.sqrt(cdist(samples, train_bank, metric="sqeuclidean").min(1)/POINTS)
    return dict(primary_morphology_score=float(score), sp_phase_mae=sp_mae,
                notch_sensitivity=sensitivity, notch_specificity=specificity,
                notch_balanced_accuracy=balanced_accuracy,
                matched_notch_count=int(matched.sum()), requested_notch_count=int(positive.sum()),
                penalized_feature_mae=penalized,
                mean_log_spectrum_rmse=spectrum_rmse,
                paired_waveform_rmse=float(np.sqrt(np.mean((samples-reference)**2))),
                mean_pointwise_std=float(samples.std(0).mean()),
                mean_abs_second_difference=float(np.abs(np.diff(samples, n=2, axis=1)).mean()),
                nearest_train_rmse_median=float(np.median(nearest)),
                selection_score=float(score+.1*spectrum_rmse))


def stratified_indices(mask, conditions, maximum_per_class=512, seed=991):
    rng = np.random.default_rng(seed)
    valid = np.flatnonzero(mask)
    pos = valid[conditions[valid, -1] > .5]
    neg = valid[conditions[valid, -1] <= .5]
    if not len(pos) or not len(neg):
        raise ValueError("Both notch classes are required in each evaluation split")
    pos = rng.choice(pos, min(maximum_per_class, len(pos)), replace=False)
    neg = rng.choice(neg, min(maximum_per_class, len(neg)), replace=False)
    return np.concatenate((pos, neg))


def load_prepared(path):
    path = Path(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != PREPARED_SHA256:
        raise ValueError("Frozen prepared.npz checksum mismatch")
    data = np.load(path, allow_pickle=False)
    required = {"pulse", "condition", "subject", "train", "validation", "test"}
    if not required.issubset(data.files):
        raise ValueError("Prepared data is incomplete")
    x, c = data["pulse"].astype(np.float32), data["condition"].astype(np.float32)
    masks = {name: data[name].astype(bool) for name in ("train", "validation", "test")}
    if x.shape[1:] != (POINTS,) or c.shape != (len(x), N_CONDITIONS):
        raise ValueError("Unexpected pulse or condition shape")
    groups = [set(data["subject"][m].tolist()) for m in masks.values()]
    if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
        raise ValueError("Subject leakage across frozen splits")
    return x, c, masks


def torch_components():
    import torch
    from torch import nn
    return torch, nn


class PulseOutputMixin:
    def _finish(self, logits):
        import torch
        y = torch.sigmoid(logits).squeeze(1)*self.edge
        return y/y.amax(1, keepdim=True).clamp_min(1e-6)

    def _make_edge(self):
        import torch
        edge = torch.clamp(torch.minimum(torch.linspace(0, 1, POINTS),
                                         torch.linspace(1, 0, POINTS))/.03, max=1)
        self.register_buffer("edge", edge**2*(3-2*edge))


def network_classes():
    import torch
    from torch import nn
    import torch.nn.functional as functional

    class FiLM(nn.Module):
        def __init__(self, channels):
            super().__init__()
            self.affine = nn.Sequential(nn.Linear(N_CONDITIONS, 64), nn.SiLU(),
                                        nn.Linear(64, 2*channels))
            nn.init.zeros_(self.affine[-1].weight)
            nn.init.zeros_(self.affine[-1].bias)

        def forward(self, x, c):
            scale, shift = self.affine(c).chunk(2, 1)
            return x*(1+scale.unsqueeze(2))+shift.unsqueeze(2)

    class UpBlock(nn.Module):
        def __init__(self, in_channels, out_channels):
            super().__init__()
            self.conv1 = nn.Conv1d(in_channels, out_channels, 5, padding=2)
            self.conv2 = nn.Conv1d(out_channels, out_channels, 5, padding=2)
            self.skip = nn.Conv1d(in_channels, out_channels, 1)
            self.norm1 = nn.GroupNorm(8, out_channels)
            self.norm2 = nn.GroupNorm(8, out_channels)
            self.film1, self.film2 = FiLM(out_channels), FiLM(out_channels)

        def forward(self, x, c):
            x = functional.interpolate(x, scale_factor=2, mode="linear", align_corners=False)
            skip = self.skip(x)
            x = functional.silu(self.film1(self.norm1(self.conv1(x)), c))
            x = self.film2(self.norm2(self.conv2(x)), c)
            return functional.silu((x+skip)/math.sqrt(2))

    class UpsampleGenerator(nn.Module, PulseOutputMixin):
        def __init__(self):
            super().__init__()
            self.fc = nn.Sequential(nn.Linear(LATENT_DIM+N_CONDITIONS, 256), nn.LeakyReLU(.2),
                                    nn.Linear(256, 32*32), nn.LeakyReLU(.2))
            self.conv = nn.Sequential(
                nn.Upsample(scale_factor=2, mode="linear", align_corners=False),
                nn.Conv1d(32, 32, 7, padding=3), nn.LeakyReLU(.2),
                nn.Upsample(scale_factor=2, mode="linear", align_corners=False),
                nn.Conv1d(32, 16, 7, padding=3), nn.LeakyReLU(.2),
                nn.Upsample(scale_factor=2, mode="linear", align_corners=False),
                nn.Conv1d(16, 1, 7, padding=3))
            self._make_edge()

        def forward(self, z, c):
            x = self.fc(torch.cat((z, c), 1)).reshape(-1, 32, 32)
            return self._finish(self.conv(x))

    class ResNetFiLMGenerator(nn.Module, PulseOutputMixin):
        def __init__(self):
            super().__init__()
            self.fc = nn.Linear(LATENT_DIM+N_CONDITIONS, 128*32)
            self.blocks = nn.ModuleList((UpBlock(128, 128), UpBlock(128, 96), UpBlock(96, 64)))
            self.out = nn.Conv1d(64, 1, 7, padding=3)
            self._make_edge()

        def forward(self, z, c):
            x = self.fc(torch.cat((z, c), 1)).reshape(-1, 128, 32)
            for block in self.blocks:
                x = block(x, c)
            return self._finish(self.out(x))

    class TCNBlock(nn.Module):
        def __init__(self, channels, dilation):
            super().__init__()
            self.conv1 = nn.Conv1d(channels, channels, 3, padding=dilation, dilation=dilation)
            self.conv2 = nn.Conv1d(channels, channels, 3, padding=dilation, dilation=dilation)
            self.norm1 = nn.GroupNorm(8, channels)
            self.norm2 = nn.GroupNorm(8, channels)
            self.film1, self.film2 = FiLM(channels), FiLM(channels)

        def forward(self, x, c):
            residual = x
            x = functional.silu(self.film1(self.norm1(self.conv1(x)), c))
            x = self.film2(self.norm2(self.conv2(x)), c)
            return functional.silu((x+residual)/math.sqrt(2))

    class TCNFiLMGenerator(nn.Module, PulseOutputMixin):
        def __init__(self):
            super().__init__()
            self.fc = nn.Linear(LATENT_DIM+N_CONDITIONS, 64*POINTS)
            self.blocks = nn.ModuleList(TCNBlock(64, d) for d in (1, 2, 4, 8, 16, 32))
            self.out = nn.Conv1d(64, 1, 7, padding=3)
            self._make_edge()

        def forward(self, z, c):
            x = self.fc(torch.cat((z, c), 1)).reshape(-1, 64, POINTS)
            for block in self.blocks:
                x = block(x, c)
            return self._finish(self.out(x))

    class MultiScaleBlock(nn.Module):
        def __init__(self, channels):
            super().__init__()
            self.branches = nn.ModuleList(nn.Conv1d(channels, channels//4, kernel,
                                                     padding=kernel//2)
                                          for kernel in (3, 9, 21, 41))
            self.merge = nn.Conv1d(channels, channels, 1)
            self.norm = nn.GroupNorm(8, channels)
            self.film = FiLM(channels)

        def forward(self, x, c):
            update = self.merge(torch.cat([branch(x) for branch in self.branches], 1))
            update = self.film(self.norm(update), c)
            return functional.silu((x+update)/math.sqrt(2))

    class MultiScaleFiLMGenerator(nn.Module, PulseOutputMixin):
        def __init__(self):
            super().__init__()
            self.fc = nn.Linear(LATENT_DIM+N_CONDITIONS, 64*POINTS)
            self.blocks = nn.ModuleList(MultiScaleBlock(64) for _ in range(4))
            self.out = nn.Conv1d(64, 1, 7, padding=3)
            self._make_edge()

        def forward(self, z, c):
            x = self.fc(torch.cat((z, c), 1)).reshape(-1, 64, POINTS)
            for block in self.blocks:
                x = block(x, c)
            return self._finish(self.out(x))

    class CriticBackbone(nn.Module):
        def __init__(self):
            super().__init__()
            layers, channels = [], (1, 32, 64, 128, 128)
            for left, right in zip(channels[:-1], channels[1:]):
                layers.extend((nn.Conv1d(left, right, 7, 2, 3), nn.LeakyReLU(.2)))
            self.net = nn.Sequential(*layers)

        def forward(self, x):
            return self.net(x.unsqueeze(1)).mean(2)

    class ProjectionCritic(nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone = CriticBackbone()
            self.base = nn.Linear(128, 1)
            self.embedding = nn.Sequential(nn.Linear(N_CONDITIONS, 128), nn.LeakyReLU(.2),
                                           nn.Linear(128, 128))
            self.aux = nn.Linear(128, N_CONDITIONS)

        def forward(self, x, c):
            h = self.backbone(x)
            score = self.base(h).squeeze(1)+(h*self.embedding(c)).sum(1)/math.sqrt(128)
            return score, self.aux(h)

    class ConcatCritic(nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone = CriticBackbone()
            self.score = nn.Sequential(nn.Linear(128+N_CONDITIONS, 128), nn.LeakyReLU(.2),
                                       nn.Linear(128, 1))
            self.aux = nn.Linear(128, N_CONDITIONS)

        def forward(self, x, c):
            h = self.backbone(x)
            return self.score(torch.cat((h, c), 1)).squeeze(1), self.aux(h)

    return dict(upsample=UpsampleGenerator, resnet_film=ResNetFiLMGenerator,
                tcn_film=TCNFiLMGenerator, multiscale_film=MultiScaleFiLMGenerator,
                projection=ProjectionCritic, concat=ConcatCritic)


def make_networks(name):
    if name not in ARCHITECTURES:
        raise ValueError(f"Unknown architecture {name}")
    classes = network_classes()
    generator_name, critic_name = name.rsplit("_", 1)
    return classes[generator_name](), classes[critic_name]()


def interpolate_phase(y, phase):
    import torch
    position = phase*(POINTS-1)
    left = position.floor().long().clamp(0, POINTS-2)
    fraction = position-left
    return y.gather(1, left[:, None]).squeeze(1)*(1-fraction) + \
        y.gather(1, (left+1)[:, None]).squeeze(1)*fraction


def morphology_loss(y, c):
    import torch
    sp = interpolate_phase(y, c[:, 1])
    dn = interpolate_phase(y, c[:, 2])
    dp = interpolate_phase(y, c[:, 3])
    offset = 4/(POINTS-1)
    sp_neighbors = .5*(interpolate_phase(y, (c[:, 1]-offset).clamp(0, 1))+
                        interpolate_phase(y, (c[:, 1]+offset).clamp(0, 1)))
    dn_neighbors = .5*(interpolate_phase(y, (c[:, 2]-offset).clamp(0, 1))+
                        interpolate_phase(y, (c[:, 2]+offset).clamp(0, 1)))
    dp_neighbors = .5*(interpolate_phase(y, (c[:, 3]-offset).clamp(0, 1))+
                        interpolate_phase(y, (c[:, 3]+offset).clamp(0, 1)))
    present = c[:, -1]
    peak = ((sp-1)**2 + torch.relu(.03-(sp-sp_neighbors))**2).mean()
    notch = (present*((dn-c[:, 4])**2+(dp-c[:, 5])**2 +
                      4*torch.relu(.015-(dn_neighbors-dn))**2+
                      4*torch.relu(.015-(dp-dp_neighbors))**2+
                      4*torch.relu(.02-(dp-dn))**2)).sum()/present.sum().clamp_min(1)
    phase = torch.linspace(0, 1, POINTS, device=y.device)
    soft_sp = (torch.softmax(50*y, 1)*phase).sum(1)
    return peak+notch+((soft_sp-c[:, 1])**2).mean()


def spectral_loss(fake, real):
    import torch
    window = torch.hann_window(POINTS, periodic=False, device=fake.device)
    def spectrum(value):
        power = torch.fft.rfft(value*window, dim=1).abs()[:, 1:].square()
        power = power/power.sum(1, keepdim=True).clamp_min(1e-8)
        return power.clamp_min(1e-8).log()
    return (spectrum(fake)-spectrum(real)).abs().mean()


def derivative_loss(fake, real):
    first_fake, first_real = torch_diff(fake), torch_diff(real)
    second_fake, second_real = torch_diff(first_fake), torch_diff(first_real)
    return ((first_fake.abs().mean(1)-first_real.abs().mean(1))**2).mean() + \
        ((second_fake.abs().mean(1)-second_real.abs().mean(1))**2).mean()


def torch_diff(value):
    return value[:, 1:]-value[:, :-1]


def auxiliary_loss(prediction, condition):
    import torch.nn.functional as functional
    return functional.mse_loss(prediction[:, :6], condition[:, :6]) + \
        functional.binary_cross_entropy_with_logits(prediction[:, 6], condition[:, 6])


def gradient_penalty(critic, real, fake, condition, generator):
    import torch
    alpha = torch.rand(len(real), 1, device=real.device, generator=generator)
    mixed = (alpha*real+(1-alpha)*fake).requires_grad_(True)
    score, _ = critic(mixed, condition)
    gradient = torch.autograd.grad(score.sum(), mixed, create_graph=True)[0]
    return ((gradient.norm(2, dim=1)-1)**2).mean()


def balanced_batch(positive, negative, batch, generator):
    import torch
    half = batch//2
    left = positive[torch.randint(len(positive), (half,), device=positive.device,
                                  generator=generator)]
    right = negative[torch.randint(len(negative), (batch-half,), device=negative.device,
                                   generator=generator)]
    return torch.cat((left, right))


def infer(generator, conditions, noise, device, batch=512):
    import torch
    result = []
    generator.eval()
    with torch.inference_mode():
        for start in range(0, len(conditions), batch):
            stop = start+batch
            result.append(generator(torch.tensor(noise[start:stop], device=device),
                                    torch.tensor(conditions[start:stop], device=device)).cpu().numpy())
    return np.concatenate(result)


def train_run(name, seed, x, c, masks, eval_indices, output, args):
    import torch
    torch.manual_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if args.require_gpu and device.type != "cuda":
        raise RuntimeError("Kaggle sweep requires GPU")
    generator, critic = make_networks(name)
    generator, critic = generator.to(device), critic.to(device)
    opt_g = torch.optim.Adam(generator.parameters(), lr=args.lr, betas=(0., .9))
    opt_d = torch.optim.Adam(critic.parameters(), lr=args.lr, betas=(0., .9))
    tx = torch.tensor(x[masks["train"]], device=device)
    tc = torch.tensor(c[masks["train"]], device=device)
    positive = torch.nonzero(tc[:, -1] > .5, as_tuple=False).flatten()
    negative = torch.nonzero(tc[:, -1] <= .5, as_tuple=False).flatten()
    data_rng = torch.Generator(device=device).manual_seed(seed+1000)
    noise_rng = torch.Generator(device=device).manual_seed(seed+2000)
    gp_rng = torch.Generator(device=device).manual_seed(seed+3000)
    val_idx = eval_indices["validation"]
    val_c, val_real = c[val_idx], x[val_idx]
    eval_rng = np.random.default_rng(7000+seed)
    val_noise = eval_rng.standard_normal((len(val_idx), LATENT_DIM)).astype(np.float32)
    train_bank = x[masks["train"]][np.random.default_rng(123).choice(
        masks["train"].sum(), min(2048, masks["train"].sum()), replace=False)]
    folder = output/name/f"seed_{seed}"
    folder.mkdir(parents=True, exist_ok=False)
    history, best, started = [], float("inf"), time.monotonic()
    for step in range(1, args.steps+1):
        for _ in range(args.ncritic):
            idx = balanced_batch(positive, negative, args.batch, data_rng)
            real, condition = tx[idx], tc[idx]
            wrong_condition = torch.cat((condition[len(condition)//2:], condition[:len(condition)//2]))
            with torch.no_grad():
                fake = generator(torch.randn(args.batch, LATENT_DIM, device=device,
                                             generator=noise_rng), condition)
            opt_d.zero_grad(set_to_none=True)
            real_score, real_aux = critic(real, condition)
            fake_score, _ = critic(fake, condition)
            wrong_score, _ = critic(real, wrong_condition)
            gp = gradient_penalty(critic, real, fake, condition, gp_rng)
            loss_d = .5*(fake_score.mean()+wrong_score.mean())-real_score.mean() + \
                args.gp_weight*gp + args.aux_d_weight*auxiliary_loss(real_aux, condition)
            loss_d.backward()
            opt_d.step()
        for parameter in critic.parameters():
            parameter.requires_grad_(False)
        opt_g.zero_grad(set_to_none=True)
        fake = generator(torch.randn(args.batch, LATENT_DIM, device=device,
                                     generator=noise_rng), condition)
        fake_score, fake_aux = critic(fake, condition)
        lm = morphology_loss(fake, condition)
        spec = spectral_loss(fake, real)
        derivative = derivative_loss(fake, real)
        boundary = (fake[:, 1].square()+fake[:, -2].square()).mean()
        loss_g = (-fake_score.mean() + args.aux_g_weight*auxiliary_loss(fake_aux, condition) +
                  args.morphology_weight*lm + args.spectral_weight*spec +
                  args.derivative_weight*derivative + args.boundary_weight*boundary)
        loss_g.backward()
        opt_g.step()
        for parameter in critic.parameters():
            parameter.requires_grad_(True)
        if step == 1 or step % args.evaluate_every == 0 or step == args.steps:
            generated = infer(generator, val_c, val_noise, device)
            metrics = morphology_metrics(generated, val_c, val_real, train_bank)
            row = dict(step=step, validation=metrics, critic_loss=float(loss_d.detach()),
                       generator_loss=float(loss_g.detach()), gp=float(gp.detach()),
                       morphology_loss=float(lm.detach()), spectral_loss=float(spec.detach()),
                       elapsed_seconds=time.monotonic()-started)
            history.append(row)
            print(json.dumps(dict(architecture=name, seed=seed, **row)), flush=True)
            if metrics["selection_score"] < best:
                best = metrics["selection_score"]
                torch.save(dict(generator=generator.state_dict(), discriminator=critic.state_dict(),
                                architecture=name, seed=seed, step=step,
                                validation=metrics, args=vars(args)), folder/"best.pt")
            save_json(folder/"history.json", history)
            generator.train()
    checkpoint = torch.load(folder/"best.pt", map_location=device, weights_only=True)
    generator.load_state_dict(checkpoint["generator"])
    critic.load_state_dict(checkpoint["discriminator"])
    test_idx = eval_indices["test"]
    test_c, test_real = c[test_idx], x[test_idx]
    test_noise = np.random.default_rng(9000+seed).standard_normal(
        (len(test_idx), LATENT_DIM)).astype(np.float32)
    generated = infer(generator, test_c, test_noise, device)
    fixed_c = np.repeat(test_c[:1], 64, 0)
    variations = infer(generator, fixed_c, np.random.default_rng(11000+seed).standard_normal(
        (64, LATENT_DIM)).astype(np.float32), device)
    test_metrics = morphology_metrics(generated, test_c, test_real, train_bank)
    test_metrics["fixed_condition_diversity"] = float(variations.std(0).mean())
    result = dict(architecture=name, seed=seed, best_step=checkpoint["step"],
                  validation=checkpoint["validation"], test=test_metrics,
                  generator_parameters=sum(p.numel() for p in generator.parameters()),
                  critic_parameters=sum(p.numel() for p in critic.parameters()),
                  seconds=time.monotonic()-started)
    save_json(folder/"result.json", result)
    np.savez_compressed(folder/"samples.npz", generated=generated, real=test_real,
                        condition=test_c, indices=test_idx, variations=variations)
    generator, critic = generator.cpu().eval(), critic.cpu().eval()
    example_z, example_c = torch.randn(2, LATENT_DIM), torch.tensor(test_c[:2])
    example_x = torch.tensor(generated[:2])
    traced_g = torch.jit.trace(generator, (example_z, example_c))
    traced_d = torch.jit.trace(critic, (example_x, example_c))
    with torch.inference_mode():
        torch.testing.assert_close(traced_g(example_z, example_c), generator(example_z, example_c))
        eager_d = critic(example_x, example_c)
        trace_d = traced_d(example_x, example_c)
        for actual, expected in zip(trace_d, eager_d):
            torch.testing.assert_close(actual, expected)
    traced_g.save(str(folder/"generator_cpu.ts"))
    traced_d.save(str(folder/"critic_cpu.ts"))
    return result


def aggregate(results):
    report = {}
    names = tuple(dict.fromkeys(row["architecture"] for row in results))
    for name in names:
        rows = [row for row in results if row["architecture"] == name]
        keys = ("selection_score", "primary_morphology_score", "sp_phase_mae",
                "notch_sensitivity", "notch_specificity", "mean_log_spectrum_rmse",
                "paired_waveform_rmse", "fixed_condition_diversity")
        entry = dict(seeds=[row["seed"] for row in rows], runs=len(rows),
                     generator_parameters=rows[0]["generator_parameters"],
                     critic_parameters=rows[0]["critic_parameters"],
                     validation_selection_median=float(np.median(
                         [row["validation"]["selection_score"] for row in rows])))
        entry["test_mean"] = {key: float(np.mean([row["test"][key] for row in rows]))
                              for key in keys}
        entry["test_std"] = {key: float(np.std([row["test"][key] for row in rows], ddof=1))
                             if len(rows) > 1 else 0. for key in keys}
        report[name] = entry
    winner = min(report, key=lambda key: report[key]["validation_selection_median"])
    return report, winner


def plot_comparison(output, results, winner):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = tuple(dict.fromkeys(row["architecture"] for row in results))
    representative = {}
    for name in names:
        rows = [row for row in results if row["architecture"] == name]
        row = min(rows, key=lambda item: item["validation"]["selection_score"])
        representative[name] = row
    fig, axes = plt.subplots(len(names), 2, figsize=(12, 3*len(names)), squeeze=False)
    for row_index, name in enumerate(names):
        row = representative[name]
        folder = output/name/f"seed_{row['seed']}"
        samples = np.load(folder/"samples.npz", allow_pickle=False)
        condition = samples["condition"]
        positive = int(np.flatnonzero(condition[:, -1] > .5)[0])
        negative = int(np.flatnonzero(condition[:, -1] <= .5)[0])
        for column, index in enumerate((positive, negative)):
            ax = axes[row_index, column]
            ax.plot(samples["real"][index], color="black", label="held-out real")
            ax.plot(samples["generated"][index], color="#0072B2", label="generated")
            ax.set_title(f"{name}{' [winner]' if name == winner else ''} | "
                         f"requested notch={int(condition[index, -1])}")
            if row_index == 0:
                ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output/"architecture_comparison.png", dpi=150)
    plt.close(fig)


def locate_prepared(argument):
    if argument:
        return Path(argument)
    if Path("/kaggle/input").is_dir():
        matches = list(Path("/kaggle/input").rglob("prepared.npz"))
        if len(matches) != 1:
            raise FileNotFoundError(f"Expected one mounted prepared.npz, found {len(matches)}")
        return matches[0]
    return Path("ml/runs/kaggle-v1/ppg_run/prepared.npz")


def main():
    kaggle = Path("/kaggle/working").is_dir()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared")
    parser.add_argument("--output", default="/kaggle/working/architecture_sweep" if kaggle
                        else "ml/runs/architecture-local")
    parser.add_argument("--architectures", nargs="+", choices=ARCHITECTURES,
                        default=list(ARCHITECTURES))
    parser.add_argument("--seeds", nargs="+", type=int, default=[41, 42, 43])
    parser.add_argument("--steps", type=int, default=3000)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--ncritic", type=int, default=3)
    parser.add_argument("--evaluate-every", type=int, default=200)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--gp-weight", type=float, default=10.)
    parser.add_argument("--aux-d-weight", type=float, default=2.)
    parser.add_argument("--aux-g-weight", type=float, default=5.)
    parser.add_argument("--morphology-weight", type=float, default=20.)
    parser.add_argument("--spectral-weight", type=float, default=.5)
    parser.add_argument("--derivative-weight", type=float, default=5.)
    parser.add_argument("--boundary-weight", type=float, default=5.)
    parser.add_argument("--require-gpu", action="store_true", default=kaggle)
    args = parser.parse_args()
    if min(args.steps, args.batch, args.ncritic, args.evaluate_every) <= 0 or args.batch < 2:
        parser.error("Positive steps/batch/ncritic/evaluate-every and batch >= 2 required")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    prepared = locate_prepared(args.prepared)
    x, c, masks = load_prepared(prepared)
    eval_indices = {split: stratified_indices(masks[split], c, seed=991)
                    for split in ("validation", "test")}
    configuration = dict(args=vars(args), prepared=str(prepared),
                         prepared_sha256=PREPARED_SHA256,
                         code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                         counts={key: int(value.sum()) for key, value in masks.items()},
                         evaluation_counts={key: int(len(value)) for key, value in eval_indices.items()},
                         selection="median validation selection score across seeds; test excluded",
                         python=platform.python_version())
    save_json(output/"configuration.json", configuration)
    results = []
    for name in args.architectures:
        for seed in args.seeds:
            results.append(train_run(name, seed, x, c, masks, eval_indices, output, args))
            save_json(output/"completed_runs.json", results)
    report, winner = aggregate(results)
    summary = dict(winner_selected_by_validation=winner, architectures=report,
                   caveat="Best among tested candidates/seeds, not universal or clinical best")
    save_json(output/"summary.json", summary)
    plot_comparison(output, results, winner)
    print("COMPLETE " + json.dumps(dict(winner=winner, runs=len(results))), flush=True)


if __name__ == "__main__":
    main()
