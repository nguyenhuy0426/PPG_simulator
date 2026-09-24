#!/usr/bin/env python3
"""Build and collision-check the BPW34 receiver's 70 x 32 mm slide frame."""
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
    # Same exterior and slide stops as the OPT101 replacement frame.  The rear
    # channel recess is 4 mm taller to clear the low-profile SMD analog stage.
    frame = g.box(137.5, 141.5, 3, 59.8, -36.7, 36.7)
    cuts = [g.box(137.4, 139.1, 15.75, 48.25, -35.25, 35.25)]
    for low, high in ((-29, -4), (4, 29)):
        cuts.append(g.box(139.0, 141.6, 18, 46, low, high))
    for y in (19.5, 44.5):
        for z in (-30.5, 30.5):
            cuts.append(g.cyl_x(137.4, 141.6, y, z, 1.3, 48))
    frame = g.dif(frame, cuts)
    frame.export(HERE / "frame_70x32_bpw34_assembly.stl")

    printed = frame.copy()
    transform = np.eye(4)
    transform[:3, :3] = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]
    printed.apply_transform(transform)
    printed.apply_translation(-printed.bounds[0])
    printed.export(HERE / "frame_70x32_bpw34_print.stl")

    pcb = g.box(137.5, 139.1, 16, 48, -35, 35)
    pcb_holes = [g.cyl_x(137.4, 139.2, y, z, 1.6, 48) for y in (19.5, 44.5) for z in (-30.5, 30.5)]
    pcb = g.dif(pcb, pcb_holes)
    pcb.export(HERE / "pcb_70x32_bpw34_assembly.stl")

    parts = {"frame": frame, "pcb": pcb}
    for channel, zc in g.LANE_Z.items():
        parts[f"bpw34_{channel}"] = g.box(131.8, 137.5, 29.3, 34.7, zc - 2.2, zc + 2.2)
        header_z = (-23.8, -17.2) if channel == "red" else (16.2, 22.8)
        parts[f"grove_header_{channel}"] = g.box(125.5, 137.5, 19.0, 23.0, *header_z)
        channel_z = (-28.5, -4.0) if channel == "red" else (4.0, 28.5)
        parts[f"rear_smd_{channel}"] = g.box(139.1, 141.1, 32.0, 45.8, *channel_z)
        parts[f"bpw34_solder_{channel}"] = g.box(139.1, 141.1, 30.5, 33.5, zc - 3.0, zc + 3.0)
        parts[f"grove_solder_{channel}"] = g.box(139.1, 141.1, 19.7, 22.3, *header_z)
    parts["ads_header"] = g.box(125.5, 137.5, 19.0, 23.0, -13.3, -4.9)
    parts["ads_solder"] = g.box(139.1, 141.1, 19.7, 22.3, -13.0, -5.2)
    for y in (19.5, 44.5):
        for z in (-30.5, 30.5):
            parts[f"screw_head_{y}_{z}"] = g.cyl_x(134.5, 137.5, y, z, 3.2, 48)

    exported = REPO / "docs/system_3d/out/stl"
    fixed = {name: trimesh.load(exported / f"{name}.stl", force="mesh") for name in ("body", "lid", "aperture_red_d16")}
    aperture_ir = fixed["aperture_red_d16"].copy()
    aperture_ir.apply_translation([0, 0, 38.5])
    fixed["aperture_ir_d16"] = aperture_ir

    checks = []
    for part_name, part in parts.items():
        for fixed_name, solid in fixed.items():
            volume = intersection(part, solid)
            checks.append({"a": part_name, "b": fixed_name, "intersection_mm3": volume, "pass": volume < 1e-4})
    volume = intersection(frame, pcb)
    checks.append({"a": "frame", "b": "pcb", "intersection_mm3": volume, "pass": volume < 1e-4})
    for name, part in parts.items():
        if name.startswith(("bpw34_", "grove_", "rear_smd", "ads_")):
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
        "board_mm": [70, 32, 1.6],
        "print_bounds_mm": printed.extents.tolist(),
        "lane_centres_z_mm": [-19.25, 19.25],
        "axis_y_mm": 32,
        "pcb_front_x_mm": 137.5,
        "bpw34_sensitive_surface_x_mm": 134.3,
        "rear_component_clearance_mm": 2.0,
        "solder_trim_max_mm": 2.0,
        "fasteners": "4 x M3x4 into 2.6 mm plastic pilot holes",
        "watertight": bool(frame.is_watertight),
        "connected_bodies": body_count(frame),
        "checks": checks,
        "passed": sum(item["pass"] for item in checks),
        "total": len(checks),
        "limitations": [
            "Conservative component envelopes, not exact purchased-part solids.",
            "BPW34 sensitive-area centre is assumed to match the package drawing nominal centre.",
            "No physical print-shrinkage, cable-bend or light-leakage test has been performed.",
        ],
    }
    (HERE / "fit_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Mechanical: {report['passed']}/{report['total']}, watertight={frame.is_watertight}")
    if not all(item["pass"] for item in checks):
        print(json.dumps([item for item in checks if not item["pass"]], indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
