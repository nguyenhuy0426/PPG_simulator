#!/usr/bin/env python3
"""Build and collision-check the BPW34 receiver's 70 x 20 mm U support."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
spec = importlib.util.spec_from_file_location("system_geometry", REPO / "docs/system_3d/build_system.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def intersection(a, b):
    result = trimesh.boolean.intersection([a, b], engine="manifold")
    return 0.0 if result is None else float(abs(result.volume))


def body_count(mesh):
    neighbours = {index: set() for index in range(len(mesh.faces))}
    for a, b in mesh.face_adjacency:
        neighbours[a].add(b)
        neighbours[b].add(a)
    remaining = set(neighbours)
    count = 0
    while remaining:
        pending = [remaining.pop()]
        count += 1
        while pending:
            fresh = neighbours[pending.pop()] & remaining
            remaining -= fresh
            pending.extend(fresh)
    return count


def main():
    shared_spec = importlib.util.spec_from_file_location('receiver_u_support', REPO/'docs/system_3d/receiver_u_support.py')
    shared = importlib.util.module_from_spec(shared_spec)
    shared_spec.loader.exec_module(shared)
    lower,upper=23.7,43.7
    frame = shared.build(g,lower,upper)
    frame.export(HERE / "frame_70x20_bpw34_assembly.stl")

    printed = frame.copy()
    transform = np.eye(4)
    transform[:3, :3] = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]
    printed.apply_transform(transform)
    printed.apply_translation(-printed.bounds[0])
    printed.export(HERE / "frame_70x20_bpw34_print.stl")

    print_folder = REPO/'docs/system_3d/out/print_bambu_180'
    print_folder.mkdir(parents=True, exist_ok=True)
    printed.export(print_folder/'15_ga_chu_U_BPW34_70x20.stl')
    pcb = g.box(137.5, 139.1, lower, upper, -35, 35)
    pcb.export(HERE / "pcb_70x20_bpw34_assembly.stl")

    parts = {"frame": frame, "pcb": pcb}
    for channel, zc in g.LANE_Z.items():
        parts[f"bpw34_{channel}"] = g.box(131.8, 137.5, 29.3, 34.7, zc - 2.2, zc + 2.2)
        header_z = (-25.8, -17.2) if channel == "red" else (17.2, 25.8)
        parts[f"grove_header_{channel}"] = g.box(125.5, 137.5, 25.03, 29.03, *header_z)
        channel_z = (-28.5, -4.0) if channel == "red" else (4.0, 28.5)
        parts[f"rear_smd_{channel}"] = g.box(139.1, 141.1, 27.0, 41.5, *channel_z)
        parts[f"rear_output_rc_{channel}"] = g.box(139.1, 141.1, 28.0, 30.0, -22.7 if channel=="red" else 20.3, -19.3 if channel=="red" else 23.7)
        parts[f"bpw34_solder_{channel}"] = g.box(139.1, 141.1, 30.5, 33.5, zc - 3.0, zc + 3.0)
        parts[f"grove_solder_{channel}"] = g.box(139.1, 141.1, 25.73, 28.33, *header_z)
    parts["ads_header"] = g.box(125.5, 137.5, 25.03, 29.03, -14.5, -3.88)
    parts["ads_solder"] = g.box(139.1, 141.1, 25.73, 28.33, -13.5, -4.88)
    exported = REPO / "docs/system_3d/out/stl"
    fixed = {name: trimesh.load(exported / f"{name}.stl", force="mesh") for name in ("body", "lid", "aperture_red_d16")}
    aperture_ir = fixed["aperture_red_d16"].copy()
    aperture_ir.apply_translation([0, 0, 38.5])
    fixed["aperture_ir_d16"] = aperture_ir

    checks = []
    checks.extend(shared.fit_checks(g, frame, lower))
    for part_name, part in parts.items():
        for fixed_name, solid in fixed.items():
            volume = intersection(part, solid)
            checks.append({"a": part_name, "b": fixed_name, "intersection_mm3": volume, "pass": volume < 1e-4})
    volume = intersection(frame, pcb)
    checks.append({"a": "frame", "b": "pcb", "intersection_mm3": volume, "pass": volume < 1e-4})
    for name, part in parts.items():
        if name.startswith(("bpw34_", "grove_", "rear_smd", "rear_output", "ads_")):
            volume = intersection(part, frame)
            checks.append({"a": name, "b": "frame", "intersection_mm3": volume, "pass": volume < 1e-4})

    # Check insertion along the same slide direction as the enclosure model.
    for delta_y in np.arange(0, 65, 2):
        for name in ("frame", "pcb", "bpw34_red", "bpw34_ir", "grove_header_red", "grove_header_ir", "ads_header"):
            moved = parts[name].copy()
            moved.apply_translation([0, float(delta_y), 0])
            volume = intersection(moved, fixed["body"])
            checks.append({"a": name, "b": "body insertion", "dy_mm": float(delta_y), "intersection_mm3": volume, "pass": volume < 1e-4})

    report = {
        "board_mm": [70, 20, 1.6],
        "print_bounds_mm": printed.extents.tolist(),
        "slide_slot_mm": 4.3,
        "support_thickness_mm": 3.8,
        "nominal_depth_clearance_mm": 0.5,
        "nominal_side_clearance_mm": 0.5,
        "lane_centres_z_mm": [-19.25, 19.25],
        "axis_y_mm": 32,
        "pcb_front_x_mm": 137.5,
        "bpw34_sensitive_surface_x_mm": 134.3,
        "rear_component_clearance_mm": 2.0,
        "solder_trim_max_mm": 2.0,
        "fasteners": "None; screwless H support, secure PCB edges with opaque tape",
        "watertight": bool(frame.is_watertight),
        "connected_bodies": body_count(frame),
        "checks": checks,
        "passed": sum(item["pass"] for item in checks),
        "total": len(checks),
        "limitations": [
            "Conservative component envelopes, not exact purchased-part solids.",
            "BPW34 sensitive-area centre is assumed to match the package drawing nominal centre.",
            "Open H requires opaque sealing above PCB and behind centre divider; no physical fit/light-leak test.",
            "Nominal 0.5 mm slot clearance must be confirmed by a short test print on the actual printer.",
        ],
    }
    (HERE / "fit_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Mechanical: {report['passed']}/{report['total']}, watertight={frame.is_watertight}")
    if not all(item["pass"] for item in checks):
        print(json.dumps([item for item in checks if not item["pass"]], indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
