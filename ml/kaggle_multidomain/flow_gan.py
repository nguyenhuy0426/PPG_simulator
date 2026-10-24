"""PhysioFlow-GAN: adversarial post-training of the PhysioFlow velocity U-Net, a GAN with a pretrained flow generator.

Why (strict judge, validation people): every generator trained from scratch adversarially is separated almost
perfectly (PhysioMix AUC 0.9995 through its time branch, LSM-GAN 1.0 on every view; the strict-critic retrains of
both stayed there), while the app's PhysioFlow is separated only through the 8-20 Hz band (band-stop 8-20 Hz drops
its AUC from 1.0 to 0.50; its d2 spread is 16% under real). So the generator here is the PhysioFlow U-Net (6.9 M
parameters) initialised from the app's weights, run as a 4-step Heun sampler, and trained as a GAN generator against
strict_judge.StrictCritic, with two additions:
- a sensor term: per-domain learnable white-noise level (initialised at 0.03, the level calibrated on training
  windows, capped at SENSOR_MAX) added to the normalised clean output and passed through the reflection-padded
  data-view filter, so the 8-20 Hz residual comes from the same filter the real data went through. Its noise is a
  fixed permutation of z (generator(z, condition) stays deterministic, the app contract);
- a distillation anchor: MSE between the clean 4-step output and the frozen 16-step PhysioFlow from the same z and
  condition (the teacher is what the judge cannot separate below 8 Hz), weight `distill`, so the adversarial term
  refines the texture instead of re-learning the beat and rate control.
lsm=True adds the LSM-GAN log-spectral matching loss (Ding et al.) and trains on one domain's windows only (the LSM-GAN
setting); the generator keeps the conditional interface and is judged prompted with that domain's labels.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

import torch
from torch import nn
from torch.utils.checkpoint import checkpoint

from ml.kaggle_lsm.train_lsm import LENGTH
from ml.kaggle_multidomain.flow import FINISH_PAD, FlowGenerator, finish
from ml.kaggle_multidomain.physio import view_mask

STUDENT_STEPS, TEACHER_STEPS = 4, 16
SENSOR_INIT, SENSOR_MAX = .03, .1
SENSOR_SEED = 20261023
TEACHER_FILE = "physioflow_generator.ts"


def normalise(x):
    return (x-x.amin(-1, keepdim=True))/(x.amax(-1, keepdim=True)-x.amin(-1, keepdim=True)).clamp_min(1e-6)


class FlowGAN(nn.Module):
    """generator(z, condition) -> (n, 1, LENGTH) in [0, 1]; parts() also returns the clean (pre-sensor) output."""
    def __init__(self, size, center, scale, domains, steps=STUDENT_STEPS, sensor=True):
        super().__init__()
        self.flow = FlowGenerator(size, center, scale, sample_steps=steps, flag_scaffold=True)
        self.domains = int(domains)
        self.sensor = bool(sensor)
        # sigma = SENSOR_MAX * sigmoid(raw), raw initialised so that sigma = SENSOR_INIT in every domain.
        start = math.log(SENSOR_INIT/(SENSOR_MAX-SENSOR_INIT))
        self.sensor_raw = nn.Parameter(torch.full((self.domains,), start))
        order = torch.randperm(LENGTH, generator=torch.Generator().manual_seed(SENSOR_SEED))
        self.register_buffer("order", order)
        self.register_buffer("band", torch.tensor(view_mask("v3", LENGTH+2*FINISH_PAD)), persistent=False)

    def sensor_sigma(self, condition):
        return SENSOR_MAX*torch.sigmoid(condition[:, :self.domains]@self.sensor_raw)

    def integrate(self, z, condition):
        """FlowGenerator.forward (t_end 0, no finish filter) with every U-Net pass under activation checkpointing
        when gradients are on: backpropagating through the 7 passes of 4 Heun steps at batch 32 held ~4.5 GB per
        run and three runs per T4 ran out of memory (flow-GAN kernel v1); a pass is recomputed in the backward."""
        flow = self.flow
        s = flow.scaffold_of(z, condition)
        if torch.is_grad_enabled():
            velocity = lambda x, t: checkpoint(flow.velocity, x, t, s, condition, use_reentrant=False)
        else:
            velocity = lambda x, t: flow.velocity(x, t, s, condition)
        x, steps = z[:, None], flow.sample_steps
        for i in range(steps):
            t, t_next = 1-i/steps, 1-(i+1)/steps
            v = velocity(x, t)
            proposal = x+(t_next-t)*v
            x = x+(t_next-t)*.5*(v+velocity(proposal, t_next)) if i < steps-1 else proposal
        return normalise(x)

    def parts(self, z, condition):
        clean = self.integrate(z, condition)
        if not self.sensor:
            return clean, clean
        noise = z[:, self.order][:, None]
        y = finish(clean+self.sensor_sigma(condition)[:, None, None]*noise, self.band)
        return normalise(y), clean

    def forward(self, z, condition):
        return self.parts(z, condition)[0]

    def export(self, z, condition):
        """TorchScript: the flow's scripted sampler (one traced U-Net pass) with the sensor term scripted around it."""
        return torch.jit.script(FlowGANSampler(self.flow.export(z, condition), self.sensor_raw.detach().clone(),
                                               self.order, self.band, self.domains, self.sensor))

    def load_teacher(self, state):
        self.flow.net.load_state_dict(state)

    def teacher(self):
        """Frozen copy of the flow at the teacher's step count (call after load_teacher)."""
        result = copy.deepcopy(self.flow).eval().requires_grad_(False)
        result.sample_steps = TEACHER_STEPS
        return result


class FlowGANSampler(nn.Module):
    """Scriptable twin of FlowGAN.forward around FlowGenerator.export()."""
    def __init__(self, sampler, sensor_raw, order, band, domains: int, sensor: bool):
        super().__init__()
        self.sampler = sampler
        self.register_buffer("sensor_raw", sensor_raw)
        self.register_buffer("order", order.clone())
        self.register_buffer("band", band.clone())
        self.domains, self.sensor, self.sensor_max, self.pad = domains, sensor, SENSOR_MAX, FINISH_PAD

    def forward(self, z, condition):
        clean = self.sampler(z, condition)
        if not self.sensor:
            return clean
        sigma = self.sensor_max*torch.sigmoid(condition[:, :self.domains]@self.sensor_raw)
        y = finish(clean+sigma[:, None, None]*z[:, self.order][:, None], self.band, self.pad)
        return normalise(y)


def teacher_state(roots):
    """The app's PhysioFlow U-Net weights from the first manifest-verified physioflow_generator.ts under roots."""
    for root in roots:
        for manifest in sorted(Path(root).rglob("manifest.json")):
            entry = json.loads(manifest.read_text()).get("models", {}).get("physioflow_generator")
            path = manifest.parent/TEACHER_FILE
            if not entry or not path.exists():
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError(f"{path}: checksum differs from its manifest")
            return torch.jit.load(str(path), map_location="cpu").net.state_dict()
    raise FileNotFoundError(f"No verified {TEACHER_FILE} under {list(roots)}")
