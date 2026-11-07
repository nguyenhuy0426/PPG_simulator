"""P2: StrictCritic's beat-locked 7-14 Hz view (strict_judge.CriticBand)."""
import math

import numpy as np
from scipy.signal import butter, sosfiltfilt
import torch

from ml.kaggle_lsm.train_lsm import FS, LENGTH
from ml.kaggle_multidomain import strict_judge as sj


def pulses(n, seed=0):
    t = torch.arange(LENGTH)/FS
    g = torch.Generator().manual_seed(seed)
    return .5+.4*torch.sin(2*math.pi*1.2*t)+.02*torch.randn(n, 1, LENGTH, generator=g)


def test_band_view_is_the_zero_phase_butterworth_band_times_its_gain():
    x = pulses(2)
    branch = sj.CriticBand(8)
    xc = (x[:, 0]-x[:, 0].mean(-1, keepdim=True)).double()
    band = torch.fft.irfft(torch.fft.rfft(xc)*branch.mask(LENGTH, x.device).double(), n=LENGTH).numpy()
    sos = butter(sj.CriticBand.ORDER, [sj.CriticBand.LOW, sj.CriticBand.HIGH], "bandpass", fs=FS, output="sos")
    reference = sosfiltfilt(sos, xc.numpy(), axis=-1)
    inner = slice(4*FS, LENGTH-4*FS)     # away from the circular (FFT) vs padded (sosfiltfilt) edges
    assert np.abs(band[:, inner]-reference[:, inner]).max() < 1e-3*np.abs(reference).max()


def test_band_critic_adds_a_fourth_logit_and_keeps_the_default_three():
    assert sj.StrictCritic(11)(pulses(4), torch.zeros(4, 11)).shape == (4, 3)
    critic = sj.StrictCritic(11, band=True)
    assert critic(pulses(4), torch.zeros(4, 11)).shape == (4, 4)
    critic.train()
    assert critic(pulses(4), torch.zeros(4, 11)).shape == (4, 4)    # random 25.6 s crops: another mask length


def test_band_critic_input_gradient_stays_bounded():
    # Same bound as the three-view critic (lazy R1 calibrated on spectral-normalised critics).
    torch.manual_seed(0)
    critic = sj.StrictCritic(11, band=True)
    x = pulses(8).requires_grad_(True)
    with torch.no_grad():
        for _ in range(20):
            critic(x, torch.zeros(8, 11))
    critic.eval()
    grad = torch.autograd.grad(critic(x, torch.zeros(8, 11)).mean(1).sum(), x)[0]
    assert grad.square().flatten(1).sum(1).mean() < 100
