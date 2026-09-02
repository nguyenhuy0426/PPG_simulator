#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify PPG simulator v3 STL output (thanh trượt đẩy-kéo Ø5 + chụp 4 trụ cắm
+ chân đỡ màn hình 7").

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
    "rod_knob_red.stl", "frame.stl", "aperture_red_blank.stl",
    "aperture_red_d2.stl", "aperture_red_d5.stl", "aperture_red_d16.stl",
    "hood_l_red.stl", "hood_r_red.stl", "base_neg.stl", "base_pos.stl",
    "screen_foot_1.stl",
}
BAMBU_FILES = {
    "00_ppg_hop_toi_A1_all_in_one.stl", "01_than_hop_toi.stl",
    "02_nap_labyrinth.stl", "03_truc_truot_D.stl", "04_carrier_led.stl",
    "05_num_thanh_truot.stl", "06_chup_luon_day_trai.stl",
    "07_chup_luon_day_phai.stl", "08_khau_do_biet.stl",
    "09_khau_do_lo2mm.stl", "10_khau_do_lo5mm.stl", "11_khau_do_lo16mm.stl",
}

# --- toạ độ tham chiếu (khớp hằng số trong build_system.py) -------------------
Z_RED, Z_IR = -19.25, 19.25            # tâm 2 làn quang
ROD_Y = 24.0                           # tâm thanh trượt Ø5
PEG_Z = 14.5                           # trụ cắm chụp: ±14.5 quanh tâm làn
PEG_YS = (5.0, 13.5)

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
check("exact file set (15 STL)", present == EXPECTED_FILES,
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

# Nắp là TẤM ĐẶC 3 mm (không còn ray/chặn/vạch chia của cần trượt nam châm):
# y = 56 (vấu chặn) .. 67 (mặt trên) — đỉnh cũ 68.4 của ray đã biến mất.
lid = m["lid"]
lb = lid.bounds
check("lid bounds y = 56..67 (tấm đặc, không còn ray cao 68.4)",
      abs(lb[0][1] - 56.0) < 0.1 and abs(lb[1][1] - 67.0) < 0.1,
      f"(y = {lb[0][1]:.2f}..{lb[1][1]:.2f})")
# Thân mọc thêm bệ thanh trượt về -X (tới -18) và bệ nhô 2 mm ở cả 2 vách.
bb = m["body"].bounds
check("body bounds x = -18..152 (bệ thanh trượt -X + 2 bệ nhô 2 mm)",
      abs(bb[0][0] + 18.0) < 0.05 and abs(bb[1][0] - 152.0) < 0.05,
      f"(x = {bb[0][0]:.2f}..{bb[1][0]:.2f})")

# ============================================== 3. chụp che sáng — 4 trụ cắm
print("=== 3. Hood 4-peg joint + mộng kín sáng (ray-cast) ===")
# trụ cắm đặc (thân trụ nằm ở x = 2.0 phía chụp trái / x = 148 phía chụp phải)
expect(m["hood_l_red"], (2.0, PEG_YS[0], Z_RED - PEG_Z), True, "hood_l peg (y=5, z=-33.75) solid")
expect(m["hood_l_red"], (2.0, PEG_YS[1], Z_RED + PEG_Z), True, "hood_l peg (y=13.5, z=-4.75) solid")
expect(m["hood_r_red"], (148.0, PEG_YS[0], Z_RED - PEG_Z), True, "hood_r peg (y=5, z=-33.75) solid")
expect(m["hood_r_red"], (148.0, PEG_YS[1], Z_RED + PEG_Z), True, "hood_r peg (y=13.5, z=-4.75) solid")
# giữa 2 trụ không có vật liệu (bích chụp chỉ tới x = -2 / 152)
expect(m["hood_l_red"], (2.0, 9.25, Z_RED), False, "hood_l giữa 2 trụ rỗng")
expect(m["hood_r_red"], (148.0, 9.25, Z_RED), False, "hood_r giữa 2 trụ rỗng")
# 4 lỗ mù Ø4.30 trên thân nhận trụ cắm — phải THÔNG tại x = 2.0
for yp in PEG_YS:
    for dz in (-PEG_Z, PEG_Z):
        expect(m["body"], (2.0, yp, Z_RED + dz), False,
               f"body lỗ trụ cắm (y={yp}, z={Z_RED + dz:.2f}) mở")
# trụ đứng đỡ đáy lỗ (x = 3..8) phải ĐẶC ngay sau đáy lỗ (đáy lỗ ở x = 5.5)
expect(m["body"], (6.5, 9.0, Z_RED - PEG_Z), True, "body trụ đứng sau đáy lỗ đặc")
# mộng âm-dương kín sáng: gân trên chụp <-> rãnh trên thân, cùng một điểm
expect(m["hood_l_red"], (-1.2, 3.4, Z_RED), True, "hood_l gân kín sáng đặc")
expect(m["body"], (-1.2, 3.4, Z_RED), False, "body rãnh kín sáng mở (nhận gân)")
# lỗ ra cáp 8 x 20 xuyên vách
expect(m["body"], (1.5, 9.5, Z_RED), False, "body lỗ ra cáp mở")

# ================================================================ 4. carrier
print("=== 4. led_carrier_red (dẫn động bằng thanh trượt) ===")
ymax = m["led_carrier_red"].bounds[1][1]
check("carrier max y = 40.0 (không còn tháp nam châm)", abs(ymax - 40.0) < 0.15,
      f"(max y = {ymax:.2f})")
expect(m["led_carrier_red"], (80.0, ROD_Y, Z_RED), False, "lỗ mù nhận thanh Ø5 mở")
expect(m["led_carrier_red"], (91.0, ROD_Y, Z_RED), True,
       "7 mm vật liệu đặc trước lỗ (không xuyên sáng)")
expect(m["led_carrier_red"], (83.0, 14.0, Z_RED), False, "lỗ D ôm trục mở")
expect(m["led_carrier_red"], (82.0, 38.0, Z_RED), True, "thân carrier đặc")

# ====================================== 5. bệ + lỗ thanh trượt + núm cầm
print("=== 5. Thanh trượt Ø5: bệ dẫn hướng, lỗ Ø5.4, núm cầm ===")
expect(m["body"], (-16.0, ROD_Y, Z_RED), False, "lỗ thanh trượt (làn đỏ) mở ngoài bệ")
expect(m["body"], (-16.0, ROD_Y, Z_IR), False, "lỗ thanh trượt (làn IR) mở ngoài bệ")
expect(m["body"], (1.5, ROD_Y, Z_RED), False, "lỗ thanh trượt xuyên hết vách")
expect(m["body"], (-10.0, ROD_Y + 3.5, Z_RED), True, "vách bệ phía trên lỗ đặc")
expect(m["body"], (-10.0, ROD_Y, Z_RED + 4.0), True, "vách bệ hai bên lỗ đặc")
expect(m["body"], (-10.0, 17.5, Z_RED), False, "dưới đỉnh nhọn 18.8 là không khí")
expect(m["body"], (-19.5, ROD_Y, Z_RED), False, "ngoài đầu bệ (x=-19.5) là không khí")
kb = m["rod_knob_red"].bounds
check("knob bounds x -45..-37, Ø16 quanh (y=24, z=-19.25)",
      abs(kb[0][0] + 45.0) < 0.05 and abs(kb[1][0] + 37.0) < 0.05
      and abs(kb[1][2] - (Z_RED + 8.0)) < 0.05,
      f"(lo={tuple(round(float(x), 2) for x in kb[0])}, "
      f"hi={tuple(round(float(x), 2) for x in kb[1])})")
expect(m["rod_knob_red"], (-39.0, ROD_Y, Z_RED), False, "lỗ mù Ø5.1 trong núm mở")
expect(m["rod_knob_red"], (-44.0, ROD_Y, Z_RED), True, "đáy lỗ mù (2 mm) đặc")
expect(m["rod_knob_red"], (-41.0, 28.0, Z_RED), False, "lỗ vít chặn M3 trong núm mở")
expect(m["rod_knob_red"], (-41.0, 31.5, Z_RED), False, "rãnh cầm tay trên vành núm")

# ================================================================ 6. lid
print("=== 6. lid (tấm đặc: hết ray / chặn / vạch chia) ===")
expect(lid, (86.0, 65.5, Z_RED), True, "cửa sổ cũ làn đỏ đã đặc")
expect(lid, (86.0, 65.5, Z_IR), True, "cửa sổ cũ làn IR đã đặc")
expect(lid, (50.0, 65.5, Z_RED), True, "rãnh cần trượt cũ nay đặc")
expect(lid, (8.5, 65.5, Z_RED), True, "vấu chặn trước cũ nay là tấm đặc")
expect(lid, (100.5, 65.5, Z_RED), True, "vấu chặn sau cũ nay là tấm đặc")
expect(lid, (82.0, 65.5, -30.0), True, "vạch chia d=25 cũ đã biến mất")
expect(lid, (22.0, 65.5, 30.0), True, "vạch chia d=85 cũ đã biến mất")

# ================================================================ 7. body
print("=== 7. body (hết lỗ mồi vít M3, khe khẩu độ, máng dây) ===")
expect(m["body"], (1.0, 10.5, -2.75), True, "lỗ mồi vít chụp cũ (-X) đã bịt")
expect(m["body"], (149.0, 10.5, 2.75), True, "lỗ mồi vít chụp cũ (+X) đã bịt")
expect(m["body"], (114.2, 30.0, Z_RED), False, "khe khẩu độ làn đỏ mở")
expect(m["body"], (114.2, 30.0, Z_IR), False, "khe khẩu độ làn IR mở")
expect(m["body"], (50.0, 2.5, -33.0), False, "máng dây LED mở (x=50)")
expect(m["body"], (5.0, 2.5, -33.0), True, "sàn đặc trước máng (x=5, dưới trụ đứng)")

# ================================================================ 8. base
print("=== 8. base (mộng ghép + bệ bắt chân màn hình + lưới lỗ mở rộng) ===")
expect(m["base_neg"], (43.0, -2.0, -6.0), True, "base_neg vị trí vít nối cũ đặc")
expect(m["base_neg"], (111.0, -2.0, -6.0), True, "base_neg vị trí vít nối cũ #2 đặc")
expect(m["base_neg"], (43.0, -2.0, 4.0), True, "base_neg mộng dương x=43 đặc")
expect(m["base_neg"], (111.0, -2.0, 4.0), True, "base_neg mộng dương x=111 đặc")
expect(m["base_pos"], (43.0, -2.0, 4.0), False, "base_pos mộng âm x=43 mở")
expect(m["base_pos"], (111.0, -2.0, 4.0), False, "base_pos mộng âm x=111 mở")
expect(m["base_pos"], (77.0, -2.0, 4.0), False, "base_pos mộng âm x=77 mở")
# chân màn hình đã chuyển sang NỬA TRƯỚC (base_neg, z = -186 / -139)
expect(m["base_neg"], (23.0, -7.0, -186.0), True, "bệ vít chân màn hình (x=20,z=-186) đặc")
expect(m["base_neg"], (20.0, -7.0, -186.0), False, "lỗ vít M3 chân màn hình #1 mở")
expect(m["base_neg"], (130.0, -7.0, -139.0), False, "lỗ vít M3 chân màn hình #4 mở")
expect(m["base_pos"], (30.0, -2.0, 62.0), False, "lưới lỗ M3 mở rộng (30, 62) mở")
expect(m["base_pos"], (120.0, -2.0, 80.0), False, "lưới lỗ M3 mở rộng (120, 80) mở")
expect(m["base_pos"], (52.0, -2.0, 71.0), True, "đế đặc giữa 4 lỗ mở rộng")

# --- thứ tự TRƯỚC -> SAU: màn hình (z<=-136) | Pi 4 + driver (-112..-52) | hộp tối
sfb = m["screen_foot_1"].bounds
check("chân màn hình nằm hẳn phía TRƯỚC cụm điện tử (z <= -130)",
      float(sfb[1][2]) <= -130.0,
      f"(mép sau chân z = {float(sfb[1][2]):.1f}, mép trước board driver z = -112)")
bnb = m["base_neg"].bounds
check("đế nửa trước phủ hết chân màn hình (z <= -196)",
      float(bnb[0][2]) <= -195.9 and float(sfb[0][2]) >= float(bnb[0][2]),
      f"(đế z0 = {float(bnb[0][2]):.1f}, chân z0 = {float(sfb[0][2]):.1f})")

# ================================================================ 9. pairs
print("=== 9. Pairwise intersection volumes ~ 0 ===")
PAIRS = [
    ("body", "lid"), ("body", "led_carrier_red"), ("body", "slide_shaft_red"),
    ("led_carrier_red", "slide_shaft_red"), ("base_neg", "screen_foot_1"),
    ("base_pos", "screen_foot_1"),
    ("body", "hood_l_red"), ("body", "hood_r_red"),
    ("base_neg", "base_pos"), ("body", "base_neg"), ("body", "base_pos"),
    ("body", "aperture_red_blank"), ("led_carrier_red", "lid"),
    ("body", "screen_foot_1"),      # chân màn hình ở z <= -136, hộp tối ở z >= -40
]
for a, bna in PAIRS:
    try:
        inter = trimesh.boolean.intersection([m[a], m[bna]])
        vol = 0.0 if inter is None or len(inter.faces) == 0 else abs(inter.volume)
    except Exception:
        vol = float("nan")
    check(f"{a} × {bna}", vol < 1e-4, f"(V={vol:.2e} mm³)")

# ================================================================ 10. bambu
print("=== 10. Bambu package ===")
bpresent = set(os.listdir(BAMBU))
check("bambu file set (12 file)", bpresent == BAMBU_FILES,
      f"({len(bpresent)} files; extra={sorted(bpresent - BAMBU_FILES)}, "
      f"missing={sorted(BAMBU_FILES - bpresent)})")
kn = trimesh.load(os.path.join(BAMBU, "05_num_thanh_truot.stl"))
kbb = kn.bounds
h = kbb[1][2] - kbb[0][2]
check("bambu núm cao ~8.0 (mặt đáy phẳng úp xuống bàn)", abs(h - 8.0) < 0.05,
      f"(h={h:.2f})")
cx = float((kbb[0][0] + kbb[1][0]) / 2)
cy = float((kbb[0][1] + kbb[1][1]) / 2)
expect(kn, (cx, cy, 5.0), False, "bambu núm: lỗ mù quay LÊN (rỗng phía trên)")
expect(kn, (cx, cy, 0.5), True, "bambu núm: đáy đặc (2 mm)")
combo = trimesh.load(os.path.join(BAMBU, "00_ppg_hop_toi_A1_all_in_one.stl"))
cb = combo.bounds
check("all-in-one nằm trong bàn 256 x 256 mm",
      cb[0][0] >= -1e-6 and cb[0][1] >= -1e-6
      and cb[1][0] <= 256.0 and cb[1][1] <= 256.0,
      f"({cb[1][0] - cb[0][0]:.1f} x {cb[1][1] - cb[0][1]:.1f} mm, "
      f"gốc ({cb[0][0]:.1f}, {cb[0][1]:.1f}))")

# ================================================================ summary
print("=" * 70)
if fails:
    print(f"RESULT: {len(fails)} CHECK(S) FAILED out of {npass + len(fails)}")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print(f"RESULT: ALL {npass} CHECKS PASSED")
