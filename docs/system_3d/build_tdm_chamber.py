#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_tdm_chamber.py — CARRIER 2 LED cho chế độ RX TDM (một OPT101).

Chế độ RX "tdm" (Thiết lập → Cảm biến RX → 1 × OPT101) bật luân phiên
RED / IR / DARK, nên LED Đỏ và IR có thể nằm chung MỘT carrier trong MỘT làn.

  - Hộp: dùng NGUYÊN thân + nắp v4 (hộp chữ nhật). Làn IR của v4 (Z=+19.25)
    đồng trục với socket U2 (IR → A0) của board thu 70 × 20 mm — đúng chỗ cắm
    OPT101 duy nhất. Làn Đỏ bỏ trống, cắm tấm khẩu độ 'blank'.
  - Carrier mới: cùng thân 22 × 35 × 18 mm, lỗ D, lỗ thanh đẩy, vít chặn như
    carrier v4 -> trượt trên ray D v4, dùng thanh đẩy, núm, chụp v4.
    Hai LED 3 mm đặt cạnh nhau theo Z (IR ở +Z, Đỏ ở −Z), tim cách 5 mm, mỗi lỗ
    nghiêng vào trong để hai trục quang hội tụ tại cửa sổ OPT101 ở khoảng cách
    D_CONV_REAL. Không đổi PCB nào.
  - Hai LED giờ cùng khoảng cách d, nên carrier có khe cắm TẤM CHE phía trước:
    lỗ Đỏ luôn Ø3, lỗ IR chọn Ø3 / Ø2 / Ø1.5 / Ø1 để giảm sáng IR khi bão hoà.
    Mức giảm phụ thuộc giản đồ phát của LED thật — phải đo, không suy ra từ
    diện tích lỗ.

Máy in đích: Bambu Lab A1 (đầu phun 0.4, lớp 0.2). Carrier và mẫu thử in DỰNG
ĐỨNG trên mặt sau để lỗ LED, lỗ D, lỗ thanh đẩy là lỗ đứng (tròn, bù lỗ XY của
Bambu Studio có tác dụng); mọi chỗ lỗ LED thu hẹp đi lên là côn ≤ 45°, miệng lỗ
mặt áp bàn vát 45° để ăn chân voi lớp đầu.

[ASSUME] SOCKET_H = 8.3 mm: mặt PCB thu -> cửa sổ OPT101 trong socket (đo lại).
[ASSUME] A1_HOLE_SHRINK_NOM/MAX: độ hụt lỗ đứng của A1 lấy từ wiki/forum Bambu,
chưa đo trên máy của người dùng (mẫu thử 30 dùng để đo).
Mọi khe lắp và kiểm tra dưới đây là hình học CAD, CHƯA in thử,
CHƯA đo rò sáng hay công suất quang.

Chạy từ gốc repo:
  .cad_venv/bin/python docs/system_3d/build_tdm_chamber.py
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys

import numpy as np
import trimesh
from trimesh.transformations import rotation_matrix, translation_matrix

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out_tdm")
V4_PRINT = os.path.join(HERE, "out", "print_bambu_180")
sys.path.insert(0, HERE)
import build_system as bs  # noqa: E402  (nguồn tham số hộp v4)

bs.DETAIL = "simple"            # đúng biến thể đã xuất trong gói in v4
bs.INCLUDE_VISUAL = False

_spec = importlib.util.spec_from_file_location(
    "receiver_u_support", os.path.join(HERE, "receiver_u_support.py"))
receiver_u_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(receiver_u_support)

box, cyl_x, cyl_z, uni, dif = bs.box, bs.cyl_x, bs.cyl_z, bs.uni, bs.dif

# ============================================================================
# THAM SỐ (mm)
# ============================================================================
SOCKET_H = 8.3                         # [ASSUME] mặt PCB -> cửa sổ OPT101 trong socket
X_S = bs.FRM_X0 - SOCKET_H             # 129.2 mặt cửa sổ OPT101 thật
Y_S = bs.Y_AX                          # 32
LANE = "ir"
Z_S = bs.LANE_Z[LANE]                  # +19.25 = socket U2 (IR -> A0)
D_OFFSET = X_S - bs.X_WIN              # 9.2: d thật = d theo thang v4 + D_OFFSET

LED_PITCH = 5.0                        # tim-tim hai LED (vành Ø3.8 -> vách ≥0.9 ở hốc vành)
LED_Z = {"ir": LED_PITCH / 2, "red": -LED_PITCH / 2}   # z cục bộ carrier
D_CONV_REAL = 50.0                     # hai trục quang cắt nhau tại cửa sổ ở d thật này
TOE = math.atan((LED_PITCH / 2) / D_CONV_REAL)          # ≈ 2.86° mỗi LED
# --- LED thật, theo datasheet trong docs/ds_linhkien --------------------------
# Đỏ  YSL-R341R3D-D2: thân Ø3.00 ±0.2; đỉnh -> đáy vành 8.6; vành dày 1.0;
#      Ø vành không ghi (hình vẽ ≈3.4, có mặt vát) -> bao bảo thủ Ø4.0.
# IR  Everlight SIR234 (T-1, KHÔNG có vành): thân Ø3.0 ±0.2; đỉnh -> đáy 5.0 ±0.3.
LED_BODY_D, LED_BODY_TOL = 3.0, 0.2
DOME_R = LED_BODY_D / 2
RED_LEN, RED_FLANGE_T, RED_FLANGE_D_MAX = 8.6, 1.0, 4.0
IR_LEN, IR_LEN_TOL = 5.0, 0.3

# --- Máy in: Bambu Lab A1, đầu phun 0.4, lớp 0.2 (hồ sơ 0.20 mm Standard) -----
# Bambu KHÔNG công bố sai số kích thước cho A1 (trang tech-specs). Số dưới đây
# lấy từ wiki Bambu (lỗ đứng M6 in với bù lỗ XY = 0 cần +0.15 mm/bên mới vừa
# khít, tức hụt ~0.3 mm Ø) và báo cáo người dùng A1 trên forum Bambu (chi tiết
# nhỏ hụt 0.1–0.25 mm; một khe 4 mm ra 3.5 mm). Bù lỗ XY của Bambu Studio chỉ áp
# dụng cho đường KÍN trong từng lớp = lỗ có trục ĐỨNG; lỗ nằm ngang thì thành
# bậc thang 0.2 mm và võng trần, không bù được. Vì vậy carrier in DỰNG ĐỨNG trên
# mặt sau: mọi lỗ dọc trục (2 lỗ LED, lỗ D, lỗ thanh đẩy) thành lỗ đứng, tròn.
A1_LAYER_H = 0.2
A1_HOLE_SHRINK_NOM = 0.2               # [ASSUME] lỗ đứng Ø3–5 hụt Ø thường gặp
A1_HOLE_SHRINK_MAX = 0.4               # [ASSUME] hụt Ø xấu nhất đem kiểm tra (đo bằng mẫu thử 30)
A1_OVERHANG_MAX_DEG = 45.0             # mặt treo tự đỡ, không support
LEAD_IN = 0.5                          # vát 45° ở miệng lỗ: ăn chân voi lớp đầu + dẫn LED
CONE_DEG = 40.0                        # nửa góc côn thu hẹp trong lỗ LED: 40° + nghiêng 2.86° < 45°

# --- Lỗ LED (đổi bằng --bore-d / --flange-bore-d sau khi thử mẫu 30_mau_thu) --
# Chọn sao cho LED lớn nhất (thân Ø3.2, vành Ø4.0) vẫn lọt khi lỗ hụt
# A1_HOLE_SHRINK_MAX, và LED danh định không lỏng quá 0.3 mm/bên khi hụt NOM.
BORE_D = 3.7                           # in ra ~Ø3.5 (NOM) .. Ø3.3 (MAX)
FLANGE_BORE_D = 4.5                    # in ra ~Ø4.3 .. Ø4.1 cho vành ≤ Ø4.0
LIP_D = 2.6                            # gờ chặn chóp: chóp cầu Ø3 tì vào mép Ø2.6
LIP_T = 1.0
LEG_R = 2.6                            # khoang chân/dây phía sau (như v4)
LEG_CEIL_X = -10.4                     # trần khoang chân = miệng vào hai lỗ LED
STEP_MARGIN = 0.7                      # vành Đỏ còn cách bậc Ø vành→Ø thân khi chóp đã tì gờ

FRONT_L = 4.0                          # khối mũi thay loa che sáng v4
FRONT_HY, FRONT_HZ = 4.5, 6.5          # nửa cao / nửa rộng khối mũi
MASK_T = 1.0                           # bề dày tấm che
MASK_SLOT_X0, MASK_SLOT_X1 = 1.6, 3.0  # khe 1.4 = 7 lớp cho tấm 1.0; trần khe là cầu in (võng)
MASK_SLOT_FLOOR = Y_S - 3.5            # đáy khe (còn 1 mm sàn khối mũi)
MASK_HZ = 5.4                          # nửa rộng tấm (khe ±5.5)
MASK_TOP = bs.CAR_Y1 - 0.5             # tai cầm nhô trên khối mũi, thấp hơn nóc carrier
MASK_KINDS = {"mo": 1.5, "ir2": 1.0, "ir1_5": 0.75, "ir1": 0.5}   # bán kính lỗ IR
MASK_RED_R = 1.5                       # lỗ Đỏ luôn Ø3

D_RANGE_V4 = (bs.D_MIN, bs.D_MAX)      # 15..90 theo thang v4 (cữ chặn của thân v4)
D_DEFAULT_REAL = D_CONV_REAL
SENSOR_HALF = 2.29 / 2                 # vùng nhạy OPT101 2.29 × 2.29 [DS]
WINDOW_X_RANGE = (126.5, 132.0)        # bao X cửa sổ khả dĩ (socket + IC)
RECEIVER_LOWER, RECEIVER_UPPER = 19.81, 39.81   # gá H OPT101 (build_adapter.py)
BED, BED_MARGIN = 180.0, 8.0
FIT_TOL_MM3 = 1e-4


# ============================================================================
# CARRIER 2 LED
# ============================================================================
def _led_rot(ch):
    """Xoay quanh chóp LED (x=LED_TIP_OUT) để trục LED chúc vào trục làn."""
    z0 = LED_Z[ch]
    ang = TOE if z0 > 0 else -TOE      # +x -> (cos, 0, -sin): LED ở +Z chúc về −Z
    pivot = [bs.LED_TIP_OUT, Y_S, z0]
    return (translation_matrix(pivot) @ rotation_matrix(ang, [0, 1, 0])
            @ translation_matrix([-p for p in pivot]))


def _along_led(ch, mesh):
    m = mesh.copy()
    m.apply_transform(_led_rot(ch))
    return m


def led_axis(ch):
    """(điểm chóp LED, vector đơn vị trục LED) trong hệ carrier."""
    R = _led_rot(ch)
    tip = (R @ np.array([bs.LED_TIP_OUT, Y_S, LED_Z[ch], 1.0]))[:3]
    return tip, R[:3, :3] @ np.array([1.0, 0.0, 0.0])


def build_dual_carrier(shrink=0.0):
    """Thân, lỗ D, lỗ thanh đẩy, vít chặn, hốc dây hông giữ nguyên carrier v4;
    thay loa Ø đơn bằng khối mũi 2 lỗ nghiêng + khe tấm che.
    shrink: Ø mọi lỗ LED (trừ mép gờ chặn) nhỏ đi bấy nhiêu = mô phỏng lỗ in hụt."""
    m = box(-bs.CAR_L, 0.0, bs.CAR_Y0, bs.CAR_Y1, -bs.CAR_ZW / 2, bs.CAR_ZW / 2)
    m = uni([m, box(-0.5, FRONT_L, Y_S - FRONT_HY, Y_S + FRONT_HY, -FRONT_HZ, FRONT_HZ)])
    flat_y = bs.SH_FLAT_Y + bs.CLR
    dbore = dif(cyl_x(-bs.CAR_L - 0.5, 0.5, bs.SH_Y, 0.0, bs.SH_R + bs.CLR, 40),
                [box(-bs.CAR_L - 1, 1, flat_y, bs.SH_Y + bs.SH_R + 2, -bs.SH_R - 2, bs.SH_R + 2)])
    # vát 45° miệng lỗ ở mặt sau (mặt áp bàn khi in dựng đứng): ăn chân voi lớp đầu
    sh_r, rod_r = bs.SH_R + bs.CLR, bs.ROD_SOCKET_R
    bed_x = -bs.CAR_L
    dbore_lead = dif(bs.frustum_x(bed_x - 0.5, bed_x + LEAD_IN, bs.SH_Y, 0.0,
                                  sh_r + LEAD_IN + 0.5, sh_r, 40),
                     [box(bed_x - 1, bed_x + 1, flat_y, bs.SH_Y + bs.SH_R + 2,
                          -bs.SH_R - 2, bs.SH_R + 2)])
    rod_lead = bs.frustum_x(bed_x - 0.5, bed_x + LEAD_IN, bs.ROD_Y, 0.0,
                            rod_r + LEAD_IN + 0.5, rod_r, 48)
    spread = LED_PITCH / 2 + (bs.CAR_L + 1.5) * math.tan(TOE)   # tâm lỗ lệch ra ở mặt sau
    cuts = [
        dbore, dbore_lead, rod_lead,
        bs._tube("x", -bs.CAR_L - 0.5, -bs.CAR_L + bs.ROD_BORE_DEPTH, bs.ROD_Y, 0.0,
                 bs.ROD_SOCKET_R, 64),
        cyl_z(-bs.CAR_ZW / 2 - 0.5, bs.CAR_ZW / 2 + 0.5, bs.ROD_GRUB_X, bs.ROD_Y, 1.3, 24),
        # khoang chân/dây chung cho 4 chân LED
        box(-bs.CAR_L - 0.5, LEG_CEIL_X, Y_S - LEG_R, Y_S + LEG_R,
            -spread - LEG_R, spread + LEG_R),
        box(-bs.CAR_L + 2.0, -bs.CAR_L + 6.0, Y_S - 2.0, Y_S + LEG_R,
            -bs.CAR_ZW / 2 - 0.5, bs.CAR_ZW / 2 + 0.5),
        box(-bs.CAR_L - 0.5, -bs.CAR_L + 5.0, bs.CAR_Y0 + 1.0, bs.CAR_Y0 + 5.0, -3.0, 3.0),
        # khe tấm che: mở từ nóc khối mũi xuống
        box(MASK_SLOT_X0, MASK_SLOT_X1, MASK_SLOT_FLOOR, Y_S + FRONT_HY + 0.5,
            -MASK_HZ - 0.1, MASK_HZ + 0.1),
    ]
    for ch in ("red", "ir"):
        cuts.append(led_bore_tools(LED_Z[ch], ch, shrink))
    return dif(m, cuts)


def lip_contact_x():
    """Mặt phẳng chóp cầu (bán kính DOME_R) chạm mép gờ Ø LIP_D khi chóp ở LED_TIP_OUT."""
    return bs.LED_TIP_OUT - (DOME_R - math.sqrt(DOME_R ** 2 - (LIP_D / 2) ** 2))


def step_x():
    """Đầu bậc Ø FLANGE_BORE_D -> Ø BORE_D, nằm trước mặt trước vành Đỏ."""
    return bs.LED_TIP_OUT - (RED_LEN - RED_FLANGE_T) + STEP_MARGIN


def led_bore_tools(z0, ch=None, shrink=0.0):
    """Dao cắt một lỗ LED tròn (dọc +X qua (Y_S, z0)), xoay theo trục LED nếu có ch.
    Khi in dựng đứng, +X là CHIỀU LÊN; mọi chỗ lỗ thu hẹp đi lên đều là côn
    CONE_DEG (tự đỡ kể cả khi trục nghiêng TOE, không có gờ phẳng treo). Sau -> trước:
      phễu ở trần khoang chân | Ø vành | côn Ø vành→Ø thân | Ø thân |
      côn Ø thân→Ø LIP_D (mép gờ chặn chóp) | loe ra trước | lỗ mũi qua khe."""
    rf, rb = (FLANGE_BORE_D - shrink) / 2, (BORE_D - shrink) / 2
    rl = LIP_D / 2
    k = 1.0 / math.tan(math.radians(CONE_DEG))   # chiều dài côn trên 1 mm bán kính
    xl, xs = lip_contact_x(), step_x()
    xc = LEG_CEIL_X
    tool = revolve_x([(-bs.CAR_L - 1.5, rf), (xc - 0.6 * k, rf),
                      (xc - 0.6 * k, rf + LEAD_IN + 0.6), (xc + LEAD_IN * k, rf),
                      (xs, rf), (xs + (rf - rb) * k, rb),
                      (xl - (rb - rl) * k, rb), (xl, rl),
                      (xl + LIP_T, BORE_D / 2), (FRONT_L + 1.0, BORE_D / 2)], Y_S, z0)
    return _along_led(ch, tool) if ch else tool


def revolve_x(profile, yc, zc, n=48):
    """Khối tròn xoay quanh trục // X qua (yc, zc) từ biên dạng [(x, r), ...]
    (x tăng dần). Một khối liền, không mép chồng giữa các đoạn như khi ghép
    nhiều trụ/nón -> không sinh vành mỏng giả khi kiểm tra mặt treo."""
    pts = [(0.0, profile[0][0])] + [(r, x) for x, r in profile] + [(0.0, profile[-1][0])]
    m = trimesh.creation.revolve(np.array(pts), sections=n)
    m.apply_transform(rotation_matrix(math.pi / 2, [0, 1, 0]))     # trục Z -> trục X
    m.apply_translation([0.0, yc, zc])
    if m.volume < 0:
        m.invert()
    return m


def build_mask(kind):
    """Tấm che cắm khe mũi carrier (hệ carrier, đã ở vị trí lắp). Lỗ nằm
    trên trục LED nghiêng; số khía trên tai cầm = thứ tự biến thể."""
    x0 = (MASK_SLOT_X0 + MASK_SLOT_X1 - MASK_T) / 2
    m = box(x0, x0 + MASK_T, MASK_SLOT_FLOOR + 0.2, MASK_TOP, -MASK_HZ, MASK_HZ)
    holes = [_along_led(ch, cyl_x(x0 - 0.5, x0 + MASK_T + 0.5, Y_S, LED_Z[ch], r, 32))
             for ch, r in (("red", MASK_RED_R), ("ir", MASK_KINDS[kind]))]
    n = list(MASK_KINDS).index(kind)
    marks = [box(x0 - 0.1, x0 + MASK_T + 0.1, MASK_TOP - 1.0, MASK_TOP + 0.1,
                 -MASK_HZ + 1.0 + 1.6 * i, -MASK_HZ + 1.8 + 1.6 * i) for i in range(n)]
    return dif(m, holes + marks)


def led_solid(ch, tip_x, worst=False, z0=0.0):
    """Bao LED theo datasheet, trục dọc +X qua (Y_S, z0), chóp tại tip_x.
    worst=True: thân Ø3.2, vành Ø4.0, IR dài 5.3 (bao lớn nhất trong dung sai)."""
    r = DOME_R + (LED_BODY_TOL / 2 if worst else 0.0)
    c = tip_x - r                                         # tâm chóp cầu
    dome = trimesh.creation.uv_sphere(radius=r, count=[24, 24])
    dome.apply_translation([c, Y_S, z0])
    if ch == "red":
        back = tip_x - RED_LEN
        rf = RED_FLANGE_D_MAX / 2 if worst else 1.9
        parts = [cyl_x(back + RED_FLANGE_T - 0.01, c, Y_S, z0, r, 40),
                 cyl_x(back, back + RED_FLANGE_T, Y_S, z0, rf, 40)]
    else:
        back = tip_x - IR_LEN - (IR_LEN_TOL if worst else 0.0)
        parts = [cyl_x(back, c, Y_S, z0, r, 40)]
    return uni([dome] + parts)


def stop_tip_x(worst=False):
    """Vị trí chóp khi chóp cầu tì vào gờ (LED Ø lớn dừng lùi hơn một chút)."""
    r = DOME_R + (LED_BODY_TOL / 2 if worst else 0.0)
    return lip_contact_x() + r - math.sqrt(r ** 2 - (LIP_D / 2) ** 2)


def led_models(ch, worst=False, shift=0.0):
    """LED đã lắp (chóp tì gờ) trong lỗ nghiêng, hệ carrier; shift dời dọc trục LED."""
    return _along_led(ch, led_solid(ch, stop_tip_x(worst) + shift, worst, LED_Z[ch]))


COUPON_STEPS = (-0.2, -0.1, 0.0, 0.1, 0.2)            # lỗ thân = BORE_D + bước
COUPON_FLANGE_STEPS = (-0.2, 0.0, 0.2)                # lỗ vành = FLANGE_BORE_D + bước
COUPON_T, COUPON_H, COUPON_W = 6.0, 16.0, 46.0        # dày 6 = 30 lớp, ~ đoạn thân trong carrier


def coupon_body_d():
    return tuple(round(BORE_D + s, 2) for s in COUPON_STEPS)


def coupon_flange_d():
    return tuple(round(FLANGE_BORE_D + s, 2) for s in COUPON_FLANGE_STEPS)


def build_fit_coupon():
    """Mẫu thử in CÙNG tư thế với carrier: tấm dày COUPON_T áp bàn, lỗ đứng,
    miệng dưới vát LEAD_IN như carrier. Mặt trên có lỗ chấm nhận dạng.
    Hàng trên: lỗ thân BORE_D −0.2 … +0.2 (1…5 chấm, chấm 3 = cỡ đang dùng).
    Hàng dưới: lỗ vành FLANGE_BORE_D −0.2 / 0 / +0.2 (1…3 chấm) và một lỗ thân
    BORE_D có côn + gờ chặn Ø LIP_D ở mặt trên (thử chóp dừng đúng, luồn từ dưới)."""
    m = box(0.0, COUPON_T, 0.0, COUPON_H, 0.0, COUPON_W)
    k = 1.0 / math.tan(math.radians(CONE_DEG))
    cuts = []

    def hole(y, z, r):
        cuts.append(revolve_x([(-0.5, r + LEAD_IN + 0.5), (LEAD_IN, r), (COUPON_T + 0.5, r)], y, z))

    def dots(y, z, n):
        for j in range(n):
            cuts.append(cyl_x(COUPON_T - 0.6, COUPON_T + 0.5, y, z + 1.6 * (j - (n - 1) / 2), 0.5, 16))

    for i, d in enumerate(coupon_body_d()):
        z = 5.0 + 9.0 * i
        hole(11.5, z, d / 2)
        dots(14.7, z, i + 1)
    for i, d in enumerate(coupon_flange_d()):
        z = 5.0 + 9.0 * i
        hole(4.5, z, d / 2)
        dots(1.1, z, i + 1)
    z_lip, rb, rl = 5.0 + 9.0 * len(COUPON_FLANGE_STEPS) + 2.0, BORE_D / 2, LIP_D / 2
    xl = COUPON_T - LIP_T
    cuts.append(revolve_x([(-0.5, rb + LEAD_IN + 0.5), (LEAD_IN, rb), (xl - (rb - rl) * k, rb),
                           (xl, rl), (COUPON_T + 0.5, rl + LIP_T + 0.5)], 4.5, z_lip))
    return dif(m, cuts)


def orient_back_down(mesh):
    """Tư thế in A1 cho carrier và mẫu thử: mặt SAU (x nhỏ nhất) áp bàn,
    trục LED (+X) hướng LÊN -> mọi lỗ dọc trục là lỗ đứng."""
    m = mesh.copy()
    m.apply_transform(rotation_matrix(-math.pi / 2, [0, 1, 0]))   # +X -> +Z bàn in
    lo, _ = m.bounds
    m.apply_translation([-lo[0], -lo[1], -lo[2]])
    return m



# ============================================================================
# ĐẶT TRONG HỘP V4 (làn IR)
# ============================================================================
def front_x(d_real):
    return X_S - d_real - bs.LED_TIP_OUT


def d_real_from_v4(d_v4):
    return d_v4 + D_OFFSET


def place(mesh, d_real):
    m = mesh.copy()
    m.apply_translation([front_x(d_real), 0.0, Z_S])
    return m


def place_rod_knob(d_real):
    x_tail = front_x(d_real) - bs.CAR_L + bs.ROD_BORE_DEPTH - bs.ROD_LEN
    rod, knob = bs.build_push_rod(), bs.build_rod_knob()
    rod.apply_translation([x_tail, bs.ROD_Y, Z_S])
    knob.apply_translation([x_tail + 6.0, bs.ROD_Y, Z_S])
    return rod, knob


def aperture(kind, ch):
    m = bs.build_aperture(kind)
    m.apply_translation([bs.AP_X0 + ((bs.AP_X1 - bs.AP_X0) - bs.AP_T) / 2.0, 0.0, bs.LANE_Z[ch]])
    return m


def receiver_parts():
    parts = {"receiver_support": receiver_u_support.build(bs, RECEIVER_LOWER, RECEIVER_UPPER),
             "receiver_pcb": box(137.5, 139.1, RECEIVER_LOWER, RECEIVER_UPPER, -35, 35)}
    for ch, zc in bs.LANE_Z.items():
        parts["socket_envelope_" + ch] = box(126.5, 137.5, 26.5, 37.5, zc - 5.5, zc + 5.5)
    return parts


def tip_world(ch, d_real):
    tip, d = led_axis(ch)
    return tip + np.array([front_x(d_real), 0.0, Z_S]), d


# ============================================================================
# KIỂM TRA
# ============================================================================
def overlap(a, b):
    lo = np.maximum(a.bounds[0], b.bounds[0])
    hi = np.minimum(a.bounds[1], b.bounds[1])
    if np.any(hi <= lo):
        return 0.0
    r = trimesh.boolean.intersection([a, b], engine="manifold")
    return float(abs(r.volume)) if r is not None and len(r.faces) else 0.0


def body_count(mesh):
    """Số khối liên thông theo cạnh chung (BFS thuần; CAD venv không có scipy)."""
    neighbours = {i: set() for i in range(len(mesh.faces))}
    for a, b in mesh.face_adjacency:
        neighbours[a].add(b)
        neighbours[b].add(a)
    remaining, count = set(neighbours), 0
    while remaining:
        todo = [remaining.pop()]
        count += 1
        while todo:
            fresh = neighbours[todo.pop()] & remaining
            remaining -= fresh
            todo.extend(fresh)
    return count


def ray_cylinder(p0, p1, r=0.2):
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    seg = p1 - p0
    c = trimesh.creation.cylinder(radius=r, height=float(np.linalg.norm(seg)), sections=12)
    c.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], seg / np.linalg.norm(seg)))
    c.apply_translation((p0 + p1) / 2)
    return c


def sensor_targets():
    pts = [(x, Y_S, Z_S) for x in (WINDOW_X_RANGE[0], X_S, WINDOW_X_RANGE[1])]
    pts += [(X_S, Y_S + dy, Z_S + dz) for dy in (-SENSOR_HALF, SENSOR_HALF)
            for dz in (-SENSOR_HALF, SENSOR_HALF)]
    return pts


def off_axis_deg(ch, d_real):
    tip, d = tip_world(ch, d_real)
    v = np.array([X_S, Y_S, Z_S]) - tip
    return math.degrees(math.acos(float(np.dot(v, d) / np.linalg.norm(v))))


def d_list():
    return [d_real_from_v4(D_RANGE_V4[0]), D_DEFAULT_REAL, d_real_from_v4(D_RANGE_V4[1])]


def max_led_bore_overhang_deg(carrier):
    """Góc treo lớn nhất (so với phương đứng) của mặt hướng xuống trong vùng lỗ LED,
    tư thế in dựng đứng (+X = lên). Vùng: cách trục LED < Ø phễu/2, từ trần khoang
    chân tới khe tấm che (trần khe là cầu in có chủ đích, không thuộc lỗ LED)."""
    r_zone = FLANGE_BORE_D / 2 + LEAD_IN - 0.05
    worst = 0.0
    axes = [led_axis(ch) for ch in ("red", "ir")]
    for n, c in zip(carrier.face_normals, carrier.triangles_center):
        if n[0] >= 0.0 or not LEG_CEIL_X - 1.0 <= c[0] < MASK_SLOT_X0:
            continue
        for tip, d in axes:
            v = c - tip
            if np.linalg.norm(v - np.dot(v, d) * d) < r_zone:
                worst = max(worst, math.degrees(math.asin(min(1.0, -float(n[0])))))
                break
    return worst


def run_checks(carrier, masks, v4):
    checks = []

    def check(label, ok, **extra):
        checks.append(dict(label=label, pass_=bool(ok), **extra))

    for name, m in ([("carrier_2led", carrier), ("mau_thu_30", build_fit_coupon())]
                    + [(f"mask_{k}", v) for k, v in masks.items()]):
        check(f"{name}: watertight, một khối", m.is_watertight and body_count(m) == 1,
              volume_mm3=round(float(m.volume), 2))

    def centre_z(ch, x):
        tip, d = led_axis(ch)
        return tip[2] + d[2] * (x - tip[0]) / d[0]
    walls = {
        "đoạn vành Ø%.1f" % FLANGE_BORE_D:
            centre_z("ir", step_x()) - centre_z("red", step_x()) - FLANGE_BORE_D,
        "đoạn thân Ø%.1f" % BORE_D:
            centre_z("ir", FRONT_L) - centre_z("red", FRONT_L) - BORE_D,
    }
    for name, w in walls.items():
        check(f"vách nhựa giữa hai lỗ LED ở {name} ≥ 0.8 mm", w >= 0.8, wall_mm=round(w, 2))
    worst_body = LED_BODY_D + LED_BODY_TOL
    for name, bore, part in (("thân", BORE_D, worst_body), ("vành Đỏ", FLANGE_BORE_D, RED_FLANGE_D_MAX)):
        c = (bore - A1_HOLE_SHRINK_NOM - part) / 2
        check(f"A1: khe hở bán kính {name} sau in (Ø{bore:g} − {A1_HOLE_SHRINK_NOM:g} − "
              f"Ø{part:g})/2 ≥ 0.1 mm", c >= 0.1 - 1e-9, clearance_mm=round(c, 3))
    printed = build_dual_carrier(A1_HOLE_SHRINK_MAX)
    for ch in ("red", "ir"):
        stop = stop_tip_x(True)
        start = -bs.CAR_L - 1.0 - (RED_LEN if ch == "red" else IR_LEN + IR_LEN_TOL)
        worst_v, t = 0.0, start
        while t <= stop - 0.5:                      # đến trước gờ (mép gờ không thu nhỏ)
            worst_v = max(worst_v, overlap(printed, led_models(ch, True, t - stop)))
            t += 0.25
        check(f"A1: LED {ch} lớn nhất vẫn luồn được khi lỗ đứng in hụt Ø "
              f"{A1_HOLE_SHRINK_MAX:g} mm [giả định xấu nhất]", worst_v < 1e-3, worst_mm3=worst_v)
    play = (BORE_D - A1_HOLE_SHRINK_NOM - LED_BODY_D) / 2
    check(f"A1: LED danh định Ø{LED_BODY_D:g} không lỏng quá 0.3 mm/bên khi lỗ hụt "
          f"{A1_HOLE_SHRINK_NOM:g} mm [giả định thường gặp]", 0.0 < play <= 0.3 + 1e-9,
          radial_play_mm=round(play, 3))
    ang = max_led_bore_overhang_deg(carrier)
    check(f"A1 in dựng đứng: mặt treo trong lỗ LED ≤ {A1_OVERHANG_MAX_DEG:g}° "
          "(không support, không gờ phẳng treo)", ang <= A1_OVERHANG_MAX_DEG + 0.5,
          max_overhang_deg=round(ang, 2))
    planes = {"đáy khe tấm che": MASK_SLOT_X0, "trần khe tấm che": MASK_SLOT_X1,
              "mặt trước carrier": 0.0, "mũi": FRONT_L}
    off = {k: round((x + bs.CAR_L) / A1_LAYER_H - round((x + bs.CAR_L) / A1_LAYER_H), 6)
           for k, x in planes.items()}
    check(f"A1 in dựng đứng: các mặt ngang của khe tấm che rơi đúng bội lớp {A1_LAYER_H:g} mm",
          all(abs(v) < 1e-6 for v in off.values()), layer_offset=off)
    lo, hi = orient_back_down(carrier).bounds
    bed_area = float(sum(a for a, n, c in zip(carrier.area_faces, carrier.face_normals,
                                              carrier.triangles_center)
                         if n[0] < -0.999 and abs(c[0] + bs.CAR_L) < 1e-6))
    check("A1 in dựng đứng: mặt sau áp bàn, cao ≤ 30 mm, diện tích bám bàn ≥ 300 mm²",
          hi[2] - lo[2] <= 30.0 and bed_area >= 300.0,
          print_height_mm=round(float(hi[2] - lo[2]), 2), bed_contact_mm2=round(bed_area, 1))
    for ch in ("red", "ir"):
        for worst in (False, True):
            tag = "LED lớn nhất theo dung sai" if worst else "LED danh định"
            # quét luồn từ sau mặt carrier tới khi chóp tì gờ, bước 0.25 mm dọc trục
            stop = stop_tip_x(worst)
            start = -bs.CAR_L - 1.0 - (RED_LEN if ch == "red" else IR_LEN + IR_LEN_TOL)
            worst_v, t = 0.0, start
            while t <= stop + 1e-9:
                worst_v = max(worst_v, overlap(carrier, led_models(ch, worst, t - stop)))
                t += 0.25
            worst_v = max(worst_v, overlap(carrier, led_models(ch, worst)))
            check(f"LED {ch} ({tag}): luồn từ mặt sau tới chặn, không cấn ở bất kỳ vị trí nào",
                  worst_v < 1e-3, worst_mm3=worst_v)
            v = overlap(carrier, led_models(ch, worst, 0.15))
            check(f"LED {ch} ({tag}): gờ trước chặn chóp (tiến thêm 0.15 mm thì chạm)", v > 1e-3,
                  intersection_mm3=v)
    check("chóp hai LED cùng mặt phẳng (cùng gờ chặn, sai lệch < 0.1 mm)",
          abs(stop_tip_x(True) - stop_tip_x(False)) < 0.1,
          tip_nominal_x=round(stop_tip_x(False), 3), tip_worst_x=round(stop_tip_x(True), 3))
    for k, m in masks.items():
        v = overlap(carrier, m)
        check(f"tấm che {k} trượt vào khe không cấn", v < FIT_TOL_MM3, intersection_mm3=v)
        lv = max(overlap(m, led_models(ch)) for ch in ("red", "ir"))
        check(f"tấm che {k} không chạm chóp LED", lv < FIT_TOL_MM3, intersection_mm3=lv)

    # quét hành trình trong làn IR của thân v4
    worst, worst_mask = 0.0, 0.0
    fixed = [v4["body"], v4["lid"]] + [aperture(k, LANE) for k in ("blank", "d2", "d5", "d16")]
    d = D_RANGE_V4[0]
    while d <= D_RANGE_V4[1] + 1e-6:
        dr = d_real_from_v4(d)
        car = place(carrier, dr)
        rod, knob = place_rod_knob(dr)
        msk = place(masks["mo"], dr)
        for f in fixed:
            worst = max(worst, overlap(car, f), overlap(rod, f), overlap(knob, f))
            worst_mask = max(worst_mask, overlap(msk, f))
        worst = max(worst, overlap(car, v4["shaft"]))
        d += 1.0
    check(f"carrier 2 LED / thanh đẩy / núm không chạm thân, nắp, ray, khẩu độ v4 "
          f"(d v4 {D_RANGE_V4[0]:g}..{D_RANGE_V4[1]:g}, bước 1)", worst < FIT_TOL_MM3, worst_mm3=worst)
    check("tấm che lắp sẵn không chạm thân/nắp/khẩu độ trên cả hành trình",
          worst_mask < FIT_TOL_MM3, worst_mm3=worst_mask)
    for name, m in receiver_parts().items():
        v = overlap(place(carrier, d_real_from_v4(D_RANGE_V4[0])), m)
        check(f"carrier ở d nhỏ nhất ∩ {name} = 0", v < FIT_TOL_MM3, intersection_mm3=v)

    def rays_worst(ap_kind, d_real, mask_kind="mo"):
        obstacles = [v4["body"], aperture(ap_kind, LANE), place(carrier, d_real),
                     place(masks[mask_kind], d_real)]
        worst_v = 0.0
        for ch in ("red", "ir"):
            tip, dvec = tip_world(ch, d_real)
            for t in sensor_targets():
                ray = ray_cylinder(tip + dvec * 0.3, t)
                worst_v = max(worst_v, max(overlap(ray, o) for o in obstacles))
        return worst_v

    blocked_d2 = False
    for ap_kind in ("d16", "d5", "d2"):
        res = {round(dr, 1): rays_worst(ap_kind, dr) for dr in d_list()}
        clear = all(v < FIT_TOL_MM3 for v in res.values())
        if ap_kind == "d2":
            blocked_d2 = not clear
        else:
            check(f"khẩu độ {ap_kind} + tấm che 'mo': tia 2 LED → tâm + 4 góc vùng nhạy, "
                  f"cửa sổ X {WINDOW_X_RANGE[0]}..{WINDOW_X_RANGE[1]}, d thật "
                  f"{[round(x, 1) for x in d_list()]}", clear, worst_mm3=max(res.values()))
    check("khẩu độ Ø2 chắn một phần tia lệch tâm → không dùng Ø2 với carrier 2 LED", blocked_d2)
    for k in MASK_KINDS:
        worst_c = 0.0
        for dr in d_list():
            for ch in ("red", "ir"):
                tip, dvec = tip_world(ch, dr)
                ray = ray_cylinder(tip + dvec * 0.3, (X_S, Y_S, Z_S), 0.15)
                worst_c = max(worst_c, overlap(ray, place(masks[k], dr)),
                              overlap(ray, place(carrier, dr)))
        check(f"tấm che {k}: tia chính hai LED → tâm OPT101 không bị chắn", worst_c < FIT_TOL_MM3,
              worst_mm3=worst_c)
    blank_blocks = True
    for dr in d_list():
        for ch in ("red", "ir"):
            tip, dvec = tip_world(ch, dr)
            if overlap(ray_cylinder(tip + dvec * 0.3, (X_S, Y_S, Z_S)),
                       aperture("blank", LANE)) < 1e-3:
                blank_blocks = False
    check("khẩu độ 'blank' chắn tia của cả hai LED", blank_blocks)
    return checks


# ============================================================================
# XUẤT FILE
# ============================================================================
REUSED = [
    ("01_than_hop_toi.stl", 1, "thân hộp chữ nhật v4 — dùng làn IR (+Z)"),
    ("02_nap_labyrinth.stl", 1, "nắp v4"),
    ("03_truc_truot_D.stl", 1, "ray D cho làn IR"),
    ("12_truc_day_tron_D5x130.stl", 1, "thanh đẩy làn IR"),
    ("05_num_thanh_truot.stl", 1, "núm làn IR"),
    ("08_khau_do_biet.stl", 1, "bịt làn Đỏ đang bỏ trống (thêm 1 tấm nếu muốn đo nền tối làn IR)"),
    ("11_khau_do_lo16mm.stl", 1, "khẩu độ làn IR (hoặc 10_khau_do_lo5mm; KHÔNG dùng Ø2)"),
    ("06_chup_luon_day_trai.stl", 2, "chụp cửa cáp vách −X, cả hai làn (giữ kín sáng)"),
    ("07_chup_luon_day_phai.stl", 2, "chụp cửa cáp vách +X, cả hai làn"),
    ("14_ga_chu_U_OPT101_70x20.stl", 1, "gá H board thu 70 × 20, chỉ cắm OPT101 ở U2/A0"),
]


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def export(carrier, masks, assembly, checks):
    stl_dir, print_dir = os.path.join(OUT, "stl"), os.path.join(OUT, "print_bambu_180")
    os.makedirs(stl_dir, exist_ok=True)
    os.makedirs(print_dir, exist_ok=True)
    for name, m in assembly.items():
        m.export(os.path.join(stl_dir, f"{name}.stl"))
    new_parts = {"25_carrier_2LED_TDM.stl": (carrier, "back_down", 1,
                                           "carrier Đỏ + IR, lỗ nghiêng; in dựng đứng, mặt sau áp bàn")}
    labels = {"mo": "IR Ø3 (không giảm)", "ir2": "IR Ø2", "ir1_5": "IR Ø1.5", "ir1": "IR Ø1"}
    for i, k in enumerate(MASK_KINDS):
        new_parts[f"{26 + i}_tam_che_{k}.stl"] = (masks[k], "lay_flat", 1,
                                                  f"tấm che: Đỏ Ø3, {labels[k]}; {i} khía trên tai")
    new_parts["30_mau_thu_lo_LED.stl"] = (
        build_fit_coupon(), "back_down", 1,
        f"mẫu thử lỗ đứng: thân Ø{coupon_body_d()[0]:g}–{coupon_body_d()[-1]:g}, "
        f"vành Ø{coupon_flange_d()[0]:g}–{coupon_flange_d()[-1]:g}, gờ chặn")
    manifest = {"bed_mm": BED, "printer": "Bambu Lab A1, nozzle 0.4, layer 0.2",
                "hole_shrink_assumed_mm": {"nominal": A1_HOLE_SHRINK_NOM, "max": A1_HOLE_SHRINK_MAX},
                "socket_h_mm_assumed": SOCKET_H, "led_pitch_mm": LED_PITCH,
                "bore_d_mm": BORE_D, "flange_bore_d_mm": FLANGE_BORE_D, "lip_d_mm": LIP_D,
                "led_tip_x_local_mm": round(stop_tip_x(False), 3),
                "toe_in_deg_each": round(math.degrees(TOE), 2), "converge_d_real_mm": D_CONV_REAL,
                "d_real_range_mm": [round(d_real_from_v4(x), 1) for x in D_RANGE_V4],
                "off_axis_deg": {f"{dr:.1f}": {ch: round(off_axis_deg(ch, dr), 2)
                                               for ch in ("red", "ir")} for dr in d_list()},
                "new_parts": [], "reused_parts": []}
    for fname, (mesh, mode, qty, desc) in new_parts.items():
        printed = orient_back_down(mesh) if mode == "back_down" else bs._orient_print(mesh, mode)
        path = os.path.join(print_dir, fname)
        printed.export(path)
        ext = [round(float(v), 2) for v in printed.extents]
        manifest["new_parts"].append(dict(file=fname, quantity=qty, description=desc,
                                          extents_xyz_mm=ext, sha256=sha256(path),
                                          fits_bed=bool(max(ext[:2]) <= BED - 2 * BED_MARGIN)))
    for fname, qty, desc in REUSED:
        src = os.path.join(V4_PRINT, fname)
        manifest["reused_parts"].append(dict(
            file=f"../../out/print_bambu_180/{fname}", quantity=qty, description=desc,
            sha256=sha256(src) if os.path.exists(src) else None))
    with open(os.path.join(print_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    report = dict(passed=sum(c["pass_"] for c in checks), total=len(checks),
                  tolerance_mm3=FIT_TOL_MM3, checks=checks,
                  scope="Hình học danh nghĩa trên CAD. Chưa in thử, chưa đo co ngót, "
                        "rò sáng, giản đồ phát LED hay công suất quang.")
    with open(os.path.join(OUT, "fit_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False,
                  default=lambda o: float(o) if isinstance(o, np.floating) else str(o))
    return manifest, report


def render_layout(carrier, masks, v4, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def draw(ax, mesh, color, lw=1.0, plane="y", value=Y_S):
        normal = [0, 1, 0] if plane == "y" else [1, 0, 0]
        origin = [0, value, 0] if plane == "y" else [value, 0, 0]
        for s in trimesh.intersections.mesh_plane(mesh, normal, origin):
            if plane == "y":
                ax.plot(s[:, 0], s[:, 2], color=color, lw=lw)
            else:
                ax.plot(s[:, 2], s[:, 1], color=color, lw=lw)

    dr = D_DEFAULT_REAL
    fig = plt.figure(figsize=(16, 10))
    ax0 = fig.add_subplot(2, 1, 1)
    draw(ax0, v4["body"], "#27303f")
    draw(ax0, place(carrier, dr), "#5d4037")
    draw(ax0, place(masks["mo"], dr), "#ef6c00")
    draw(ax0, v4["shaft"], "#78909c", 0.8, value=14.0)
    for ch, col in (("red", "#c62828"), ("ir", "#4527a0")):
        tip, _ = tip_world(ch, dr)
        ax0.plot([tip[0], X_S], [tip[2], Z_S], color=col, lw=0.8, ls="--")
    draw(ax0, aperture("d16", LANE), "#ef6c00")
    draw(ax0, aperture("blank", "red"), "#ef6c00")
    rp = receiver_parts()
    draw(ax0, rp["receiver_support"], "#2e7d32")
    draw(ax0, rp["receiver_pcb"], "#1b5e20")
    ax0.plot([X_S], [Z_S], "o", color="#00897b")
    ax0.annotate("OPT101 U2 → A0", (X_S, Z_S), xytext=(6, 8), textcoords="offset points",
                 fontsize=9, color="#00897b")
    ax0.annotate("làn Đỏ v4 bỏ trống — khẩu độ blank", (35, -19), fontsize=9, color="#555")
    ax0.set_title(f"Hộp v4, mặt cắt Y={Y_S:g}: carrier 2 LED trong làn IR, d thật {dr:g} mm")
    ax0.set_aspect("equal")
    ax0.grid(alpha=0.25)
    ax0.set_xlabel("X (mm)")
    ax0.set_ylabel("Z (mm)")

    ax1 = fig.add_subplot(2, 2, 3)
    draw(ax1, carrier, "#5d4037")
    draw(ax1, masks["ir1_5"], "#ef6c00")
    for ch, col in (("red", "#c62828"), ("ir", "#4527a0")):
        draw(ax1, led_models(ch), col, 0.9)
        tip, d = led_axis(ch)
        ax1.plot([tip[0], tip[0] + 12 * d[0]], [tip[2], tip[2] + 12 * d[2]], color=col, ls="--", lw=0.8)
    ax1.set_title(f"Carrier, cắt Y={Y_S:g}: IR (+Z) / Đỏ (−Z), tim {LED_PITCH:g} mm, "
                  f"nghiêng {math.degrees(TOE):.2f}°, tấm che IR Ø1.5", fontsize=10)
    ax1.set_aspect("equal")
    ax1.grid(alpha=0.25)
    ax1.set_xlabel("X cục bộ (mm)")
    ax1.set_ylabel("Z cục bộ (mm)")

    ax2 = fig.add_subplot(2, 2, 4)
    draw(ax2, carrier, "#5d4037", plane="x", value=-15.0)
    draw(ax2, carrier, "#8d6e63", 0.6, plane="x", value=0.2)
    draw(ax2, masks["ir1_5"], "#ef6c00", plane="x", value=(MASK_SLOT_X0 + MASK_SLOT_X1) / 2)
    ax2.set_title("Carrier nhìn từ trước: cắt X=−15 (lỗ D, thanh đẩy, khoang dây), "
                  "X=0.2 (mũi), tấm che", fontsize=10)
    ax2.set_aspect("equal")
    ax2.grid(alpha=0.25)
    ax2.set_xlabel("Z cục bộ (mm)")
    ax2.set_ylabel("Y (mm)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def render_bores(carrier, path):
    """Mặt cắt lỗ LED (ngang + nhìn từ trước) và mặt lỗ của mẫu thử."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def cut(ax, mesh, normal, origin, color, lw=1.0, front=False):
        for s in trimesh.intersections.mesh_plane(mesh, normal, origin):
            ax.plot(s[:, 2], s[:, 1], color=color, lw=lw) if front else \
                ax.plot(s[:, 0], s[:, 2], color=color, lw=lw)

    fig, ax = plt.subplots(1, 3, figsize=(17, 5.5))
    cut(ax[0], carrier, [0, 1, 0], [0, Y_S, 0], "#5d4037")
    for ch, col in (("red", "#c62828"), ("ir", "#4527a0")):
        cut(ax[0], led_models(ch), [0, 1, 0], [0, Y_S, 0], col, 0.9)
    ax[0].set_xlim(-bs.CAR_L - 2, FRONT_L + 2)
    ax[0].set_title("Cắt ngang Y=32: Đỏ (có vành) / IR (không vành) tì gờ trước", fontsize=10)
    x_body = (step_x() + lip_contact_x()) / 2
    cut(ax[1], carrier, [1, 0, 0], [x_body, 0, 0], "#5d4037", front=True)
    cut(ax[1], carrier, [1, 0, 0], [step_x() - 1.5, 0, 0], "#ef6c00", 0.8, front=True)
    ax[1].set_ylim(Y_S - 6, Y_S + 6)
    ax[1].set_title(f"Nhìn từ trước: lỗ thân Ø{BORE_D:g} (nâu), lỗ vành Ø{FLANGE_BORE_D:g} (cam)",
                    fontsize=10)
    cut(ax[2], build_fit_coupon(), [1, 0, 0], [COUPON_T / 2, 0, 0], "#37474f", front=True)
    cd, fd = coupon_body_d(), coupon_flange_d()
    ax[2].set_title(f"Mẫu thử 30: trên Ø{cd[0]:g}…{cd[-1]:g} (1…5 chấm); "
                    f"dưới Ø{fd[0]:g}/{fd[1]:g}/{fd[2]:g} + gờ", fontsize=10)
    for a in ax:
        a.set_aspect("equal")
        a.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    global BORE_D, FLANGE_BORE_D
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-checks", action="store_true", help="chỉ xuất STL, bỏ kiểm tra")
    ap.add_argument("--bore-d", type=float, default=BORE_D,
                    help="Ø lỗ thân LED trong CAD (chọn theo mẫu thử 30, mặc định %(default)s)")
    ap.add_argument("--flange-bore-d", type=float, default=FLANGE_BORE_D,
                    help="Ø lỗ vành LED Đỏ trong CAD (mặc định %(default)s)")
    args = ap.parse_args()
    if not 3.2 <= args.bore_d <= 4.2 or not args.bore_d < args.flange_bore_d <= 5.0:
        ap.error("cần 3.2 ≤ --bore-d ≤ 4.2 và --bore-d < --flange-bore-d ≤ 5.0")
    BORE_D, FLANGE_BORE_D = args.bore_d, args.flange_bore_d

    print("Building dual-LED carrier + v4 references ...")
    carrier = build_dual_carrier()
    masks = {k: build_mask(k) for k in MASK_KINDS}
    shaft = bs.build_shaft()
    shaft.apply_translation([0.0, 0.0, Z_S])
    v4 = {"body": bs.build_body(), "lid": bs.build_lid(), "shaft": shaft}
    checks = [] if args.no_checks else run_checks(carrier, masks, v4)
    rod, knob = place_rod_knob(D_DEFAULT_REAL)
    assembly = {"tdm_carrier_2led": place(carrier, D_DEFAULT_REAL),
                "tdm_mask_mo": place(masks["mo"], D_DEFAULT_REAL),
                "ref_led_red": place(led_models("red"), D_DEFAULT_REAL),
                "ref_led_ir": place(led_models("ir"), D_DEFAULT_REAL),
                "ref_push_rod": rod, "ref_knob": knob, "ref_shaft_ir_lane": shaft}
    manifest, report = export(carrier, masks, assembly, checks)
    render_layout(carrier, masks, v4, os.path.join(OUT, "tdm_layout.png"))
    render_bores(carrier, os.path.join(OUT, "carrier_bores.png"))

    for p in manifest["new_parts"]:
        print(f"  {p['file']:<28} x{p['quantity']}  {p['extents_xyz_mm']}  "
              f"{'fits' if p['fits_bed'] else 'DOES NOT FIT'} {BED:g} mm bed")
    print("  off-axis (deg):", manifest["off_axis_deg"])
    if checks:
        print(f"Checks: {report['passed']}/{report['total']} pass")
        for c in checks:
            if not c["pass_"]:
                print("  FAIL:", c["label"], {k: v for k, v in c.items() if k not in ("label", "pass_")})
    return 0 if all(c["pass_"] for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
