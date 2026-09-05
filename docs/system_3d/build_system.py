#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_system.py — MÔ HÌNH 3D TOÀN HỆ THỐNG "PPG SIMULATOR" (nguồn duy nhất).

Sinh ra:
  out/stl/*.stl   — các chi tiết IN 3D được (đã xoay về tư thế in)
  out/model.json  — toàn bộ hình học (float32/uint32 base64) cho viewer
  viewer.html     — trình duyệt 3D offline (three.js nhúng sẵn)

v2 (2026-08-30): cơ cấu chỉnh d bằng cần trượt nam châm ngoài nắp (bỏ cửa
hatch), chụp bắt vít xuyên từ mặt ngoài, 5 mộng nối đế.
v3 (2026-09-02): bỏ nam châm — thanh trụ Ø5 gắn cứng vào carrier xuyên vách -X
qua bệ dẫn hướng 21 mm (bẫy sáng khe vành, đẩy/kéo bằng tay, phần lộ ra = d);
chụp cáp khớp 4 trụ cắm Ø4 + mộng âm-dương kín sáng (bỏ vít M3); thêm 2 chân
đỡ màn hình cảm ứng 7 inch + lưới lỗ M3 mở rộng trên nửa đế +Z.

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
# 0. CHẾ ĐỘ BUILD  (đặt bằng dòng lệnh — xem main()/argparse)
# ============================================================================
# DETAIL:
#   "full"   — đầy đủ chi tiết thẩm mỹ (vát góc, chỉ bóng, rãnh cầm tay, khắc mã).
#              Dùng cho viewer trình diễn / render đẹp.
#   "simple" — CHỈ giữ chi tiết chức năng: mọi bề mặt phẳng, không vát, không
#              khắc. STL gọn hơn, ít boolean hơn, in 3D dễ và chắc hơn. Dùng
#              khi muốn xuất file in hoặc chỉnh sửa cơ khí.
DETAIL = "full"
STL_ONLY = False        # True: chỉ xuất STL in 3D (bỏ model.json + viewer.html)
INCLUDE_VISUAL = True   # False: bỏ toàn bộ chi tiết mua sẳn/dây/chùm sáng
ONLY = None             # list tên (con-chuỗi): chỉ build các phần khớp
SCALE = 1.0             # thu nhỏ đều mô hình (--scale; 0.85 -> hộp ~12.7cm).
                        # Các cặp lắp ghép (nắp-thân, khẩu độ-khe, hood-bệ)
                        # vẫn khớp nhau vì cùng tỉ lệ; lỗ vít/linh kiện ngoài
                        # (M3, Ø8 shaft) sẽ nhỏ theo — xem ghi chú --scale.

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
AP_X0, AP_X1 = 113.2, 115.2                # rãnh trượt (rộng 2.0 mm cho tấm 1.6 -> 0.2/cạnh)
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

# --- thanh trượt đẩy-kéo (thay cần trượt nam châm) ----------------------------
# Thanh trụ tròn Ø5 mm gắn cứng vào mặt sau carrier, song song trục D (trục X),
# xuyên vách -X qua bệ dẫn hướng dài -> đẩy/kéo bằng tay từ bên ngoài.
ROD_D = 5.0                                # [SPEC] thanh trụ tròn Ø5 h8 mua sẵn (thép/inox)
ROD_R = ROD_D / 2.0
ROD_BORE_R = ROD_R + 0.20                  # Ø5.4 — khe hướng kính 0.20 mm (trượt nhẹ, kín sáng)
ROD_Y = 24.0                               # tâm thanh: giữa mặt vát D-shaft (16.75) và hốc chân LED (29.2)
ROD_BOSS_L = 18.0                          # bệ dẫn hướng nhô ra ngoài vách -X
ROD_BOSS_X0 = X0 - ROD_BOSS_L              # -18.0
ROD_BOSS_R = ROD_BORE_R + 2.5              # Ø10.4 — vách bệ 2.5 mm quanh lỗ
ROD_BOSS_APEX = ROD_Y - ROD_BOSS_R         # 18.8 — đỉnh nhọn hướng xuống (in không cần support)
ROD_BORE_DEPTH = 15.0                      # lỗ mù trong carrier (carrier dài 22 -> còn 7 mm đặc)
ROD_GRUB_X = -19.0                         # vị trí lỗ vít chặn M3 (toạ độ cục bộ carrier)
ROD_LEN = 130.0                            # chọn L=130 -> phần thanh lộ ra ngoài bệ = d (mm)
ROD_KNOB_D, ROD_KNOB_T = 16.0, 8.0         # núm cầm in 3D ở đuôi thanh

# --- lỗ ra cáp + chụp che sáng (khớp 4 trụ cắm) -------------------------------
EX_Y0, EX_Y1 = 5.5, 13.5                   # lỗ xuyên vách 8 x 20 mm (hạ xuống, nhường bệ thanh trượt)
EX_ZW = 20.0                               # bề rộng lỗ theo Z
HOOD_Y0, HOOD_Y1 = 1.5, 18.0               # bao ngoài bích chụp theo Y (dưới đỉnh bệ 18.8)
HOOD_HZ = 17.75                            # nửa bề rộng bích chụp theo Z
HOOD_PEG_D = 4.0                           # Ø trụ cắm (thay 2 vít M3 cũ)
HOOD_PEG_R = HOOD_PEG_D / 2.0
HOOD_PEG_YS = (5.0, 13.5)                  # 2 hàng trụ theo Y
HOOD_PEG_Z = 14.5                          # ±14.5 quanh tâm làn — NGOÀI rãnh kín (±13)
HOOD_PEG_L = 6.5                           # chiều dài trụ cắm vào thân
HOOD_PEG_CLR = 0.15                        # khe lỗ trụ: Ø4.30 cho trụ Ø4.00 -> ép nhẹ, rút được tay
# Rãnh + gân kín sáng (mộng âm-dương) bao quanh lỗ cáp: 2 lần bẻ 90°
GRV_Y0, GRV_Y1 = 2.5, 16.5                 # bao NGOÀI của vòng rãnh
GRV_HZ = 13.0                              # nửa bề rộng bao ngoài vòng rãnh
GRV_W = 1.5                                # bề rộng lòng rãnh
GRV_D = 1.5                                # chiều sâu rãnh trên bệ (bệ 2.0 + vách 3.0 = 5.0)
PLATEAU_T = 2.0                            # bệ nhô ngoài vách: dày thêm chỗ khoét + tạo mặt tì cho chụp
PLATEAU_Y1 = 19.0                          # đỉnh bệ (khớp đỉnh nhọn bệ thanh trượt 18.8)
PEG_PIL_L = 5.0                            # trụ đứng trong hộp đỡ đáy lỗ trụ cắm
PEG_PIL_HZ = 4.5                           # nửa bề rộng trụ đứng (mép trong cách carrier 1.0 mm)
PEG_PIL_TOP = 19.5                         # đỉnh trụ đứng

# --- đế đỡ màn hình cảm ứng 7 inch (vùng +Z còn trống của đế) -----------------
# [SPEC] Raspberry Pi 7" Touch Display: 194 x 110 x 20 mm (bao gồm bo mạch sau).
# Máng kẹp thiết kế dung sai rộng 15..26 mm nên vẫn nhận panel 7" phổ thông.
SCR_W, SCR_H, SCR_T = 194.0, 110.0, 20.0
SCR_TILT = 15.0                            # độ ngả ra sau (so với phương thẳng đứng)
SCR_FOOT_X = (20.0, 130.0)                 # 2 chân, cách nhau 110 mm, đối xứng qua x = 75
SCR_FOOT_Z0 = -190.0                       # mép trước chân — HÀNG ĐẦU của hệ (xem BASE_Z0)
SCR_FOOT_L = 54.0                          # chiều dài chân theo Z
SCR_FOOT_W = 16.0                          # bề rộng chân theo X
SCR_SLOT_W = 21.0                          # bề rộng máng kẹp (panel [SPEC] 20 mm -> khe 0.5/cạnh)
SCR_SLOT_D = 14.0                          # chiều sâu máng
SCR_SLOT_Y = 8.0                           # đáy máng (cách mặt đế)
SCR_SLOT_Z = 24.0                          # tâm đáy máng theo z cục bộ
SCR_BOLT_Z = (4.0, 51.0)                   # 2 lỗ M3 bắt chân xuống đế (z cục bộ)
SCR_CLAMP_Y = 12.0                         # vít kẹp M3 ngang xuyên thành sau máng

# --- lưới lỗ bắt module mở rộng trên nửa đế +Z ---------------------------------
EXP_HOLE_X = (30.0, 75.0, 120.0)           # 3 cột, bước 45 mm
EXP_HOLE_Z = (62.0, 80.0)                  # sau tai bắt hộp (z <= 51.5), trước gân (z >= 87)

# --- đế chung + khối điện tử ngoài --------------------------------------------
BASE_T = 4.0                               # bề dày tấm đế (mặt trên y = 0)
BASE_X0, BASE_X1 = -24.0, 174.0
# -Z là MẶT TRƯỚC (phía người dùng). Thứ tự trước -> sau:
#   màn hình 7" (z -190..-136)  ->  Pi 4 + board driver (z -112..-52)
#   ->  hộp tối (z -40..+40, tai bắt tới ±51.5)  ->  vùng mở rộng (z 52..92).
BASE_Z0, BASE_Z1 = -196.0, 92.0
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

# Board driver LED 70 x 55 mm (gọn theo ảnh thực tế — hình 1) đặt KỀ Pi 4 theo
# phương X, cùng dải z với Pi -> cả cụm điện tử nằm gọn trong 1 hàng ngang giữa
# màn hình (trước) và hộp tối (sau). KHÔNG xoay: hệ cục bộ board (x 0..70,
# z 0..55) trùng hướng thế giới -> world x in [DRV_WX, DRV_WX+70],
# z in [DRV_WZ, DRV_WZ+55].
#   DRV_WX = -12 -> mép +X board x=58, cách mép -X của Pi (x=62) 4 mm;
#                   mép -X board cách mép đế (x=-24) 12 mm.
#   DRV_WZ = -112 -> mép +Z board z=-57, cách tai bắt hộp (z=-51.5) 5.5 mm;
#                   header ra LED (cạnh +Z) hướng thẳng về hộp tối.
DRV_L, DRV_W, DRV_T = 70.0, 55.0, 1.6
DRV_WX, DRV_WZ = -12.0, -112.0             # góc (-X, -Z) của board trên đế
DRV_STAND = 5.0
DRV_Y0 = DRV_STAND
DRV_Y1 = DRV_Y0 + DRV_T


def drv_world(lx, lz):
    """Toạ độ (x, z) thế giới của điểm cục bộ (lx, lz) trên board driver."""
    return DRV_WX + lx, DRV_WZ + lz

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
BASE_CHAM = 8.0          # vát 2 góc ngoài mỗi nửa đế
LID_CHAM = 1.5                        # vát vành mép trên nắp
LID_PANEL_X0, LID_PANEL_X1 = 8.0, 142.0    # panel giữa thụt trên nắp (thẩm mỹ,
LID_PANEL_Z0, LID_PANEL_Z1 = -34.0, 34.0   # đồng thời giảm cong vênh mặt phẳng lớn)
LID_PANEL_D = 0.8                     # panel giữa thụt xuống

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


def _rod_boss(zc, n=48):
    """Bệ dẫn hướng thanh trượt Ø5: nửa trên là trụ Ø10.4, nửa dưới là 2 mặt 45°
    hội tụ xuống đỉnh nhọn y=ROD_BOSS_APEX.

    Thân hộp in với world +Y -> print +Z, nên bệ này là một TRỤ NẰM NGANG trong
    tư thế in; mặt dưới của trụ tròn sẽ là overhang. Tiết diện "giọt nước ngược"
    (đỉnh nhọn hướng xuống) giữ mọi mặt dưới <= 45° -> in không cần support.
    """
    R = ROD_BOSS_R
    pts = [(ROD_Y + R * math.sin(math.pi * i / n), zc + R * math.cos(math.pi * i / n))
           for i in range(n + 1)]
    pts.append((ROD_BOSS_APEX, zc))
    return prism("x", pts, ROD_BOSS_X0, X_IN0)


def _seal_groove(sgn, zc, extra=0.0, depth=None):
    """Vòng rãnh chữ nhật kín bao quanh lỗ cáp trên mặt bệ nhô (dao cắt).

    `extra` nới cả 4 phía (dùng khi khoét rãnh trên THÂN để chừa khe cho gân
    của chụp).  Trả về 4 thanh dao (trên / dưới / 2 bên) — nối liền thành vòng.
    """
    _, xo, _ = _wall_out_x(sgn)
    d = GRV_D if depth is None else depth
    xa, xb = xo + sgn * 0.5, xo - sgn * d
    oy0, oy1 = GRV_Y0 - extra, GRV_Y1 + extra
    oz0, oz1 = zc - GRV_HZ - extra, zc + GRV_HZ + extra
    iy0, iy1 = oy0 + GRV_W, oy1 - GRV_W
    iz0, iz1 = oz0 + GRV_W, oz1 - GRV_W
    return [box(xa, xb, oy0, iy0, oz0, oz1),
            box(xa, xb, iy1, oy1, oz0, oz1),
            box(xa, xb, iy0, iy1, oz0, iz0),
            box(xa, xb, iy0, iy1, iz1, oz1)]


def _wall_out_x(sgn):
    """(mặt ngoài vách, mặt ngoài bệ nhô, mặt trong vách) cho vách -X (sgn=-1)
    hoặc +X (sgn=+1)."""
    xw = X0 if sgn < 0 else X_TOT
    return xw, xw + sgn * PLATEAU_T, (X_IN0 if sgn < 0 else X_IN1)


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
        # bắt đầu ở x=9 (sau trụ đứng chân chụp x=3..8) để dây không chui hầm
        cuts.append(box(9.0, 104.0, Y_FL - 1.4, Y_FL + 0.05, zw - 3.0, zw + 3.0))
    m = dif(m, cuts)

    # --- bệ dẫn hướng thanh trượt Ø5 xuyên vách -X ----------------------------
    # Bệ dài 18 mm + vách 3 mm = 21 mm lỗ dẫn hướng cho khe hướng kính 0.20 mm
    # -> tỉ lệ L/khe ~= 105:1, bẫy sáng hình khuyên (chưa kể thanh lấp gần kín).
    # Bệ làm chỗ khoét DÀY LÊN (2.5 mm vách quanh lỗ + 3 mm vách gốc) nên vách
    # KHOẺ HƠN chứ không yếu đi.
    boss = [_rod_boss(zc) for zc in LANE_Z.values()]

    # --- bệ nhô ngoài 2 vách + bậc (rabbet) ôm bích chụp + trụ đứng chân chụp -
    plate = []
    for sgn in (-1.0, 1.0):
        xw, xo, xi = _wall_out_x(sgn)
        plate.append(box(xw, xo, Y0, PLATEAU_Y1, Z0 + BODY_CHAM, Z1 - BODY_CHAM))
        for zc in LANE_Z.values():
            for dz in (-HOOD_PEG_Z, HOOD_PEG_Z):
                plate.append(box(xi, xi - sgn * PEG_PIL_L, Y_FL, PEG_PIL_TOP,
                                 zc + dz - PEG_PIL_HZ, zc + dz + PEG_PIL_HZ))
    m = uni([m] + boss + plate)

    # lỗ ra cáp xuyên vách + bậc ôm bích + 4 lỗ mù cho trụ cắm của chụp
    holes = []
    for zc in LANE_Z.values():
        holes.append(_tube("x", ROD_BOSS_X0 - 0.5, X_IN0 + 0.5, ROD_Y, zc,
                           ROD_BORE_R, 48))
        for sgn in (-1.0, 1.0):
            xw, xo, xi = _wall_out_x(sgn)
            holes.append(box(xo - sgn * 0.5, xi + sgn * 0.5,
                             EX_Y0, EX_Y1, zc - EX_ZW / 2, zc + EX_ZW / 2))
            holes += _seal_groove(sgn, zc)
            for dz in (-HOOD_PEG_Z, HOOD_PEG_Z):
                for yp in HOOD_PEG_YS:
                    holes.append(_tube("x", xo + sgn * 0.5,
                                       xo - sgn * (HOOD_PEG_L + 1.0),
                                       yp, zc + dz, HOOD_PEG_R + HOOD_PEG_CLR, 24))

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

    # --- xử lý tạo hình (thẩm mỹ, chỉ DETAIL="full"): vát 4 góc đứng phần thân
    #     dưới, chỉ bóng ngang, vát vành mép trên. Tất cả đều NẰM NGOÀI vùng
    #     rãnh labyrinth (y = Y_TOP-LID_GROOVE_D .. Y_TOP) nên không đụng kín sáng.
    if DETAIL == "full":
        style = chamfer_box_v(X0, X_TOT, Z0, Z1, BODY_CHAM, Y0 - 0.5, BODY_CHAM_Y1)
        style += chamfer_edge_top(X0, X_TOT, Z0, Z1, Y_TOP, 1.0)
        for a, b in ((Z0 - 0.5, Z0 + SHADOW_D), (Z1 - SHADOW_D, Z1 + 0.5)):
            style.append(box(8.0, X_TOT - 8.0, SHADOW_Y0, SHADOW_Y1, a, b))
        for a, b in ((X0 - 0.5, X0 + SHADOW_D), (X_TOT - SHADOW_D, X_TOT + 0.5)):
            style.append(box(a, b, SHADOW_Y0, SHADOW_Y1, Z0 + 8.0, Z1 - 8.0))
    else:
        style = []
    return dif(m, holes + style)


def build_lid():
    """Nắp labyrinth: tấm ĐẶC + gờ cắm vào rãnh (kể cả trên vách ngăn) + vấu chặn.

    Sau khi bỏ cần trượt nam châm, nắp KHÔNG còn ray / chặn / vùng mỏng 2.2 mm:
    tấm dày đều LID_T = 3.0 mm trên toàn bộ mặt (trừ panel thụt 0.8 mm thuần
    thẩm mỹ) -> cứng hơn, kín sáng hơn, không có chi tiết mỏng dễ vênh khi in.
    """
    m = box(X0, X_TOT, Y_TOP, Y_LID, Z0, Z1)
    m = uni([m] + _lid_groove_boxes(shrink=CLR / 2))
    tabs = [box(FRM_X0 - 2.4, FRM_X0 - 0.6, 56.0, Y_TOP, zc - 14.0, zc + 14.0)
            for zc in LANE_Z.values()]
    m = uni([m] + tabs)

    # panel giữa thụt 0.8 mm — thuần thẩm mỹ, nắp còn 2.2 mm ở đây vẫn kín sáng
    m = dif(m, [box(LID_PANEL_X0, LID_PANEL_X1, Y_LID - LID_PANEL_D, Y_LID + 0.6,
                    LID_PANEL_Z0, LID_PANEL_Z1)])

    if DETAIL == "full":
        cuts = chamfer_edge_top(X0, X_TOT, Z0, Z1, Y_LID, LID_CHAM)
        cuts += chamfer_edge_top(LID_PANEL_X0, LID_PANEL_X1, LID_PANEL_Z0, LID_PANEL_Z1,
                                 Y_LID, LID_PANEL_D, out=True)
        return dif(m, cuts)
    return m


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
    """Khối trượt mang LED: lỗ D ôm trục, TRƯỢT TỰ DO (bỏ kẹp xẻ + vít M3),
    loa che sáng 45°.

    Dẫn động TRỰC TIẾP bằng THANH TRỤ Ø5 cắm vào lỗ mù sâu 15 mm ở mặt lưng
    (carrier dài 22 -> còn 7 mm vật liệu đặc phía trước lỗ: KHÔNG có đường
    sáng thẳng xuyên qua carrier), khoá bằng 1 vít chặn M3 xuyên ngang.

    Chọn ROD_Y = 24.0: nằm giữa mặt vát D-shaft (16.75) và đáy hốc chân LED
    (29.2). Cánh tay đòn tới tim trục trượt chỉ 24 - 14 = 10 mm; tiêu chuẩn tự
    hãm của bạc trượt dài L = CAR_L = 22 mm với hệ số ma sát PLA/thép mu ~ 0.3
    là L/(2*mu) ~ 36.7 mm >> 10 mm -> đẩy/kéo KHÔNG bị kẹt nghiêng.

    2 hốc dây bên hông (đối xứng) cho chân LED thoát NGANG, không vắt qua thanh.
    Hệ cục bộ: mặt trước carrier x=0; trục trượt y=SH_Y,z=0; trục quang y=Y_AX,z=0."""
    m = box(-CAR_L, 0.0, CAR_Y0, CAR_Y1, -CAR_ZW / 2, CAR_ZW / 2)
    m = uni([m, frustum_x(0.0, COLLAR_L, Y_AX, 0.0, 5.2, 2.1, 40)])
    dbore = dif(cyl_x(-CAR_L - 0.5, 0.5, SH_Y, 0.0, SH_R + CLR, 40),
                [box(-CAR_L - 1, 1, SH_FLAT_Y + CLR, SH_Y + SH_R + 2,
                     -SH_R - 2, SH_R + 2)])
    cuts = [dbore,
            cyl_x(-9.0, COLLAR_L + 0.2, Y_AX, 0.0, 1.65, 32),        # thân LED Ø3.0 +0.3
            cyl_x(-10.4, -9.0, Y_AX, 0.0, 2.05, 32),                 # hốc vành LED Ø3.8
            cyl_x(-CAR_L - 0.5, -10.4, Y_AX, 0.0, 2.6, 32),          # khoang chân/dây
            # lỗ mù Ø5.1 nhận thanh trượt (ép nhẹ) + vít chặn M3 xuyên ngang
            cyl_x(-CAR_L - 0.5, -CAR_L + ROD_BORE_DEPTH, ROD_Y, 0.0, ROD_R + 0.05, 40),
            cyl_z(-CAR_ZW / 2 - 0.5, CAR_ZW / 2 + 0.5, ROD_GRUB_X, ROD_Y, 1.3, 24),
            # 2 hốc dây bên hông: chân LED thoát ngang khỏi khoang sau
            box(-CAR_L + 2.0, -CAR_L + 6.0, Y_AX - 2.0, Y_AX + 2.6,
                -CAR_ZW / 2 - 0.5, CAR_ZW / 2 + 0.5),
            box(-CAR_L - 0.5, -CAR_L + 5.0, CAR_Y0 + 1.0, CAR_Y0 + 5.0, -3.0, 3.0)]
    m = dif(m, cuts)
    if DETAIL == "full":
        m = dif(m, chamfer_box_v(-CAR_L, 0.0, -CAR_ZW / 2, CAR_ZW / 2, 1.2,
                                 CAR_Y0 - 0.5, CAR_Y1 + 0.5))
    return m


def build_rod_knob():
    """Núm cầm ở đuôi thanh trượt: đĩa Ø16 x 8 mm, lỗ mù Ø5.1 sâu 6 mm + vít
    chặn M3 xuyên ngang.

    Hệ cục bộ: trục thanh nằm trên trục X, y = z = 0; MIỆNG lỗ (hướng về hộp)
    tại x = 0, núm kéo dài về -X. 6 rãnh lõm quanh vành để cầm không trượt tay.
    """
    R = ROD_KNOB_D / 2.0
    m = cyl_x(-ROD_KNOB_T, 0.0, 0.0, 0.0, R, 48)
    cuts = [cyl_x(-6.0, 0.5, 0.0, 0.0, ROD_R + 0.05, 40),
            cyl_y(-R - 0.5, R + 0.5, -ROD_KNOB_T / 2.0, 0.0, 1.3, 24)]
    for i in range(6):
        t = 2 * math.pi * i / 6.0
        cuts.append(cyl_x(-ROD_KNOB_T - 0.5, 0.5,
                          (R + 1.2) * math.cos(t), (R + 1.2) * math.sin(t), 2.4, 24))
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
    if DETAIL != "full" or not marks:
        return m
    return dif(m, marks)


def build_hood(sgn):
    """Chụp che sáng lối ra cáp — lắp bằng 4 TRỤ CẮM Ø4 (bỏ hoàn toàn vít M3).

    Khớp nối: 4 trụ tròn Ø4.00 x 6.5 mm trên bích chụp -> 4 lỗ mù Ø4.30 trên
    thân (khe 0.15 mm/bán kính: ép nhẹ bằng tay, giữ chắc, rút ra được, không
    cần dụng cụ).  Lỗ trên thân là LỖ MÙ nên tháo chụp ra hộp vẫn kín sáng.

    Tăng độ kín: vòng GÂN chữ nhật quanh cửa sổ cáp ăn vào vòng RÃNH tương ứng
    trên bệ nhô của thân (mộng âm-dương) -> thêm 2 lần bẻ 90° cho tia xiên,
    ngoài 2 lần bẻ 90° sẵn có của ống + khe sàn ở đầu xa.

    Hệ cục bộ: u = khoảng cách ĐI RA khỏi mặt ngoài danh nghĩa của vách
    (x = sgn*u sau khi tịnh tiến); mặt bệ nhô của thân ở u = PLATEAU_T.
    sgn=+1 lắp ở thành +X (cáp OPT101); sgn=-1 ở thành -X (cáp LED).
    """
    BRIM_T, TUBE_T, TUBE_D = 3.0, 2.5, 13.0     # bích / tường ống / sâu ống
    U_F0 = PLATEAU_T                            # 2.0  mặt tì của bích lên bệ nhô
    U_F1 = U_F0 + BRIM_T                        # 5.0  mặt ngoài bích
    U_T1 = U_F1 + TUBE_D                        # 18.0 đầu xa ống (bằng bệ thanh trượt)
    VW = EX_ZW / 2 + 0.75                       # 10.75 nửa rộng cửa sổ trong chụp
    VY0, VY1 = EX_Y0 - 1.0, EX_Y1 + 1.0         # 4.5 .. 14.5

    def bx(u0, u1, y0, y1, z0, z1):
        return box(sgn * u0, sgn * u1, y0, y1, z0, z1)

    # --- bích + ống ----------------------------------------------------------
    m = uni([bx(U_F0, U_F1, HOOD_Y0, HOOD_Y1, -HOOD_HZ, HOOD_HZ),
             bx(U_F1, U_T1, HOOD_Y0, VY1 + TUBE_T, -VW - TUBE_T, VW + TUBE_T)])

    # --- vòng gân kín sáng (ăn vào rãnh trên bệ nhô của thân) ----------------
    # Gân dày GRV_W - 2*C = 1.2 mm, thụt vào 0.15 mm ở CẢ HAI mép của lòng
    # rãnh (mép ngoài lùi vào, mép trong lùi ra) -> lắp không kênh, không cấn.
    u_r = U_F0 - (GRV_D - 0.2)                  # 0.7 — chừa 0.2 mm đáy rãnh
    C = HOOD_PEG_CLR                            # 0.15 khe mỗi mặt
    oy0, oy1 = GRV_Y0 + C, GRV_Y1 - C
    oz0, oz1 = -GRV_HZ + C, GRV_HZ - C
    iy0, iy1 = GRV_Y0 + GRV_W - C, GRV_Y1 - GRV_W + C
    iz0, iz1 = -GRV_HZ + GRV_W - C, GRV_HZ - GRV_W + C
    ribs = [bx(U_F0, u_r, oy0, iy0, oz0, oz1),
            bx(U_F0, u_r, iy1, oy1, oz0, oz1),
            bx(U_F0, u_r, iy0, iy1, oz0, iz0),
            bx(U_F0, u_r, iy0, iy1, iz1, oz1)]

    # --- 4 trụ cắm Ø4 (mũi thu nhỏ 0.8 mm làm mồi dẫn hướng) ----------------
    pegs = []
    u_tip, u_sh = U_F0 - HOOD_PEG_L, U_F0 - HOOD_PEG_L + 0.8
    for dz in (-HOOD_PEG_Z, HOOD_PEG_Z):
        for yp in HOOD_PEG_YS:
            pegs.append(_tube("x", sgn * U_F0, sgn * u_sh, yp, dz, HOOD_PEG_R, 28))
            xa, xb = sgn * u_sh, sgn * u_tip
            pegs.append(frustum_x(xa, xb, yp, dz, HOOD_PEG_R, HOOD_PEG_R - 0.6)
                        if xa < xb else
                        frustum_x(xb, xa, yp, dz, HOOD_PEG_R - 0.6, HOOD_PEG_R))
    m = uni([m] + ribs + pegs)

    cuts = [
        # ruột ống + cửa sổ xuyên bích (⊇ lỗ cáp vách y 5.5..13.5, z ±10)
        bx(U_F0 - 0.5, U_T1 - TUBE_T, VY0, VY1, -VW, VW),
        # khe sàn ở ĐẦU XA ống — cáp thoát xuống đế, tia sáng phải gập 2 lần 90°
        bx(U_T1 - 5.0, U_T1 + 0.5, HOOD_Y0 - 0.5, VY0 + 0.5, -6.5, 6.5),
    ]
    m = dif(m, cuts)
    if DETAIL == "full":
        xa, xb = sorted((sgn * (U_F0 + 0.6), sgn * U_T1))
        m = dif(m, chamfer_edge_top(xa, xb, -HOOD_HZ, HOOD_HZ, HOOD_Y1, 1.0))
    return m


def build_screen_foot():
    """Chân đỡ màn hình cảm ứng 7 inch — in 2 bản, bắt xuống đế bằng 2 vít M3.

    Máng kẹp ngả SCR_TILT = 15° so với phương thẳng đứng, rộng 21.0 mm (panel
    [SPEC] 194 x 110 x 20 mm -> khe 0.5 mm mỗi bên), sâu 14 mm. 1 vít kẹp M3
    xuyên thành SAU máng (dày >= 10 mm, đủ ren trong nhựa) giữ chắc cả panel
    mỏng hơn (~15..21 mm) — không cần biết trước toạ độ lỗ bắt của panel.

    Biên dạng 2D trong mặt (y, z) đùn theo X: mặt trên vuông góc panel (ngả 15°
    so với phương ngang), mọi mặt hướng xuống <= 39° so với phương thẳng đứng
    -> in ĐỨNG nguyên tư thế lắp, KHÔNG cần support.
    Hệ cục bộ: x = 0 giữa chân, y = 0 mặt trên đế, z = 0 mép trước.
    """
    t = math.radians(SCR_TILT)
    ua, ub = math.cos(t), math.sin(t)          # dọc panel, hướng lên
    na, nb = -math.sin(t), math.cos(t)         # pháp tuyến panel (hướng +z)
    hw = SCR_SLOT_W / 2.0

    def pt(a, b):
        """Điểm (y, z) = tâm đáy máng + a·(dọc panel) + b·(pháp tuyến panel)."""
        return (SCR_SLOT_Y + a * ua + b * na, SCR_SLOT_Z + a * ub + b * nb)

    ty, tz = pt(SCR_SLOT_D, 0.0)               # tâm miệng máng
    zb = SCR_FOOT_L - 6.0                      # vách sau (mặt ngoài) tại z = 48
    yb = ty + (zb - tz) * na / nb              # mặt trên gặp vách sau
    qf = pt(SCR_SLOT_D, -(hw + 4.0))           # góc TRƯỚC của mặt trên
    prof = [(0.0, 0.0), (0.0, SCR_FOOT_L), (5.0, SCR_FOOT_L), (5.0, zb),
            (yb, zb), qf, (5.0, 8.0), (5.0, 0.0)]
    m = prism("x", prof, -SCR_FOOT_W / 2.0, SCR_FOOT_W / 2.0)

    # máng kẹp: hình bình hành kéo dài 20 mm quá mặt trên để mở miệng
    dd = SCR_SLOT_D + 20.0
    slot = prism("x", [pt(0.0, -hw), pt(0.0, hw), pt(dd, hw), pt(dd, -hw)],
                 -SCR_FOOT_W / 2.0 - 0.5, SCR_FOOT_W / 2.0 + 0.5)
    cuts = [slot,
            cyl_z(SCR_FOOT_L + 0.5, 34.0, 0.0, SCR_CLAMP_Y, 1.25, 24)]  # vít kẹp M3
    for zc in SCR_BOLT_Z:                                                # 2 lỗ M3 xuống đế
        cuts.append(cyl_y(-0.5, 6.0, 0.0, zc, 1.75, 24))
    m = dif(m, cuts)
    if DETAIL == "full":
        m = dif(m, chamfer_box_v(-SCR_FOOT_W / 2.0, SCR_FOOT_W / 2.0,
                                 0.0, SCR_FOOT_L, 1.2, -0.5, 5.5))
    return m


def build_base(half):
    """Đế chung, chia đôi tại z=0 cho vừa bàn in.
    half='neg': z<0 — NỬA TRƯỚC: 2 chân đỡ màn hình 7" (z -190..-136), rồi
                board driver + Pi 4 + Grove HAT (z -112..-52).
    half='pos': z>0 — nửa sau: đế dưới hộp tối + chụp +X + lưới lỗ mở rộng."""
    neg = (half == "neg")
    z0, z1 = (BASE_Z0, 0.0) if neg else (0.0, BASE_Z1)
    m = box(BASE_X0, BASE_X1, -BASE_T, 0.0, z0, z1)
    zr = (z0, z0 + 5.0) if neg else (z1 - 5.0, z1)
    # Gân chu vi dưới đế (chỉ DETAIL="full"): bỏ ở simple để đế là tấm phẳng
    # 4 mm — in không phải bridge qua khoảng trống giữa các gân.
    add = []
    if DETAIL == "full":
        add = [box(BASE_X0, BASE_X0 + 5.0, -BASE_T - RIB_H, -BASE_T, z0, z1),
               box(BASE_X1 - 5.0, BASE_X1, -BASE_T - RIB_H, -BASE_T, z0, z1),
               box(BASE_X0, BASE_X1, -BASE_T - RIB_H, -BASE_T, zr[0], zr[1])]
    holes = []
    if neg:                                    # 2 chân màn hình + trụ Pi 4B + driver
        for xc in SCR_FOOT_X:                  # bệ vít M3 bắt 2 chân đỡ màn hình 7"
            for dz in SCR_BOLT_Z:
                pz = SCR_FOOT_Z0 + dz
                add.append(cyl_y(-BASE_T - RIB_H, -BASE_T, xc, pz, 4.6, 24))
                holes.append(cyl_y(-BASE_T - RIB_H - 0.5, 0.5, xc, pz, 1.4, 16))
        for dx in (0.0, PI_HOLE_PX):
            for dz in (0.0, PI_HOLE_PZ):
                px, pz = PI_X0 + PI_HOLE_INSET + dx, PI_Z0 + PI_HOLE_INSET + dz
                add.append(cyl_y(0.0, PI_STAND, px, pz, 3.6, 24))
                holes.append(cyl_y(-BASE_T - 0.5, PI_STAND + 0.5, px, pz, 1.15, 16))
        for lx in (4.0, DRV_L - 4.0):          # board driver 70 x 55 mm (không xoay)
            for lz in (4.0, DRV_W - 4.0):
                px, pz = drv_world(lx, lz)
                add.append(cyl_y(0.0, DRV_STAND, px, pz, 3.6, 24))
                holes.append(cyl_y(-BASE_T - 0.5, DRV_STAND + 0.5, px, pz, 1.4, 16))
    else:
        # Lưới lỗ M3 dự phòng (mở rộng): dải đế TRỐNG phía SAU hộp tối,
        # x = 30/75/120 (bước 45), z = 62/80 (bước 18) — đủ chỗ bắt thêm module
        # (MCP4725 dự phòng, cảm biến môi trường, quạt, bộ nguồn...) mà không
        # đụng tai bắt hộp (z <= 51.5) hay gân chu vi (z >= 87).
        # Lỗ suốt Ø3.4 -> vít M3 + đai ốc.
        for xc in EXP_HOLE_X:
            for pz in EXP_HOLE_Z:
                holes.append(cyl_y(-BASE_T - RIB_H - 0.5, 0.5, xc, pz, 1.7, 20))
    for xc in (21.0, 129.0):                   # bệ bắt tai hộp
        zs, sg = (Z0, -1.0) if neg else (Z1, 1.0)
        add.append(cyl_y(-BASE_T - RIB_H, -BASE_T, xc, zs + sg * 5.5, 4.6, 24))
        holes.append(cyl_y(-BASE_T - RIB_H - 0.5, 0.5, xc, zs + sg * 5.5, 1.4, 16))
    for xc in (10.0, 43.0, 77.0, 111.0, 144.0):
        # 5 mộng vuông nối 2 nửa (vít dọc Y không thể bắt chéo đường nối z=0 —
        # đã bỏ 2 lỗ vít vô dụng); 4 vít M3 bắt hộp xuống đế kẹp chốt cụm
        if neg:
            add.append(box(xc - 11.0, xc + 11.0, -BASE_T + 0.8, -0.8, 0.0, 9.0))
        else:
            holes.append(box(xc - 11.3, xc + 11.3, -BASE_T + 0.5, -0.5, -0.2, 9.3))
    m = uni([m] + add)

    # --- xử lý tạo hình (chỉ DETAIL="full"): vát 2 góc ngoài + vành mép trên
    #     (mép z=0 để vuông vì đó là mặt ghép 2 nửa).
    if DETAIL != "full":
        return dif(m, holes)
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
        v.add(box(X_BR, X_BR + 1.8, Y_AX + 14.0, Y_AX + 19.0,          # cầu đấu 3 chân — MẶT SAU board
                  zc - 7.6, zc + 7.6), 0x1b6ea8)
        for i in range(3):
            v.add(cyl_x(X_BR + 1.8, X_BR + 5.2, Y_AX + 16.5,
                        zc - 5.08 + i * 5.08, 1.2, 10), C_SILVER)
        v.add(box(X_BR, X_BR + 3.5, Y_AX - 20.0, Y_AX - 16.0,           # tụ 100 nF cạnh VS — mặt sau
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
    2× NPN TO-92 + 2× điện trở cảm biến (E→GND, thay được) phía dưới,
    header cái ra LED ở cạnh +Z (hướng về hộp tối). Hệ cục bộ; collect_parts() đặt.
    Mạch tối giản thật: LM358 -> NPN -> R(E→GND) -> GND, LED trên collector."""
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
    # 2× NPN TO-92 — khóa dòng LED, phía dưới LM358
    _to92(v, 30.0, yb, 38.0)                           # Q1 — kênh IR
    _to92(v, 40.0, yb, 38.0)                           # Q2 — kênh Đỏ
    # header cái ra LED — cạnh +Z board (world x 12..29, z ≈ -59): quay thẳng
    # về phía hộp tối, dây ra không phải vắt qua mặt board (tránh đâm linh kiện)
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


def push_rod_vis(v, ch):
    """Thanh trượt Ø5 mua sẵn (thép/inox h8) — chỉ để nhìn, không xuất STL.
    Đầu trước cắm sâu 15 mm vào lỗ mù mặt lưng carrier, đuôi mang núm cầm."""
    x1 = x_front(ch) - CAR_L + ROD_BORE_DEPTH        # đáy lỗ mù trong carrier
    v.add(cyl_x(x1 - ROD_LEN, x1, ROD_Y, LANE_Z[ch], ROD_R, 32), 0x9aa3ad)
    return v


def screen_vis(v):
    """Màn hình cảm ứng 7 inch [SPEC] 194 x 110 x 20 mm, ngả 15° — chỉ để nhìn.
    Cạnh dưới panel nằm ở đáy máng kẹp của 2 chân đỡ."""
    T = (translation_matrix([75.0, SCR_SLOT_Y, SCR_FOOT_Z0 + SCR_SLOT_Z])
         @ rotation_matrix(math.radians(SCR_TILT), [1, 0, 0]))
    hw, ht = SCR_W / 2.0, SCR_T / 2.0
    for mesh, col in ((box(-hw, hw, 0.0, SCR_H, -ht, ht), 0x2b3038),
                      (box(-hw + 7.0, hw - 7.0, 9.0, SCR_H - 9.0,
                           -ht - 0.6, -ht + 0.3), 0xf4f6f7)):
        mm = mesh.copy()
        mm.apply_transform(T)
        v.add(mm, col)
    return v


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
    # ---------- TX: driver (kề Pi, cùng dải z) -> LED ----------
    # Header cái ra LED ở cạnh +Z board (world x 12..29, z = -59), quay về phía
    # hộp tối. Bẹ 2 sợi đỏ/đen rời board ngay tại cạnh +Z, xuống đế, chạy dọc
    # NGOÀI đầu ống chụp (x = -21, đầu xa ống ở x = -18) rồi CHUI LÊN qua KHE
    # SÀN của chụp (x -18.5..-13, y 1..5, z = tâm làn ±6.5) -> lòng ống ->
    # cửa sổ cáp trên vách -> máng sàn trong hộp -> carrier LED.
    #   làn Đỏ  (z = -19.25): chạy ở y = 1.8
    #   làn IR  (z = +19.25): chạy ở y = 4.4 khi đi song song -> không đè lên
    #                         bó Đỏ ở đoạn z = -41..-21.
    tx = {
        "ir": [(15.5, 13.5, -59), (14.0, 10.0, -56.5), (10.0, 6.0, -53.5),
               (2.0, 3.0, -50.0), (-8.0, 4.4, -47.0), (-16.0, 4.4, -44.0),
               (-21.0, 4.4, -40.0), (-21.0, 4.4, -12.0), (-21.0, 2.4, 4.0),
               (-19.5, 2.0, 13.0), (-16.5, 3.0, 19.25), (-14.0, 5.0, 19.25),
               (-10.0, 8.0, 19.25), (-4.0, 9.0, 19.25), (-1.0, 8.0, 19.25),
               (2.0, 7.0, 19.25),
               (3.8, 6.0, 19.25), (6, 6.5, 21), (10, 4.0, 24), (12, 2.6, 29),
               (16, 2.6, 32), (15, 5.5, 24), (13, 7, 20.5)],
        "red": [(23.5, 13.5, -59), (22.0, 10.0, -56.5), (18.0, 6.0, -53.5),
                (10.0, 2.4, -50.0), (-2.0, 1.8, -47.0), (-14.0, 1.8, -44.0),
                (-21.0, 1.8, -40.0), (-21.0, 1.8, -27.0), (-19.5, 2.0, -21.0),
                (-16.5, 3.0, -19.25), (-14.0, 5.0, -19.25), (-10.0, 8.0, -19.25),
                (-4.0, 9.0, -19.25), (-1.0, 8.0, -19.25), (2.0, 7.0, -19.25),
                (3.8, 6.0, -19.25), (6, 6.5, -21), (10, 4.0, -24),
                (12, 2.6, -29), (16, 2.6, -32), (64, 2.6, -32), (70, 5.5, -24),
                (72, 7, -20.5)],
    }
    for pts in tx.values():
        for m, c in harness(pts, [(-0.55, C_WIRE_R), (0.55, C_WIRE_K)],
                            r=0.55, n=8, tie_step=14.0, tie_skip_y=(0.0, 5.6)):
            v.add(m, c)

    # ---------- RX: OPT101 -> khe trên khung -> chụp +X -> cáp Grove -> HAT ----------
    for ch, sock in (("ir", "A0"), ("red", "A2")):
        zc = LANE_Z[ch]
        # 3 sợi (đỏ/đen/vàng) từ header 6 chân, VƯỢT QUA MIỆNG board (y>57, khe
        # dây lên máng z làn±6.5), vào CẦU ĐẤU MẶT SAU board (x X_BR..X_BR+5.2),
        # rồi vòng ra kênh sau khung (x 141.5..147) đi xuống, ra chụp +X.
        rx = [(132.0, 23, zc), (132.5, 44, zc), (133.2, 52, zc), (135, 56, zc),
              (138, 58.5, zc), (141.5, 57.5, zc), (143.6, 54, zc), (143.8, 49, zc),
              (142.6, 48.6, zc), (143.8, 44, zc), (143.8, 20, zc),
              (143.8, 13, zc), (147, 10.5, zc), (151, 10.5, zc),
              (156, 12, zc), (162, 16, zc), (168, 19, zc), (167, 8, zc),
              (167, 3.2, zc), (166, 2.5, zc)]
        for m, c in harness(rx, [(-5.08, C_WIRE_R), (0.0, C_WIRE_K), (5.08, C_WIRE_Y)],
                            r=0.35, n=6, tie_step=16.0, tie_skip_y=(55.0, 63.0)):
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

    # ---------- I2C: HAT -> 2 module MCP4725 trên board driver (kề Pi) ----------
    # Header 5 chân của 2 module hướng LÊN tại z = -106.5 (module #1 0x60/IR ở
    # x -8.4..4.3, module #2 0x61/Đỏ ở x 39.8..52.5), đỉnh chân y = 18.1.
    #   i2c_b (0x61, Đỏ):  vòng qua mép +X board (x 58) rồi cắm xuống module #2.
    #   i2c_a (0x60, IR):  đi vòng phía TRƯỚC board (z = -114, không có gì cản)
    #                      sang mép -X rồi cắm xuống module #1 — không vắt qua
    #                      mặt board (2 module + 2 header + LM358 đều cao <= 18.1).
    i2c_a = [(74, 19.9, -80), (74, 27, -80), (66, 27, -85), (60, 24, -95),
             (58, 18, -104), (58, 10, -113), (30, 8, -114.5), (2, 8, -114.5),
             (-2, 13, -112), (-2, 21, -109.5), (-2, 19.5, -106.5)]
    i2c_b = [(89, 19.9, -80), (89, 27, -80), (80, 27, -84), (68, 25, -92),
             (60, 23, -100), (54, 21, -105), (46, 19.5, -106.5)]
    for pts, w in ((i2c_a, [(0.0, C_WHITE)]), (i2c_b, [(0.0, C_WHITE)])):
        for m, c in harness(pts, w, r=0.75, n=8, tie_step=18.0):
            v.add(m, c)

    # ---------- PWR: USB-C -> Pi (tiếp cận từ -Z, đúng hướng cổng) ----------
    # Thoát ra mép +X đế: khe z = -108..-136 giữa Pi và 2 chân màn hình, KHÔNG
    # chui xuống gầm panel (panel phủ z -175.7..-127.9 nhưng ở y >= 5.4).
    for m, c in harness([(130, 7, -124), (112, 7, -124), (96, 7, -122),
                         (84, 7, -118), (76, 7.5, -113),
                         (73, 8.2, -109.5)], [(0.0, C_WIRE_K)], r=1.2, n=8,
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
    add("lid", build_lid(), C_LID, [0, 42, 0],
        label="Nắp labyrinth (tấm đặc 3 mm, không còn ray)")
    for ch, cc, vn in (("red", C_CAR_R, "Đỏ"), ("ir", C_CAR_I, "IR")):
        add(f"slide_shaft_{ch}", _place_shaft(ch), C_SHAFT, [-60, 0, 0],
            printable=(ch == "red"),
            label="Trục trượt D Ø8 — in 2 bản (dùng file bản đỏ)")
        add(f"led_carrier_{ch}", _place_carrier(ch), cc, [-46, 0, 0],
            printable=(ch == "red"),
            label=f"Carrier LED {vn} (chỉnh từ ngoài bằng thanh trượt Ø5)")
        add(f"led_{ch}", None, C_LEDR if ch == "red" else C_LEDI, [-46, 0, 0],
            label=("LED Đỏ 622nm [ASSUME]" if ch == "red" else "LED IR 875nm"),
            printable=False, subs=_vis_subs(led_vis, ch, x_front(ch)))
    for ch, vn in (("red", "Đỏ"), ("ir", "IR")):
        m = build_rod_knob()
        # miệng lỗ núm nằm cách đuôi thanh 6 mm (= chiều sâu lỗ mù)
        x_tail = x_front(ch) - CAR_L + ROD_BORE_DEPTH - ROD_LEN
        m.apply_transform(translation_matrix([x_tail + 6.0, ROD_Y, LANE_Z[ch]]))
        add(f"rod_knob_{ch}", m, 0x5a6a7c, [-30, 0, 0],
            printable=(ch == "red"),
            label=f"Núm cầm thanh trượt — làn {vn} (in 2 bản, dùng file bản đỏ)")
    add("frame", build_frame(), C_FRAME, [26, 0, 0], label="Khung giữ board 5×7")
    for kind, kl in (("blank", "bịt kín"), ("d2", "Ø2 mm"), ("d5", "Ø5 mm"), ("d16", "Ø16 mm")):
        for ch in ("red", "ir"):
            m = build_aperture(kind)
            m.apply_transform(translation_matrix(
                [AP_X0 + ((AP_X1 - AP_X0) - AP_T) / 2.0, 0.0, LANE_Z[ch]]))
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
    for i, xc in enumerate(SCR_FOOT_X):
        m = build_screen_foot()
        m.apply_transform(translation_matrix([xc, 0.0, SCR_FOOT_Z0]))
        add(f"screen_foot_{i + 1}", m, C_PRINT2, [0, -20, -30],
            printable=(i == 0),
            label=("Chân đỡ màn hình 7 inch — in 2 bản (dùng file bản 1)"
                   if i == 0 else "Chân đỡ màn hình 7 inch — bản thứ 2"))
    add("base_neg", build_base("neg"), C_BASE, [0, -26, -10],
        label="Đế nửa TRƯỚC — chân màn hình + Pi 4 + Grove HAT + driver")
    add("base_pos", build_base("pos"), C_BASE, [0, -26, 10],
        label="Đế nửa SAU — dưới hộp tối + lưới lỗ mở rộng")

    # ---- mua sẳn / chỉ để nhìn (không xuất STL) ----
    # Mọi phần dưới đây đều là hình minh hoạ (printable=False) — bỏ hẳn khi
    # INCLUDE_VISUAL=False để build nhanh và model.json gọn (chỉ hình in).
    if not INCLUDE_VISUAL:
        return parts
    for ch, lbl in (("ir", "OPT101 #1 — IR → A0"), ("red", "OPT101 #2 — Đỏ → A2")):
        add(f"opt101_{ch}", None, C_PCB_PU, [40, 0, 0], label=lbl,
            printable=False, subs=_vis_subs(opt101_vis, ch))
    add("sensor_board", None, C_PCB_G, [40, 0, 0],
        label="Board cảm biến 5×7 cm", printable=False, subs=_vis_subs(sensor_board_vis))
    add("pi4", None, C_PCB_PI, [0, -16, -34], label="Raspberry Pi 4 Model B",
        printable=False, subs=_vis_subs(pi4_vis))
    add("grove_hat", None, C_PCB_G, [0, -32, -34], label="Grove Base HAT (ADC 0x08)",
        printable=False, subs=_vis_subs(grove_hat_vis))

    # board driver: hệ cục bộ trùng hướng thế giới, chỉ tịnh tiến (xem drv_world).
    drv_T = translation_matrix([DRV_WX, 0.0, DRV_WZ])

    def place(subs, T):
        out = []
        for s in subs:
            m = s["mesh"].copy()
            m.apply_transform(T)
            d = dict(s)
            d["mesh"] = m
            out.append(d)
        return out

    add("driver_board", None, C_PCB_G, [0, -16, -34],
        label="Board driver LED (LM358 + 2×NPN + 2×MCP4725)", printable=False,
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

    for ch, vn in (("red", "Đỏ"), ("ir", "IR")):
        add(f"push_rod_{ch}", None, 0x9aa3ad, [-30, 0, 0], printable=False,
            label=f"Thanh trượt Ø5 × 130 mm (mua sẵn) — làn {vn}",
            subs=_vis_subs(push_rod_vis, ch))
    add("screen7", None, 0x2b3038, [0, 0, -30], printable=False,
        label='Màn hình cảm ứng 7" [SPEC] 194×110×20 mm',
        subs=_vis_subs(screen_vis))
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
    _drv_label(30.0, 38.0, 8.5, "Q1 NPN (IR)"),
    _drv_label(40.0, 38.0, 8.5, "Q2 NPN (Đỏ)"),
    _drv_label(28.0, 47.0, 7.5, "R_sense IR (E→GND)"),
    _drv_label(37.0, 47.0, 7.5, "R_sense Đỏ (E→GND)"),
    dict(pos=[122.4, 49.0, 19.25], text="OPT101 #1 (IR → A0)"),
    dict(pos=[122.4, 49.0, -19.25], text="OPT101 #2 (Đỏ → A2)"),
    dict(pos=[104.0, 18.0, -79.0], text="Grove Base HAT (ADC 0x08)"),
]


def export(parts, write_model=True):
    os.makedirs(STL_DIR, exist_ok=True)
    model, written = dict(units="mm", parts=[]), set()
    for p in parts:
        if SCALE != 1.0:
            if p.get("explode"):
                p["explode"] = [v * SCALE for v in p["explode"]]
            for s in (p.get("subs") or [{"mesh": p["mesh"]}]):
                if s.get("mesh") is not None:
                    s["mesh"].apply_scale(SCALE)
    for p in parts:
        subs = p.get("subs") or [dict(mesh=p["mesh"], color=p["color"])]
        if p.get("printable", True):
            stl = (p["mesh"] or subs[0]["mesh"]).copy()
            if p.get("flip"):
                stl.apply_transform(rotation_matrix(math.pi, [1, 0, 0], point=[0, 0, 0]))
            stl.export(os.path.join(STL_DIR, p["name"] + ".stl"))
            written.add(p["name"] + ".stl")
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
            # bản _ir của chi tiết in dùng chung STL bản _red (dedup) -> ghi rõ
            twin = p["name"].replace("_ir", "_red") if "_ir" in p["name"] else None
            named = {q["name"]: q for q in parts}
            dedup = (twin is not None and twin in named
                     and named[twin].get("printable", True))
            note = (" — không xuất STL (dùng chung file bản _red, in 2 bản)"
                    if dedup else "  — not exported to STL")
            print(f"  {p['name']:<22} (visual, {len(subs)} sub-materials){note}")
    if not ONLY:            # dọn STL mồ côi của lần build trước (đổi tên chi tiết)
        for fn in sorted(os.listdir(STL_DIR)):
            if fn.endswith(".stl") and fn not in written:
                os.remove(os.path.join(STL_DIR, fn))
                print(f"  (xoá STL cũ không còn trong thiết kế: {fn})")
    if write_model:
        with open(os.path.join(OUT, "model.json"), "w") as fh:
            json.dump(model, fh)
        print(f"  model.json: {os.path.getsize(os.path.join(OUT, 'model.json'))/1e6:.1f} MB")


# ============================================================================
# 7. VIEWER (three.js offline, nhúng sẵn vendor/*.js)
# ============================================================================



def build_viewer():
    with open(os.path.join(HERE, "viewer_template.html")) as f:
        template = f.read()
    with open(os.path.join(HERE, "vendor", "three.min.js")) as f:
        three = f.read()
    with open(os.path.join(HERE, "vendor", "OrbitControls.js")) as f:
        orbit = f.read()
    with open(os.path.join(OUT, "model.json")) as f:
        model = f.read()
    dim = (f"{BASE_X1 - BASE_X0:.0f} × {Y_LID + BASE_T + RIB_H:.0f} × "
           f"{BASE_Z1 - BASE_Z0:.0f}")
    html = (template
            .replace("__THREE__", three)
            .replace("__ORBIT__", orbit)
            .replace("__MODEL__", model)
            .replace("__DRVLABELS__", json.dumps(DRVLABELS))
            .replace("__DIM__", dim))
    path = os.path.join(HERE, "viewer.html")
    with open(path, "w") as f:
        f.write(html)
    print(f"  viewer.html: {os.path.getsize(path)/1e6:.1f} MB")


# ============================================================================
# 7b. GÓI IN BAMBU A1 (--bambu)
# ============================================================================
# Chỉ xuất CÁC CHI TIẾT HỘP TỐI cho máy in 3D (Bambu Lab A1, bàn 256x256):
#   thân hộp (có sẵn lỗ luồn dây qua vách + khe khẩu độ + máng dây LED)
#   + nắp labyrinth  + trục D + carrier + NÚM CẦM THANH TRƯỢT
#   + 4 tấm khẩu độ  + 2 chụp luồn dây chống sáng. BỎ phần đế/khung board/chân
#   màn hình — thêm lại khi cần bằng build thường (--stl-only).
#   [BOM] mua ngoài 2 thanh trụ tròn Ø5 h8 x 130 mm (thép/inox) + 2 vít lục
#   giác chìm M3x6 chặn núm. Chụp cáp KHÔNG còn vít (4 trụ cắm Ø4 liền khối).
PRINT_SET = [  # (tên part, tên file xuất, xoay tư thế in)
    ("body",              "01_than_hop_toi.stl",          None),
    ("lid",               "02_nap_labyrinth.stl",         None),
    ("slide_shaft_red",   "03_truc_truot_D.stl",          "shaft"),      # in 2
    ("led_carrier_red",   "04_carrier_led.stl",           None),         # in 2 — đáy xuống bàn, lỗ mù thanh trượt nằm ngang
    ("rod_knob_red",      "05_num_thanh_truot.stl",       "knob"),       # in 2 — mặt đĩa áp bàn
    ("hood_l_red",        "06_chup_luon_day_trai.stl",    None),
    ("hood_r_red",        "07_chup_luon_day_phai.stl",    None),
    ("aperture_red_blank","08_khau_do_biet.stl",          "lay_flat"),
    ("aperture_red_d2",   "09_khau_do_lo2mm.stl",         "lay_flat"),
    ("aperture_red_d5",   "10_khau_do_lo5mm.stl",         "lay_flat"),
    ("aperture_red_d16",  "11_khau_do_lo16mm.stl",        "lay_flat"),
]
A1_PLATE = 256.0


def _orient_print(mesh, mode):
    """Chuyển từ hệ THẾ GIỚI (Y=lên trời) sang hệ SLICER (Z=lên trời, Bambu
    Studio): R_x(+90°) — world Y -> print Z (chiều cao in), world Z -> print Y.
    Không chuyển đổi này, mọi file đều NẰM NGHIÊNG khi mở bằng slicer.
    Chuẩn hoá về gốc TRƯỚC khi xoay (mesh từ collect_parts đã ở toạ độ thế giới).
      - body/hood : in nguyên tư thế lắp — mặt đáy xuống bàn, không cần support.
      - lid       : in nguyên tư thế lắp — mặt recess + ray hướng lên.
      - shaft     : D-flat quay xuống làm mặt bám bàn (in trục không support).
      - carrier   : in nguyên tư thế lắp — đáy xuống bàn; lỗ mù thanh trượt và
                    lỗ vít chặn đều nằm ngang, Ø nhỏ, không cần support.
      - knob      : trục núm dựng đứng (world X -> print Z) — mặt đĩa áp bàn,
                    lỗ mù Ø5.1 mở lên trên.
      - aperture 'lay_flat': mặt tấm 35×58 áp bàn (bề dày 1.6 = chiều cao),
                    cắt phần tay cầm lún dưới mặt bàn (tab 1.4mm còn lại)."""
    m = mesh.copy()
    lo, _ = m.bounds
    m.apply_translation([-lo[0], -lo[1], -lo[2]])   # góc bbox về (0,0,0)
    if mode == "shaft":                      # trục D: flat quay xuống
        lo, hi = m.bounds
        c = (lo + hi) / 2
        m.apply_translation([-c[0], -c[1], -c[2]])
        m.apply_transform(rotation_matrix(math.pi, [1, 0, 0]))
    elif mode == "knob":                     # núm: trục X -> trục Z bàn in
        m.apply_transform(rotation_matrix(-math.pi / 2, [0, 1, 0]))
    elif mode == "lay_flat":   # (x,y,z) -> (-y, -z, x): mặt 35×58 áp bàn,
        m.apply_transform(rotation_matrix(math.pi / 2, [0, 0, 1]))   # bề dày 1.6 = Z
        m.apply_transform(rotation_matrix(math.pi / 2, [1, 0, 0]))
        # Tay cầm quấn quanh 2 mặt tấm (±1.4mm): cắt phần lún dưới mặt bàn,
        # còn tab nhô 1.4mm phía trên để nhấc bằng tay.
        m = dif(m, [box(-500, 500, -500, 500, -500, 1.4)])
        if m is None or len(m.faces) == 0:
            raise RuntimeError("Cắt tay cầm khẩu độ dưới mặt bàn thất bại")
    else:
        m.apply_transform(rotation_matrix(math.pi / 2, [1, 0, 0]))
    lo, _ = m.bounds
    m.apply_translation([-lo[0], -lo[1], -lo[2]])   # đáy chạm bàn, góc tại 0,0
    return m


def _rect_sub(r, u):
    """Cắt ô trống r bởi vùng vừa dùng u -> các mảnh trống còn lại."""
    rx, ry, rw, rh = r
    ux, uy, uw, uh = u
    if (ux >= rx + rw - 1e-9 or ux + uw <= rx + 1e-9
            or uy >= ry + rh - 1e-9 or uy + uh <= ry + 1e-9):
        return [r]                                   # không giao -> giữ nguyên
    out = []
    if uy > ry:
        out.append((rx, ry, rw, uy - ry))
    if uy + uh < ry + rh:
        out.append((rx, uy + uh, rw, ry + rh - uy - uh))
    if ux > rx:
        out.append((rx, ry, ux - rx, rh))
    if ux + uw < rx + rw:
        out.append((ux + uw, ry, rx + rw - ux - uw, rh))
    return [q for q in out if q[2] > 1e-6 and q[3] > 1e-6]


def _rect_in(a, q):
    """a chứa trọn q?"""
    return (a[0] <= q[0] + 1e-9 and a[1] <= q[1] + 1e-9
            and a[0] + a[2] >= q[0] + q[2] - 1e-9
            and a[1] + a[3] >= q[1] + q[3] - 1e-9)


def _pack_plate(placed, plate=A1_PLATE, margin=8.0, gap=6.0):
    """Xếp footprint TRÊN MẶT BÀN (mặt XY của STL — Z là chiều cao in) bằng
    MaxRects / best-short-side-fit, cho phép XOAY 90° quanh Z (an toàn khi
    in vì chỉ đổi hướng trong mặt phẳng bàn). Khác shelf next-fit cũ, thuật
    toán này quay lại lấp mọi khoảng trống đã mở, nên 11 chi tiết (kể cả
    thân 170 mm sau khi mọc bệ thanh trượt) vẫn nằm gọn trong bàn 256 mm.
    Trả list [(tên, mesh, x, y)]."""
    lim = plate - 2 * margin + gap        # mỗi chi tiết tự mang khe gap
    free = [(0.0, 0.0, lim, lim)]
    order = sorted(placed, key=lambda kv: -max(
        kv[1].bounds[1][0] - kv[1].bounds[0][0],
        kv[1].bounds[1][1] - kv[1].bounds[0][1]))     # cạnh dài giảm dần
    out = []
    for name, m in order:
        b = m.bounds
        w0, d0 = b[1][0] - b[0][0], b[1][1] - b[0][1]
        best = None
        for rot in (False, True):
            w, d = (d0, w0) if rot else (w0, d0)
            wg, dg = w + gap, d + gap
            for fx, fy, fw, fh in free:
                if wg > fw + 1e-9 or dg > fh + 1e-9:
                    continue
                key = (min(fw - wg, fh - dg), max(fw - wg, fh - dg), fy, fx)
                if best is None or key < best[0]:
                    best = (key, fx, fy, w, d, rot)
        if best is None:
            raise RuntimeError(f"Không vừa bàn in {plate:.0f}mm: {name}")
        _, fx, fy, w, d, rot = best
        mm = m
        if rot:
            mm = m.copy()
            mm.apply_transform(rotation_matrix(math.pi / 2, [0, 0, 1]))
            b2 = mm.bounds
            mm.apply_translation([-b2[0][0], -b2[0][1], 0])   # góc về (0,0)
        out.append((name, mm, fx + margin, fy + margin))
        used = (fx, fy, w + gap, d + gap)
        nf = []
        for r in free:
            nf += _rect_sub(r, used)
        free = [a for i, a in enumerate(nf)
                if not any(j != i and _rect_in(q, a)
                           and (j < i or not _rect_in(a, q))
                           for j, q in enumerate(nf))]
    return out


def export_print_package(parts):
    """Xuất out/print_bambu/: STL từng chi tiết (đúng tư thế in) + 1 file
    all-in-one xếp sẵn trên bàn 256x256 cho Bambu Studio."""
    pdir = os.path.join(OUT, "print_bambu")
    os.makedirs(pdir, exist_ok=True)
    idx = {p["name"]: p for p in parts}
    oriented = []
    print("\nGói in Bambu A1 -> out/print_bambu/"
          + (f"  [scale = {SCALE:.2f} — hộp ~{X_TOT*SCALE:.0f}×{Y_LID*SCALE:.0f}"
             f"×{(Z1-Z0)*SCALE:.0f} mm]" if SCALE != 1.0 else ""))
    if SCALE < 0.8:
        print(f"  ⚠ scale {SCALE:.2f}: bề dày tường chỉ {WALL*SCALE:.2f} mm "
              f"(< 2.4 mm khuyến nghị cho kín sáng)")
    for name, fname, mode in PRINT_SET:
        if name.startswith("aperture_red_"):
            # dựng lại ở hệ cục bộ — mesh trong collect_parts đã bị dịch tới
            # vị trí thế giới (x≈113) nên không dùng được cho phép xoay lay_flat
            m0 = build_aperture(name.rsplit("_", 1)[-1])
        else:
            p = idx[name]
            m0 = p["mesh"] or p["subs"][0]["mesh"]
        m = _orient_print(m0, mode)
        if SCALE != 1.0:
            m.apply_scale(SCALE)      # min vẫn = 0 (scale quanh gốc)
        m.export(os.path.join(pdir, fname))
        b = m.bounds
        w, d, h = b[1][0] - b[0][0], b[1][1] - b[0][1], b[1][2] - b[0][2]
        ok = "watertight" if m.is_watertight else "!! NOT WATERTIGHT"
        print(f"  {fname:<28} {w:6.1f} x {d:6.1f} x cao {h:5.1f} mm  "
              f"{len(m.faces):>5} tris  {ok}")
        oriented.append((fname, m))
    # --- all-in-one: xếp trên 1 bàn (MaxRects, cạnh dài giảm dần) ---
    layout = _pack_plate(oriented)
    combo_parts = []
    for _, m, x, y in layout:
        c = m.copy()
        c.apply_translation([x, y, 0])   # dời trên MẶT BÀN (x,y) — z giữ = chiều cao
        combo_parts.append(c)
    combo = cat(combo_parts)
    combo.export(os.path.join(pdir, "00_ppg_hop_toi_A1_all_in_one.stl"))
    keep = {f for _, f, _ in PRINT_SET} | {"00_ppg_hop_toi_A1_all_in_one.stl"}
    for fn in sorted(os.listdir(pdir)):     # dọn file mồ côi của lần build trước
        if fn.endswith(".stl") and fn not in keep:
            os.remove(os.path.join(pdir, fn))
            print(f"  (xoá STL cũ không còn trong thiết kế: {fn})")
    b = combo.bounds
    # kiểm tra chồng lấn bbox TRÊN MẶT BÀN (mặt XY — z là chiều cao in, bỏ qua)
    boxes = []
    for _, m, x, y in layout:
        bb = m.bounds
        boxes.append((bb[0][0] + x, bb[0][1] + y, bb[1][0] + x, bb[1][1] + y))
    overlap = False
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, c = boxes[i], boxes[j]
            if a[0] < c[2] and c[0] < a[2] and a[1] < c[3] and c[1] < a[3]:
                overlap = True
    print(f"  00_ppg_hop_toi_A1_all_in_one.stl  "
          f"{b[1][0]-b[0][0]:.0f} x {b[1][1]-b[0][1]:.0f} mm trên bàn (cao "
          f"{b[1][2]-b[0][2]:.0f} mm), {len(layout)} chi tiết, "
          f"{len(combo.faces)} tris, "
          f"{'!! CHỒNG LẤN' if overlap else 'không chồng lấn'}")
    print("  (Bambu Studio: mở file all-in-one -> tách 'Split to objects' "
          "nếu muốn in riêng từng phần)")


def main():
    global DETAIL, STL_ONLY, INCLUDE_VISUAL, ONLY, SCALE
    ap = argparse.ArgumentParser(
        description="Build mô hình 3D PPG Simulator (STL in 3D + viewer web).")
    ap.add_argument("--detail", choices=("full", "simple"), default="full",
                    help="full: đủ chi tiết thẩm mỹ (mặc định, viewer đẹp). "
                         "simple: chỉ chi tiết chức năng — bề mặt phẳng, in 3D dễ hơn.")
    ap.add_argument("--stl-only", action="store_true",
                    help="chỉ xuất STL in 3D (bỏ model.json + viewer.html) — build nhanh.")
    ap.add_argument("--no-visual", action="store_true",
                    help="bỏ chi tiết mua sẳn/dây/chùm sáng khỏi model.json (STL không đổi).")
    ap.add_argument("--only", action="append", metavar="NAME",
                    help="chỉ build phần có tên chứa NAME (dùng nhiều lần, ví dụ "
                         "--only carrier). Dùng để chỉnh 1 chi tiết nhanh.")
    ap.add_argument("--bambu", action="store_true",
                    help="xuất gói in Bambu Lab A1 (out/print_bambu/): chỉ hộp tối + "
                         "chụp luồn dây + khẩu độ — bỏ phần gắn module.")
    ap.add_argument("--scale", type=float, default=1.0, metavar="S",
                    help="thu nhỏ đều toàn bộ mô hình, ví dụ 0.85 -> hộp "
                         "~127×57×68 mm. Các cặp lắp ghép (nắp-thân, khẩu độ-khe) "
                         "vẫn khớp nhau vì cùng tỉ lệ; lỗ vít M3 / trục Ø8 nhỏ "
                         "theo (khoan lại hoặc dán). Khuyến nghị S >= 0.8 để "
                         "tường >= 2.4 mm kín sáng.")
    args = ap.parse_args()
    DETAIL = args.detail
    STL_ONLY = args.stl_only
    # --stl-only: visual vô ích (không ghi model.json) -> bỏ luôn cho nhanh.
    INCLUDE_VISUAL = not args.no_visual and not args.stl_only
    ONLY = args.only
    SCALE = max(0.3, min(2.0, args.scale))

    if args.bambu:
        # Gói in: luôn bản simple (ít boolean, bề mặt phẳng), không đụng viewer
        DETAIL = "simple"
        INCLUDE_VISUAL = False
        print("=" * 78)
        print(f"PPG SIMULATOR — GÓI IN BAMBU LAB A1 (bàn {A1_PLATE:.0f}×{A1_PLATE:.0f} mm)")
        print("  Chỉ: hộp tối (lỗ luồn dây + khe khẩu độ + máng dây) · nắp labyrinth"
              " · trục + carrier + núm thanh trượt · 4 tấm khẩu độ · 2 chụp"
              " — KHÔNG đế/khung board/chân màn hình")
        print("=" * 78)
        print("\nBuilding parts (manifold CSG) ...")
        parts = collect_parts()
        export_print_package(parts)
        print("\nDone. Copy file trong docs/system_3d/out/print_bambu/ vào "
              "Bambu Studio (đơn vị mm).")
        return

    print("=" * 78)
    print("PPG SIMULATOR — MÔ HÌNH 3D TOÀN HỆ THỐNG (docs/system_3d)")
    print(f"  Hộp tối: {X_TOT:.0f} × {Y_LID:.0f} × {Z1 - Z0:.0f} mm   "
          f"Đế chung: {BASE_X1 - BASE_X0:.0f} × {BASE_Z1 - BASE_Z0:.0f} mm (chia đôi in)")
    print(f"  Khoảng cách mặc định: Đỏ d={D_DEFAULT['red']:.0f} mm, "
          f"IR d={D_DEFAULT['ir']:.0f} mm (chóp LED → cửa sổ OPT101 tại x={X_WIN:.0f})")
    print(f"  Chế độ: detail={DETAIL}"
          + (", STL-only" if STL_ONLY else "")
          + ("" if INCLUDE_VISUAL else ", no-visual")
          + (f", only={ONLY}" if ONLY else ""))
    print("=" * 78)
    print("\nBuilding parts (manifold CSG) ...")
    parts = collect_parts()
    if ONLY:
        parts = [p for p in parts if any(s in p["name"] for s in ONLY)]
        print(f"  Lọc --only: còn {len(parts)} phần: {[p['name'] for p in parts]}")
    print("Exporting ...")
    export(parts, write_model=not STL_ONLY)
    if not STL_ONLY:
        build_viewer()
        print("\nDone. Open docs/system_3d/viewer.html in a browser.")
    else:
        print(f"\nDone. STL in docs/system_3d/out/stl/ ({DETAIL}).")


if __name__ == "__main__":
    main()
