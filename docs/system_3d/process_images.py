#!/usr/bin/env python3
"""Process product images for the 3D system model.

Pipeline per component:
  1. Load the raw shop photo (JPEG/WEBP).
  2. Remove the background:
       - flood-fill from the borders (adaptive corner tolerance), and/or
       - colour-selector masks (PCB hue) for photos with clutter
         (retail box, graph paper, spare parts),
       - connected-component cleanup: keep only the target object,
       - fill interior holes so connectors/chips stay opaque.
  3. Crop to the object's alpha bounding box (+2 px pad).
  4. Resize so the longest side is <= 512 px (LANCZOS).
  5. Save assets/<name>.png (RGBA) and emit assets/textures.json with
      base64 data URLs for build_system.py to embed in
      model.json / viewer.html.

Run:  ../../.cad_venv/bin/python process_images.py   (from docs/system_3d/)
"""
import base64
import io
import json
import os
from collections import deque

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
MAX_DIM = 512  # per spec: textures capped at 512 px


# ---------------------------------------------------------------------------
# low-level mask helpers (pure numpy BFS — no scipy dependency)
# ---------------------------------------------------------------------------
def _bfs_reach(mask, seeds):
    """Set of (y, x) reachable from seeds by traversing mask==True 4-neighbours."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    dq = deque(seeds)
    for s in seeds:
        seen[s] = True
    while dq:
        y, x = dq.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                dq.append((ny, nx))
    return seen


def flood_background(rgb, tol=28):
    """Mask (True = background) of pixels connected to the border and within
    tol (Manhattan RGB) of the nearest border-seed colour — handles white
    studios, gradients and vignetting better than a fixed key colour."""
    h, w, _ = rgb.shape
    border = []
    for x in range(w):
        border += [(0, x), (h - 1, x)]
    for y in range(h):
        border += [(y, 0), (y, w - 1)]
    key = {p: rgb[p[0], p[1]].astype(np.int32) for p in border}
    queue = deque()
    bg = np.zeros((h, w), dtype=bool)
    for p in border:
        c = key[p]
        d = np.abs(rgb[p[0], p[1]] - c).sum()
        # seed every border pixel that is close to some border colour mode
        modes = [rgb[0, 0], rgb[0, w - 1], rgb[h - 1, 0], rgb[h - 1, w - 1]]
        if any(np.abs(rgb[p[0], p[1]] - m).sum() < tol * 1.5 for m in modes):
            bg[p] = True
            queue.append(p)
    while queue:
        y, x = queue.popleft()
        c = rgb[y, x]
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and not bg[ny, nx]:
                if np.abs(rgb[ny, nx].astype(np.int32) - c.astype(np.int32)).sum() < tol:
                    bg[ny, nx] = True
                    queue.append((ny, nx))
    return bg


def near_white(rgb, thr=232):
    return rgb.min(axis=2) > thr


def near_black(rgb, thr=42):
    return rgb.max(axis=2) < thr


def select_green_pcb(rgb):
    r, g, b = rgb[..., 0].astype(int), rgb[..., 1].astype(int), rgb[..., 2].astype(int)
    return (g - np.maximum(r, b)) > 12


def select_red_pcb(rgb):
    r, g, b = rgb[..., 0].astype(int), rgb[..., 1].astype(int), rgb[..., 2].astype(int)
    return (r - np.maximum(g, b)) > 40


def components(mask):
    """Yield (area, fill_ratio_hint, y_centroid, x_centroid, comp_mask) sorted by area desc."""
    h, w = mask.shape
    remaining = mask.copy()
    out = []
    while True:
        ys, xs = np.nonzero(remaining)
        if len(ys) == 0:
            break
        reach = _bfs_reach(remaining, [(ys[0], xs[0])])
        if reach.sum() < 24:  # noise speck
            remaining &= ~reach
            continue
        out.append((int(reach.sum()), float(ys.mean()), float(xs.mean()), reach))
        remaining &= ~reach
    out.sort(key=lambda t: -t[0])
    return out


def fill_holes(mask):
    """Add interior False pockets (chips, connectors, silkscreen) to the mask."""
    h, w = mask.shape
    inv = ~mask
    border = [(0, x) for x in range(w)] + [(h - 1, x) for x in range(w)] + \
             [(y, 0) for y in range(h)] + [(y, w - 1) for y in range(h)]
    outside = _bfs_reach(inv, [p for p in border if inv[p]])
    return mask | (inv & ~outside)


# ---------------------------------------------------------------------------
# per-image recipes
# ---------------------------------------------------------------------------
def process(rgb, recipe):
    mask = ~flood_background(rgb, tol=recipe.get("tol", 28))
    if recipe.get("white"):
        mask &= ~near_white(rgb)
    if recipe.get("black"):
        mask &= ~near_black(rgb)
    if recipe.get("selector"):
        sel = recipe["selector"](rgb)
        # restrict to regions the selector likes, but keep attached context
        comps = components(sel)
        if comps:
            keep = comps[0][3]
            if recipe.get("pick_topmost_of_big"):  # two boards shown: keep the upper one
                big = [c for c in comps if c[0] > 0.45 * comps[0][0]]
                keep = min(big, key=lambda c: c[1])[3]
            mask = mask & fill_holes(keep)
    comps = components(mask)
    if not comps:
        raise RuntimeError("no object found")
    mask = fill_holes(comps[0][3])

    alpha = (mask * 255).astype(np.uint8)
    ys, xs = np.nonzero(alpha > 10)
    x0, x1, y0, y1 = max(xs.min() - 2, 0), min(xs.max() + 3, alpha.shape[1]), \
                     max(ys.min() - 2, 0), min(ys.max() + 3, alpha.shape[0])

    im = Image.fromarray(np.dstack([rgb[y0:y1, x0:x1], alpha[y0:y1, x0:x1]]), "RGBA")
    w, h = im.size
    if max(w, h) > MAX_DIM:
        s = MAX_DIM / max(w, h)
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    return im


# name -> (raw file, recipe)
RECIPES = {
    "led_red":   ("led_red_raw.jpg",   dict(white=True, tol=34)),
    "led_ir":    ("led_ir_raw.jpg",    dict(white=True, tol=34)),
    "opt101":    ("opt101_raw.jpg",    dict(black=True, tol=30)),
    "pi4":       ("pi4_raw.jpg",       dict(white=True, selector=select_green_pcb)),
    "grove_hat": ("grove_hat_raw.jpg", dict(white=True, tol=34)),
    "mcp4725":   ("mcp4725_raw.jpg",   dict(selector=select_red_pcb,
                                            pick_topmost_of_big=True, tol=40)),
}


def main():
    textures = {}
    print(f"Processing product images (max {MAX_DIM}px) ...")
    for name, (raw, recipe) in RECIPES.items():
        src = os.path.join(ASSETS, raw)
        if not os.path.exists(src):
            print(f"  SKIP {name}: {raw} missing")
            continue
        rgb = np.asarray(Image.open(src).convert("RGB"), dtype=np.uint8)
        im = process(rgb, recipe)
        out_png = os.path.join(ASSETS, f"{name}.png")
        im.save(out_png, "PNG", optimize=True)
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        data = base64.b64encode(buf.getvalue()).decode("ascii")
        a = np.asarray(im)[..., 3]
        ys, xs = np.nonzero(a > 10)
        ar = (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)
        textures[name] = dict(dataUrl=f"data:image/png;base64,{data}",
                              px=[im.size[0], im.size[1]], ar=round(float(ar), 4))
        print(f"  {name:10s} {im.size}  ar={ar:.3f}  "
              f"png={os.path.getsize(out_png)/1024:.0f}KB  b64={len(data)/1024:.0f}KB")
    with open(os.path.join(ASSETS, "textures.json"), "w") as fh:
        json.dump(textures, fh)
    print(f"  -> assets/textures.json "
          f"({os.path.getsize(os.path.join(ASSETS, 'textures.json'))/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
