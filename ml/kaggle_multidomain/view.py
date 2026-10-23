"""Shared 40 Hz signal views. v1 is frozen for reproducing earlier packs.

v1: 161-tap 0.9-5 Hz zero-phase FIR on the raw-DC resampled record. Its passband edge
attenuates a 60 bpm fundamental by about 6 dB and 40-45 bpm by 27-41 dB, and the raw DC
step at zero-padded record edges leaks into the first window.
v3: remove the record mean, resample with linear edge padding, then a zero-phase
Butterworth band-pass whose low edge keeps 40 bpm fundamentals representable.
"""
import numpy as np
from scipy.signal import butter, resample_poly, sosfiltfilt

from ml.kaggle_lsm.train_lsm import FS, bandpass

VIEWS = {"v1": None, "v3": dict(low=.5, high=8., order=4)}


def describe(view):
    if view == "v1":
        return "resample_poly; 161-tap 0.9-5Hz zero-phase FIR; per-window minmax; no learned preprocessing"
    spec = VIEWS[view]
    return (f"record mean removed; resample_poly padtype=line; Butterworth order {spec['order']} "
            f"{spec['low']}-{spec['high']} Hz sosfiltfilt; per-window minmax")


def resample_filter(raw, up, down, view="v1"):
    if view not in VIEWS:
        raise ValueError(f"Unknown view: {view}")
    if view == "v1":
        return bandpass(resample_poly(raw, up, down))
    spec = VIEWS[view]
    wave = resample_poly(raw-np.mean(raw), up, down, padtype="line")
    sos = butter(spec["order"], [spec["low"], spec["high"]], "bandpass", fs=FS, output="sos")
    return sosfiltfilt(sos, wave)
