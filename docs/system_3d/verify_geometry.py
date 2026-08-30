#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify PPG simulator v2 STL output (magnetic slider redesign).

Run (từ docs/system_3d/):
  ../../.cad_venv/bin/python verify_geometry.py

Containment is decided by TRUE RAY-CAST (Möller–Trumbore parity, pure numpy —
no scipy/rtree in this venv) and cross-checked with a tiny-cube boolean
intersection through manifold3d. Both must agree with the expectation.
"""
import os
import sys
import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
STL = os.path.join(HERE, "out", "stl")
BAMBU = os.path.join(HERE, "out", "print_bambu")

EXPECTED_FILES = {
    "body.stl", "lid.stl", "slide_shaft_red.stl", "led_carrier_red.stl",
    "mag_slider_red.stl", "frame.stl", "aperture_red_blank.stl",
    "aperture_red_d2.stl", "aperture_red_d5.stl", "aperture_red_d16.stl",
    "hood_l_red.stl", "hood_r_red.stl", "base_neg.stl", "base_pos.stl",
}

fails = []
npass = 0


def check(label, cond, detail=""):
    global npass
    if cond:
        npass += 1
        print(f"  PASS  {label} {detail}")
    else:
        fails.append(label)
        print(f"  FAIL  {label} {detail}")


# ---------------------------------------------------------------- ray cast
def inside_ray(mesh, pt, direction=(0.8307, 0.4127, 0.1889), eps=1e-9):
    """Point-in-mesh via ray parity (Möller–Trumbore, vectorised)."""
    d = np.asarray(direction, float)
    d /= np.linalg.norm(d)
    o = np.asarray(pt, float)
    v = np.asarray(mesh.vertices, float)
    f = np.asarray(mesh.faces, np.int64)
    v0, v1, v2 = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    e1, e2 = v1 - v0, v2 - v0
    pvec = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, pvec)
    ok = np.abs(det) > 1e-12
    e1, e2, pvec, det, v0 = e1[ok], e2[ok], pvec[ok], det[ok], v0[ok]
    tvec = o - v0
    u = np.einsum("ij,ij->i", tvec, pvec) / det
    qvec = np.cross(tvec, e1)
    vv = np.einsum("ij,ij->i", np.broadcast_to(d, e1.shape), qvec) / det
    t = np.einsum("ij,ij->i", e2, qvec) / det
    hit = (u >= -1e-9) & (vv >= -1e-9) & (u + vv <= 1 + 1e-9) & (t > eps)
    return bool(np.count_nonzero(hit) % 2 == 1)


def inside_cube(mesh, pt, s=0.04):
    """Cross-check: tiny cube around pt intersected with mesh (manifold)."""
    cube = trimesh.creation.box(extents=[s, s, s])
    cube.apply_translation(np.asarray(pt, float))
    try:
        inter = trimesh.boolean.intersection([mesh, cube])
    except Exception:
        return False
    return inter is not None and len(inter.faces) > 0 and inter.volume > 1e-7


def expect(mesh, pt, want_inside, label):
    r = inside_ray(mesh, pt)
    c = inside_cube(mesh, pt)
    ok = (r == want_inside) and (c == want_inside)
    check(label, ok,
          f"(ray={'in' if r else 'out'}, cube={'in' if c else 'out'}, "
          f"expect={'in' if want_inside else 'out'})")


# ================================================================ 1. files
print("=== 1. File set (out/stl) ===")
present = set(os.listdir(STL))
check("exact file set", present == EXPECTED_FILES,
      f"({len(present)} files; extra={sorted(present - EXPECTED_FILES)}, "
      f"missing={sorted(EXPECTED_FILES - present)})")

# ================================================================ 2. load
print("=== 2. Watertight + bounds ===")
m = {}
for name in sorted(EXPECTED_FILES):
    mesh = trimesh.load(os.path.join(STL, name))
    m[name[:-4]] = mesh
    ok = "watertight" if mesh.is_watertight else "!! NOT WATERTIGHT"
    print(f"  {name:<26} tris={len(mesh.faces):>5}  {ok}")
    print(f"    bounds=({mesh.bounds[0][0]:8.2f},{mesh.bounds[0][1]:8.2f},"
          f"{mesh.bounds[0][2]:8.2f}) .. ({mesh.bounds[1][0]:8.2f},"
          f"{mesh.bounds[1][1]:8.2f},{mesh.bounds[1][2]:8.2f})")
    check(f"{name} watertight", bool(mesh.is_watertight))

# lid STL xuất ở HỆ THẾ GIỚI (không lật — flip đã bỏ sau review): y dương.
# Bounds y: mộng vấu 56 .. mặt trên nắp 67 (thanh ray nhô tới RAIL_TOP=68.4).
lid = m["lid"]
lb = lid.bounds
check("lid bounds y ~ 56..68.4 (world frame, not flipped)",
      abs(lb[0][1] - 56.0) < 0.1 and abs(lb[1][1] - 68.4) < 0.1
      and lb[0][1] > 0.0,
      f"(y = {lb[0][1]:.2f}..{lb[1][1]:.2f})")

# ================================================================ 3. hoods
print("=== 3. Hood screw holes OPEN at outer face (ray-cast) ===")
expect(m["hood_l_red"], (-3.15, 10.5, -35.75), False, "hood_l hole z=-35.75 open")
expect(m["hood_l_red"], (-3.15, 10.5, -2.75), False, "hood_l hole z=-2.75 open")
expect(m["hood_r_red"], (153.15, 10.5, -35.75), False, "hood_r hole z=-35.75 open")
expect(m["hood_r_red"], (153.15, 10.5, -2.75), False, "hood_r hole z=-2.75 open")
# spec-literal points (ir-lane bolts) — must also be open w.r.t. the red hood
expect(m["hood_r_red"], (153.15, 10.5, 2.75), False, "hood_r spec pt z=+2.75")
expect(m["hood_r_red"], (153.15, 10.5, 35.75), False, "hood_r spec pt z=+35.75")

# ================================================================ 4. carrier
print("=== 4. led_carrier_red ===")
ymax = m["led_carrier_red"].bounds[1][1]
check("carrier max y ~ 63.5", abs(ymax - 63.5) < 0.15, f"(max y = {ymax:.2f})")
expect(m["led_carrier_red"], (82, 61.8, -19.25), False, "magnet pocket void open")
expect(m["led_carrier_red"], (83, 14, -19.25), False, "D-bore void open")
expect(m["led_carrier_red"], (82, 50, -19.25), True, "tower solid")

# ================================================================ 5. slider
print("=== 5. mag_slider_red ===")
b = m["mag_slider_red"].bounds
exp_lo, exp_hi = (74.0, 66.2, -26.45), (90.0, 71.5, -12.05)
close = np.allclose(b[0], exp_lo, atol=0.05) and np.allclose(b[1], exp_hi, atol=0.05)
check("slider bounds ~ x74..90 y66.2..71.5 z-26.45..-12.05", close,
      f"(lo={tuple(round(x,2) for x in b[0])}, hi={tuple(round(x,2) for x in b[1])})")
expect(m["mag_slider_red"], (82, 67.8, -19.25), False, "slider magnet pocket void open")
expect(m["mag_slider_red"], (82, 70.5, -19.25), True, "slider roof solid")

# ================================================================ 6. lid
print("=== 6. lid (hatches removed, rails/stops/ticks present) ===")
expect(lid, (86, 65.5, -19.25), True, "old hatch red now solid")
expect(lid, (86, 65.5, 19.25), True, "old hatch ir now solid")
expect(lid, (50, 67.0, -10.75), True, "red rail +z side solid")
expect(lid, (50, 67.0, 10.75), True, "ir rail -z side solid")
expect(lid, (50, 67.0, -19.25), False, "slider channel gap open")
expect(lid, (8.5, 67.0, -19.25), True, "front stop solid")
expect(lid, (100.5, 67.0, -19.25), True, "rear stop solid")
expect(lid, (8.5, 67.0, 19.25), True, "front stop ir solid")
# engraved d-scale ticks (floor of recess, outside rails)
expect(lid, (82.0, 66.0, -30.0), False, "red big tick d=25 engraved")
expect(lid, (22.0, 66.0, 30.0), False, "ir big tick d=85 engraved")
expect(lid, (37.0, 66.0, -30.0), False, "red small tick d=70 engraved")

# ================================================================ 7. body
print("=== 7. body (hood pilots 2.6 mm, aperture slot) ===")
for pt, lbl in (((1.0, 10.5, -2.75), "pilot L z=-2.75 open"),
                ((1.0, 10.5, -35.75), "pilot L z=-35.75 open"),
                ((149.0, 10.5, 2.75), "pilot R z=+2.75 open"),
                ((149.0, 10.5, 35.75), "pilot R z=+35.75 open"),
                ((114.2, 30, -19.25), "aperture slot red open"),
                ((114.2, 30, 19.25), "aperture slot ir open")):
    expect(m["body"], pt, False, lbl)

# ================================================================ 8. base
print("=== 8. base (5 tenons, seam screws removed) ===")
expect(m["base_neg"], (43, -2, -6), True, "base_neg old seam screw solid")
expect(m["base_neg"], (111, -2, -6), True, "base_neg old seam screw #2 solid")
expect(m["base_neg"], (43, -2, 4), True, "base_neg tenon x=43 solid")
expect(m["base_neg"], (111, -2, 4), True, "base_neg tenon x=111 solid")
expect(m["base_pos"], (43, -2, 4), False, "base_pos mortise x=43 open")
expect(m["base_pos"], (111, -2, 4), False, "base_pos mortise x=111 open")
expect(m["base_pos"], (77, -2, 4), False, "base_pos mortise x=77 open (old)")

# ================================================================ 9. pairs
print("=== 9. Pairwise intersection volumes ~ 0 ===")
PAIRS = [
    ("body", "lid"), ("body", "led_carrier_red"), ("body", "slide_shaft_red"),
    ("led_carrier_red", "slide_shaft_red"), ("lid", "mag_slider_red"),
    ("body", "hood_l_red"), ("body", "hood_r_red"),
    ("base_neg", "base_pos"), ("body", "base_neg"), ("body", "base_pos"),
    ("body", "aperture_red_blank"), ("led_carrier_red", "lid"),
]
for a, bna in PAIRS:
    try:
        inter = trimesh.boolean.intersection([m[a], m[bna]])
        vol = 0.0 if inter is None or len(inter.faces) == 0 else abs(inter.volume)
    except Exception as e:
        vol = float("nan")
    check(f"{a} × {bna}", vol < 1e-4, f"(V={vol:.2e} mm³)")

# ================================================================ 10. bambu
print("=== 10. Bambu package ===")
sl = trimesh.load(os.path.join(BAMBU, "05_can_truot_nam_cham.stl"))
bb = sl.bounds
h = bb[1][2] - bb[0][2]
check("bambu slider height ~5.3 (prints flat)", abs(h - 5.3) < 0.1, f"(h={h:.2f})")
expect(sl, (8.0, 7.2, 4.5), False, "bambu slider pocket opens UP (void near top)")
expect(sl, (8.0, 7.2, 1.0), True, "bambu slider floor solid")
combo = os.path.join(BAMBU, "00_ppg_hop_toi_A1_all_in_one.stl")
check("all-in-one exists", os.path.isfile(combo),
      f"({os.path.getsize(combo) / 1e6:.1f} MB)" if os.path.isfile(combo) else "")

# ================================================================ summary
print("=" * 70)
if fails:
    print(f"RESULT: {len(fails)} CHECK(S) FAILED out of {npass + len(fails)}")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print(f"RESULT: ALL {npass} CHECKS PASSED")
