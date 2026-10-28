#!/usr/bin/env python3
"""70x40 driver adapter for the existing 70x55 base mounting pattern.

Print coordinates X,Y are the old board coordinates; Z points upward.
The adapter rests on the existing 5 mm base standoffs. New PCB local (x,y)
maps to adapter (x,y+7), with its underside at adapter Z=6 mm.
"""
import json
from pathlib import Path
import numpy as np
import trimesh

HERE=Path(__file__).resolve().parent
def box(x0,x1,y0,y1,z0,z1):
    m=trimesh.creation.box(extents=(x1-x0,y1-y0,z1-z0))
    m.apply_translation(((x0+x1)/2,(y0+y1)/2,(z0+z1)/2)); return m
def cylinder(x,y,z0,z1,r):
    m=trimesh.creation.cylinder(radius=r,height=z1-z0,sections=64)
    m.apply_translation((x,y,(z0+z1)/2)); return m
def diff(a,others): return trimesh.boolean.difference([a,*others],engine='manifold')
def intersection(a,b):
    return abs(trimesh.boolean.intersection([a,b],engine='manifold').volume)

def bodies(mesh):
    adj={i:set() for i in range(len(mesh.faces))}
    for a,b in mesh.face_adjacency: adj[a].add(b); adj[b].add(a)
    remaining=set(adj); count=0
    while remaining:
        todo=[remaining.pop()]; count+=1
        while todo:
            fresh=adj[todo.pop()] & remaining; remaining-=fresh; todo.extend(fresh)
    return count

# --- Gá driver KHÔNG VÍT: 4 nút nhựa thẳng, ép ma sát ---------------------------
# PCB nằm trên 4 ống đỡ Ø6. Mỗi lỗ PCB Ø3.2 có một NÚT NHỰA RỜI THẲNG (không khấc,
# không gờ bấm): đầu Ø5.6 ép lên mặt PCB, thân hơi thon (đầu to, chóp nhỏ) đi qua
# PCB, ống đỡ và tấm gá; giữ bằng ma sát trong lỗ ống Ø2.9 (in ra nhỏ hơn). Giữ
# bằng ma sát nên PHỤ THUỘC độ hụt lỗ in của máy, chưa kiểm chứng bằng bản in.
# Adapter in nằm (mặt tấm áp bàn); nút in dựng, đầu áp bàn, không support.
# 4 lỗ góc của tấm trùng 4 lỗ Raspberry Pi HAT (58 x 49 mm) để xếp trụ đồng M2.5
# lên Grove Base Hat. Nguồn: file Eagle chính thức của Seeed (Raspberry Pi Grove
# Base HAT v1.0.brd): board 65 x 56 mm, 4 lỗ Ø2.75 tại (3.5;3.5), (3.5;52.5),
# (61.5;3.5), (61.5;52.5) = bước 58 x 49. Chưa đo trên Hat thật.
A1_HOLE_SHRINK_NOM, A1_HOLE_SHRINK_MAX = 0.2, 0.4   # [ASSUME] lỗ đứng in hụt Ø trên Bambu A1
PLATE_T = 1.6                 # dày tấm (8 lớp 0.2); bản vít cũ dày 2.0
PCB_Z0, PCB_T = 6.0, 1.6      # mặt dưới PCB trên gá, dày PCB
TUBE_R = 3.0                  # ống đỡ Ø6
HOLE_D = 2.9                  # lỗ ống + tấm cho nút; in ra 2.5..2.9
PCB_HOLE_R = 1.6              # lỗ PCB Ø3.2
PIN_D_HEAD, PIN_D_TIP = 3.05, 2.45     # thân nút thon: Ø3.05 sát đầu, Ø2.45 ở chóp
HEAD_R, HEAD_T = 2.8, 1.0     # đầu nút Ø5.6 x 1.0
SHAFT_L = PCB_T + PCB_Z0      # 7.6: PCB + ống + tấm; chóp cách mặt dưới tấm 0.0
TIP_CHAMFER = 0.4
BAR_W = 6.0                   # thanh ngang giữa hai thanh bên (bản cũ 8)
WIN_X, WIN_Y = (8.0, 62.0), (BAR_W, 55.0 - BAR_W)
HAT_PITCH = (58.0, 49.0)      # bước lỗ Raspberry Pi HAT
HAT_HOLE_D = 3.2              # lỗ gá cho trụ/ren M2.5 (in ra 2.8..3.0); lỗ HAT thật Ø2.75
BUTTON_COUNT = 4
SRC_PCB = HERE.parent / 'led_ir_driver.kicad_pcb'
HEAD_MARGIN = 0.3             # đầu nút phải cách vùng courtyard linh kiện >= 0.3 mm


def hat_holes():
    cx, cy = 35.0, 27.5
    return [(cx + sx * HAT_PITCH[0] / 2, cy + sy * HAT_PITCH[1] / 2) for sx in (-1, 1) for sy in (-1, 1)]


def nearest_component_mm():
    """Khoảng cách nhỏ nhất từ tâm 4 lỗ PCB tới pad / courtyard của linh kiện (tọa độ PCB local)."""
    import re
    import math
    txt = SRC_PCB.read_text()
    ox, oy = 100.0, 100.0                          # lỗ local (4,24) <-> KiCad (104,124)
    holes = [(4, 24), (66, 24), (4, 36), (66, 36)]

    def rot(x, y, deg):
        t = math.radians(deg)
        return x * math.cos(t) + y * math.sin(t), -x * math.sin(t) + y * math.cos(t)

    pts = []
    for blk in re.split(r'\n\t\(footprint ', txt)[1:]:
        if blk.startswith('"TX:Hole"'):
            continue
        at = re.search(r'\n\t\t\(at ([\-\d\.]+) ([\-\d\.]+)(?: ([\-\d\.]+))?\)', blk)
        fx, fy, fr = float(at.group(1)), float(at.group(2)), float(at.group(3) or 0)

        def loc(px, py):
            rx, ry = rot(px, py, fr)
            return fx + rx - ox, fy + ry - oy
        for m in re.finditer(r'\(pad "[^"]*"\s+\w+\s+\w+\s*\(at ([\-\d\.]+) ([\-\d\.]+)(?: ([\-\d\.]+))?\)\s*\(size ([\-\d\.]+) ([\-\d\.]+)\)', blk):
            px, py, pr = float(m.group(1)), float(m.group(2)), float(m.group(3) or 0)
            w, h = float(m.group(4)), float(m.group(5))
            kind = [loc(px + qx, py + qy) for qx, qy in
                    (rot(dx, dy, pr - fr) for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)))]
            pts.append(('pad', kind))
        for m in re.finditer(r'\(fp_(?:line|rect)\s*\(start ([\-\d\.]+) ([\-\d\.]+)\)\s*\(end ([\-\d\.]+) ([\-\d\.]+)\)(.*?)\(layer "([^"]+)"\)', blk, re.S):
            if 'CrtYd' in m.group(6):
                pts.append(('courtyard', [loc(float(m.group(1)), float(m.group(2))), loc(float(m.group(3)), float(m.group(4)))]))

    def d(h, poly):
        xs, ys = [q[0] for q in poly], [q[1] for q in poly]
        return math.hypot(max(min(xs) - h[0], 0, h[0] - max(xs)), max(min(ys) - h[1], 0, h[1] - max(ys)))
    out = {}
    for kind in ('pad', 'courtyard'):
        out[kind] = round(min(d(h, poly) for h in holes for k, poly in pts if k == kind), 2)
    return out


def build_driver_adapter():
    frame = diff(box(0, 70, 0, 55, 0, PLATE_T), [box(WIN_X[0], WIN_X[1], WIN_Y[0], WIN_Y[1], -1, PLATE_T + 1)])
    mounts = [(4, 31), (66, 31), (4, 43), (66, 43)]
    parts = [frame] + [cylinder(x, y, PLATE_T - 0.2, PCB_Z0, TUBE_R) for x, y in mounts]
    frame = trimesh.boolean.union(parts, engine='manifold')
    cuts = [cylinder(x, y, -.1, PCB_Z0 + .1, HOLE_D / 2) for x, y in mounts]         # lỗ cho nút
    cuts += [cylinder(x, y, -.1, PLATE_T + .1, HAT_HOLE_D / 2) for x, y in hat_holes()]  # 4 lỗ HAT
    return diff(frame, cuts), mounts


def build_button():
    """Nút nhựa thẳng ở tư thế in: đầu áp bàn (z=0), thân thon hướng lên, chóp ở trên."""
    r1, r0 = PIN_D_HEAD / 2, PIN_D_TIP / 2
    prof = np.array([[0, 0], [HEAD_R, 0], [HEAD_R, HEAD_T], [r1, HEAD_T],
                     [r0 + 0.0, HEAD_T + SHAFT_L - TIP_CHAMFER], [r0 - TIP_CHAMFER * 0.5, HEAD_T + SHAFT_L], [0, HEAD_T + SHAFT_L]])
    return trimesh.creation.revolve(prof, sections=96)


def button_in_assembly(button, x, y):
    """Nút đã cắm: đầu nằm trên mặt PCB (z = PCB_Z0 + PCB_T), lật 180° quanh trục X."""
    m = button.copy()
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))
    m.apply_translation((x, y, PCB_Z0 + PCB_T + HEAD_T))
    return m


def main():
    frame, mounts = build_driver_adapter()
    button = build_button()
    old_volume = 3946.9                              # bản 4 vít, dày 2.0, thanh ngang 8
    frame.export(HERE/'driver_70x40_adapter_print.stl')
    button.export(HERE/'driver_snap_button_print.stl')
    import shutil
    out180 = HERE.parents[2]/'docs/system_3d/out/print_bambu_180'
    shutil.copy2(HERE/'driver_70x40_adapter_print.stl', out180/'16_ga_driver_70x40.stl')
    shutil.copy2(HERE/'driver_snap_button_print.stl', out180/'18_nut_nhua_driver.stl')
    pcb = diff(box(0, 70, 7, 47, PCB_Z0, PCB_Z0 + PCB_T), [cylinder(x, y, PCB_Z0 - .1, PCB_Z0 + PCB_T + .1, PCB_HOLE_R) for x, y in mounts])
    pcb.export(HERE/'driver_70x40_pcb_assembly.stl')
    solder = box(8, 62, 10, 45, 4, 6)                 # chân hàn <= 2 mm trên mặt tấm
    placed = [button_in_assembly(button, x, y) for x, y in mounts]
    comp = nearest_component_mm()
    # ép ma sát: độ chặt (đường kính thân tại mặt trên ống) trừ đường kính lỗ in ra
    d_at_tube_top = PIN_D_HEAD - (PIN_D_HEAD - PIN_D_TIP) * PCB_T / SHAFT_L
    interference = {f'shrink_{sh:g}': round((d_at_tube_top - (HOLE_D - sh)) / 2, 3)
                    for sh in (0.0, A1_HOLE_SHRINK_NOM, A1_HOLE_SHRINK_MAX)}
    taper_len = lambda sh: max(0.0, min(SHAFT_L - PCB_T, (PIN_D_HEAD - (HOLE_D - sh)) / (PIN_D_HEAD - PIN_D_TIP) * SHAFT_L - PCB_T))
    grip_len = {f'shrink_{sh:g}': round(taper_len(sh), 2) for sh in (0.0, A1_HOLE_SHRINK_NOM, A1_HOLE_SHRINK_MAX)}
    hat = hat_holes()
    pcb_x = (0, 70); pcb_y = (7, 47)
    hat_clear = min(max(pcb_x[0] - x, x - pcb_x[1], pcb_y[0] - y, y - pcb_y[1]) for x, y in hat)
    checks = {'adapter_watertight': bool(frame.is_watertight), 'adapter_single_body': bodies(frame) == 1,
              'button_watertight': bool(button.is_watertight), 'button_single_body': bodies(button) == 1,
              'buttons_needed': BUTTON_COUNT,
              'pcb_interference_mm3': intersection(frame, pcb), 'solder_interference_mm3': intersection(frame, solder),
              'button_vs_adapter_press_fit_mm3': round(max(intersection(frame, b) for b in placed), 3),
              'button_vs_pcb_mm3': max(intersection(pcb, b) for b in placed),
              'button_head_radius_mm': HEAD_R,
              'nearest_pad_to_hole_centre_mm': comp['pad'], 'nearest_courtyard_to_hole_centre_mm': comp['courtyard'],
              'head_clearance_to_courtyard_mm': round(comp['courtyard'] - HEAD_R, 2),
              'head_clearance_to_pad_mm': round(comp['pad'] - HEAD_R, 2),
              'pin_clearance_in_pcb_hole_per_side_mm': round(PCB_HOLE_R - PIN_D_HEAD / 2, 3),
              'friction_interference_per_side_mm_at_tube_top': interference,
              'friction_grip_length_in_tube_mm': grip_len,
              'tube_wall_mm': round(TUBE_R - (HOLE_D - A1_HOLE_SHRINK_MAX) / 2, 2),
              'hat_holes_mm': [(round(x, 1), round(y, 1)) for x, y in hat], 'hat_pitch_mm': list(HAT_PITCH),
              'hat_source': 'Seeed Eagle v1.0: board 65x56 mm, holes d=2.75 mm at (3.5,3.5),(3.5,52.5),(61.5,3.5),(61.5,52.5)',
              'hat_holes_clear_of_pcb_mm': round(hat_clear, 2),
              'adapter_volume_mm3': round(float(frame.volume), 1), 'button_volume_mm3': round(float(button.volume), 1),
              'adapter_saving_vs_screw_version_pct': round(100 * (1 - frame.volume / old_volume), 1)}
    assert checks['adapter_watertight'] and checks['adapter_single_body']
    assert checks['button_watertight'] and checks['button_single_body']
    for k in ('pcb_interference_mm3', 'solder_interference_mm3', 'button_vs_pcb_mm3'):
        assert checks[k] < 1e-4, k
    # nút ôm thành ống có chủ đích (ép ma sát): chỉ cho phép phần giao nhỏ ở lỗ danh nghĩa
    assert checks['button_vs_adapter_press_fit_mm3'] < 3.0, 'nút ép quá chặt vào gá'
    assert checks['head_clearance_to_courtyard_mm'] >= HEAD_MARGIN, 'đầu nút chạm vùng linh kiện'
    assert checks['pin_clearance_in_pcb_hole_per_side_mm'] >= 0.05
    assert checks['hat_holes_clear_of_pcb_mm'] >= 1.0, 'lỗ HAT bị PCB che'
    report = {'adapter_mm': [round(float(v), 2) for v in frame.extents],
              'button_mm': [round(float(v), 2) for v in button.extents], 'buttons_needed': BUTTON_COUNT,
              'pcb_mm': [70, 40, 1.6], 'pcb_holes_mm_local': [(x, y - 7) for x, y in mounts],
              'pcb_origin_on_adapter_mm': [0, 7, PCB_Z0], 'pcb_height_increase_mm': PCB_Z0,
              'fastening': '4 straight tapered plastic pins, friction fit, no screws, no barbs',
              'checks': checks,
              'limits': ['Nominal solids only; no physical print, no insertion or pull-out test.',
                         'Friction fit depends on the printed hole size: with no hole shrink (2.9 mm) the pin is nearly loose.',
                         'A1 hole shrink (0.2-0.4 mm) is an assumption from Bambu wiki/forum reports.',
                         'Component clearance uses KiCad pads and courtyards, not 3D bodies or tall parts.',
                         'HAT hole pitch 58 x 49 mm (65 x 56 mm board, 2.75 mm holes) comes from Seeed Eagle file v1.0, not measured on a physical Hat.',
                         'No 3D model of the Hat was found on the Seeed page: connector and chip heights are unknown, so the standoff height is not checked.',
                         'MCP4725 module body dimensions are not measured; check actual modules before manufacture.']}
    (HERE/'fit_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Driver adapter + 4 straight pins (no screws):',
          f"adapter {checks['adapter_volume_mm3']} mm3 ({checks['adapter_saving_vs_screw_version_pct']}% less than screw version),",
          f"button {checks['button_volume_mm3']} mm3, head-to-courtyard {checks['head_clearance_to_courtyard_mm']} mm.")


if __name__=='__main__': main()
