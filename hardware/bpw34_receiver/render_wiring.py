#!/usr/bin/env python3
"""Export actual copper/pad geometry and draw a human-readable wiring map."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def export():
    import pcbnew as p

    board = p.LoadBoard(str(HERE / "bpw34_receiver.kicad_pcb"))
    origin = (100, 100)

    def xy(position):
        return [p.ToMM(position.x) - origin[0], p.ToMM(position.y) - origin[1]]

    data = {"tracks": [], "footprints": []}
    for track in board.GetTracks():
        if isinstance(track, p.PCB_VIA) or not isinstance(track, p.PCB_TRACK):
            continue
        data["tracks"].append({
            "net": track.GetNetname().lstrip("/"),
            "layer": board.GetLayerName(track.GetLayer()),
            "width": p.ToMM(track.GetWidth()),
            "a": xy(track.GetStart()),
            "b": xy(track.GetEnd()),
        })
    for fp in sorted(board.GetFootprints(), key=lambda item: item.GetReference()):
        data["footprints"].append({
            "ref": fp.GetReference(),
            "value": fp.GetValue(),
            "side": board.GetLayerName(fp.GetLayer()),
            "ref_xy": xy(fp.Reference().GetPosition()),
            "pads": [
                {"number": pad.GetNumber(), "net": pad.GetNetname().lstrip("/"), "xy": xy(pad.GetPosition()), "drill": p.ToMM(pad.GetDrillSize().x)}
                for pad in fp.Pads()
            ],
        })
    (HERE / "reports/routing_geometry.json").write_text(json.dumps(data, indent=2) + "\n")


def plot():
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Circle, Rectangle

    data = json.loads((HERE / "reports/routing_geometry.json").read_text())
    palette = {
        "3V3": "#d97706",
        "GND": "#667085",
        "SUM": "#c026d3",
        "FB": "#2563eb",
        "VREF": "#059669",
        "OUT": "#dc2626",
        "NC": "#a1a1aa",
    }

    def group(net):
        for prefix in ("3V3", "GND", "SUM", "FB", "VREF", "OUT"):
            if net.startswith(prefix):
                return prefix
        return "NC"

    fig, axes = plt.subplots(1, 2, figsize=(18, 7.6), layout="constrained")
    for ax, layer in zip(axes, ("F.Cu", "B.Cu")):
        ax.add_patch(Rectangle((0, 0), 70, 32, facecolor="#f8fafc", edgecolor="#263341", linewidth=1.3))
        for track in data["tracks"]:
            if track["layer"] != layer:
                continue
            a, b = track["a"], track["b"]
            ax.plot([a[0], b[0]], [a[1], b[1]], color=palette[group(track["net"])], linewidth=1.2 + track["width"] * 2, solid_capstyle="round", zorder=2)
        for fp in data["footprints"]:
            if fp["ref"].startswith("H"):
                ax.add_patch(Circle(fp["pads"][0]["xy"], 1.6, fill=False, edgecolor="#8a94a0", linewidth=1))
                continue
            if fp["ref"].startswith(("R", "C")) and len(fp["pads"]) == 2:
                a, b = fp["pads"][0]["xy"], fp["pads"][1]["xy"]
                ax.plot([a[0], b[0]], [a[1], b[1]], "--", color="#aab3bc", linewidth=0.8, zorder=1)
            for pad in fp["pads"]:
                x, y = pad["xy"]
                ax.add_patch(Circle((x, y), 0.58, facecolor="white", edgecolor=palette[group(pad["net"])], linewidth=1.1, zorder=4))
                ax.text(x, y, pad["number"], ha="center", va="center", fontsize=5.2, color="#111827", zorder=5)
            x, y = fp["ref_xy"]
            ax.text(x, y, fp["ref"], ha="center", va="center", fontsize=6.7, fontweight="bold", color="#263341", bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.15}, zorder=6)
        ax.axvspan(33.5, 36.5, color="#111827", alpha=0.06)
        ax.set_title("Top copper / through-hole wiring" if layer == "F.Cu" else "Rear analog layout / B.Cu viewed from top", fontsize=13)
        ax.set_xlim(-1.5, 71.5)
        ax.set_ylim(33.5, -1.5)
        ax.set_aspect("equal")
        ax.set_xlabel("mm")
        ax.set_ylabel("mm")
        ax.grid(alpha=0.12)
    fig.legend(
        [Line2D([0], [0], color=color, linewidth=3) for color in palette.values()],
        ["3.3 V", "channel ground", "photodiode summing node", "TIA feedback/output", "0.30 V reference", "ADC output", "unused"],
        loc="outside lower center",
        ncol=4,
        frameon=False,
    )
    fig.suptitle("Dual BPW34 receiver v1.1 - actual routed copper and pad numbers", fontsize=16)
    fig.savefig(HERE / "reports/wiring_guide.png", dpi=180)
    fig.savefig(HERE / "reports/wiring_guide.pdf")
    plt.close(fig)


if __name__ == "__main__":
    export() if "--export" in sys.argv else plot()
