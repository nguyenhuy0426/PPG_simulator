#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_pcb_mount_plate.py — gộp 3 gá PCB thành MỘT file in.

  14_ga_chu_U_OPT101_70x20.stl   gá H board OPT101 (không vít)
  15_ga_chu_U_BPW34_70x20.stl    gá H board BPW34  (không vít)
  16_ga_driver_70x40.stl         gá driver (không vít)
  18_nut_nhua_driver.stl         nút nhựa thẳng thay vít: 4 cái

Mỗi chi tiết giữ nguyên tư thế in của nó; chỉ tịnh tiến trong mặt bàn, cách
nhau PLATE_GAP. Đọc 14/15/16 từ out/print_bambu_180, ghi
out/print_bambu_180/17_ga_pcb_OPT101_BPW34_driver.stl và manifest riêng.

Chạy từ gốc repo:  .cad_venv/bin/python docs/system_3d/build_pcb_mount_plate.py
"""
import hashlib
import json
import os
import sys

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
PRINT = os.path.join(HERE, "out", "print_bambu_180")
OUT_NAME = "17_ga_pcb_OPT101_BPW34_driver.stl"
BUTTON_FILE, BUTTONS_USED, BUTTONS_SPARE = "18_nut_nhua_driver.stl", 4, 0
BUTTON_PITCH = 4.0                     # khoảng cách giữa các nút (đầu Ø6 -> 4 mm giữa hai đầu)
PLATE_GAP = 6.0
BED, BED_MARGIN = 180.0, 8.0
PARTS = [("driver", "16_ga_driver_70x40.stl"),
         ("opt101", "14_ga_chu_U_OPT101_70x20.stl"),
         ("bpw34", "15_ga_chu_U_BPW34_70x20.stl")]


def body_count(mesh):
    """Số khối liên thông theo cạnh chung (BFS; CAD venv không có scipy)."""
    nb = {i: set() for i in range(len(mesh.faces))}
    for a, b in mesh.face_adjacency:
        nb[a].add(b)
        nb[b].add(a)
    todo_all, n = set(nb), 0
    while todo_all:
        todo = [todo_all.pop()]
        n += 1
        while todo:
            fresh = nb[todo.pop()] & todo_all
            todo_all -= fresh
            todo.extend(fresh)
    return n


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    meshes, placed = [], []
    x_next = y_next = y_buttons = 0.0
    for name, fname in PARTS:
        m = trimesh.load(os.path.join(PRINT, fname))
        assert m.is_watertight, f"{fname} không kín"
        lo = m.bounds[0]
        if name == "driver":
            x0, y0 = 0.0, 0.0
            x_next, y_next = m.extents[0] + PLATE_GAP, 0.0
            y_buttons = m.extents[1] + PLATE_GAP
        else:                                          # hai gá H xếp thành cột bên phải
            x0, y0 = x_next, y_next
            y_next += m.extents[1] + PLATE_GAP
        m = m.copy()
        m.apply_translation([x0 - lo[0], y0 - lo[1], -lo[2]])
        meshes.append(m)
        placed.append(dict(part=name, source=fname, origin_xy_mm=[round(x0, 2), round(y0, 2)],
                           extents_xyz_mm=[round(float(v), 2) for v in m.extents],
                           volume_mm3=round(float(m.volume), 1)))
    btn = trimesh.load(os.path.join(PRINT, BUTTON_FILE))
    assert btn.is_watertight, f"{BUTTON_FILE} không kín"
    for i in range(BUTTONS_USED + BUTTONS_SPARE):      # một hàng nút dưới gá driver
        m = btn.copy()
        x0 = i * (btn.extents[0] + BUTTON_PITCH)
        m.apply_translation([x0 - m.bounds[0][0], y_buttons - m.bounds[0][1], -m.bounds[0][2]])
        meshes.append(m)
        placed.append(dict(part="button_" + ("spare_" if i >= BUTTONS_USED else "") + str(i + 1),
                           source=BUTTON_FILE, origin_xy_mm=[round(x0, 2), round(y_buttons, 2)],
                           extents_xyz_mm=[round(float(v), 2) for v in m.extents],
                           volume_mm3=round(float(m.volume), 1)))
    plate = trimesh.util.concatenate(meshes)
    path = os.path.join(PRINT, OUT_NAME)
    plate.export(path)

    gap = min(np.linalg.norm(np.maximum(0, np.maximum(a.bounds[0] - b.bounds[1], b.bounds[0] - a.bounds[1])))
              for i, a in enumerate(meshes) for b in meshes[i + 1:])
    ext = plate.extents
    checks = [
        ("kín (watertight)", bool(plate.is_watertight)),
        (f"đúng {len(meshes)} khối rời (3 gá + {BUTTONS_USED} nút)",
         bool(body_count(plate) == len(meshes))),
        (f"các khối cách nhau ≥ {BUTTON_PITCH - 1e-6:g} mm (gá H và gá driver cách 6 mm)",
         bool(gap >= BUTTON_PITCH - 1e-6)),
        ("chạm bàn đúng z = 0", bool(abs(float(plate.bounds[0][2])) < 1e-9)),
        (f"nằm trong bàn {BED:g} mm, lề {BED_MARGIN:g} mm",
         bool(max(ext[0], ext[1]) <= BED - 2 * BED_MARGIN)),
    ]
    manifest = dict(file=OUT_NAME, extents_xyz_mm=[round(float(v), 2) for v in ext],
                    total_volume_mm3=round(float(plate.volume), 1), sha256=sha256(path),
                    parts=placed, checks=[dict(label=l, ok=ok) for l, ok in checks],
                    note="Chưa in thử. Gá H cần thử lắp trượt vào hộp thật; nút bấm của gá driver "
                         "chưa thử cài vào PCB thật.")
    with open(os.path.join(PRINT, "17_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"{OUT_NAME}: {manifest['extents_xyz_mm']} mm, {manifest['total_volume_mm3']} mm3")
    for l, ok in checks:
        print(("  PASS " if ok else "  FAIL ") + l)
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
