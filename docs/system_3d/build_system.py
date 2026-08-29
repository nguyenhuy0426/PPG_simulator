#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_system.py — MÔ HÌNH 3D TOÀN HỆ THỐNG "PPG SIMULATOR" (nguồn duy nhất).

Sinh ra:
  out/stl/*.stl   — các chi tiết IN 3D được (đã xoay về tư thế in)
  out/model.json  — toàn bộ hình học (float32/uint32 base64) cho viewer
  viewer.html     — trình duyệt 3D offline (three.js nhúng sẵn)

HỆ TRỤC (mm):
  +X = trục quang, hướng từ đầu LED  ->  board cảm biến
  +Y = lên trên
  +Z = ngang; làn ĐỎ ở -Z, làn IR ở +Z, vách ngăn quang tại z = 0

TRẠNG THÁI BẰNG CHỨNG (bắt buộc đọc):
  [DS]   = lấy từ datasheet trong docs/ds_linhkien/
  [SPEC] = quy cách cơ khí công bố rộng rãi (Raspberry Pi HAT / Pi 4B)
  [ASSUME] = kích thước GIẢ ĐỊNH cho mục đích dựng hình — CHƯA đo trên vật thật
  Mọi số [ASSUME] phải được đo lại trên linh kiện thật trước khi in / gia công.
  Mô hình này là công cụ thiết kế & mô phỏng. Không phải thiết bị y tế,
  không có giá trị lâm sàng.
"""
import os, math, json, base64, argparse
import numpy as np
import trimesh
from trimesh.transformations import translation_matrix, rotation_matrix

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
STL_DIR = os.path.join(OUT, "stl")

# ============================================================================
# 1. THAM SỐ HÌNH HỌC  (đơn vị mm)
# ============================================================================
WALL = 3.0                     # bề dày vách hộp (đục quang, >= 2.4 mm)
CLR = 0.25                     # khe lắp ghép in 3D

# --- hộp tối -----------------------------------------------------------------
X0, X_TOT = 0.0, 150.0
X_IN0, X_IN1 = WALL, X_TOT - WALL          # 3 .. 147 (lòng hộp theo X)
Y0 = 0.0
Y_FL = WALL                                # 3  mặt sàn trong
Y_IN1 = 61.0                               # 61 đáy rãnh labyrinth
Y_TOP = 64.0                               # mặt trên thành hộp
LID_T = 3.0
Y_LID = Y_TOP + LID_T                      # 67
Z0, Z1 = -40.0, 40.0
Z_IN0, Z_IN1 = Z0 + WALL, Z1 - WALL        # -37 .. +37

SEPT_HW = 1.5                              # nửa bề dày vách ngăn quang (3 mm)
Y_AX = 32.0                                # trục quang
LANE_Z = {"red": -19.25, "ir": 19.25}      # tâm 2 làn quang
LANE_SIGN = {"red": -1.0, "ir": 1.0}

# --- trục trượt D-shaft + cột đỡ ---------------------------------------------
SH_Y = 14.0                                # tâm trục trượt
SH_R = 4.0                                 # Ø8 mm
SH_FLAT_Y = 16.5                           # mặt vát chống xoay (D-shaft)
SH_X0, SH_X1 = 1.0, 111.0                  # đuôi cắm vào lỗ mù ở vách trái
POST_X0, POST_X1 = 105.0, 111.0            # cột đỡ đầu trục
POST_TOP = 21.0                            # đỉnh cột (thấp hơn trục quang 12 mm)
POST_ZW = 12.0                             # bề rộng cột theo Z (chắn ít chùm tia)
TICK_X0, TICK_X1, TICK_STEP = 30.0, 105.0, 5.0

# --- carrier LED (khối trượt) ------------------------------------------------
CAR_L = 22.0                               # dài theo X (mặt trước = 0 cục bộ)
CAR_ZW = 18.0                              # rộng theo Z
CAR_Y0, CAR_Y1 = 5.0, 40.0
LED_TIP_OUT = 1.0                          # chóp LED nhô trước mặt carrier
COLLAR_L = 3.0                             # loa che sáng phía trước

D_MIN, D_MAX = 15.0, 90.0                  # dải khoảng cách LED -> cửa sổ OPT101
D_DEFAULT = {"red": 25.0, "ir": 85.0}

# --- khe khẩu độ (aperture) --------------------------------------------------
AP_T = 1.6
AP_X0, AP_X1 = 113.3, 115.1                # rãnh trượt (rộng 1.8 mm)
AP_RIB_T = 1.6                             # gân dẫn hướng nhô vào làn
AP_Y0, AP_Y1 = 1.9, 60.0                   # tấm cắm xuống rãnh sàn 1.1 mm

# --- mặt phẳng thu ------------------------------------------------------------
X_WIN = 120.0                              # mặt cửa sổ OPT101  (= mốc đo d)
DIP_T = 4.3                                # [DS] chiều cao thân PDIP-8 OPT101
X_MOD0 = X_WIN + DIP_T                     # 124.3 mặt trước PCB module
MOD_T = 1.2                                # [ASSUME] PCB module OPT101
X_MOD1 = X_MOD0 + MOD_T                    # 125.5
STANDOFF_L = 12.0                          # trụ nylon M2.5 module -> board
X_BF = X_MOD1 + STANDOFF_L                 # 137.5 mặt trước board 5x7
BRD_T = 1.6
X_BR = X_BF + BRD_T                        # 139.1 mặt sau board
FRM_X0, FRM_X1 = X_BF, 141.5               # khung giữ board
SEPT_R_X0 = FRM_X1                         # vách ngăn phía sau khung

# --- board cảm biến 5 x 7 cm --------------------------------------------------
BRD_Z, BRD_Y = 70.0, 50.0
BRD_Z0, BRD_Z1 = -BRD_Z / 2, BRD_Z / 2     # -35 .. 35
BRD_Y0, BRD_Y1 = Y_AX - BRD_Y / 2, Y_AX + BRD_Y / 2   # 7 .. 57

# --- lỗ ra cáp + chụp che sáng ------------------------------------------------
EX_Y0, EX_Y1 = 6.0, 16.0                   # lỗ xuyên vách
EX_ZW = 20.0                               # bề rộng lỗ theo Z
HOOD_D = 10.0                              # chiều sâu chụp ra ngoài vách
HOOD_T = 2.5                               # bề dày chụp
HOOD_Y0, HOOD_Y1 = 3.0, 24.0

# --- đế chung + khối điện tử ngoài --------------------------------------------
BASE_T = 4.0                               # bề dày tấm đế (mặt trên y = 0)
BASE_X0, BASE_X1 = -24.0, 174.0
BASE_Z0, BASE_Z1 = -164.0, 122.0           # nửa -Z kéo dài để chứa driver + Pi chung 1 bên
RIB_H = 6.0                                # gân chu vi dưới đế

PI_X0, PI_Z0 = 62.0, -108.0                # [SPEC] Pi 4B PCB 85 x 56 x 1.4
PI_L, PI_W, PI_T = 85.0, 56.0, 1.4
PI_STAND = 5.0                             # trụ M2.5 dưới Pi
PI_Y0 = PI_STAND                           # mặt dưới PCB Pi
PI_Y1 = PI_Y0 + PI_T
PI_HOLE_INSET = 3.5                        # [SPEC] tâm lỗ cách mép 3.5 mm
PI_HOLE_PX, PI_HOLE_PZ = 58.0, 49.0        # [SPEC] bước lỗ 58 x 49 mm

HAT_L, HAT_W, HAT_T = 65.0, 56.5, 1.6      # [SPEC] khuôn dạng HAT 65 x 56.5
HDR_H = 8.5                                # [ASSUME] header cái 2x20 cao 8.5 mm
HAT_Y0 = PI_Y1 + HDR_H
HAT_Y1 = HAT_Y0 + HAT_T

# Board driver LED 70 x 55 mm (gọn theo ảnh thực tế — hình 1) đặt CÙNG BÊN -Z
# với Pi 4 (xoay 90° về Y). Hệ cục bộ board: x 0..70, z 0..55; sau xoay
# (x,z)->(-z,x) + tịnh tiến [DRV_WX, 0, DRV_WZ] -> world x in [DRV_WX-55, DRV_WX],
# z in [DRV_WZ, DRV_WZ+70].  DRV_WX=62 khớp mép +X của Pi (62), DRV_WZ=-164 mép -Z đế.
DRV_L, DRV_W, DRV_T = 70.0, 55.0, 1.6
DRV_WX, DRV_WZ = 62.0, -164.0              # góc đặt board sau xoay (mép +X / mép -Z)
DRV_STAND = 5.0
DRV_Y0 = DRV_STAND
DRV_Y1 = DRV_Y0 + DRV_T
_DRV_R = rotation_matrix(-math.pi / 2, [0, 1, 0])[:3, :3]   # (x,z)->(-z,x)


def drv_world(lx, lz):
    """Toạ độ (x, z) thế giới của điểm cục bộ (lx, lz) trên board driver (đã xoay)."""
    w = _DRV_R @ np.array([lx, 0.0, lz]) + np.array([DRV_WX, 0.0, DRV_WZ])
    return float(w[0]), float(w[2])

DAC_L, DAC_W, DAC_T = 17.8, 15.2, 1.2      # [ASSUME] breakout MCP4725
DAC_HDR_H = 8.5

# --- màu ----------------------------------------------------------------------
C_BODY   = 0x27303f
C_LID    = 0x36414f
C_PRINT2 = 0x4a5566
C_SHAFT  = 0xb9c0cb
C_CAR_R  = 0x8f2a24
C_CAR_I  = 0x27357f
C_FRAME  = 0x3d4757
C_APER   = 0x2f3846
C_BASE   = 0x59637a
C_PCB_G  = 0x0f6b3c        # perfboard xanh
C_PCB_PI = 0x1c7a45        # PCB Pi 4B
C_PCB_PU = 0x6f2b86        # module OPT101 (tím)
C_PCB_RD = 0xa8231d        # breakout MCP4725 (đỏ)
C_GOLD   = 0xd0a24c
C_BLACK  = 0x15171c
C_SILVER = 0xc3c9d2
C_WHITE  = 0xf0ece0        # vỏ connector Grove
C_LEDR   = 0xd22a20
C_LEDI   = 0x2b2350
C_GLASS  = 0xdfe8f0
C_WIRE_R = 0xd93b2b
C_WIRE_K = 0x1a1a1e
C_WIRE_Y = 0xe0b021
C_WIRE_B = 0x2f6fd0
C_WIRE_W = 0xdadde3
C_TIE    = 0x353a42        # dây rút (cable tie) buộc bẹ dây
C_NYLON  = 0xe8e4d8

# ============================================================================
# 2. NGUYÊN THỦY HÌNH HỌC
# ============================================================================
def _finish(m):
    trimesh.repair.fix_normals(m, multibody=False)
    return m


def _tube(axis, a0, a1, c1, c2, r, n=32, r2=None):
    """Trụ / nón cụt dọc trục 'axis' từ a0..a1, tâm (c1,c2) trên 2 trục còn lại."""
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
        faces.append([i, n + j, n + i])
        faces.append([i, j, n + j])
        faces.append([2 * n, j, i])
        faces.append([2 * n + 1, n + i, n + j])
    m = trimesh.Trimesh(vertices=np.array(verts, dtype=np.float64),
                        faces=np.array(faces), process=True)
    return _finish(m)


def box(x0, x1, y0, y1, z0, z1):
    return trimesh.creation.box(
        extents=[abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)],
        transform=translation_matrix([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]))


def cyl_x(x0, x1, yc, zc, r, n=32):
    return _tube("x", x0, x1, yc, zc, r, n)


def cyl_y(y0, y1, xc, zc, r, n=32):
    return _tube("y", y0, y1, xc, zc, r, n)


def cyl_z(z0, z1, xc, yc, r, n=32):
    return _tube("z", z0, z1, xc, yc, r, n)


def frustum_x(x0, x1, yc, zc, r0, r1, n=32):
    return _tube("x", x0, x1, yc, zc, r0, n, r2=r1)


def sphere(r, cx, cy, cz, sub=2):
    s = trimesh.creation.icosphere(subdivisions=sub, radius=r)
    s.apply_translation([cx, cy, cz])
    return s


def uni(meshes):
    ms = [m for m in meshes if m is not None]
    return ms[0] if len(ms) == 1 else trimesh.boolean.union(ms)


def dif(a, bs):
    bs = [b for b in bs if b is not None]
    return a if not bs else trimesh.boolean.difference([a] + list(bs))


def cat(meshes):
    """Ghép cứng (không CSG) — dùng cho chi tiết CHỈ để nhìn."""
    ms = [m for m in meshes if m is not None]
    return trimesh.util.concatenate(ms)


def prism(axis, pts, a0, a1):
    """Lăng trụ LỒI: đa giác 2D `pts` kéo dài dọc `axis` từ a0 -> a1.

    axis='y' -> pts là (x, z);  axis='x' -> pts là (y, z);  axis='z' -> pts là (x, y).
    Dùng để vát cạnh / bo góc bằng CSG (dif) mà không cần shapely.
    """
    n = len(pts)
    if axis == "y":
        lo = [[p[0], a0, p[1]] for p in pts]; hi = [[p[0], a1, p[1]] for p in pts]
    elif axis == "x":
        lo = [[a0, p[0], p[1]] for p in pts]; hi = [[a1, p[0], p[1]] for p in pts]
    else:
        lo = [[p[0], p[1], a0] for p in pts]; hi = [[p[0], p[1], a1] for p in pts]
    f = []
    for i in range(1, n - 1):
        f.append([0, i, i + 1])
        f.append([n, n + i + 1, n + i])
    for i in range(n):
        j = (i + 1) % n
        f += [[i, n + i, n + j], [i, n + j, j]]
    v = np.array(lo + hi, np.float64)
    f = np.array(f, np.int64)
    # Chiều quấn của mặt bên phụ thuộc dấu của đa giác 2D -> tự kiểm thể tích
    # có dấu rồi lật nếu âm (fix_normals() của trimesh cần scipy, không có ở đây).
    t = v[f]
    if float(np.einsum("ij,ij->i",
                       t[:, 0], np.cross(t[:, 1], t[:, 2])).sum()) < 0.0:
        f = f[:, ::-1]
    return trimesh.Trimesh(vertices=v, faces=f, process=True)


def chamfer_v(xc, zc, sx, sz, c, y0, y1):
    """Dao cắt vát 45 độ cho MỘT góc đứng (sx, sz = hướng chân vát vào trong khối)."""
    return prism("y", [(xc, zc), (xc + sx * c, zc), (xc, zc + sz * c)], y0, y1)


def chamfer_box_v(x0, x1, z0, z1, c, y0, y1):
    """4 dao vát cho 4 góc đứng của một khối hộp chữ nhật."""
    return [chamfer_v(x, z, sx, sz, c, y0, y1)
            for x, sx in ((x0, 1.0), (x1, -1.0))
            for z, sz in ((z0, 1.0), (z1, -1.0))]


def chamfer_edge_top(x0, x1, z0, z1, yt, c, out=False):
    """4 dao vát 45 độ cho vành mép TRÊN của một tấm/khối hộp chữ nhật.
    out=True: chân vát hướng ra ngoài — dùng để vát VIỀN của một hốc âm."""
    g = -1.0 if out else 1.0
    ov = (c + 0.6) if out else 0.6
    return [prism("x", [(yt, z0), (yt, z0 + g * c), (yt - c, z0)], x0 - ov, x1 + ov),
            prism("x", [(yt, z1), (yt, z1 - g * c), (yt - c, z1)], x0 - ov, x1 + ov),
            prism("z", [(x0, yt), (x0 + g * c, yt), (x0, yt - c)], z0 - ov, z1 + ov),
            prism("z", [(x1, yt), (x1 - g * c, yt), (x1, yt - c)], z0 - ov, z1 + ov)]


def tube_path(points, r, n=10):
    """Bó dây: nối các đoạn trụ + cầu ở khớp. Chỉ để nhìn."""
    segs = []
    P = [np.asarray(p, dtype=float) for p in points]
    for a, b in zip(P[:-1], P[1:]):
        v = b - a
        L = float(np.linalg.norm(v))
        if L < 1e-6:
            continue
        c = trimesh.creation.cylinder(radius=r, height=L, sections=n)
        zax = np.array([0.0, 0.0, 1.0])
        ax = np.cross(zax, v / L)
        na = float(np.linalg.norm(ax))
        if na > 1e-9:
            c.apply_transform(rotation_matrix(math.atan2(na, float(np.dot(zax, v / L))), ax / na))
        elif float(np.dot(zax, v / L)) < 0:
            c.apply_transform(rotation_matrix(math.pi, [1, 0, 0]))
        c.apply_translation((a + b) / 2)
        segs.append(c)
    for p in P[1:-1]:
        segs.append(sphere(r, *p, sub=1))
    return cat(segs)


def arc_pts(p0, p1, rise, n=14):
    """Cung parabol giữa 2 điểm, đỉnh nâng thêm 'rise' theo +Y — mô phỏng dây võng ngược."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    out = []
    for i in range(n + 1):
        t = i / n
        p = p0 + (p1 - p0) * t
        p[1] += 4.0 * rise * t * (1.0 - t)
        out.append(p.tolist())
    return out


def harness(points, wires, r=0.5, n=8, tie_step=14.0, tie_t=3.0, tie_h=2.4,
            tie_gap=1.6, tie_skip_y=None):
    """Bẹ dây: nhiều sợi song song trên một lộ trình chung, buộc dây rút định kỳ.

    points = [(x, y, z), ...] — lộ trình trung tâm (tim bẹ).
    wires = [(offset_bên, màu), ...] — mỗi sợi lệch 'offset' mm theo hướng
             vuông góc với lộ trình (tính trên toàn bộ điểm điều khiển).
    r = bán kính mỗi sợi; n = số cạnh đa giác.
    tie_step = khoảng cách giữa 2 dây rút (mm); 0 = không buộc.
    tie_skip_y = (lo, hi) — bỏ dây rút khi tim bẹ nằm trong dải y này
                  (dùng khi dây chui qua khe hẹp / dưới chi tiết khác).
    Trả về list [(mesh, màu), ...] để v.add từng phần tử.
    """
    P = [np.asarray(p, float) for p in points]
    d = P[-1] - P[0]
    L = float(np.linalg.norm(d))
    d = d / L if L > 1e-9 else np.array([1.0, 0.0, 0.0])
    up = np.array([0.0, 1.0, 0.0])
    side = np.cross(up, d)
    sn = float(np.linalg.norm(side))
    if sn < 1e-6:
        side = np.array([0.0, 0.0, 1.0])
    else:
        side /= sn
    out = []
    for off, col in wires:
        shifted = [p + side * off for p in P]
        out.append((tube_path(shifted, r, n), col))
    if tie_step and tie_step > 0:
        # tính chiều dài tích luỹ các đoạn
        seg = [float(np.linalg.norm(b - a)) for a, b in zip(P[:-1], P[1:])]
        cum = [0.0]
        for s in seg:
            cum.append(cum[-1] + s)
        total = cum[-1]
        if total > 1e-6:
            half_w = max(abs(o) for o, _ in wires) + r + tie_gap / 2
            ties = []
            pos = tie_step * 0.5
            while pos < total:
                for i in range(len(P) - 1):
                    if cum[i] <= pos <= cum[i + 1] and seg[i] > 1e-6:
                        t = (pos - cum[i]) / seg[i]
                        pt = P[i] + (P[i + 1] - P[i]) * t
                        if tie_skip_y and tie_skip_y[0] <= pt[1] <= tie_skip_y[1]:
                            break
                        pd = (P[i + 1] - P[i]) / seg[i]
                        # đai: hộp dọc pd (dày tie_t), cao tie_h, ngang 2*half_w.
                        # Đặt sao cho ĐÁY đai nằm ngay trên đỉnh sợi (không chui
                        # xuống dưới dây -> không đâm vào sàn/khe lắp ghép).
                        tie = box(-tie_t / 2, tie_t / 2, -tie_h / 2, tie_h / 2,
                                  -half_w, half_w)
                        ax = np.cross(up, pd)
                        na = float(np.linalg.norm(ax))
                        if na > 1e-9:
                            tie.apply_transform(rotation_matrix(
                                math.atan2(na, float(np.dot(up, pd))), ax / na))
                        elif float(np.dot(up, pd)) < 0:
                            tie.apply_transform(rotation_matrix(math.pi, [1, 0, 0]))
                        tie.apply_translation(pt + up * (r + tie_h / 2 + 0.15))
                        ties.append(tie)
                        break
                pos += tie_step
            if ties:
                out.append((cat(ties), C_TIE))
    return out


class Vis:
    """Gom các mesh chỉ-để-nhìn theo (màu, độ trong, texture) rồi ghép lại.

    Texture (tex) là id trong assets/textures.json — mesh mang texture phải là
    textured_quad() (có UV); export() sẽ phát 'map' + 'uvbase64' cho viewer.
    """

    def __init__(self):
        self._d = {}
        self._order = []

    def add(self, mesh, color, opacity=1.0, tex=None):
        if mesh is None:
            return self
        k = (color, round(float(opacity), 3), tex)
        if k not in self._d:
            self._d[k] = []
            self._order.append(k)
        self._d[k].append(mesh)
        return self

    def subs(self):
        out = []
        for (c, o, tex) in self._order:
            group = self._d[(c, o, tex)]
            mesh = group[0] if len(group) == 1 else cat(group)
            d = dict(mesh=mesh, color=c)
            if o < 1.0:
                d["opacity"] = o
            if tex is not None:
                d["map"] = tex
                if hasattr(mesh.visual, "uv") and mesh.visual.uv is not None:
                    d["uvbase64"] = base64.b64encode(
                        np.asarray(mesh.visual.uv, np.float32).tobytes()).decode("ascii")
            out.append(d)
        return out


def pad_grid(plane, const, a0, a1, b0, b1, pitch=2.54, r=0.62, margin=2.0):
    """Lưới pad mạ vàng của perfboard (đĩa mỏng, 6 cạnh -> rẻ tri-count)."""
    ms = []
    na = int((a1 - a0 - 2 * margin) // pitch)
    nb = int((b1 - b0 - 2 * margin) // pitch)
    a_s = a0 + margin + ((a1 - a0 - 2 * margin) - na * pitch) / 2
    b_s = b0 + margin + ((b1 - b0 - 2 * margin) - nb * pitch) / 2
    for i in range(na + 1):
        for j in range(nb + 1):
            a, b = a_s + i * pitch, b_s + j * pitch
            if plane == "y":       # board nằm ngang, pad trên mặt y = const
                ms.append(_tube("y", const, const + 0.06, a, b, r, 6))
            else:                  # board đứng (pháp tuyến X), pad trên mặt x = const
                ms.append(_tube("x", const - 0.06, const, a, b, r, 6))
    return cat(ms)


# ============================================================================
# 3. CHI TIẾT IN 3D
# ============================================================================
# --- thông số tạo hình (thẩm mỹ) --------------------------------------------
BODY_CHAM = 2.5          # vát 4 góc đứng thân hộp (còn 2.47 mm thành tại góc)
BODY_CHAM_Y1 = 57.0      # dừng dưới vùng rãnh labyrinth -> không ảnh hưởng kín sáng
SHADOW_Y0, SHADOW_Y1 = 46.0, 48.5     # chỉ bóng ngang quanh 4 thành
SHADOW_D = 0.8                        # chiều sâu chỉ bóng (thành còn 2.2 mm)
PAD_CHAM = 2.0           # vát góc bệ bắt chụp
PAD_T, PAD_HW = 5.0, 18.0             # bề dày / nửa bề rộng bệ bắt chụp
HOOD_BOLT_Y = (5.5, 21.0)             # 2 hàng vít M3 giữ chụp (nằm trong y 3..24)
HOOD_BOLT_Z = (-14.5, 14.5)
HOOD_SLOT_L, HOOD_SLOT_HW = 7.0, 6.0  # khe luồn cáp ở sàn chụp (đủ cho bẹ 3 sợi)
HOOD_CHAM = 2.0          # vát góc chụp che sáng
BASE_CHAM = 8.0          # vát 2 góc ngoài mỗi nửa đế
LID_CHAM = 1.5                        # vát vành mép trên nắp
LID_PANEL_X0, LID_PANEL_X1 = 24.0, 126.0
LID_PANEL_Z0, LID_PANEL_Z1 = -30.0, 30.0
LID_PANEL_D = 0.8                     # panel giữa thụt xuống
LID_GRIP_X = (8.0, 130.0)             # 2 cụm rãnh cầm tay (âm, không phải gân nổi)
LID_GRIP_N, LID_GRIP_W, LID_GRIP_P, LID_GRIP_D = 4, 2.2, 3.6, 1.0

LID_GROOVE_W = 2.0          # bề rộng rãnh labyrinth trên đỉnh thành
LID_GROOVE_D = 4.0          # chiều sâu rãnh (Y_TOP-4 .. Y_TOP)


def _lid_groove_boxes(shrink=0.0):
    """Đường rãnh labyrinth: chạy giữa bề dày từng thành + trên vách ngăn."""
    h = LID_GROOVE_W / 2 - shrink
    y0 = Y_TOP - LID_GROOVE_D + (0.2 if shrink else 0.0)
    y1 = Y_TOP + (0.0 if shrink else 0.2)
    cz_b, cz_f = (Z0 + Z_IN0) / 2, (Z1 + Z_IN1) / 2
    cx_l, cx_r = (X0 + X_IN0) / 2, (X_TOT + X_IN1) / 2
    return [
        box(X0, X_TOT, y0, y1, cz_b - h, cz_b + h),          # thành sau  (-Z)
        box(X0, X_TOT, y0, y1, cz_f - h, cz_f + h),          # thành trước(+Z)
        box(cx_l - h, cx_l + h, y0, y1, Z0, Z1),             # thành trái (-X)
        box(cx_r - h, cx_r + h, y0, y1, Z0, Z1),             # thành phải (+X)
        box(X_IN0, X_IN1, y0, y1, -h, h),                    # vách ngăn quang
    ]


def build_body():
    """Thân hộp tối: 2 làn quang cách ly bởi vách ngăn liền khối, hở nóc."""
    m = box(X0, X_TOT, Y0, Y_TOP, Z0, Z1)
    m = dif(m, [box(X_IN0, X_IN1, Y_FL, Y_TOP + 0.5, Z_IN0, Z_IN1)])

    # vách ngăn quang: đoạn trước (tới mặt board) + đoạn sau (sau khung board).
    # Barrier z∈[-1.5,1.5] liên tục: vách [3,137.5] + board FR4 [137.5,139.1]
    # + khung đặc [139.1,141.5] + vách sau [141.5,147] — xem ghi chú build_frame().
    m = uni([m,
             box(X_IN0, FRM_X0, Y_FL, Y_TOP, -SEPT_HW, SEPT_HW),
             box(SEPT_R_X0, X_IN1, Y_FL, Y_TOP, -SEPT_HW, SEPT_HW)])

    # cột đỡ đầu trục trượt + gân dẫn hướng tấm khẩu độ + vai chặn khung board
    add = []
    for ch, zc in LANE_Z.items():
        s = LANE_SIGN[ch]
        add.append(box(POST_X0, POST_X1, Y_FL, POST_TOP,
                       zc - POST_ZW / 2, zc + POST_ZW / 2))
        for zs in (s * Z_IN1, s * SEPT_HW):
            zi = zs - s * AP_RIB_T if abs(zs) > 10 else zs + s * AP_RIB_T
            for (rx0, rx1) in ((AP_X0 - 0.4, AP_X0), (AP_X1, AP_X1 + 0.4)):
                add.append(box(rx0, rx1, Y_FL, AP_Y1, min(zs, zi), max(zs, zi)))
    for zs in (Z_IN0, Z_IN1 - 3.0):
        add.append(box(FRM_X1, FRM_X1 + 3.5, Y_FL, 58.0, zs, zs + 3.0))
    m = uni([m] + add)

    m = dif(m, _lid_groove_boxes())

    cuts = []
    for ch, zc in LANE_Z.items():
        s = LANE_SIGN[ch]
        cuts.append(cyl_x(0.6, X_IN0 + 0.3, SH_Y, zc, SH_R + CLR, 40))       # lỗ mù giữ trục
        cuts.append(cyl_x(POST_X0 - 0.5, POST_X1 + 0.5, SH_Y, zc, SH_R + CLR, 40))
        cuts.append(box(AP_X0, AP_X1, Y_FL - 1.1, Y_FL + 0.05, zc - 17.8, zc + 17.8))
        zw = s * (Z_IN1 - 4.0)                                               # máng dây LED
        cuts.append(box(4.0, 104.0, Y_FL - 1.4, Y_FL + 0.05, zw - 3.0, zw + 3.0))
    m = dif(m, cuts)

    # bệ dày cục bộ để bắt vít M3 mù cho 4 chụp che sáng
    pads, holes = [], []
    for zc in LANE_Z.values():
        for xs, sgn in ((X0, -1.0), (X_TOT, 1.0)):
            pads.append(dif(box(xs, xs + sgn * PAD_T, Y0, HOOD_Y1,
                                zc - PAD_HW, zc + PAD_HW),
                            chamfer_box_v(min(xs, xs + sgn * PAD_T),
                                          max(xs, xs + sgn * PAD_T),
                                          zc - PAD_HW, zc + PAD_HW,
                                          PAD_CHAM, Y0 - 0.5, HOOD_Y1 + 0.5)))
            # Lối ra cáp phải khoan SAU khi đắp bệ, nếu không bệ bịt kín cổng.
            holes.append(box(xs + sgn * (PAD_T + 0.5), xs - sgn * (X_IN0 + 0.5),
                             EX_Y0, EX_Y1, zc - EX_ZW / 2, zc + EX_ZW / 2))
            for dy in HOOD_BOLT_Y:
                for dz in HOOD_BOLT_Z:
                    holes.append(_tube("x", xs + sgn * (PAD_T + 0.3),
                                       xs - sgn * 1.5, dy, zc + dz, 1.35, 16))
    m = uni([m] + pads)

    # tai bắt vít xuống đế
    ears = []
    for xc in (21.0, 129.0):
        for zs in (Z0, Z1):
            sg = -1.0 if zs < 0 else 1.0
            ears.append(uni([box(xc - 6.0, xc + 6.0, Y0, Y0 + 4.0,
                                 zs, zs + sg * 5.5),
                             cyl_y(Y0, Y0 + 4.0, xc, zs + sg * 5.5, 6.0, 28)]))
            holes.append(cyl_y(Y0 - 0.5, Y0 + 4.5, xc, zs + sg * 5.5, 1.75, 20))
    m = uni([m] + ears)

    # --- xử lý tạo hình (thẩm mỹ): vát 4 góc đứng phần thân dưới, chỉ bóng
    #     ngang, vát vành mép trên. Tất cả đều NẰM NGOÀI vùng rãnh labyrinth
    #     (y = Y_TOP-LID_GROOVE_D .. Y_TOP) nên không đụng tới kín sáng.
    style = chamfer_box_v(X0, X_TOT, Z0, Z1, BODY_CHAM, Y0 - 0.5, BODY_CHAM_Y1)
    style += chamfer_edge_top(X0, X_TOT, Z0, Z1, Y_TOP, 1.0)
    for a, b in ((Z0 - 0.5, Z0 + SHADOW_D), (Z1 - SHADOW_D, Z1 + 0.5)):
        style.append(box(8.0, X_TOT - 8.0, SHADOW_Y0, SHADOW_Y1, a, b))
    for a, b in ((X0 - 0.5, X0 + SHADOW_D), (X_TOT - SHADOW_D, X_TOT + 0.5)):
        style.append(box(a, b, SHADOW_Y0, SHADOW_Y1, Z0 + 8.0, Z1 - 8.0))
    return dif(m, holes + style)


def build_lid():
    """Nắp labyrinth: tấm + gờ cắm vào rãnh (kể cả trên vách ngăn) + vấu chặn khung."""
    m = box(X0, X_TOT, Y_TOP, Y_LID, Z0, Z1)
    m = uni([m] + _lid_groove_boxes(shrink=CLR / 2))
    tabs = [box(FRM_X0 - 2.4, FRM_X0 - 0.6, 56.0, Y_TOP, zc - 14.0, zc + 14.0)
            for zc in LANE_Z.values()]
    m = uni([m] + tabs)

    # --- xử lý tạo hình: vát vành mép trên, panel giữa thụt 0.8 mm, hai cụm
    #     rãnh cầm tay ÂM (thay cho 3 gân nổi cũ — gân nổi vừa xấu vừa vướng).
    cuts = chamfer_edge_top(X0, X_TOT, Z0, Z1, Y_LID, LID_CHAM)
    cuts.append(box(LID_PANEL_X0, LID_PANEL_X1, Y_LID - LID_PANEL_D, Y_LID + 0.6,
                    LID_PANEL_Z0, LID_PANEL_Z1))
    cuts += chamfer_edge_top(LID_PANEL_X0, LID_PANEL_X1, LID_PANEL_Z0, LID_PANEL_Z1,
                             Y_LID, LID_PANEL_D, out=True)
    for gx in LID_GRIP_X:
        for i in range(LID_GRIP_N):
            a = gx + i * LID_GRIP_P
            cuts.append(box(a, a + LID_GRIP_W, Y_LID - LID_GRIP_D, Y_LID + 0.6,
                            LID_PANEL_Z0, LID_PANEL_Z1))
    return dif(m, cuts)


def build_shaft():
    """Trục trượt D (Ø8, vát phẳng chống xoay) + vạch chia 5 mm trên mặt vát."""
    m = cyl_x(SH_X0, SH_X1, SH_Y, 0.0, SH_R, 40)
    m = dif(m, [box(SH_X0 - 0.5, SH_X1 + 0.5, SH_FLAT_Y, SH_Y + SH_R + 2.0,
                    -SH_R - 2.0, SH_R + 2.0)])
    ticks, x = [], TICK_X0
    while x <= TICK_X1 + 1e-6:
        big = abs((x / 25.0) - round(x / 25.0)) < 1e-6
        w, hz = (0.9, 3.4) if big else (0.5, 2.0)
        ticks.append(box(x - w, x + w, SH_FLAT_Y - 0.7, SH_FLAT_Y + 0.5, -hz, hz))
        x += TICK_STEP
    return dif(m, ticks)


def build_carrier():
    """Khối trượt mang LED: lỗ D ôm trục, kẹp xẻ rãnh + vít M3, loa che sáng 45°.
    Hệ cục bộ: mặt trước carrier x=0; trục trượt y=SH_Y,z=0; trục quang y=Y_AX,z=0."""
    m = box(-CAR_L, 0.0, CAR_Y0, CAR_Y1, -CAR_ZW / 2, CAR_ZW / 2)
    m = uni([m, frustum_x(0.0, COLLAR_L, Y_AX, 0.0, 5.2, 2.1, 40)])
    dbore = dif(cyl_x(-CAR_L - 0.5, 0.5, SH_Y, 0.0, SH_R + CLR, 40),
                [box(-CAR_L - 1, 1, SH_FLAT_Y + CLR, SH_Y + SH_R + 2,
                     -SH_R - 2, SH_R + 2)])
    cuts = [dbore,
            cyl_x(-9.0, COLLAR_L + 0.2, Y_AX, 0.0, 1.65, 32),        # thân LED Ø3.0 +0.3
            cyl_x(-10.4, -9.0, Y_AX, 0.0, 2.05, 32),                 # hốc vành LED Ø3.8
            cyl_x(-CAR_L - 0.5, -10.4, Y_AX, 0.0, 2.8, 32),          # khoang chân/dây
            box(-18.0, -4.0, CAR_Y0 - 0.5, SH_Y, -0.9, 0.9),         # rãnh xẻ kẹp
            cyl_z(-CAR_ZW / 2 - 0.5, CAR_ZW / 2 + 0.5, -11.0, 9.4, 1.75, 20),
            cyl_z(2.4, CAR_ZW / 2 + 0.5, -11.0, 9.4, 3.3, 20),       # hốc đầu vít M3
            box(-CAR_L - 0.5, -CAR_L + 5.0, CAR_Y0 + 1.0, CAR_Y0 + 5.0, -3.0, 3.0),
            box(-2.2, -0.6, CAR_Y1 - 1.4, CAR_Y1 + 0.5, -1.2, 1.2)]  # vạch chỉ vị trí
    return dif(m, cuts)


def x_front(ch, d=None):
    """Toạ độ X mặt trước carrier ứng với d (chóp LED -> mặt cửa sổ OPT101)."""
    d = D_DEFAULT[ch] if d is None else d
    return X_WIN - d - LED_TIP_OUT


def build_frame():
    """Khung giữ board 5x7: bịt kín tiết diện lòng hộp, mang bản vách ngăn nối tiếp.

    LƯU Ý CÁCH LY QUANG: hốc đặt board rộng hơn board 0.35 mm mỗi cạnh (khe lắp
    ghép). Vách ngăn 3 mm liên tục nhờ: vây trước board (X_MOD1..X_BF) + chính
    board FR4 đặc + phần khung liền z∈[-4,4] phía sau (x∈[X_BR,FRM_X1]). Khe
    0.2-0.35 mm quanh mép board phải được bịt (băng keo đen / keo dán) khi lắp
    thật để chống rò sáng giữa 2 làn — giống mọi buồng tối in 3D thực tế."""
    m = box(FRM_X0, FRM_X1, Y_FL, 59.8, Z_IN0 + 0.3, Z_IN1 - 0.3)
    cuts = [box(FRM_X0 - 0.2, X_BR + 0.2, BRD_Y0 - 0.35, BRD_Y1 + 0.35,
                BRD_Z0 - 0.35, BRD_Z1 + 0.35)]                       # hốc đặt board
    for zc in LANE_Z.values():
        s = 1.0 if zc > 0 else -1.0
        a, b = sorted((s * 4.0, s * 32.0))
        cuts.append(box(X_BR + 0.2, FRM_X1 + 0.2, 12.0, 58.0, a, b))  # cửa luồn dây
        cuts.append(box(FRM_X0 - 0.2, FRM_X1 + 0.2, BRD_Y1 - 1.0, BRD_Y1 + 3.2,
                        zc - 6.5, zc + 6.5))                          # khe dây lên máng
    # Khung được giữ bằng 2 vai chặn trên thân (mặt +X) và 2 vấu nắp (mặt -X):
    # không khoan vít xuyên khung vì mọi vị trí khả dĩ đều phá vào hốc đặt board.
    return dif(m, cuts)


AP_W = (Z_IN1 - SEPT_HW) - 0.6      # 34.9 mm — đối xứng quanh tâm làn


def build_aperture(kind):
    """Tấm khẩu độ cắm rãnh; lỗ đúng tâm trục quang. Một thiết kế dùng cho cả 2 làn."""
    m = box(0.0, AP_T, AP_Y0, 60.0, -AP_W / 2, AP_W / 2)
    m = uni([m, box(-1.4, AP_T + 1.4, 60.0, 63.0, -11.0, 11.0)])     # tay cầm
    r = {"blank": 0.0, "d2": 1.0, "d5": 2.5, "d16": 8.0}[kind]
    if r > 0:
        m = dif(m, [cyl_x(-0.5, AP_T + 0.5, Y_AX, 0.0, r, 48)])
    n = {"blank": 0, "d2": 1, "d5": 2, "d16": 3}[kind]                # khắc mã nhận dạng
    marks = [box(-0.1, 0.7, 61.0, 62.2, -8.0 + 3.0 * i, -6.8 + 3.0 * i) for i in range(n)]
    return dif(m, marks) if marks else m


def build_hood(sgn):
    """Chụp che sáng lối ra cáp: ánh sáng phải quay 90° hai lần mới tới lỗ vách.
    sgn=+1 lắp ở thành +X (cáp OPT101); sgn=-1 ở thành -X (cáp LED)."""
    HW = EX_ZW / 2 + 8.0
    a0 = 5.0                       # mặt ngoài bệ trên thân hộp
    a1 = a0 + 4.0                  # mặt bích
    a2 = a1 + HOOD_D + HOOD_T

    def bx(u0, u1, y0, y1, z0, z1):
        return box(sgn * u0, sgn * u1, y0, y1, z0, z1)

    m = bx(a0, a2, HOOD_Y0, HOOD_Y1, -HW, HW)
    # Lối cáp là KHE Ở SÀN đầu xa, không phải cửa mặt ngoài: ánh sáng ngoài muốn
    # tới lỗ vách phải qua khe hở 3 mm dưới chụp -> ngoặt 90 độ lên -> ngoặt 90
    # độ theo +X. Ít cửa hơn và bẻ góc nhiều hơn so với cửa mặt ngoài trước đây.
    cuts = [bx(a0 - 0.5, a2 - HOOD_T, HOOD_Y0 + HOOD_T, HOOD_Y1 - HOOD_T,
               -HW + HOOD_T, HW - HOOD_T),
            bx(a2 - HOOD_T - HOOD_SLOT_L, a2 - HOOD_T, HOOD_Y0 - 0.5,
               HOOD_Y0 + HOOD_T + 0.5, -HOOD_SLOT_HW, HOOD_SLOT_HW)]
    for dy in HOOD_BOLT_Y:
        for dz in HOOD_BOLT_Z:
            cuts.append(_tube("x", sgn * (a0 - 0.5), sgn * (a1 + 0.5), dy, dz, 1.75, 16))
    u0, u1 = sorted((sgn * a1, sgn * a2))            # phần nhô ra ngoài bệ
    cuts += chamfer_box_v(u0, u1, -HW, HW, HOOD_CHAM, HOOD_Y0 - 0.5, HOOD_Y1 + 0.5)
    cuts += chamfer_edge_top(u0, u1, -HW, HW, HOOD_Y1, HOOD_CHAM)
    return dif(m, cuts)


def build_base(half):
    """Đế chung, chia đôi tại z=0 cho vừa bàn in.
    half='neg': z<0 (Pi 4 + Grove HAT + board driver + 2x MCP4725 — cùng 1 bên).
    half='pos': z>0 (phần đế dưới hộp tối + chụp +X)."""
    neg = (half == "neg")
    z0, z1 = (BASE_Z0, 0.0) if neg else (0.0, BASE_Z1)
    m = box(BASE_X0, BASE_X1, -BASE_T, 0.0, z0, z1)
    zr = (z0, z0 + 5.0) if neg else (z1 - 5.0, z1)
    add = [box(BASE_X0, BASE_X0 + 5.0, -BASE_T - RIB_H, -BASE_T, z0, z1),
           box(BASE_X1 - 5.0, BASE_X1, -BASE_T - RIB_H, -BASE_T, z0, z1),
           box(BASE_X0, BASE_X1, -BASE_T - RIB_H, -BASE_T, zr[0], zr[1])]
    holes = []
    if neg:                                    # trụ đỡ Pi 4B (M2.5) + driver (M3)
        for dx in (0.0, PI_HOLE_PX):
            for dz in (0.0, PI_HOLE_PZ):
                px, pz = PI_X0 + PI_HOLE_INSET + dx, PI_Z0 + PI_HOLE_INSET + dz
                add.append(cyl_y(0.0, PI_STAND, px, pz, 3.6, 24))
                holes.append(cyl_y(-BASE_T - 0.5, PI_STAND + 0.5, px, pz, 1.15, 16))
        for lx in (4.0, DRV_L - 4.0):          # board driver xoay 90° (70 x 90 mm)
            for lz in (4.0, DRV_W - 4.0):
                px, pz = drv_world(lx, lz)
                add.append(cyl_y(0.0, DRV_STAND, px, pz, 3.6, 24))
                holes.append(cyl_y(-BASE_T - 0.5, DRV_STAND + 0.5, px, pz, 1.4, 16))
    for xc in (21.0, 129.0):                   # bệ bắt tai hộp
        zs, sg = (Z0, -1.0) if neg else (Z1, 1.0)
        add.append(cyl_y(-BASE_T - RIB_H, -BASE_T, xc, zs + sg * 5.5, 4.6, 24))
        holes.append(cyl_y(-BASE_T - RIB_H - 0.5, 0.5, xc, zs + sg * 5.5, 1.4, 16))
    for xc in (10.0, 77.0, 144.0):             # mộng vuông nối 2 nửa
        if neg:
            add.append(box(xc - 11.0, xc + 11.0, -BASE_T + 0.8, -0.8, 0.0, 9.0))
        else:
            holes.append(box(xc - 11.3, xc + 11.3, -BASE_T + 0.5, -0.5, -0.2, 9.3))
    for xc in (43.0, 111.0):                   # 2 vít M3 xiết mối nối
        holes.append(cyl_y(-BASE_T - 0.5, 0.5, xc, -6.0 if neg else 6.0, 1.75, 16))
    m = uni([m] + add)

    # --- xử lý tạo hình: vát 2 góc ngoài + vành mép trên (mép z=0 để vuông
    #     vì đó là mặt ghép 2 nửa).
    ze = z0 if neg else z1
    sz = 1.0 if neg else -1.0                  # hướng vào trong tấm đế
    style = [chamfer_v(BASE_X0, ze, 1.0, sz, BASE_CHAM, -BASE_T - RIB_H - 0.5, 0.5),
             chamfer_v(BASE_X1, ze, -1.0, sz, BASE_CHAM, -BASE_T - RIB_H - 0.5, 0.5)]
    ov = 0.6
    style += [prism("x", [(0.0, ze), (0.0, ze - (-1.0 if neg else 1.0) * 1.5),
                          (-1.5, ze)], BASE_X0 - ov, BASE_X1 + ov),
              prism("z", [(BASE_X0, 0.0), (BASE_X0 + 1.5, 0.0), (BASE_X0, -1.5)],
                    z0 - ov, z1 + ov),
              prism("z", [(BASE_X1, 0.0), (BASE_X1 - 1.5, 0.0), (BASE_X1, -1.5)],
                    z0 - ov, z1 + ov)]
    return dif(m, holes + style)


# ============================================================================
# 4. CHI TIẾT MUA SẴN / CHỈ ĐỂ NHÌN  (không xuất STL)
# ============================================================================
def led_vis(v, ch, xf):
    """LED 3 mm trong carrier. xf = toạ độ X mặt trước carrier.
    [DS] Ø thân 3.0, vành Ø3.8, bước chân 2.54 — kích thước LED 3 mm tiêu chuẩn."""
    col = C_LEDR if ch == "red" else C_LEDI
    y, z = Y_AX, LANE_Z[ch]
    v.add(cyl_x(xf - 10.4, xf - 9.4, y, z, 1.9, 24), col, 0.9)          # vành
    v.add(cyl_x(xf - 9.4, xf - 0.5, y, z, 1.5, 24), col, 0.9)           # thân
    v.add(sphere(1.5, xf - 0.5, y, z, sub=2), col, 0.9)                 # chóp cầu
    v.add(frustum_x(xf - 9.0, xf - 7.4, y, z, 1.1, 0.45, 16), C_SILVER) # chén phản xạ
    v.add(box(xf - 7.6, xf - 7.2, y - 0.35, y + 0.35, z - 0.35, z + 0.35), C_BLACK)
    for dz in (-1.27, 1.27):                                            # 2 chân
        v.add(cyl_x(xf - 20.0, xf - 10.2, y, z + dz, 0.28, 8), C_SILVER)
    return v


def opt101_vis(v, ch):
    """Module OPT101: PDIP-8 vỏ trong + PCB nhỏ. Cửa sổ quang tại x = X_WIN.
    [DS] opt101.pdf: 8 chân DIP, hàng chân cách 7.62 mm, vùng nhạy 2.29 x 2.29 mm.
    [ASSUME] vị trí photodiode trong vỏ chỉ có trên HÌNH VẼ datasheet, không trích
             được bằng chữ -> mô hình đặt ĐÚNG TÂM vỏ; phải đo lại trên vật thật."""
    y, z = Y_AX, LANE_Z[ch]
    v.add(box(X_WIN, X_MOD0, y - 3.18, y + 3.18, z - 4.9, z + 4.9), C_GLASS, 0.45)
    v.add(box(X_WIN - 0.05, X_WIN + 0.4, y - 1.145, y + 1.145,       # photodiode 2.29²
              z - 1.145, z + 1.145), 0x1b2530)
    v.add(box(X_WIN + 0.5, X_MOD0, y - 2.6, y + 2.6, z - 2.2, z + 2.2), 0x2a3340, 0.6)
    for i in range(4):                                                # 8 chân DIP
        zz = z - 3.81 + i * 2.54
        for dy in (-3.81, 3.81):
            v.add(box(X_MOD0 - 0.6, X_MOD1 + 1.4, y + dy - 0.25, y + dy + 0.25,
                      zz - 0.4, zz + 0.4), C_SILVER)
    v.add(box(X_MOD0, X_MOD1, y - 12.0, y + 12.0, z - 12.0, z + 12.0), C_PCB_PU)
    v.add(pad_grid("x", X_MOD0, y - 12.0, y + 12.0, z - 12.0, z + 12.0,
                   pitch=2.54, r=0.7, margin=2.5), C_GOLD)
    v.add(cyl_x(X_MOD0 - 0.1, X_MOD1 + 0.1, y + 4.6, z + 4.6, 1.35, 12), C_BLACK)
    for dy in (-8.5, 8.5):                                            # 4 lỗ bắt trụ
        for dz in (-8.5, 8.5):
            v.add(_tube("x", X_MOD0 - 0.1, X_MOD1 + 0.1, y + dy, z + dz, 1.4, 12), C_GOLD)
    # Header 6 chân (2 hàng x 3 cột) mép dưới module — cắm 3 dây V+/GND/Vout
    # [ASSUME] số chân theo module CJMCU-101 phổ biến; xác nhận trên vật thật.
    hx0 = X_MOD1 + 0.2
    v.add(box(hx0, hx0 + 6.0, y - 12.0, y - 6.0, z - 6.0, z + 6.0), C_BLACK)
    for i in range(3):
        zz = z - 5.08 + i * 5.08
        for dy in (-1.27, 1.27):
            v.add(box(hx0 + 1.2, hx0 + 2.2, y - 11.0 + dy - 0.4, y - 11.0 + dy + 0.4,
                      zz - 0.4, zz + 0.4), C_GOLD)
    return v


def sensor_board_vis(v):
    """Board cảm biến 5 x 7 cm dựng đứng (pháp tuyến = trục quang X), 2 module OPT101
    đặt cạnh nhau, đúng tâm 2 làn quang."""
    v.add(box(X_BF, X_BR, BRD_Y0, BRD_Y1, BRD_Z0, BRD_Z1), C_PCB_G)
    v.add(pad_grid("x", X_BF, BRD_Y0, BRD_Y1, BRD_Z0, BRD_Z1,
                   pitch=2.54, r=0.64, margin=3.2), C_GOLD)
    for dz in (BRD_Z0 + 3.5, BRD_Z1 - 3.5):                           # 4 lỗ bắt khung
        for dy in (BRD_Y0 + 3.5, BRD_Y1 - 3.5):
            v.add(_tube("x", X_BF - 0.1, X_BR + 0.1, dy, dz, 1.7, 12), C_GOLD)
    for ch, zc in LANE_Z.items():
        for dy in (-8.5, 8.5):                                        # trụ nylon M2.5
            for dz in (-8.5, 8.5):
                v.add(_tube("x", X_MOD1, X_BF, Y_AX + dy, zc + dz, 2.5, 6), C_NYLON)
                v.add(_tube("x", X_BR, X_BR + 3.0, Y_AX + dy, zc + dz, 1.5, 8), C_SILVER)
        v.add(box(X_BF - 0.2, X_BR, Y_AX + 14.0, Y_AX + 19.0,         # cầu đấu 3 chân
                  zc - 7.6, zc + 7.6), 0x1b6ea8)
        for i in range(3):
            v.add(cyl_x(X_BF - 3.4, X_BF - 0.2, Y_AX + 16.5,
                        zc - 5.08 + i * 5.08, 1.2, 10), C_SILVER)
        v.add(box(X_BF, X_BR, Y_AX - 20.0, Y_AX - 16.0,               # tụ 100 nF cạnh VS
                  zc - 2.0, zc + 2.0), 0x7a5a2a)
    return v


# ---- linh kiện rời dùng lại nhiều nơi ---------------------------------------
def _dip(v, xc, yb, zc, npin, lx=9.8, lz=6.4, h=4.0, pitch=2.54):
    """DIP nằm ngang trên board (mặt board y = yb), thân dài theo X."""
    v.add(box(xc - lx / 2, xc + lx / 2, yb, yb + h, zc - lz / 2, zc + lz / 2), C_BLACK)
    v.add(cyl_y(yb + h - 0.05, yb + h + 0.05, xc - lx / 2 + 1.6, zc, 1.0, 12), 0x2c3440)
    k = npin // 2
    for i in range(k):
        ux = xc - (k - 1) * pitch / 2 + i * pitch
        for dz in (-lz / 2 - 0.9, lz / 2 + 0.9):
            v.add(box(ux - 0.3, ux + 0.3, yb - 1.2, yb + 0.6, zc + dz - 0.5, zc + dz + 0.5),
                  C_SILVER)


def _to92(v, xc, yb, zc, h=4.6, r=2.3):
    """TO-92 (2SC1815): thân trụ vát phẳng + 3 chân."""
    v.add(cyl_y(yb + 1.2, yb + 1.2 + h, xc, zc, r, 16), 0x1d2026)
    for i in (-1, 0, 1):
        v.add(cyl_y(yb - 1.0, yb + 1.4, xc + i * 1.27, zc, 0.28, 6), C_SILVER)


def _res(v, xc, yb, zc, along="x", L=6.2, r=1.15):
    """Điện trở axial nằm ngang."""
    y = yb + 1.3
    if along == "x":
        v.add(cyl_x(xc - L / 2, xc + L / 2, y, zc, r, 10), 0xc9a15c)
        for s in (-1, 1):
            v.add(cyl_x(xc + s * L / 2, xc + s * (L / 2 + 3.0), y, zc, 0.26, 6), C_SILVER)
            v.add(cyl_y(yb - 0.8, y, xc + s * (L / 2 + 3.0), zc, 0.26, 6), C_SILVER)
    else:
        v.add(cyl_z(zc - L / 2, zc + L / 2, xc, y, r, 10), 0xc9a15c)
        for s in (-1, 1):
            v.add(cyl_z(zc + s * L / 2, zc + s * (L / 2 + 3.0), xc, y, 0.26, 6), C_SILVER)
            v.add(cyl_y(yb - 0.8, y, xc, zc + s * (L / 2 + 3.0), 0.26, 6), C_SILVER)


def _cap_film(v, xc, yb, zc, w=4.4, t=2.2, h=5.0, col=0x2f6ea8):
    v.add(box(xc - w / 2, xc + w / 2, yb + 1.0, yb + 1.0 + h, zc - t / 2, zc + t / 2), col)
    for s in (-1.27, 1.27):
        v.add(cyl_y(yb - 0.8, yb + 1.2, xc + s, zc, 0.26, 6), C_SILVER)


def _cap_elec(v, xc, yb, zc, d=6.3, h=11.0):
    v.add(cyl_y(yb + 0.6, yb + 0.6 + h, xc, zc, d / 2, 16), 0x1b2b52)
    v.add(cyl_y(yb + 0.6 + h - 0.4, yb + 0.6 + h + 0.05, xc, zc, d / 2 - 0.5, 16), 0x0e1730)
    v.add(box(xc - d / 2 + 0.2, xc - d / 2 + 1.4, yb + 1.0, yb + 0.6 + h - 1.0,
              zc - 1.6, zc + 1.6), 0xd8dde6)
    for s in (-1.27, 1.27):
        v.add(cyl_y(yb - 0.8, yb + 0.8, xc + s, zc, 0.26, 6), C_SILVER)


def _header(v, x0, x1, yb, z0, z1, h=8.5, pitch=2.54, female=False):
    """Header 2 hàng (hoặc 1 hàng nếu |z1-z0| nhỏ) — thân nhựa + chân mạ vàng."""
    v.add(box(x0, x1, yb, yb + h, z0, z1), C_BLACK)
    n = int(round((x1 - x0 - 0.6) / pitch))
    rows = [z0 + 1.27, z1 - 1.27] if (z1 - z0) > 4.0 else [(z0 + z1) / 2]
    for i in range(n):
        ux = x0 + 1.27 + i * pitch
        for zz in rows:
            if female:
                v.add(cyl_y(yb + h - 1.2, yb + h + 0.05, ux, zz, 0.55, 6), 0x30363f)
            else:
                v.add(box(ux - 0.32, ux + 0.32, yb + h, yb + h + 3.0,
                          zz - 0.32, zz + 0.32), C_GOLD)


def _term_block(v, x0, x1, yb, zc, npos=3, w=8.0, h=9.0, face="-x"):
    """Cầu đấu vít (screw terminal) 2.54/5.08 mm."""
    v.add(box(x0, x1, yb, yb + h, zc - w / 2, zc + w / 2), 0x1b6ea8)
    for i in range(npos):
        zz = zc - (npos - 1) * 2.54 + i * 5.08
        v.add(cyl_y(yb + h - 0.6, yb + h + 0.2, (x0 + x1) / 2, zz, 1.5, 10), C_SILVER)
        if face == "-x":
            v.add(cyl_x(x0 - 0.6, x0 + 1.0, yb + h / 2, zz, 1.2, 10), C_BLACK)


def _screw(v, x, y, z, r=2.6, h=1.8, axis="y"):
    if axis == "y":
        v.add(cyl_y(y, y + h, x, z, r, 12), C_SILVER)
        v.add(box(x - r + 0.4, x + r - 0.4, y + h - 0.35, y + h + 0.05, z - 0.5, z + 0.5),
              0x8a929c)
    else:
        v.add(cyl_x(x, x + h, y, z, r, 12), C_SILVER)


def pi4_vis(v):
    """Raspberry Pi 4 Model B.
    [SPEC] PCB 85 x 56 x 1.4 mm, 4 lỗ M2.5 cách mép 3.5 mm, bước lỗ 58 x 49 mm.
    [ASSUME] toạ độ chi tiết của từng connector/IC — chỉ để nhận dạng trực quan,
             KHÔNG dùng để gia công. Bản vẽ cơ khí trong tài liệu Pi là ảnh,
             không trích được số bằng chữ."""
    def u(a): return PI_X0 + a
    def w(a): return PI_Z0 + a
    y0, y1 = PI_Y0, PI_Y1
    v.add(box(u(0), u(85), y0, y1, w(0), w(56)), C_PCB_PI)
    for du in (3.5, 61.5):
        for dw in (3.5, 52.5):
            v.add(_tube("y", y0 - 0.1, y1 + 0.1, u(du), w(dw), 1.35, 12), C_SILVER)
            _screw(v, u(du), y1, w(dw))
    _header(v, u(7.0), u(57.8), y1, w(50.0), w(55.0), h=8.5)           # GPIO 2x20
    v.add(box(u(66.0), u(85.0), y1, y1 + 13.5, w(40.5), w(56.5)), C_SILVER)   # RJ45
    v.add(box(u(84.0), u(85.0), y1 + 2.0, y1 + 11.0, w(43.0), w(54.0)), C_BLACK)
    for (a, b) in ((21.0, 34.0), (3.0, 16.0)):                          # USB3 / USB2
        v.add(box(u(68.5), u(85.0), y1, y1 + 15.6, w(a), w(b)), C_SILVER)
        for hy in (y1 + 1.6, y1 + 9.6):
            v.add(box(u(84.2), u(85.0), hy, hy + 5.0, w(a + 1.5), w(b - 1.5)),
                  0x2352a8 if a == 21.0 else C_BLACK)
    v.add(box(u(6.5), u(15.5), y1, y1 + 3.2, w(-1.5), w(5.5)), C_SILVER)      # USB-C
    for a in (21.0, 34.5):                                                    # micro-HDMI
        v.add(box(u(a), u(a + 8.0), y1, y1 + 3.6, w(-1.0), w(5.5)), C_SILVER)
    v.add(cyl_z(w(-2.0), w(5.5), u(53.5), y1 + 3.0, 3.1, 16), C_BLACK)        # A/V jack
    v.add(box(u(25.5), u(40.5), y1, y1 + 1.6, w(20.5), w(35.5)), 0x23262c)    # BCM2711
    v.add(box(u(43.0), u(55.0), y1, y1 + 1.1, w(24.0), w(36.0)), 0x2b2f36)    # LPDDR4
    v.add(box(u(60.0), u(69.0), y1, y1 + 1.0, w(28.0), w(37.0)), 0x2b2f36)    # VL805
    v.add(box(u(14.0), u(24.0), y1, y1 + 1.4, w(8.0), w(18.0)), 0x2b2f36)     # PMIC
    v.add(box(u(44.5), u(47.5), y1, y1 + 3.0, w(14.0), w(30.0)), 0x22262d)    # CSI
    v.add(box(u(5.0), u(8.0), y1, y1 + 3.0, w(14.0), w(30.0)), 0x22262d)      # DSI
    v.add(box(u(-1.0), u(14.0), y0 - 2.0, y0, w(21.5), w(33.5)), C_SILVER)    # microSD
    for i, cc in enumerate((0xc02020, 0x20b040)):
        v.add(box(u(2.0), u(3.6), y1, y1 + 0.9, w(36.0 + i * 3.0), w(38.0 + i * 3.0)), cc)
    return v


GROVE_PORTS = {                    # [ASSUME] vị trí socket — CHỈ minh hoạ trực quan
    "A0": (9.5, 50.5), "A2": (22.5, 50.5), "A4": (35.5, 50.5), "A6": (48.5, 50.5),
    "D5": (9.5, 5.5),  "D16": (22.5, 5.5), "D18": (35.5, 5.5), "PWM": (48.5, 5.5),
    "I2C1": (12.0, 28.0), "I2C2": (27.0, 28.0), "UART": (42.0, 28.0),
}


def grove_port_xyz(name):
    """Toạ độ thế giới của miệng socket Grove (điểm cắm dây)."""
    cu, cw = GROVE_PORTS[name]
    return [PI_X0 + cu, HAT_Y1 + 3.4, PI_Z0 + cw]


def grove_hat_vis(v):
    """Grove Base HAT for Raspberry Pi (MM32F031F6P6, ADC I2C 0x08).
    [DS] grove_base_hat.pdf chỉ xác nhận MCU MM32 + địa chỉ 0x08 và việc có các cổng
         Digital/Analog/I2C/PWM/UART. Tài liệu KHÔNG có bản vẽ vị trí socket.
    [SPEC] khuôn dạng HAT 65 x 56.5 mm.
    [ASSUME] toàn bộ số lượng & toạ độ socket dưới đây."""
    def u(a): return PI_X0 + a
    def w(a): return PI_Z0 + a
    v.add(box(u(0), u(HAT_L), HAT_Y0, HAT_Y1, w(0), w(HAT_W)), C_PCB_G)
    for du in (3.5, 61.5):
        for dw in (3.5, 52.5):
            v.add(_tube("y", HAT_Y0 - 0.1, HAT_Y1 + 0.1, u(du), w(dw), 1.35, 12), C_SILVER)
    _header(v, u(7.0), u(57.8), PI_Y1, w(50.0), w(55.0), h=HDR_H, female=True)
    v.add(box(u(28.0), u(35.0), HAT_Y1, HAT_Y1 + 0.9, w(18.0), w(25.0)), 0x23262c)  # MM32
    v.add(box(u(40.0), u(44.0), HAT_Y1, HAT_Y1 + 1.0, w(18.0), w(22.0)), 0x2b2f36)
    for name, (cu, cw) in GROVE_PORTS.items():
        v.add(box(u(cu - 6.1), u(cu + 6.1), HAT_Y1, HAT_Y1 + 6.8,
                  w(cw - 3.8), w(cw + 3.8)), C_WHITE)
        v.add(box(u(cu - 4.9), u(cu + 4.9), HAT_Y1 + 1.2, HAT_Y1 + 6.0,
                  w(cw - 3.8), w(cw - 2.6)), 0xbdb9ac)
        for i in range(4):
            v.add(box(u(cu - 3.0 + i * 2.0 - 0.3), u(cu - 3.0 + i * 2.0 + 0.3),
                      HAT_Y1, HAT_Y1 + 3.2, w(cw - 1.2), w(cw + 1.2)), C_GOLD)
    return v


def mcp4725_vis(v, x0, z0, yb):
    """Breakout MCP4725 (12-bit DAC, I2C). [ASSUME] PCB 17.8 x 15.2 x 1.2 mm.
    5 chân theo đúng các net trong PPG_PROTOTYPE_SCHEMATIC.md: VDD, GND, SCL, SDA, VOUT."""
    y1 = yb + DAC_HDR_H
    _header(v, x0 + 1.6, x0 + 1.6 + 5 * 2.54, yb, z0 + 1.5, z0 + 3.5, h=DAC_HDR_H)
    v.add(box(x0, x0 + DAC_L, y1, y1 + DAC_T, z0, z0 + DAC_W), C_PCB_RD)
    v.add(box(x0 + 4.0, x0 + 11.0, y1 + DAC_T, y1 + DAC_T + 1.1,
              z0 + 6.0, z0 + 12.0), 0x23262c)                     # MCP4725 SOT-23-6
    v.add(box(x0 + 12.5, x0 + 14.3, y1 + DAC_T, y1 + DAC_T + 0.8,
              z0 + 6.5, z0 + 8.3), 0x8a6a2a)                      # tụ bypass on-module
    v.add(pad_grid("y", y1 + DAC_T, x0, x0 + DAC_L, z0, z0 + DAC_W,
                   pitch=2.54, r=0.6, margin=1.4), C_GOLD)
    return v


def driver_board_vis(v):
    """Perfboard driver 70 x 55 mm — bố cục theo ảnh thực tế (hình 1), gọn area:
    2× MCP4725 ở 2 góc trên (trái 0x60->IR, phải 0x61->Đỏ), LM358 ở giữa,
    2× 2N4401 (TO-92) + 2× điện trở cảm biến (E→GND, thay được) phía dưới,
    header cái ra LED ở cạnh dưới. Hệ cục bộ; collect_parts() xoay + đặt.
    Mạch tối giản thật: LM358 -> 2N4401 -> R(E→GND) -> GND, LED trên collector."""
    yb = DRV_Y1
    v.add(box(0, DRV_L, DRV_Y0, DRV_Y1, 0, DRV_W), C_PCB_G)
    v.add(pad_grid("y", DRV_Y1, 0, DRV_L, 0, DRV_W, pitch=2.54, r=0.62, margin=3.0), C_GOLD)
    for lx in (4.0, DRV_L - 4.0):
        for lz in (4.0, DRV_W - 4.0):
            v.add(_tube("y", DRV_Y0 - 0.1, DRV_Y1 + 0.1, lx, lz, 1.7, 12), C_GOLD)
            _screw(v, lx, DRV_Y1, lz, r=3.0)
    # 2× MCP4725 breakout (đỏ) — góc trên trái / phải, header hướng cạnh trên
    mcp4725_vis(v, 2.0, 3.0, yb)                       # 0x60 -> IR
    mcp4725_vis(v, DRV_L - 2.0 - DAC_L, 3.0, yb)       # 0x61 -> Đỏ
    # 2 header 4 chân nối I2C/GPIO (cạnh trên, giữa 2 module)
    _header(v, 24.0, 31.6, yb, 1.0, 5.0, h=8.5)
    _header(v, 38.4, 46.0, yb, 1.0, 5.0, h=8.5)
    # LM358 (DIP-8) — op-amp điều khiển cấp dòng, chung 2 kênh, giữa board
    _dip(v, 35.0, yb, 26.0, 8)
    # tụ decouple 100 nF cạnh LM358 (duy nhất)
    _cap_film(v, 48.0, yb, 30.0, col=0x2f6ea8)
    # 2× 2N4401 (TO-92) — khóa dòng LED, phía dưới LM358
    _to92(v, 30.0, yb, 38.0)                           # Q1 — kênh IR
    _to92(v, 40.0, yb, 38.0)                           # Q2 — kênh Đỏ
    # header cái ra LED — đặt SÁT MÉP -X board (world x≈7..11): dây ra thẳng
    # về phía hộp tối, không phải chạy vắt qua mặt board (tránh đâm linh kiện)
    _header(v, 24.0, 41.0, yb, 51.0, 55.0, h=8.5, female=True)
    # 2× điện trở cảm biến (E→GND) là part riêng 'rsense_*' — xem collect_parts()
    return v


def sense_resistor_subs(lx, lz):
    """Điện trở axial nằm ngang trên board driver với 4 vòng màu (mã 4 vạch).
    Trả list (mesh, màu) theo THỨ TỰ CỐ ĐỊNH: [thân, vòng1..4, chân1, chân2] —
    viewer đổi màu vòng (children 1..4) theo giá trị R người dùng chọn."""
    yb = DRV_Y1 + 1.3                                  # thân nổi trên board
    L, r = 6.2, 1.15
    out = []
    out.append((cyl_x(lx - L / 2, lx + L / 2, yb, lz, r, 12), 0xc9a15c))   # thân
    for off in (-1.7, -0.9, -0.1, 0.7):                # 4 vòng màu gần 1 đầu
        out.append((cyl_x(lx + off - 0.32, lx + off + 0.32, yb, lz, r + 0.09, 12),
                    0x777777))                          # placeholder — JS tô lại
    for s in (-1, 1):                                  # 2 chân
        out.append((cyl_x(lx + s * L / 2, lx + s * (L / 2 + 3.0), yb, lz, 0.26, 6),
                    C_SILVER))
    return out


def beam_vis(v, ch):
    """Chùm sáng LED dạng nón (frustum) từ chóp LED tới cửa sổ OPT101.
    [DS] datasheet LED: 2θ½ Đỏ 40-60° (lấy 50°), IR 30° -> nửa góc 25°/15°.
    Viewer bật/tắt + điều chỉnh độ trong suốt theo sóng PPG khi mô phỏng."""
    tip = X_WIN - D_DEFAULT[ch]                        # chóp LED tại khoảng cách mặc định
    half = math.radians(25.0 if ch == "red" else 15.0)
    r1 = 1.5 + (X_WIN - tip) * math.tan(half)
    col = 0xff4040 if ch == "red" else 0x9a6aff
    v.add(frustum_x(tip, X_WIN, Y_AX, LANE_Z[ch], 1.5, r1, 32), col, 0.10)
    v.add(sphere(2.4, tip, Y_AX, LANE_Z[ch], sub=2), col, 0.30)   # quầng sáng tại chóp LED
    return v


# ============================================================================
# 5. DÂY DẪN / CÁP (chỉ để nhìn — toạ độ [ASSUME] theo bố cục bên trên)
# ============================================================================
def wires_vis(v):
    """Toàn bộ bó dây của hệ thống:
    TX : cầu đấu board driver -> chụp -X -> máng sàn -> carrier LED
    RX : 3 dây OPT101 -> chụp +X -> cáp Grove -> socket A0/A2 trên HAT
    I2C: socket I2C trên HAT -> 2 module MCP4725 trên board driver
    PWR: cáp USB-C cấp nguồn cho Pi."""
    # ---------- TX: driver (cùng bên -Z với Pi) -> LED ----------
    # Header ra LED ở cạnh dưới board (local z=45 -> world x=17, z=-136/-127).
    # Bẹ 2 sợi đỏ/đen chạy trên board ra mép -X, xuống đế, dọc mép -X đế,
    # qua khe sàn chụp -X -> cổng -> máng sàn -> nối vào carrier LED.
    tx = {
        "ir": [(9, 13.5, -131), (5, 7, -130), (2, 2, -127), (-3, 1.8, -122),
               (-7, 1.8, -100), (-7, 1.8, -40), (-7, 1.8, 0), (-7, 1.8, 12),
               (-6, 6, 18), (-4, 9, 19.25), (-1, 8, 19.25), (2, 7, 19.25),
               (3.8, 5.5, 19.25), (5, 2.6, 31), (12, 2.6, 31), (13, 7, 20.5)],
        "red": [(9, 13.5, -128), (5, 7, -127), (2, 2, -124), (-3, 1.8, -119),
                (-7, 1.8, -105), (-7, 1.8, -80), (-7, 1.8, -40), (-7, 1.8, -28),
                (-6, 6, -18), (-4, 9, -19.25), (-1, 8, -19.25), (2, 7, -19.25),
                (3.8, 5.5, -19.25), (5, 2.6, -31), (68, 2.6, -31), (72, 7, -20.5)],
    }
    for pts in tx.values():
        for m, c in harness(pts, [(-0.55, C_WIRE_R), (0.55, C_WIRE_K)],
                            r=0.55, n=8, tie_step=14.0, tie_skip_y=(0.0, 5.6)):
            v.add(m, c)

    # ---------- RX: OPT101 -> khe trên khung -> chụp +X -> cáp Grove -> HAT ----------
    for ch, sock in (("ir", "A0"), ("red", "A2")):
        zc = LANE_Z[ch]
        # 3 sợi (đỏ/đen/vàng) từ header 6 chân, qua khe dây trên khung, ra chụp,
        # xuống khe sàn chụp rồi nối vào cáp Grove trắng.
        rx = [(132.0, 23, zc), (132.5, 46, zc), (133.2, 53, zc), (135, 56, zc),
              (138, 58.5, zc), (141, 58, zc), (141, 40, zc), (141, 20, zc),
              (141, 12, zc), (144, 11, zc), (147, 10.5, zc), (151, 10.5, zc),
              (156, 12, zc), (162, 16, zc), (168, 19, zc), (167, 8, zc),
              (167, 3.2, zc), (166, 2.5, zc)]
        for m, c in harness(rx, [(-5.08, C_WIRE_R), (0.0, C_WIRE_K), (5.08, C_WIRE_Y)],
                            r=0.35, n=6, tie_step=16.0):
            v.add(m, c)
        # cáp Grove trắng: khe sàn chụp -> leo qua mép ngoài chụp -> chạy TRÊN NỌC
        # chụp -> bám mặt +X hộp -> mép nắp -> chạy trên nắp -> bám mặt -Z hộp ->
        # socket HAT. Cáp ĐÍNH SÁT hộp (không thả lỏng võng trên cao).
        ge = grove_port_xyz(sock)
        wz = -41.5 if ch == "ir" else -43.8           # lệch nhau khi bám mặt -Z
        gv = [(167, 2.5, zc), (172, 2.5, zc), (173.5, 6, zc), (173.5, 14, zc),
              (172.5, 22, zc), (170, 25.5, zc), (165, 25.5, zc), (157, 25.5, zc),
              (152.5, 30, zc), (151.5, 40, zc), (151.5, 55, zc), (151.5, 66, zc),
              (150, 68.6, zc), (145, 68.6, 5), (140, 68.6, -15), (136, 68.6, -30),
              (133, 68.6, -39), (133, 64, wz), (131, 54, wz), (128, 42, wz),
              (125, 30, wz), (122, 24, wz - 0.5 if ch == "red" else wz + 0.5),
              (115, 25, -46), (105, 25, -52), (95, 25, -57)]
        if ch == "ir":
            gv += [(85, 25, -58.5), (78, 24.5, -58.5), (71.5, 20, -57.5), ge]
        else:
            gv += [(90, 25, -58.5), (87, 24.5, -58.5), (84.5, 20, -57.5), ge]
        for m, c in harness(gv, [(0.0, C_WHITE)], r=1.1, n=8, tie_step=40.0):
            v.add(m, c)

    # ---------- I2C: HAT -> 2 module MCP4725 trên board driver (cùng bên -Z) ----------
    # Header I2C của 2 module nằm tại world x≈56.5 (module #1 z≈-154, #2 z≈-106).
    # Cáp trắng vòng lên trên HAT (y=28) rồi chạy DỌC MÉP +X board (x=62.5, ngoài
    # các module cao 16.3) và cắm xuống từng header từ phía trên.
    i2c_a = [(74, 19.9, -80), (74, 28, -80), (66, 28, -84), (63, 22, -87),
             (62.5, 12, -92), (62.5, 12, -152), (57.5, 16.6, -154)]
    i2c_b = [(89, 19.9, -80), (89, 28, -80), (80, 28, -83), (64, 22, -86),
             (63.8, 12, -91), (63.8, 12, -106), (58.5, 16.6, -106)]
    for pts, w in ((i2c_a, [(0.0, C_WHITE)]), (i2c_b, [(0.0, C_WHITE)])):
        for m, c in harness(pts, w, r=0.75, n=8, tie_step=18.0):
            v.add(m, c)

    # ---------- PWR: USB-C -> Pi (tiếp cận từ -Z, đúng hướng cổng) ----------
    for m, c in harness([(96, 7, -128), (90, 7, -122), (82, 7, -116), (78, 7, -112),
                         (75, 7.5, -109.5), (73, 8.2, -109.5)], [(0.0, C_WIRE_K)], r=1.2, n=8,
                        tie_step=18.0):
        v.add(m, c)
    return v


# ============================================================================
# 6. LẮP RÁP & XUẤT FILE
# ============================================================================
def _place_shaft(ch):
    m = build_shaft()
    m.apply_transform(translation_matrix([0.0, 0.0, LANE_Z[ch]]))
    return m


def _place_carrier(ch):
    m = build_carrier()
    m.apply_transform(translation_matrix([x_front(ch), 0.0, LANE_Z[ch]]))
    return m


def _vis_subs(builder, *args):
    v = Vis()
    builder(v, *args)
    return v.subs()


def collect_parts():
    parts = []

    def add(name, mesh, color, explode, flip=False, label=None, subs=None, printable=True):
        parts.append(dict(name=name, mesh=mesh, color=color, explode=explode, flip=flip,
                          label=label or name, subs=subs, printable=printable))

    add("body", build_body(), C_BODY, [0, 0, 0], label="Thân hộp tối (2 làn quang)")
    add("lid", build_lid(), C_LID, [0, 42, 0], flip=True, label="Nắp labyrinth")
    for ch, cc, vn in (("red", C_CAR_R, "Đỏ"), ("ir", C_CAR_I, "IR")):
        add(f"slide_shaft_{ch}", _place_shaft(ch), C_SHAFT, [-60, 0, 0],
            label=f"Trục trượt D Ø8 — làn {vn}")
        add(f"led_carrier_{ch}", _place_carrier(ch), cc, [-46, 0, 0], flip=True,
            label=f"Carrier LED {vn}")
        add(f"led_{ch}", None, C_LEDR if ch == "red" else C_LEDI, [-46, 0, 0],
            label=("LED Đỏ 622nm" if ch == "red" else "LED IR 875nm"),
            printable=False, subs=_vis_subs(led_vis, ch, x_front(ch)))
    add("frame", build_frame(), C_FRAME, [26, 0, 0], label="Khung giữ board 5×7")
    for kind, kl in (("blank", "bịt kín"), ("d2", "Ø2 mm"), ("d5", "Ø5 mm"), ("d16", "Ø16 mm")):
        for ch in ("red", "ir"):
            m = build_aperture(kind)
            m.apply_transform(translation_matrix([AP_X0, 0.0, LANE_Z[ch]]))
            add(f"aperture_{ch}_{kind}", m, C_APER, [0, 26, 0], printable=(ch == "red"),
                label=f"Khẩu độ {'Đỏ' if ch == 'red' else 'IR'} {kl}")
    for ch in ("red", "ir"):
        for sgn, snm, sn in ((-1.0, "l", "trái"), (1.0, "r", "phải")):
            m = build_hood(sgn)
            # build_hood() dựng quanh gốc: phải dời về đúng thành hộp và đúng làn.
            m.apply_transform(translation_matrix(
                [0.0 if sgn < 0 else X_TOT, 0.0, LANE_Z[ch]]))
            add(f"hood_{snm}_{ch}", m, C_PRINT2, [sgn * 26, 0, 0],
                printable=(ch == "red"),
                label=f"Chụp che sáng {sn} — {'Đỏ' if ch == 'red' else 'IR'}")
    add("base_neg", build_base("neg"), C_BASE, [0, -26, -10],
        label="Đế — Pi 4 + Grove HAT + driver + 2× MCP4725")
    add("base_pos", build_base("pos"), C_BASE, [0, -26, 10],
        label="Đế — nửa đối diện (dưới hộp tối)")

    # ---- mua sẵn / chỉ để nhìn (không xuất STL) ----
    for ch, lbl in (("ir", "OPT101 #1 — IR → A0"), ("red", "OPT101 #2 — Đỏ → A2")):
        add(f"opt101_{ch}", None, C_PCB_PU, [40, 0, 0], label=lbl,
            printable=False, subs=_vis_subs(opt101_vis, ch))
    add("sensor_board", None, C_PCB_G, [40, 0, 0],
        label="Board cảm biến 5×7 cm", printable=False, subs=_vis_subs(sensor_board_vis))
    add("pi4", None, C_PCB_PI, [0, -16, -34], label="Raspberry Pi 4 Model B",
        printable=False, subs=_vis_subs(pi4_vis))
    add("grove_hat", None, C_PCB_G, [0, -32, -34], label="Grove Base HAT (ADC 0x08)",
        printable=False, subs=_vis_subs(grove_hat_vis))

    # board driver: dựng hệ cục bộ rồi XOAY 90° quanh Y + đặt cùng bên -Z với Pi.
    drv_T = (translation_matrix([DRV_WX, 0.0, DRV_WZ])
             @ rotation_matrix(-math.pi / 2, [0, 1, 0]))

    def place(subs, T):
        out = []
        for s in subs:
            m = s["mesh"].copy()
            m.apply_transform(T)
            d = dict(s)
            d["mesh"] = m
            out.append(d)
        return out

    add("driver_board", None, C_PCB_G, [0, -16, 34],
        label="Board driver LED (LM358 + 2×2N4401 + 2×MCP4725)", printable=False,
        subs=place(_vis_subs(driver_board_vis), drv_T))

    # 2× điện trở cảm biến (E→GND, THAY ĐƯỢC) — 4 vòng màu tô lại trong viewer
    # theo giá trị R người dùng chọn. Thứ tự subs: [thân, vòng1..4, chân1, chân2].
    for ch, (lx, lz), def_r in (("ir", (28.0, 47.0), 82), ("red", (37.0, 47.0), 100)):
        subs = []
        for mesh, col in sense_resistor_subs(lx, lz):
            m = mesh.copy()
            m.apply_transform(drv_T)
            subs.append(dict(mesh=m, color=col))
        add(f"rsense_{ch}", None, 0xc9a15c, [0, 0, 0],
            label=(f"R cảm biến IR (E→GND) — mặc định {def_r} Ω" if ch == "ir"
                   else f"R cảm biến Đỏ (E→GND) — mặc định {def_r} Ω"),
            printable=False, subs=subs)

    # chùm sáng LED (bật/tắt trong viewer theo mô phỏng PPG)
    for ch, lbl in (("red", "Chùm sáng LED Đỏ"), ("ir", "Chùm sáng LED IR")):
        add(f"beam_{ch}", None, 0xff4040 if ch == "red" else 0x9a6aff, [0, 0, 0],
            label=lbl, printable=False, subs=_vis_subs(beam_vis, ch))

    add("wiring", None, C_WIRE_K, [0, 0, 0],
        label="Dây dẫn / cáp (minh hoạ)", printable=False, subs=_vis_subs(wires_vis))
    return parts


# Nhãn linh kiện hiển thị trong viewer (sprite) — toạ độ thế giới + chữ
def _drv_label(lx, lz, dy, text):
    x, z = drv_world(lx, lz)
    return dict(pos=[round(x, 1), round(DRV_Y1 + dy, 1), round(z, 1)], text=text)


DRVLABELS = [
    _drv_label(11.0, 10.6, 9.0, "MCP4725 #1 (0x60) → IR"),
    _drv_label(59.0, 10.6, 9.0, "MCP4725 #2 (0x61) → Đỏ"),
    _drv_label(35.0, 26.0, 8.5, "LM358"),
    _drv_label(30.0, 38.0, 8.5, "Q1 2N4401 (IR)"),
    _drv_label(40.0, 38.0, 8.5, "Q2 2N4401 (Đỏ)"),
    _drv_label(28.0, 47.0, 7.5, "R_sense IR (E→GND)"),
    _drv_label(37.0, 47.0, 7.5, "R_sense Đỏ (E→GND)"),
    dict(pos=[122.4, 49.0, 19.25], text="OPT101 #1 (IR → A0)"),
    dict(pos=[122.4, 49.0, -19.25], text="OPT101 #2 (Đỏ → A2)"),
    dict(pos=[104.0, 18.0, -79.0], text="Grove Base HAT (ADC 0x08)"),
]


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
            if s.get("map"):
                d["map"] = s["map"]
            if s.get("uvbase64"):
                d["uvbase64"] = s["uvbase64"]
            subdata.append(d)
            b = mesh.bounds.reshape(-1)
            allb = [float(x) for x in b] if allb is None else [
                min(float(allb[i]), float(b[i])) if i < 3 else max(float(allb[i]), float(b[i])) for i in range(6)]
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


# ============================================================================
# 7. VIEWER (three.js offline, nhúng sẵn vendor/*.js)
# ============================================================================
VIEWER_TEMPLATE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>PPG Simulator — mô hình 3D toàn hệ thống</title>
<style>
 :root{--bg:#0d0f13;--panel:#161a22;--ink:#dfe5ee;--dim:#8b94a6;--acc:#e8b64c;}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,'Segoe UI',Roboto,sans-serif;overflow:hidden}
 #view{position:fixed;inset:0}
 .panel{position:fixed;top:12px;left:12px;width:300px;max-height:calc(100vh - 24px);overflow:auto;
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
  select.sel{flex:1.4;background:#232a38;color:var(--ink);border:1px solid #35405a;
    border-radius:8px;padding:4px 6px;font-size:12.5px}
 #hud{position:fixed;right:14px;bottom:12px;color:var(--dim);font-size:12px}
</style>
</head>
<body>
<div id="view"></div>
<div class="panel">
  <h1>PPG Simulator — mô hình 3D toàn hệ thống</h1>
  <div class="sub">Hộp tối 2 làn quang (Đỏ -Z / IR +Z) · board 5×7 + 2× OPT101 ·
  đế chung Pi 4 + Grove HAT + driver + 2× MCP4725<br>
  <span style="color:#ff6060">■</span> LED Đỏ &nbsp;
  <span style="color:#8a5cf0">■</span> LED IR &nbsp;
  <span style="color:#66ccff">■</span> cửa sổ OPT101 &nbsp;
  <span style="color:#e8e4d8">■</span> cáp Grove</div>
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
    <button data-v="inIR">Trong làn IR</button><button data-v="inRed">Trong làn Đỏ</button>
  </div>
  <div class="row"><button data-v="elec">Khối điện tử</button><button data-v="top2">Nhìn hộp từ nóc</button></div>
  <fieldset><legend>Mô phỏng quang học — mô hình PPG (Allen 2007)</legend>
    <div class="row"><button id="bSim">🔦 Bật LED phát sáng</button><button id="bLbl">🏷️ Nhãn linh kiện</button></div>
    <div class="row"><label>Nhịp tim (BPM)</label><input id="hr" type="range" min="40" max="180" value="75"></div>
    <div class="row"><label>Chỉ số tưới PI (%)</label><input id="pi" type="range" min="5" max="200" value="30"></div>
    <div class="row"><label>SpO₂ (%)</label><input id="spo2" type="range" min="85" max="100" value="98"></div>
    <div class="row"><label>Nhịp thở (/phút)</label><input id="rr" type="range" min="8" max="30" value="16"></div>
    <div class="row"><label>Độ sáng hiển thị</label><input id="ledPow" type="range" min="0" max="100" value="60"></div>
    <div class="row"><label>R cảm biến IR (E→GND)</label><select id="rsIr" class="sel"></select></div>
    <div class="row"><label>R cảm biến Đỏ (E→GND)</label><select id="rsRed" class="sel"></select></div>
    <canvas id="ppgPrev" width="268" height="64" style="width:100%;background:#0b0e13;border:1px solid #2a3140;border-radius:6px;margin-top:4px"></canvas>
    <div id="iInfo" class="hint" style="margin-top:4px"></div>
  </fieldset>
  <fieldset><legend>Bộ phận (bấm để ẩn/hiện)</legend><div id="parts"></div></fieldset>
  <div class="hint">
    Kéo chuột: xoay • Lăn chuột: thu phóng • Chuột phải: di chuyển.<br>
    <b>Mặt cắt</b>: trượt để cắt mô hình theo phương X.<br>
    <b>Tách rời</b>: kéo để xem thứ tự lắp ráp.<br>
    Kích thước đế tổng thể <b>__DIM__ mm</b> (đơn vị mô hình: mm).<br>
    Khoảng cách mặc định: Đỏ d=25mm • IR d=85mm (chóp LED → cửa sổ OPT101).
  </div>
</div>
<div id="hud">docs/system_3d / build_system.py</div>
<script>/* three.js (inlined, MIT) */__THREE__</script>
<script>/* OrbitControls (inlined, MIT) */__ORBIT__</script>
<script>const MODEL = __MODEL__;</script>
<script>
/* base64 -> ArrayBuffer, roi DIEN GIAI LAI bit-pattern (khong duoc ghep so hoc:
   ghep 4 byte thanh so nguyen se bien float 25.0 thanh 1103101952). */
function b64buf(b){const s=atob(b),n=s.length,u=new Uint8Array(n);
 for(let i=0;i<n;i++)u[i]=s.charCodeAt(i);return u.buffer}
function b64f32(b){return new Float32Array(b64buf(b))}
function b64u32(b){return new Uint32Array(b64buf(b))}
const scene=new THREE.Scene();scene.background=new THREE.Color(0x12151b);
const camera=new THREE.PerspectiveCamera(42,innerWidth/innerHeight,0.5,4000);
const renderer=new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setSize(innerWidth,innerHeight);
renderer.outputEncoding=THREE.sRGBEncoding;
renderer.localClippingEnabled=true;document.getElementById('view').appendChild(renderer.domElement);
const key=new THREE.DirectionalLight(0xffffff,1.2);key.position.set(160,260,180);scene.add(key);
const fill=new THREE.DirectionalLight(0x9db4ff,.55);fill.position.set(-200,-80,-160);scene.add(fill);
const rim=new THREE.DirectionalLight(0xffc46a,.4);rim.position.set(-120,180,-140);scene.add(rim);
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
    const mp={color:new THREE.Color(s.color),roughness:.75,metalness:.15,
      side:trans?THREE.FrontSide:THREE.DoubleSide,clippingPlanes:[clipPlane],
      transparent:trans,opacity:s.opacity||1,depthWrite:!trans};
    const mat=new THREE.MeshStandardMaterial(mp);
    grp.add(new THREE.Mesh(g,mat));
  });
  grp.userData.explode=new THREE.Vector3(...p.explode);
  partsGroup.add(grp);meshes[p.name]=grp;basePos[p.name]=new THREE.Vector3();
});
// optical axis helpers (lanes at z = ±19.25, optical axis y = 32)
const axesGroup=new THREE.Group();scene.add(axesGroup);axesGroup.visible=false;
function axisLine(z,col,label){
  const g=new THREE.BufferGeometry().setFromPoints(
    [new THREE.Vector3(3,32,z),new THREE.Vector3(121,32,z)]);
  axesGroup.add(new THREE.Line(g,new THREE.LineBasicMaterial({color:col})));
  const cv=document.createElement('canvas');cv.width=512;cv.height=64;const ctx=cv.getContext('2d');
  ctx.font='bold 30px system-ui';ctx.fillStyle='#'+col.toString(16).padStart(6,'0');
  ctx.fillText(label,6,42);
  const sp=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(cv),depthTest:false}));
  sp.scale.set(52,6.5,1);sp.position.set(148,42,z);axesGroup.add(sp);
}
axisLine(-19.25,0xff5555,'Đỏ 622nm → OPT101 → A2 (d=25mm)');
axisLine(19.25,0x6688ff,'IR 875nm → OPT101 → A0 (d=85mm)');
const grid=new THREE.GridHelper(560,56,0x223,0x1a2030);
grid.position.set(75,-10.5,0);scene.add(grid);
function setView(v){
  const d=rad*1.4;
  if(v==="inIR"){camera.position.set(6,32,19.25);controls.target.set(118,32,19.25);}
  else if(v==="inRed"){camera.position.set(6,32,-19.25);controls.target.set(118,32,-19.25);}
  else if(v==="elec"){camera.position.set(75,190,175);controls.target.set(75,8,0);}
  else if(v==="top2"){camera.position.set(75,190,0.5);controls.target.set(75,10,0);}
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
$('clip').oninput=e=>{clipPlane.constant=-24+e.target.value/100*(174+24);};
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
/* ========== MÔ PHỎNG QUANG HỌC — PORT TỪ models/ppg_model.py ==========
   Mô hình 3 thành phần Gaussian (Allen 2007):
     đỉnh tâm thu  tại 15% chu kỳ (σ=0.055)
     chỗ cắt dicrotic tại 30%      (σ=0.020, bị TRỪ)
     đỉnh tâm trương tại 40%       (σ=0.100, biên 0.4)
   Chuẩn hoá (raw)/1.4 kẹp [0,1].  Ratio-of-ratios SpO2: R=(110−SpO2)/25 ∈[0.4,1.6],
   AC_Đỏ = R·AC_IR (DC hai kênh bằng nhau). Điều biến hô hấp AM ±25%, BW ±0.6%.
   Liên hệ nhịp: biên độ giảm ~3.2%/10 BPM trên 60. SpO2<94% làm mờ chỗ cắt. */
const P={SYST_POS:.15,NOTCH_POS:.30,DIAS_POS:.40,SYST_W:.055,DIAS_W:.10,NOTCH_W:.02,
         DIAS_RATIO:.4,NOTCH_DEPTH:.25,PULSE_MAX:1.4,FS:3.28,DC:1.5};
const SIM={on:false,hr:75,pi:3.0,spo2:98,rr:16,pow:0.6,t:0,_sec:-1};
const RSENSE={ir:82,red:100};
function pulseShape(ph,df){ph=((ph%1)+1)%1;
  const s=Math.exp(-((ph-P.SYST_POS)**2)/(2*P.SYST_W**2));
  const d=P.DIAS_RATIO*Math.exp(-((ph-P.DIAS_POS)**2)/(2*P.DIAS_W**2));
  const n=P.NOTCH_DEPTH*df*Math.exp(-((ph-P.NOTCH_POS)**2)/(2*P.NOTCH_W**2));
  return Math.max(0,Math.min(1,(s+d-n)/P.PULSE_MAX));}
function ppgAt(t){ // tín hiệu DAC (V) tại thời gian t (giây) — hàm thuần
  const beat=60/SIM.hr, ph=(t%beat)/beat;
  let df=1; if(SIM.spo2<94) df=1-0.6*Math.min(1,(94-SIM.spo2)/10);
  const pulse=pulseShape(ph,df);
  const R=Math.max(0.4,Math.min(1.6,(110-SIM.spo2)/25));
  let acIr=SIM.pi/100*P.DC, acRed=R*acIr;
  const hrF=Math.max(.7,1-.0032*Math.max(0,SIM.hr-60)); acIr*=hrF; acRed*=hrF;
  const respRad=t*SIM.rr/60*2*Math.PI;
  const am=1+.25*Math.sin(respRad);
  const bw=.006*P.DC*(.33*Math.sin(t*.3*2*Math.PI)+.67*Math.sin(respRad));
  const cl=v=>Math.max(0,Math.min(P.FS,v));
  return {ir:cl(P.DC+acIr*pulse*am+bw), red:cl(P.DC+acRed*pulse*am+bw),
          acIr:acIr*pulse*am, acRed:acRed*pulse*am};}
// LED phát sáng: emissive trên thân LED (đỏ/IR)
['led_red','led_ir'].forEach(n=>{const col=n==='led_red'?0xff3020:0x8a5cff;
  meshes[n].children.forEach(m=>{m.material.emissive=new THREE.Color(col);
    m.material.emissiveIntensity=0;});});
// đèn điểm tại chóp LED chiếu sáng lòng hộp
const ledLights={};
ledLights.red=new THREE.PointLight(0xff3020,0,500,2);ledLights.red.position.set(95,32,-19.25);scene.add(ledLights.red);
ledLights.ir=new THREE.PointLight(0x8a5cff,0,500,2);ledLights.ir.position.set(35,32,19.25);scene.add(ledLights.ir);
// chùm sáng: ẩn mặc định, hiện khi mô phỏng
if(meshes['beam_red'])meshes['beam_red'].visible=false;
if(meshes['beam_ir'])meshes['beam_ir'].visible=false;
// ---- điện trở cảm biến: 4 vòng màu theo mã 4 vạch (E12, ±5%) ----
const DIG=['#1a1a1e','#7a4426','#c62828','#e07b1f','#e8c72e','#3d8b37','#2456a8','#7b3fb5','#8a8f98','#f2f0e6'];
const GOLD='#c9a227';
const E12=[10,12,15,18,22,27,33,39,47,56,68,82,100,120,150,180,220,270,330,390,470,560,680,1000];
function bandCols(R){let m=0,v=R;while(v>=100){v/=10;m++;}
  const d1=Math.floor(v/10),d2=Math.round(v-d1*10);
  return [DIG[d1],DIG[d2],DIG[Math.min(9,m)],GOLD];}
function updRsense(){for(const lane of['ir','red']){const c=bandCols(RSENSE[lane]);
  meshes['rsense_'+lane].children.forEach((m,i)=>{if(i>=1&&i<=4)m.material.color.set(c[i-1]);});}
  updIInfo();}
// ---- nhãn linh kiện (sprite) ----
const DRVLABELS=__DRVLABELS__;
const lblGroup=new THREE.Group();lblGroup.visible=false;scene.add(lblGroup);
DRVLABELS.forEach(L=>{const cv=document.createElement('canvas');cv.width=320;cv.height=52;
  const c2=cv.getContext('2d');c2.fillStyle='rgba(13,15,19,.88)';c2.fillRect(2,2,316,48);
  c2.strokeStyle='#e8b64c';c2.lineWidth=2;c2.strokeRect(2,2,316,48);
  c2.fillStyle='#dfe5ee';c2.font='bold 21px system-ui';c2.fillText(L.text,14,33);
  const sp=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(cv),depthTest:false}));
  sp.scale.set(34,5.5,1);sp.position.set(L.pos[0],L.pos[1],L.pos[2]);lblGroup.add(sp);});
$('bLbl').onclick=e=>{lblGroup.visible=!lblGroup.visible;
  e.target.classList.toggle('on',lblGroup.visible);};
// ---- đồ thị PPG 2 kênh trên canvas ----
const pcv=$('ppgPrev'),pctx=pcv.getContext('2d');
function drawPPG(){
  const W=pcv.width,H=pcv.height,beat=60/SIM.hr;
  pctx.clearRect(0,0,W,H);
  pctx.strokeStyle='#222a38';pctx.lineWidth=1;
  for(let i=0;i<=4;i++){pctx.beginPath();pctx.moveTo(0,H*i/4);pctx.lineTo(W,H*i/4);pctx.stroke();}
  const draw=(col,ch)=>{pctx.beginPath();pctx.strokeStyle=SIM.on?col:'#4a5566';
    pctx.lineWidth=1.8;
    for(let i=0;i<W;i++){const s=ppgAt(i/W*beat*2.4);const v=s[ch]/P.FS;
      const x=i,y=H-(H*0.92*v+2);i?pctx.lineTo(x,y):pctx.moveTo(x,y);}
    pctx.stroke();};
  draw('#8a5cff','ir');draw('#e85a4f','red');
  pctx.fillStyle='#8b94a6';pctx.font='10px system-ui';
  pctx.fillText(SIM.on?('IR (tím) & Đỏ (đỏ) theo PPG • '+(SIM.hr|0)+' BPM • PI '+SIM.pi.toFixed(1)+
    '% • SpO2 '+SIM.spo2+'%'):'Bật "LED phát sáng" để xem hiệu ứng ánh sáng',6,12);
}
function updIInfo(){
  const s=ppgAt(SIM.t);
  $('iInfo').textContent='I_LED = V_DAC / R — IR: '+(s.ir/RSENSE.ir*1000).toFixed(1)+
    ' mA (R='+RSENSE.ir+' Ω) · Đỏ: '+(s.red/RSENSE.red*1000).toFixed(1)+' mA (R='+RSENSE.red+' Ω)';
}
$('bSim').onclick=e=>{SIM.on=!SIM.on;e.target.classList.toggle('on',SIM.on);
  $('bSim').textContent=SIM.on?'🔦 Tắt LED':'🔦 Bật LED phát sáng';drawPPG();};
$('hr').oninput=e=>{SIM.hr=+e.target.value;drawPPG();};
$('pi').oninput=e=>{SIM.pi=+e.target.value/10;drawPPG();};
$('spo2').oninput=e=>{SIM.spo2=+e.target.value;drawPPG();};
$('rr').oninput=e=>{SIM.rr=+e.target.value;drawPPG();};
$('ledPow').oninput=e=>{SIM.pow=+e.target.value/100;};
const rsSel={ir:$('rsIr'),red:$('rsRed')};
E12.forEach(v=>{for(const lane of['ir','red']){const o=document.createElement('option');
  o.value=v;o.textContent=v+' Ω';rsSel[lane].appendChild(o);}});
rsSel.ir.value='82';rsSel.red.value='100';
rsSel.ir.onchange=e=>{RSENSE.ir=+e.target.value;updRsense();};
rsSel.red.onchange=e=>{RSENSE.red=+e.target.value;updRsense();};
updRsense();drawPPG();
let lastT=performance.now()/1000;
(function loop(){requestAnimationFrame(loop);
  const now=performance.now()/1000, dt=Math.min(.05,now-lastT); lastT=now; SIM.t+=dt;
  if(auto){const t=Date.now()/3000;
    camera.position.set(ctr.x+rad*1.5*Math.cos(t),ctr.y+rad*.8,ctr.z+rad*1.5*Math.sin(t));
    camera.lookAt(ctr);}
  // độ sáng LED ∝ I_LED = V_DAC / R_sense (chuẩn hoá 15 mA @ 1.5 V / 100 Ω)
  const sig=SIM.on?ppgAt(SIM.t):null;
  ['ir','red'].forEach(lane=>{
    const s=sig?sig[lane]:0;
    const k=SIM.on?Math.max(.05,Math.min(2.5,(s/RSENSE[lane])/0.015)):0;
    const I=k*SIM.pow*1.3;
    meshes['led_'+lane].children.forEach(m=>{m.material.emissiveIntensity=I;});
    if(meshes['beam_'+lane]){meshes['beam_'+lane].visible=SIM.on&&I>0.02;
      meshes['beam_'+lane].children.forEach(m=>{m.material.opacity=Math.min(.4,.04+.22*k*SIM.pow);});}
    ledLights[lane].intensity=SIM.on?Math.min(4,k*SIM.pow*2.2):0;
  });
  if((now|0)!==SIM._sec){SIM._sec=now|0;updIInfo();}
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
    dim = (f"{BASE_X1 - BASE_X0:.0f} × {Y_LID + BASE_T + RIB_H:.0f} × "
           f"{BASE_Z1 - BASE_Z0:.0f}")
    html = (VIEWER_TEMPLATE
            .replace("__THREE__", three)
            .replace("__ORBIT__", orbit)
            .replace("__MODEL__", model)
            .replace("__DRVLABELS__", json.dumps(DRVLABELS))
            .replace("__DIM__", dim))
    path = os.path.join(HERE, "viewer.html")
    with open(path, "w") as f:
        f.write(html)
    print(f"  viewer.html: {os.path.getsize(path)/1e6:.1f} MB")


def main():
    print("=" * 78)
    print("PPG SIMULATOR — MÔ HÌNH 3D TOÀN HỆ THỐNG (docs/system_3d)")
    print(f"  Hộp tối: {X_TOT:.0f} × {Y_LID:.0f} × {Z1 - Z0:.0f} mm   "
          f"Đế chung: {BASE_X1 - BASE_X0:.0f} × {BASE_Z1 - BASE_Z0:.0f} mm (chia đôi in)")
    print(f"  Khoảng cách mặc định: Đỏ d={D_DEFAULT['red']:.0f} mm, "
          f"IR d={D_DEFAULT['ir']:.0f} mm (chóp LED → cửa sổ OPT101 tại x={X_WIN:.0f})")
    print("=" * 78)
    print("\nBuilding parts (manifold CSG) ...")
    parts = collect_parts()
    print("Exporting ...")
    export(parts)
    build_viewer()
    print("\nDone. Open docs/system_3d/viewer.html in a browser.")


if __name__ == "__main__":
    main()
