"""Draw the graphical abstract (figures/graphical_abstract.{pdf,png}): a schematic with numbers quoted in the abstract.

Elsevier asks for at least 1328 x 531 px (w x h), readable at 5 x 13 cm; this draws 13.28 x 5.31 cm at 300 dpi.
Submit it as a separate file; it is not part of main.tex.

    python3 docs/paper/make_graphical_abstract.py
"""
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = pathlib.Path(__file__).resolve().parent
INK, MUTED, SCAFFOLD, LEARNED, RULES = "#1f2933", "#52606d", "#c2410c", "#2563eb", "#7c3aed"


def box(ax, x, w, title, body, color):
    ax.add_patch(FancyBboxPatch((x, 0.30), w, 0.50, boxstyle="round,pad=0.01,rounding_size=0.03", fc="white",
                                ec=color, lw=1.4))
    ax.text(x+w/2, 0.76, title, ha="center", va="top", fontsize=7, weight="bold", color=color)
    ax.text(x+w/2, 0.66, body, ha="center", va="top", fontsize=5.4, color=INK, linespacing=1.3)


def arrow(ax, x0, x1):
    ax.add_patch(FancyArrowPatch((x0, 0.55), (x1, 0.55), arrowstyle="-|>", mutation_scale=8, lw=1.1, color=MUTED))


def main():
    fig = plt.figure(figsize=(13.28/2.54, 5.31/2.54), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 2.5)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.03, 0.95, "Rate-controllable PPG synthesis for a low-cost simulator", fontsize=8, weight="bold",
            color=INK, va="top")

    t = np.linspace(0, 1, 300)
    box(ax, 0.03, 0.42, "Command", "rate 40-180 bpm\nirregularity\nrecording context", MUTED)
    arrow(ax, 0.46, 0.53)
    box(ax, 0.54, 0.50, "Rhythm scaffold", "beat times fixed\nfrom the command", SCAFFOLD)
    beats = np.exp(-((t[:, None]-np.linspace(0.1, 0.9, 5)[None])/0.025)**2).sum(1)
    ax.plot(0.60+0.38*t, 0.34+0.10*beats/beats.max(), color=SCAFFOLD, lw=0.8)
    arrow(ax, 1.05, 1.12)
    box(ax, 1.13, 0.58, "Learned waveform", "PhysioMix: GAN, 0.16 M\nPhysioFlow: rectified flow, 6.9 M", LEARNED)
    phase = (t*5) % 1
    wave = np.exp(-((phase-0.25)/0.09)**2)+0.35*np.exp(-((phase-0.55)/0.10)**2)
    ax.plot(1.19+0.46*t, 0.34+0.08*wave/wave.max(), color=LEARNED, lw=0.8)
    arrow(ax, 1.72, 1.79)
    box(ax, 1.80, 0.67, "Raspberry Pi 4", "2 x 12-bit DAC at 500 Hz\nred and infrared LED driver\noptical path not yet validated",
        MUTED)

    ax.text(0.03, 0.20, "Rate error below 1 bpm from 40 to 180 bpm", fontsize=6.2, color=SCAFFOLD, weight="bold")
    ax.text(1.80, 0.20, "Pre-registered selection rules", fontsize=6.2, color=RULES, weight="bold")
    ax.text(0.03, 0.115, "Unseen subjects rated indistinguishable: PhysioFlow 50-91 %, PhysioMix 7-45 %, parametric 0 %",
            fontsize=5.6, color=INK)
    ax.text(0.03, 0.04, "Everyday wrist PPG from an unseen device: below 1 % for both models", fontsize=5.6, color=INK)
    for ext in ("pdf", "png"):
        fig.savefig(HERE/"figures"/f"graphical_abstract.{ext}", dpi=300)
    print("wrote figures/graphical_abstract.pdf and .png")


if __name__ == "__main__":
    main()
