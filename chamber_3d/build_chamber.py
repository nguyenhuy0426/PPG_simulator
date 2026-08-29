#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parametric dark optical chamber (buồng tối) for the PPG simulator
(Raspberry Pi + dual MCP4725 LED driver + 2x OPT101 -> Grove Base HAT A0=IR, A2=Red).

Single source of truth for the 3D-printed chamber. Generates:
  out/stl/*.stl          one printable STL per part (print-oriented)
  out/model.json         colored assembly for the web viewer (base64 buffers)
  viewer.html            self-contained three.js viewer (works offline, double-click)

Units: millimetres. Axis convention (assembly/world frame):
  +X : optical axis, LED wall (left) -> OPT101 wall (right)
  +Y : up (Red chamber on top, IR chamber below — like the concept sketch)
  +Z : front (aperture plates drop into floor channels, lid closes on top)

Run:  .cad_venv/bin/python build_chamber.py [--budget-only]
Requires: trimesh + manifold3d + numpy (see ../.cad_venv)
"""
import argparse
import base64
import json
import math
import os

import numpy as np
import trimesh
from trimesh.transformations import rotation_matrix, translation_matrix

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
STL_DIR = os.path.join(OUT, "stl")

# ----------------------------------------------------------------------------
# 1. PARAMETERS (all mm) — edit here, everything re-derives
# ----------------------------------------------------------------------------
WALL = 3.0            # outer wall thickness (opaque, >= 2.4 mm for light tightness)
L_IN = 100.0          # interior optical-axis length (LED wall face -> window plane)
CH_H = 26.0           # interior height of each chamber
DIV = 3.0             # central divider thickness (floor-to-ceiling isolation)
D_IN = 30.0           # interior depth (Z)
DUCT_W = 10.0         # wiring duct depth behind the right wall (incl. outer skin)
FEET_H = 2.0

# Derived frame
X0 = 0.0                       # left outer face
X_LW = WALL                    # interior face of LED wall (optical x=0)
X1 = X_LW + L_IN               # OPT101 window plane (interior face of right wall)
X_RW = X1 + WALL               # outer face of right wall / duct start
X_SKIN = X_TOT = X_RW + DUCT_W # total outer length (duct: X_RW..X_TOT)
DUCT_X1 = X_TOT - 3.4          # duct interior end (outer skin stays 3.4 mm sealed)

Y0 = 0.0
Y_FL = WALL                    # floor top face
CH_RED_Y0 = Y_FL               # Red chamber (top):  y in [3, 29]
CH_RED_Y1 = CH_RED_Y0 + CH_H
Y_DIV0 = CH_RED_Y1
Y_DIV1 = Y_DIV0 + DIV
CH_IR_Y0 = Y_DIV1              # IR chamber (bottom): y in [32, 58]
CH_IR_Y1 = CH_IR_Y0 + CH_H
Y_CEIL0 = CH_IR_Y1
Y_TOT = Y_CEIL0 + WALL         # top outer face

Z0 = 0.0
Z_F0 = WALL                    # back?? no: front wall inner face
Z1 = Z_F0 + D_IN               # back wall inner face
Z_TOT = Z1 + WALL

ZC = (Z_F0 + Z1) / 2.0         # optical axis Z
RED_CY = (CH_RED_Y0 + CH_RED_Y1) / 2.0
IR_CY = (CH_IR_Y0 + CH_IR_Y1) / 2.0

# Recommended optical distances (LED dome tip -> OPT101 window face), from budget
RED_D_DEFAULT = 25.0
IR_D_DEFAULT = 85.0

# Aperture plate geometry (defined before the rail so the rail can stop before it)
AP_X = 95.0                    # aperture plate plane (plate occupies AP_X-1.6..AP_X);
                                # placed close to the sensor window so every LED
                                # position (d=15..85) is behind it → effective
                                # field-stop against stray light.
AP_T = 1.6
AP_CH = 1.9                    # floor channel depth that captures the plate
AP_W = 26.0                    # plate width (Z)

RAIL_W = 8.0
RAIL_H = 4.0
RAIL_X0 = 6.0
RAIL_X1 = AP_X - 3.0          # rail stops before the aperture-plate floor slot
DETENT_STEP = 5.0
DETENT_X0 = 15.0
DETENT_X1 = 85.0

CARRIER_L = 12.0               # LED slider block length (X)
CARRIER_H = 18.0               # sits on rail top, LED axis at +9
LED_AXIS_UP = 9.0              # LED axis height inside carrier (local Y)
DOME_OUT = 1.0                 # dome protrusion beyond carrier front face

WIRES_X0 = 8.0                 # wire lane along the back floor corner
WIRES_X1 = AP_X - 4.0          # wire cover stops before the aperture plate
LANE_W = 4.4                   # wire cover lane width (Z)
LANE_GAP = 1.6                 # wire gap under the cover plate

CLEAR = 0.25

CHAMBERS = {                   # name: (optical-axis Y, floor Y of that chamber)
    "red": (RED_CY, Y_FL),              # Red chamber: BUỒNG TRÊN (y 3..29)
    "ir": (IR_CY, CH_IR_Y0),            # IR chamber: BUỒNG DƯỚI (y 32..58)
}


def floor_y(ch):
    return CHAMBERS[ch][1]

# ----------------------------------------------------------------------------
# 2. MESH PRIMITIVES (manual, deterministic orientation; then fix_normals)
# ----------------------------------------------------------------------------
def _finish(m):
    trimesh.repair.fix_normals(m, multibody=False)
    return m


def _tube(axis, a0, a1, c1, c2, r, n=40, r2=None):
    """Cylinder/frustum along 'axis' from a0..a1, center (c1,c2) on the other two axes.
    r2 -> frustum (radius r at a0, r2 at a1). Vertex generation is axis-direct."""
    r2 = r if r2 is None else r2
    lo, hi = min(a0, a1), max(a0, a1)

    def pt(a, rr, t):
        u, v = c1 + rr * math.cos(t), c2 + rr * math.sin(t)
        return {"x": [a, u, v], "y": [u, a, v], "z": [u, v, a]}[axis]

    verts = [pt(lo, r, 2 * math.pi * i / n) for i in range(n)]
    verts += [pt(hi, r2, 2 * math.pi * i / n) for i in range(n)]
    verts += [pt(lo, 0, 0), pt(hi, 0, 0)]
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, n + j, n + i])          # side
        faces.append([i, j, n + j])              # side
        faces.append([2 * n, j, i])              # cap at lo
        faces.append([2 * n + 1, n + i, n + j])  # cap at hi
    m = trimesh.Trimesh(vertices=np.array(verts, dtype=np.float64),
                        faces=np.array(faces), process=True)
    _finish(m)
    return m


def box(x0, x1, y0, y1, z0, z1):
    return trimesh.creation.box(
        extents=[abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)],
        transform=translation_matrix([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]))


def cyl_x(x0, x1, yc, zc, r, n=40):
    return _tube("x", x0, x1, yc, zc, r, n)


def cyl_y(y0, y1, xc, zc, r, n=40):
    return _tube("y", y0, y1, xc, zc, r, n)


def cyl_z(z0, z1, xc, yc, r, n=40):
    return _tube("z", z0, z1, xc, yc, r, n)


def frustum_x(x0, x1, yc, zc, r0, r1, n=40):
    return _tube("x", x0, x1, yc, zc, r0, n, r2=r1)


def uni(meshes):
    return trimesh.boolean.union(list(meshes))


def dif(a, bs):
    return trimesh.boolean.difference([a] + list(bs))


# ----------------------------------------------------------------------------
# 3. PARTS
# ----------------------------------------------------------------------------
def build_body():
    m = box(X0, X_TOT, Y0, Y_TOT, Z0, Z_TOT)
    m = dif(m, [box(X_LW, X1, CH_RED_Y0, CH_RED_Y1, Z_F0, Z1),
                box(X_LW, X1, CH_IR_Y0, CH_IR_Y1, Z_F0, Z1)])
    # wiring duct behind the right wall (fully internal; exits through floor ports)
    m = dif(m, [box(X_RW, DUCT_X1, Y_FL, Y_CEIL0, Z_F0, Z1)])

    # ---- lid labyrinth groove (fully inside each wall footprint => no light path)
    g = []
    for (a0, a1) in [(0.3, 2.7), (X_TOT - 2.7, X_TOT - 0.3)]:
        g.append(box(a0, a1, Y_TOT - 4.0, Y_TOT, Z0, Z_TOT))
    for (c0, c1) in [(0.3, 2.7), (Z_TOT - 2.7, Z_TOT - 0.3)]:
        g.append(box(X0, X_TOT, Y_TOT - 4.0, Y_TOT, c0, c1))
    m = dif(m, [uni(g)])

    # NOTE: no LED press hole in the left wall. The LED lives on a sliding
    # carrier INSIDE the chamber (held by the rail); a wall hole would only
    # leak ambient light into the dark chamber.
    for ch, (cy, seat) in CHAMBERS.items():
        rail = box(RAIL_X0, RAIL_X1, seat, seat + RAIL_H,
                   ZC - RAIL_W / 2, ZC + RAIL_W / 2)
        notches = []
        # carrier spring tabs sit 9..4 mm behind its front face, i.e. tab center
        # at X1 - DOME_OUT - 6.5 - d for each distance position d
        for d in range(int(DETENT_X0), int(DETENT_X1) + 1, int(DETENT_STEP)):
            x = X1 - DOME_OUT - 6.5 - d
            for sgn in (-1, 1):
                notches.append(box(x - 0.6, x + 0.6, seat + 1.4, seat + RAIL_H,
                                   ZC + sgn * RAIL_W / 2 + (0 if sgn < 0 else -0.9),
                                   ZC + sgn * RAIL_W / 2 + (0.9 if sgn < 0 else 0)))
        rail = dif(rail, notches)
        m = uni([m, rail])

    # ---- OPT101 pocket + pin pass-through into the duct (one per chamber)
    for cy in (RED_CY, IR_CY):
        m = dif(m, [box(X1 - 2.0, X1, cy - 5.2, cy + 5.2, ZC - 4.6, ZC + 4.6)])
        holes = []
        for dy in (-3.81, -1.27, 1.27, 3.81):
            for dz in (-3.81, 3.81):
                holes.append(cyl_x(X1 - 2.2, DUCT_X1, cy + dy, ZC + dz, 0.55, 24))
        m = dif(m, holes)
        # countersink funnel around the sensor window (secondary stray-light baffle)
        m = dif(m, [frustum_x(X1 - 1.4, X1, cy, ZC, 6.4, 4.9, 40)])

    # ---- aperture-plate floor channel (one per chamber, drops in before lid)
    for cy, seat in CHAMBERS.values():
        m = dif(m, [box(AP_X - 8.0, AP_X + 8.0, seat - AP_CH + 0.0, seat,
                        ZC - AP_W / 2, ZC + AP_W / 2)])

    # ---- floor scale ticks every 10 mm (distance measured from window plane)
    ticks = []
    for d in range(15, 90, 10):
        x = X1 - d
        for ch, (cy, seat) in CHAMBERS.items():
            ticks.append(box(x - 0.4, x + 0.4, seat, seat + 0.6,
                             ZC + RAIL_W / 2 + 1.0, ZC + RAIL_W / 2 + 7.0))
    m = dif(m, ticks)

    # ---- wire lane: pass-through from chamber floor into the duct (per chamber)
    for ch, (cy, seat) in CHAMBERS.items():
        m = dif(m, [box(X1 - 0.5, DUCT_X1, seat + 0.3, seat + 2.4,
                        Z1 - LANE_W + 0.3, Z1 - 0.3)])

    # ---- duct floor ports (wires drop to the base tray)
    m = dif(m, [box(X_RW + 2.0, DUCT_X1 - 1.0, Y0 - 0.1, Y_FL + 0.1, Z_F0 + 5.0, Z1 - 5.0)])

    # ---- feet with M3 clearance through-holes
    feet_pos = [(6.0, 6.0), (6.0, Z_TOT - 6.0), (X_RW - 6.0, 6.0), (X_RW - 6.0, Z_TOT - 6.0)]
    m = uni([m, *[box(fx - 4, fx + 4, Y0 - FEET_H, Y0, fz - 4, fz + 4) for fx, fz in feet_pos]])
    m = dif(m, [cyl_y(Y0 - FEET_H - 0.1, Y0 + 2.0, fx, fz, 1.6, 24) for fx, fz in feet_pos])
    return m


def build_lid():
    m = box(X0, X_TOT, Y_TOT, Y_TOT + 3.0, Z0, Z_TOT)
    t = []
    for (a0, a1) in [(0.55, 2.45), (X_TOT - 2.45, X_TOT - 0.55)]:
        t.append(box(a0, a1, Y_TOT - 3.6, Y_TOT, Z0, Z_TOT))
    for (c0, c1) in [(0.55, 2.45), (Z_TOT - 2.45, Z_TOT - 0.55)]:
        t.append(box(X0, X_TOT, Y_TOT - 3.6, Y_TOT, c0, c1))
    m = uni([m, uni(t)])
    m = dif(m, [box(X0 + 30.0, X0 + 50.0, Y_TOT - 0.6, Y_TOT + 3.0,
                    Z_TOT - 12.0, Z_TOT + 0.1)])  # finger notch
    return m


def build_led_carrier():
    """Local frame: front face at x=0 (dome side +X), rides rail at local y<0."""
    m = box(-CARRIER_L, 0.0, 0.0, CARRIER_H, -6.5, 6.5)
    m = dif(m, [box(-CARRIER_L + 1.0, -0.5, -RAIL_H - CLEAR, -0.01,
                    -RAIL_W / 2 - CLEAR, RAIL_W / 2 + CLEAR)])
    # LED bore through dome region AND shade collar, flange pocket, stop ring
    m = dif(m, [cyl_x(-4.9, 4.2, LED_AXIS_UP, 0.0, 1.6, 40),
                cyl_x(-6.6, -4.9, LED_AXIS_UP, 0.0, 2.3, 40),
                cyl_x(-6.8, -6.6, LED_AXIS_UP, 0.0, 2.6, 40)])
    # 45-degree shade collar in front of the dome
    m = uni([m, frustum_x(0.0, 4.0, LED_AXIS_UP, 0.0, 5.2, 1.9, 40)])
    # spring detent tabs pressing the rail sides (local y within the channel zone)
    for sgn in (-1, 1):
        m = uni([m, box(-9.0, -4.0, -3.8, -0.6,
                        sgn * (RAIL_W / 2 + CLEAR - 0.2), sgn * (RAIL_W / 2 + CLEAR + 1.0))])
    # wire exit notch at the rear face bottom
    m = dif(m, [box(-CARRIER_L, -CARRIER_L + 6.0, 0.0, 4.5, -6.6, -4.5)])
    # orientation groove on top (marks the dome direction)
    m = dif(m, [box(-3.0, -1.0, CARRIER_H - 1.2, CARRIER_H + 0.1, -1.0, 1.0)])
    return m


def _place_carrier(ch):
    cy, seat = CHAMBERS[ch]
    d = RED_D_DEFAULT if ch == "red" else IR_D_DEFAULT
    x_front = X1 - d - DOME_OUT
    m = build_led_carrier()
    m.apply_transform(translation_matrix([x_front, seat + RAIL_H, ZC]))
    return m


def build_aperture_plate(hole_y_world, kind):
    """Plate standing in the floor channel; hole centered on the optical axis.
    Bottom AP_CH into the floor slot (captured), top 0.6 mm under the ceiling."""
    cy, seat = hole_y_world
    H = CH_H - 0.6 + AP_CH          # 27.3 mm tall; drops into the 1.9 mm channel
    m = box(-AP_T, 0.0, 0.0, H, -AP_W / 2, AP_W / 2)
    yloc = cy - seat + AP_CH        # hole center above plate bottom → world y = cy
    if kind == "d2":
        m = dif(m, [cyl_x(-AP_T - 0.1, 0.1, yloc, 0.0, 1.0, 32)])
    elif kind == "d5":
        m = dif(m, [cyl_x(-AP_T - 0.1, 0.1, yloc, 0.0, 2.5, 40)])
    elif kind == "open":
        m = dif(m, [cyl_x(-AP_T - 0.1, 0.1, yloc, 0.0, 8.0, 48)])
    m.apply_transform(translation_matrix([AP_X, seat - AP_CH, ZC]))
    return m


def build_wire_cover(seat):
    """Snaps over the wire lane at the back floor corner (wire runs under it)."""
    L = WIRES_X1 - WIRES_X0
    m = box(0.0, L, LANE_GAP, LANE_GAP + 1.4, -LANE_W / 2, LANE_W / 2)
    m = uni([m, box(0.5, L - 0.5, 0.0, LANE_GAP, -LANE_W / 2, -LANE_W / 2 + 0.8)])
    m = uni([m, box(0.5, L - 0.5, 0.0, LANE_GAP, LANE_W / 2 - 0.8, LANE_W / 2)])
    m.apply_transform(translation_matrix([WIRES_X0, seat, Z1 - LANE_W / 2]))
    return m


def build_base_tray():
    """Electronics tray under the chamber: driver perfboard + Grove HAT stand."""
    PW, PD = 104.0, 40.0
    m = box(0.0, PW, 0.0, 3.0, 0.0, PD)
    m = uni([m, box(0.0, PW, 0.0, 8.0, 0.0, 3.0)])
    m = uni([m, box(0.0, PW, 0.0, 8.0, PD - 3.0, PD)])
    m = uni([m, box(0.0, 3.0, 0.0, 8.0, 0.0, PD)])
    m = uni([m, box(PW - 3.0, PW, 0.0, 8.0, 0.0, PD)])
    feet_pos = [(6.0, 6.0), (6.0, Z_TOT - 6.0), (X_RW - 6.0, 6.0), (X_RW - 6.0, Z_TOT - 6.0)]
    for fx, fz in feet_pos:
        m = uni([m, cyl_y(3.0, 11.0, fx, fz, 4.0, 40)])
        m = dif(m, [cyl_y(3.0, 11.2, fx, fz, 1.4, 24)])
    m = uni([m, box(14.0, 90.0, 3.0, 5.0, 9.0, 10.5)])
    m = uni([m, box(14.0, 90.0, 3.0, 5.0, PD - 15.0, PD - 13.5)])
    return m


def _sphere(r, cx, cy, cz, subdivisions=2):
    """Closed icosphere used for LED dome (rear half is hidden by the opaque body)."""
    s = trimesh.creation.icosphere(subdivisions=subdivisions, radius=r)
    s.apply_translation([cx, cy, cz])
    return s


def build_led(ch):
    """3.3 mm LED in carrier-local frame (axis y=LED_AXIS_UP, z=0; dome tip at x=+1.0).
    Returns [(mesh,color[,opacity]), ...] sub-components — purchased part, visual only."""
    ay = LED_AXIS_UP
    r = 1.65
    dome = _sphere(r, 1.0 - r, ay, 0.0)   # tip at x = +1.0 (DOME_OUT)
    body = uni([dome,
                cyl_x(-4.3, 1.0 - r, ay, 0.0, r, 40),       # epoxy body Ø3.3
                cyl_x(-6.6, -4.3, ay, 0.0, 2.3, 40),         # shoulder (bore Ø4.6)
                cyl_x(-6.8, -6.6, ay, 0.0, 2.6, 40)])        # stop ring (bore Ø5.2)
    leads = uni([box(-16.0, -6.8, ay + dy - 0.2, ay + dy + 0.2, -0.2, 0.2)
                 for dy in (-1.27, 1.27)])                   # 2 leads poke out the carrier back
    if ch == "red":
        bc, dc = 0xcc2222, 0xff9090
    else:
        bc, dc = 0x2e2150, 0xa884e8
    return [(body, bc), (dome, dc, 0.35), (leads, 0xd4a017)]


def build_opt101(cy):
    """OPT101 (DIP-8) in world frame: window at X1 facing -X (toward LED), body sits in
    the pocket, 8 pins pass through the wall into the duct. Visual only."""
    body = box(X1 - 3.2, X1, cy - 4.25, cy + 4.25, ZC - 3.5, ZC + 3.5)
    window = box(X1 - 0.15, X1 + 0.2, cy - 1.145, cy + 1.145,
                 ZC - 1.145, ZC + 1.145)                     # photodiode 2.29×2.29
    pins = uni([box(X1 - 3.2, X1 + 2.8, cy + dy - 0.25, cy + dy + 0.25,
                    ZC + dz - 0.25, ZC + dz + 0.25)
                for dy in (-3.81, -1.27, 1.27, 3.81)
                for dz in (-3.81, 3.81)])
    return [(body, 0x1d1d24), (window, 0x66ccff, 0.95), (pins, 0xd4a017)]


def _place_led(ch):
    """Translate the LED sub-components into world frame at its default distance d."""
    cy, seat = CHAMBERS[ch]
    d = RED_D_DEFAULT if ch == "red" else IR_D_DEFAULT
    x_front = X1 - d - DOME_OUT
    T = translation_matrix([x_front, seat + RAIL_H, ZC])
    out = []
    for m, c, *rest in build_led(ch):
        mm = m.copy()
        mm.apply_transform(T)
        out.append((mm, c, *rest))
    return out


# ----------------------------------------------------------------------------
# 4. OPTICAL BUDGET (datasheet numbers; graphical estimates flagged)
# ----------------------------------------------------------------------------
BUDGET = {
    "red": dict(
        lam="620-625 nm dominant (YSL-R341R3D-D2)",
        ie_uw_sr_at20ma=711.0,   # 175 mcd converted at V(622nm)=0.36 -> ~0.71 mW/sr
        r_v_per_uw=0.35,         # OPT101 @622 nm: graphical estimate (0.45 @650 tabulated)
        if_at_vdac=lambda v: v / 200.0,   # R6 = 100 ohm, divider /2
        area_cm2=(2.29 * 2.29) / 100.0,
    ),
    "ir": dict(
        lam="875 +/-45 nm (SIR234, typ bin M-ish 9 mW/sr)",
        ie_uw_sr_at20ma=9000.0,  # bins L..P: 5600..24000 uW/sr
        r_v_per_uw=0.49,         # OPT101 @875 nm: graphical estimate (near peak)
        if_at_vdac=lambda v: v / 164.0,   # R3 = 82 ohm
        area_cm2=(2.29 * 2.29) / 100.0,
    ),
}
V_CEIL = 2.13   # OPT101 output ceiling at VS = 3.28 V (VS - 1.15 V)
V_DARK = 0.0075


def rx_voltage(ch, v_dac, d_mm):
    b = BUDGET[ch]
    i_f = b["if_at_vdac"](v_dac)
    ie = b["ie_uw_sr_at20ma"] * (i_f / 0.020)
    e = ie / (d_mm / 10.0) ** 2
    return b["r_v_per_uw"] * e * b["area_cm2"] + V_DARK


def max_vdac_no_clip(ch, d_mm):
    lo, hi = 0.0, 3.28
    for _ in range(60):
        mid = (lo + hi) / 2
        if rx_voltage(ch, mid, d_mm) < V_CEIL:
            lo = mid
        else:
            hi = mid
    return lo


def print_budget():
    print("=" * 84)
    print("OPTICAL BUDGET (datasheet-derived; 622/875 nm responsivity = graphical est.)")
    print("=" * 84)
    ds = (15, 20, 25, 30, 40, 60, 85)
    for ch in ("red", "ir"):
        b = BUDGET[ch]
        print(f"\n[{ch.upper()}] {b['lam']}  Rv={b['r_v_per_uw']} V/uW  "
              f"Ie@20mA={b['ie_uw_sr_at20ma']} uW/sr  A={b['area_cm2']:.3f} cm2")
        print(f"{'Vdac':>6} {'I_LED':>8} " + "".join(f"d={d:>4}mm".rjust(10) for d in ds))
        for vd in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
            row = "".join(f"{rx_voltage(ch, vd, d):10.3f}" for d in ds)
            print(f"{vd:6.2f} {b['if_at_vdac'](vd)*1000:7.2f}m {row}")
        print(f"  ceiling {V_CEIL} V reached at: "
              + ", ".join(f"d={d} -> Vdac<={max_vdac_no_clip(ch, d):.2f} V" for d in (25, 85)))


# ----------------------------------------------------------------------------
# 5. EXPORT
# ----------------------------------------------------------------------------
def collect_parts():
    parts = []

    def add(name, mesh, color, explode, flip=False, label=None, subs=None, printable=True):
        parts.append(dict(name=name, mesh=mesh, color=color, explode=explode, flip=flip,
                          label=label or name, subs=subs, printable=printable))

    add("body", build_body(), 0x27303f, [0, 0, 0], label="Thân buồng (2 khoang)")
    add("lid", build_lid(), 0x3b4656, [0, 30, 0], flip=True, label="Nắp labyrinth")
    add("led_carrier_red", _place_carrier("red"), 0x9c2626, [-34, 0, 0], flip=True,
        label="Carrier LED Đỏ")
    add("led_carrier_ir", _place_carrier("ir"), 0x2a3fad, [-34, 0, 0], flip=True,
        label="Carrier LED IR")
    # Purchased components — shown in the viewer, NOT exported to STL
    for ch, nm, lbl, dfl in (("red", "led_red", "LED Đỏ 622nm", 0xcc2222),
                             ("ir", "led_ir", "LED IR 875nm", 0x8a5cf0)):
        subs = _place_led(ch)
        add(nm, None, dfl, [-34, 0, 0], label=lbl, printable=False,
            subs=[dict(mesh=s[0], color=s[1], **({"opacity": s[2]} if len(s) > 2 else {}))
                  for s in subs])
    for ch, nm, lbl in (("red", "opt101_red", "OPT101 #2 — Đỏ → A2"),
                        ("ir", "opt101_ir", "OPT101 #1 — IR → A0")):
        subs = build_opt101(CHAMBERS[ch][0])
        add(nm, None, subs[0][1], [34, 0, 0], label=lbl, printable=False,
            subs=[dict(mesh=s[0], color=s[1], **({"opacity": s[2]} if len(s) > 2 else {}))
                  for s in subs])
    for kind, kl in (("blank", "bịt kín"), ("d2", "Ø2 mm"), ("d5", "Ø5 mm"), ("open", "Ø16 mm")):
        for ch in ("red", "ir"):
            add(f"aperture_{ch}_{kind}", build_aperture_plate(CHAMBERS[ch], kind),
                0x3c4554, [0, 0, 30], label=f"Khẩu độ {'Đỏ' if ch=='red' else 'IR'} {kl}")
    add("wire_cover_red", build_wire_cover(CHAMBERS["red"][1]), 0x2c3540, [0, 34, 0], flip=True,
        label="Nắp rãnh dây Đỏ")
    add("wire_cover_ir", build_wire_cover(CHAMBERS["ir"][1]), 0x2c3540, [0, 34, 0], flip=True,
        label="Nắp rãnh dây IR")
    add("base_tray", build_base_tray(), 0x4a5566, [0, -20, 0], label="Khay điện tử")
    return parts


def export(parts):
    os.makedirs(STL_DIR, exist_ok=True)
    model = dict(units="mm", parts=[])
    for p in parts:
        subs = p.get("subs") or [dict(mesh=p["mesh"], color=p["color"])]
        if p.get("printable", True):
            stl = (p["mesh"] or subs[0]["mesh"]).copy()
            if p.get("flip"):
                stl.apply_transform(rotation_matrix(math.pi, [1, 0, 0], point=[0, 0, 0]))
            stl.export(os.path.join(STL_DIR, p["name"] + ".stl"))
        subdata, allb = [], None
        for s in subs:
            mesh = s["mesh"]
            v = np.asarray(mesh.vertices, dtype=np.float32)
            f = np.asarray(mesh.faces, dtype=np.uint32)
            d = dict(color=s["color"],
                     vbase64=base64.b64encode(v.tobytes()).decode("ascii"),
                     fbase64=base64.b64encode(f.tobytes()).decode("ascii"))
            if "opacity" in s:
                d["opacity"] = s["opacity"]
            subdata.append(d)
            b = mesh.bounds.reshape(-1)
            allb = [float(x) for x in b] if allb is None else [
                min(float(allb[i]), float(b[i])) if i % 2 == 0 else max(float(allb[i]), float(b[i])) for i in range(6)]
        model["parts"].append(dict(name=p["name"], label=p.get("label", p["name"]),
                                   color=subdata[0]["color"], explode=p["explode"],
                                   subs=subdata, bounds=[float(x) for x in allb]))
        if p.get("printable", True):
            m0 = p["mesh"] or subs[0]["mesh"]
            ok = "watertight" if m0.is_watertight else "!! NOT WATERTIGHT"
            print(f"  {p['name']:<22} tris={len(m0.faces):>6}  {ok}")
        else:
            print(f"  {p['name']:<22} (visual, {len(subs)} sub-materials)  — not exported to STL")
    with open(os.path.join(OUT, "model.json"), "w") as fh:
        json.dump(model, fh)
    print(f"  model.json: {os.path.getsize(os.path.join(OUT, 'model.json'))/1e6:.1f} MB")


# ----------------------------------------------------------------------------
# 6. VIEWER
# ----------------------------------------------------------------------------
VIEWER_TEMPLATE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>Buồng tối PPG — OPT101 hai kênh (duyệt mô hình 3D)</title>
<style>
 :root{--bg:#0d0f13;--panel:#161a22;--ink:#dfe5ee;--dim:#8b94a6;--acc:#e8b64c;}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,'Segoe UI',Roboto,sans-serif;overflow:hidden}
 #view{position:fixed;inset:0}
 .panel{position:fixed;top:12px;left:12px;width:290px;max-height:calc(100vh - 24px);overflow:auto;
   background:var(--panel);border:1px solid #2a3140;border-radius:12px;padding:14px 16px;
   box-shadow:0 8px 30px rgba(0,0,0,.5)}
 h1{font-size:15px;margin:0 0 2px} .sub{color:var(--dim);font-size:12px;margin-bottom:10px}
 .row{display:flex;align-items:center;gap:8px;margin:8px 0}
 .row label{flex:1;font-size:13px}
 input[type=range]{flex:1.4;accent-color:var(--acc)}
 button{background:#232a38;border:1px solid #35405a;color:var(--ink);border-radius:8px;
   padding:5px 10px;cursor:pointer;font-size:12.5px;margin:2px}
 button:hover{background:#2c3549} button.on{background:var(--acc);color:#111;border-color:var(--acc)}
 fieldset{border:1px solid #2a3140;border-radius:10px;margin:10px 0;padding:8px 10px}
 legend{color:var(--dim);font-size:12px;padding:0 4px}
 .part{display:flex;align-items:center;gap:8px;padding:2.5px 0;font-size:13px}
 .sw{width:13px;height:13px;border-radius:4px;border:1px solid #0008;flex:none}
 .hint{color:var(--dim);font-size:11.5px;margin-top:10px;line-height:1.5}
 #hud{position:fixed;right:14px;bottom:12px;color:var(--dim);font-size:12px}
</style>
</head>
<body>
<div id="view"></div>
<div class="panel">
  <h1>Buồng tối PPG — duyệt mô hình 3D</h1>
  <div class="sub">Hai buồng cách quang: Đỏ 622nm / IR 875nm → 2× OPT101<br>
  <span style="color:#ff6060">■</span> LED Đỏ &nbsp; <span style="color:#8a5cf0">■</span> LED IR &nbsp;
  <span style="color:#66ccff">■</span> cửa sổ OPT101</div>
  <div class="row"><label>Tách rời (exploded)</label><input id="explode" type="range" min="0" max="100" value="0"></div>
  <div class="row"><label>Mặt cắt theo X</label><input id="clip" type="range" min="0" max="100" value="100"></div>
  <div class="row">
    <button id="bTrans">Trong suốt thân</button>
    <button id="bWire">Khung lưới</button>
    <button id="bAxes">Trục quang</button>
  </div>
  <div class="row">
    <button id="bAuto">Tự xoay</button>
    <button data-v="iso">Góc iso</button><button data-v="front">Trước</button>
  </div>
  <div class="row">
    <button data-v="top">Trên</button>
    <button data-v="inIR">Trong buồng IR</button><button data-v="inRed">Trong buồng Đỏ</button>
  </div>
  <fieldset><legend>Bộ phận (bấm để ẩn/hiện)</legend><div id="parts"></div></fieldset>
  <div class="hint">
    Kéo chuột: xoay • Lăn chuột: thu phóng • Chuột phải: di chuyển.<br>
    <b>Mặt cắt</b>: trượt để cắt hộp theo phương X, nhìn inside buồng.<br>
    <b>Tách rời</b>: kéo để xem thứ tự lắp ráp.<br>
    Kích thước tổng thể <b>__DIM__ mm</b> (đơn vị mô hình: mm).<br>
    Bĕ xa mēt: Đỏ d=25mm • IR d=85mm (đo từ chóp LED đến mặt cửa sổ OPT101).
  </div>
</div>
<div id="hud">chamber_3d / build_chamber.py</div>
<script>/* three.js r147 (inlined, MIT) */__THREE__</script>
<script>/* OrbitControls (inlined, MIT) */__ORBIT__</script>
<script>const MODEL = __MODEL__;</script>
<script>
function b64f32(b){const s=atob(b),n=s.length/4,a=new Float32Array(n);
 for(let i=0;i<n;i++){const o=4*i;
   a[i]=(s.charCodeAt(o)|(s.charCodeAt(o+1)<<8)|(s.charCodeAt(o+2)<<16)|(s.charCodeAt(o+3)<<24));}
 return a}
function b64u32(b){const s=atob(b),n=s.length/4,a=new Uint32Array(n);
 for(let i=0;i<n;i++){const o=4*i;
   a[i]=(s.charCodeAt(o)|(s.charCodeAt(o+1)<<8)|(s.charCodeAt(o+2)<<16)|(s.charCodeAt(o+3)<<24));}
 return a}
const scene=new THREE.Scene();scene.background=new THREE.Color(0x12151b);
const camera=new THREE.PerspectiveCamera(42,innerWidth/innerHeight,0.5,4000);
const renderer=new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setSize(innerWidth,innerHeight);
renderer.localClippingEnabled=true;document.getElementById('view').appendChild(renderer.domElement);
const key=new THREE.DirectionalLight(0xffffff,1.2);key.position.set(120,180,140);scene.add(key);
const fill=new THREE.DirectionalLight(0x9db4ff,.55);fill.position.set(-140,-60,-120);scene.add(fill);
const rim=new THREE.DirectionalLight(0xffc46a,.4);rim.position.set(-80,130,-110);scene.add(rim);
scene.add(new THREE.AmbientLight(0xffffff,.6));
const controls=new THREE.OrbitControls(camera,renderer.domElement);
controls.enableDamping=true;controls.dampingFactor=.08;
const bb=new THREE.Box3();
MODEL.parts.forEach(p=>{bb.expandByPoint(new THREE.Vector3(p.bounds[0],p.bounds[1],p.bounds[2]));
  bb.expandByPoint(new THREE.Vector3(p.bounds[3],p.bounds[4],p.bounds[5]))});
const ctr=bb.getCenter(new THREE.Vector3()),rad=bb.getSize(new THREE.Vector3()).length()/2;
const partsGroup=new THREE.Group();scene.add(partsGroup);
const meshes={},basePos={};
const clipPlane=new THREE.Plane(new THREE.Vector3(-1,0,0),1e6);
MODEL.parts.forEach(p=>{
  const grp=new THREE.Group();
  (p.subs||[{color:p.color,vbase64:p.vbase64,fbase64:p.fbase64}]).forEach(s=>{
    const g=new THREE.BufferGeometry();
    g.setAttribute('position',new THREE.BufferAttribute(b64f32(s.vbase64),3));
    g.setIndex(new THREE.BufferAttribute(b64u32(s.fbase64),1));
    g.computeVertexNormals();
    const trans=!!s.opacity&&s.opacity<1;
    const mat=new THREE.MeshStandardMaterial({color:new THREE.Color(s.color),
      roughness:.75,metalness:.15,side:trans?THREE.FrontSide:THREE.DoubleSide,
      clippingPlanes:[clipPlane],transparent:trans,opacity:s.opacity||1,
      depthWrite:!trans});
    grp.add(new THREE.Mesh(g,mat));
  });
  grp.userData.explode=new THREE.Vector3(...p.explode);
  partsGroup.add(grp);meshes[p.name]=grp;basePos[p.name]=new THREE.Vector3();
});
// optical axis helpers
const axesGroup=new THREE.Group();scene.add(axesGroup);axesGroup.visible=false;
function axisLine(y,col,label){
  const g=new THREE.BufferGeometry().setFromPoints(
    [new THREE.Vector3(3,y,18),new THREE.Vector3(103,y,18)]);
  axesGroup.add(new THREE.Line(g,new THREE.LineBasicMaterial({color:col})));
  const cv=document.createElement('canvas');cv.width=512;cv.height=64;const ctx=cv.getContext('2d');
  ctx.font='bold 30px system-ui';ctx.fillStyle='#'+col.toString(16).padStart(6,'0');
  ctx.fillText(label,6,42);
  const sp=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(cv),depthTest:false}));
  sp.scale.set(46,5.8,1);sp.position.set(126,y,18);axesGroup.add(sp);
}
axisLine(16,0xff5555,'Đỏ 622nm → OPT101 → A2 (d=25mm)');
axisLine(45,0x6688ff,'IR 875nm → OPT101 → A0 (d=85mm)');
const grid=new THREE.GridHelper(280,28,0x223,0x1a2030);
grid.position.set(58,-2.5,18);scene.add(grid);
function setView(v){
  const d=rad*1.5;
  if(v==="inIR"){camera.position.set(18,45,18);controls.target.set(103,45,18);}
  else if(v==="inRed"){camera.position.set(18,16,18);controls.target.set(103,16,18);}
  else{
    const P={iso:[ctr.x+d*.8,ctr.y+d*.65,ctr.z+d*.9],
             front:[ctr.x+d*1.05,ctr.y,ctr.z+d*1.25],
             top:[ctr.x,ctr.y+d*1.7,ctr.z+1]};
    camera.position.set(...P[v]);controls.target.copy(ctr);}
  controls.update();
}
document.querySelectorAll('[data-v]').forEach(b=>b.onclick=()=>setView(b.dataset.v));
setView('iso');
const $=id=>document.getElementById(id);
$('explode').oninput=e=>{const k=e.target.value/100;
  for(const n in meshes)meshes[n].position.copy(basePos[n]).addScaledVector(meshes[n].userData.explode,k);};
$('clip').oninput=e=>{clipPlane.constant=1e-3+e.target.value/100*(118-1e-3);};
function wireAll(on){MODEL.parts.forEach(p=>meshes[p.name].children.forEach(m=>m.material.wireframe=on));}
$('bWire').onclick=e=>{const on=!meshes[MODEL.parts[0].name].children[0].material.wireframe;
  wireAll(on);e.target.classList.toggle('on',on);};
let bodyX=true;
function bodyOpacity(o){const m=meshes['body'].children[0].material;m.transparent=true;
  m.opacity=o;m.depthWrite=o>.9;m.side=o<1?THREE.FrontSide:THREE.DoubleSide;}
bodyOpacity(.55);
$('bTrans').onclick=e=>{bodyX=!bodyX;bodyOpacity(bodyX?.55:1);e.target.classList.toggle('on',bodyX);};
$('bTrans').classList.add('on');
let auto=false;$('bAuto').onclick=e=>{auto=!auto;e.target.classList.toggle('on',auto);};
$('bAxes').onclick=e=>{axesGroup.visible=!axesGroup.visible;e.target.classList.toggle('on',axesGroup.visible);};
const list=$('parts');
MODEL.parts.forEach(p=>{
  const cb=document.createElement('input');cb.type='checkbox';cb.checked=true;
  cb.onchange=()=>meshes[p.name].visible=cb.checked;
  const sw=document.createElement('span');sw.className='sw';
  sw.style.background='#'+p.color.toString(16).padStart(6,'0');
  const lab=document.createElement('span');lab.textContent=p.label||p.name;lab.style.flex='1';
  const row=document.createElement('div');row.className='part';row.append(cb,sw,lab);
  list.append(row);
});
addEventListener('resize',()=>{camera.aspect=innerWidth/innerHeight;
  camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);});
(function loop(){requestAnimationFrame(loop);
  if(auto){const t=Date.now()/3000;
    camera.position.set(ctr.x+rad*1.5*Math.cos(t),ctr.y+rad*.8,ctr.z+rad*1.5*Math.sin(t));
    camera.lookAt(ctr);}
  controls.update();renderer.render(scene,camera);})();
</script>
</body>
</html>
"""


def build_viewer():
    with open(os.path.join(HERE, "vendor", "three.min.js")) as f:
        three = f.read()
    with open(os.path.join(HERE, "vendor", "OrbitControls.js")) as f:
        orbit = f.read()
    with open(os.path.join(OUT, "model.json")) as f:
        model = f.read()
    html = (VIEWER_TEMPLATE
            .replace("__THREE__", three)
            .replace("__ORBIT__", orbit)
            .replace("__MODEL__", model)
            .replace("__DIM__", f"{X_TOT:.0f} × {Y_TOT + FEET_H:.0f} × {Z_TOT:.0f}"))
    path = os.path.join(HERE, "viewer.html")
    with open(path, "w") as f:
        f.write(html)
    print(f"  viewer.html: {os.path.getsize(path)/1e6:.1f} MB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-only", action="store_true")
    args = ap.parse_args()
    print_budget()
    if args.budget_only:
        return
    print("\nBuilding parts (manifold CSG) ...")
    parts = collect_parts()
    print("Exporting ...")
    export(parts)
    build_viewer()
    print("\nDone. Open chamber_3d/viewer.html in a browser.")


if __name__ == "__main__":
    main()
