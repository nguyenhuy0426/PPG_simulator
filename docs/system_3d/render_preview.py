#!/usr/bin/env python3
"""Render preview PNGs of the assembled PPG simulator SYSTEM model.

Generic: colors come straight from out/model.json (first sub-material color),
so this script never needs a per-part color map.

Run:  ../../.cad_venv/bin/python render_preview.py   (needs matplotlib)
"""
import base64
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

with open(os.path.join(OUT_DIR, "model.json")) as f:
    parts = json.load(f)["parts"]

# Parts that would visually smother the internals in the cross-section view.
HEAVY = {"body", "lid", "base_neg", "base_pos"}


def decode_part(p):
    all_v, all_f, voff = [], [], 0
    for s in p.get("subs", []):
        v = np.frombuffer(base64.b64decode(s["vbase64"]), dtype=np.float32).reshape(-1, 3)
        f = np.frombuffer(base64.b64decode(s["fbase64"]), dtype=np.uint32).reshape(-1, 3)
        all_v.append(v)
        all_f.append(f + voff)
        voff += len(v)
    if not all_v:
        return np.zeros((0, 3), np.float32), np.zeros((0, 3), np.uint32)
    return np.concatenate(all_v), np.concatenate(all_f)


def hex_color(c):
    return "#%06x" % (c & 0xFFFFFF)


def bounds_of(filter_fn=None):
    lo, hi = None, None
    for p in parts:
        if filter_fn and not filter_fn(p):
            continue
        b = p["bounds"]
        lo = b[:3] if lo is None else [min(lo[i], b[i]) for i in range(3)]
        hi = b[3:] if hi is None else [max(hi[i], b[i + 3]) for i in range(3)]
    return np.array(lo), np.array(hi)


def draw(ax, explode=0.0, alpha_map=None, filter_fn=None):
    for p in parts:
        if filter_fn and not filter_fn(p):
            continue
        v, f = decode_part(p)
        if not len(f):
            continue
        v = v + np.asarray(p["explode"], np.float32) * explode
        col = hex_color(p["color"])
        a = 1.0
        if alpha_map:
            a = alpha_map.get(p["name"], alpha_map.get("*", 1.0))
        poly = Poly3DCollection(v[f], facecolor=col, edgecolor="none",
                                alpha=a, linewidth=0)
        ax.add_collection3d(poly)


def finish(ax, lo, hi, title, pad=20):
    ctr = (lo + hi) / 2
    half = max(hi - lo) / 2 + pad
    ax.set_xlim(ctr[0] - half, ctr[0] + half)
    ax.set_ylim(ctr[1] - half, ctr[1] + half)
    ax.set_zlim(ctr[2] - half, ctr[2] + half)
    ax.set_box_aspect([1, 1, 1])
    ax.set_xlabel("X (mm) — trục quang")
    ax.set_ylabel("Y (mm)")
    ax.set_zlabel("Z (mm)")
    ax.grid(True, alpha=0.2)
    ax.set_title(title, fontsize=12, fontweight="bold")


def save(fig, name):
    path = os.path.join(OUT_DIR, name)
    fig.savefig(path, dpi=130, bbox_inches="tight", facecolor="#f0f0f0")
    plt.close(fig)
    print(f"  -> {name}  ({os.path.getsize(path)//1024} KB)")


print("Rendering preview images ...")

# 1) Assembled — 3 angles
lo, hi = bounds_of()
fig = plt.figure(figsize=(19, 6.5))
for i, (elev, azim, t) in enumerate(((18, -50, "Góc trước-phải"),
                                     (18, 130, "Góc sau-trái"),
                                     (55, -90, "Nhìn từ trên"))):
    ax = fig.add_subplot(1, 3, i + 1, projection="3d")
    ax.set_proj_type("ortho")
    draw(ax, alpha_map={"body": 0.92})
    ax.view_init(elev=elev, azim=azim)
    finish(ax, lo, hi, t, pad=30)
save(fig, "preview_assembled.png")

# 2) Exploded
fig = plt.figure(figsize=(19, 6.5))
for i, (elev, azim, t) in enumerate(((16, -50, "Tháo rời — trước-phải"),
                                     (16, 130, "Tháo rời — sau-trái"),
                                     (50, -90, "Tháo rời — từ trên"))):
    ax = fig.add_subplot(1, 3, i + 1, projection="3d")
    ax.set_proj_type("ortho")
    draw(ax, explode=1.6, alpha_map={"body": 0.85})
    ax.view_init(elev=elev, azim=azim)
    finish(ax, lo, hi, t, pad=80)
save(fig, "preview_exploded.png")

# 3) Top cross-section — the two optical lanes (Z), body transparent
lo2, hi2 = bounds_of(lambda p: p["name"] not in HEAVY | {"wiring", "pi4", "grove_hat",
                                                         "driver_board"})
fig = plt.figure(figsize=(14, 7))
ax = fig.add_subplot(111, projection="3d")
ax.set_proj_type("ortho")
draw(ax, alpha_map={"body": 0.07, "lid": 0.05, "base_neg": 0.25, "base_pos": 0.25,
                    "wiring": 0.0, "pi4": 0.0, "grove_hat": 0.0, "driver_board": 0.0},
     filter_fn=lambda p: p["name"] != "wiring")
ax.view_init(elev=64, azim=-90)
ctr, half = (lo2 + hi2) / 2, max(hi2 - lo2) / 2 + 40
ax.set_xlim(ctr[0] - half, ctr[0] + half)
ax.set_ylim(ctr[1] - half * 0.7, ctr[1] + half * 0.7)
ax.set_zlim(ctr[2] - half, ctr[2] + half)
ax.set_box_aspect([1, 0.7, 1])
ax.set_xlabel("X (mm) — trục quang")
ax.set_ylabel("Y (mm)")
ax.set_zlabel("Z (mm)")
ax.grid(True, alpha=0.2)
ax.set_title("Mặt cắt nhìn từ nóc — 2 làn quang Đỏ (-Z) / IR (+Z), "
             "carrier + trục trượt + khẩu độ + board OPT101", fontsize=12,
             fontweight="bold")
ax.text(94, 40, -34, "LED Đỏ d=25", color="#c02020", fontsize=9, fontweight="bold")
ax.text(34, 40, 26, "LED IR d=85", color="#5c3cb0", fontsize=9, fontweight="bold")
ax.text(128, 46, -12, "OPT101 → A2", color="#1d1d24", fontsize=9, fontweight="bold")
ax.text(128, 46, 12, "OPT101 → A0", color="#1d1d24", fontsize=9, fontweight="bold")
save(fig, "preview_cross_section.png")

# 4) Electronics bay (base only, box hidden)
lo3, hi3 = bounds_of(lambda p: p["name"] in {"pi4", "grove_hat", "driver_board",
                                             "base_neg", "base_pos", "wiring"})
fig = plt.figure(figsize=(14, 7))
ax = fig.add_subplot(111, projection="3d")
ax.set_proj_type("ortho")
draw(ax, alpha_map={"base_neg": 0.45, "base_pos": 0.45})
ax.view_init(elev=42, azim=-115)
ctr, half = (lo3 + hi3) / 2, max(hi3 - lo3) / 2 + 20
ax.set_xlim(ctr[0] - half, ctr[0] + half)
ax.set_ylim(ctr[1] - half * 0.5, ctr[1] + half * 0.5)
ax.set_zlim(ctr[2] - half, ctr[2] + half)
ax.set_box_aspect([1, 0.5, 1])
ax.set_xlabel("X (mm)")
ax.set_ylabel("Y (mm)")
ax.set_zlabel("Z (mm)")
ax.grid(True, alpha=0.2)
ax.set_title("Khối điện tử trên đế chung — Pi 4 + Grove HAT (-Z) · "
             "driver + 2× MCP4725 (+Z) · cáp Grove/I2C/USB-C", fontsize=12,
             fontweight="bold")
save(fig, "preview_electronics.png")

print("Done — 4 preview images.")
