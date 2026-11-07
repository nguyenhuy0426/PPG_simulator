"""Figures and the training video of the PPG-physiGPT section (docs/model-report/gan-report.html).

Input is a shard written by ml/kaggle_physigpt/mimic_wdb.py (real MIMIC-III windows, ODbL 1.0), for example
    python3 -c "from ml.kaggle_physigpt.mimic_wdb import main; main(['--output', 'SHARD', '--start', '0', '--stop', '4', '--cap', '6'])"
then
    python3 scripts/build_physigpt_media.py SHARD docs/model-report/media

The video shows the training target, not model output: the real patch i, and the straight path from Gaussian noise to
it that the flow head learns given patches 1..i-1. No trained PPG-physiGPT exists yet, so nothing here is generated.
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import animation
import numpy as np

FS, PATCH, PATCHES = 40, 40, 30
INK, PURPLE, GOLD, GREY = "#1f2937", "#6b4fbb", "#f59e0b", "#9ca3af"


def load(shard):
    shard = Path(shard)
    signal = np.concatenate([np.load(p) for p in sorted(shard.glob("chunk_*_signal.npy"))]).astype(np.float32)/65535
    meta = np.concatenate([np.load(p) for p in sorted(shard.glob("chunk_*_meta.npy"))])
    return signal, meta


def data_figure(signal, meta, picks, path):
    t = np.arange(signal.shape[1])/FS
    fig, axes = plt.subplots(len(picks), 1, figsize=(9, 1.45*len(picks)+.5), dpi=110, sharex=True)
    for ax, (i, label) in zip(axes, picks):
        ax.plot(t, signal[i], lw=1.1, color=PURPLE)
        ax.set_title(f"MIMIC-III bản ghi {meta['record'][i]} · {label}", loc="left", fontsize=10, color=INK)
        ax.set_yticks([]), ax.set_xlim(0, 30)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
    axes[-1].set_xlabel("giây")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def patch_video(window, path, seed=7, fps=8):
    rng = np.random.default_rng(seed)
    t_axis = np.arange(len(window))/FS
    x1 = 2*window.reshape(PATCHES, PATCH)-1
    x0 = rng.standard_normal(x1.shape)
    frames = [(i, s) for i in range(PATCHES) for s in (np.linspace(0, 1, 9) if i < 3 else np.linspace(0, 1, 4))]
    frames = [(0, 0.)]*fps+frames+[(PATCHES-1, 1.)]*(2*fps)

    fig = plt.figure(figsize=(9, 5.4), dpi=110)
    top = fig.add_axes([.04, .55, .92, .3])
    bottom = fig.add_axes([.3, .1, .4, .32])
    title = fig.suptitle("", fontsize=11.5, color=INK, y=.97)
    note = fig.text(.5, .875, "", ha="center", fontsize=9.5, color=GREY, linespacing=1.4)
    (context,) = top.plot([], [], lw=1.3, color=PURPLE)
    (current,) = top.plot([], [], lw=1.6, color=GOLD)
    band = top.axvspan(0, 1, color=GOLD, alpha=.15)
    top.set_xlim(0, 30), top.set_ylim(-.15, 1.15), top.set_yticks([]), top.set_xlabel("giây", fontsize=9)
    future = top.text(15, .5, "", ha="center", va="center", color=GREY, fontsize=10)
    (target,) = bottom.plot([], [], lw=1, ls="--", color=GREY, label="patch thật (đích)")
    (path_line,) = bottom.plot([], [], lw=1.6, color=GOLD, label="đang đi từ nhiễu tới đích")
    bottom.set_xlim(0, 1), bottom.set_ylim(-1.3, 2.3), bottom.set_yticks([]), bottom.set_xlabel("giây trong patch", fontsize=9)
    bottom.legend(loc="upper right", fontsize=8, frameon=False)
    for ax in (top, bottom):
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
    patch_t = np.arange(PATCH)/FS

    def draw(frame):
        i, s = frame
        lo, hi = i*PATCH, (i+1)*PATCH
        context.set_data(t_axis[:lo], window[:lo])
        xt = (1-s)*x0[i]+s*x1[i]
        current.set_data(t_axis[lo:hi], ((xt+1)/2).clip(-.15, 1.15))
        band.set_x(i)
        future.set_position(((i+1+30)/2, .5))
        future.set_text("chưa thấy" if i < PATCHES-1 else "")
        target.set_data(patch_t, window[lo:hi])
        path_line.set_data(patch_t, (xt+1)/2)
        title.set_text(f"Lúc train · patch {i+1}/30 · t = {s:.2f}")
        note.set_text("Tím: các patch model đã thấy · Vàng: patch i, đi thẳng từ nhiễu (t = 0) tới sóng thật (t = 1)\n"
                      "Đây là đích để model học, chưa phải sóng do model vẽ")
        return context, current, target, path_line

    writer = animation.FFMpegWriter(fps=fps, codec="libx264", extra_args=["-pix_fmt", "yuv420p", "-crf", "28"])
    with writer.saving(fig, str(path), dpi=110):
        for frame in frames:
            draw(frame)
            writer.grab_frame()
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("shard")
    parser.add_argument("output")
    parser.add_argument("--clean", type=int, default=0, help="window index for the video and the clean example")
    parser.add_argument("--second", type=int, default=6)
    parser.add_argument("--artifact", type=int, default=13)
    args = parser.parse_args(argv)
    signal, meta = load(args.shard)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    picks = [(args.clean, f"nhịp ≈ {meta['rate'][args.clean]:.0f}/phút, sạch"),
             (args.second, f"nhịp ≈ {meta['rate'][args.second]:.0f}/phút"),
             (args.artifact, "có nhiễu cử động (vẫn nằm trong dữ liệu train)")]
    data_figure(signal, meta, picks, output/"physigpt-du-lieu.png")
    patch_video(signal[args.clean], output/"physigpt-hoc-tung-patch.mp4")
    print(output/"physigpt-du-lieu.png", output/"physigpt-hoc-tung-patch.mp4")


if __name__ == "__main__":
    main()
