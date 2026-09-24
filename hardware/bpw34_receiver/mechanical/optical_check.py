#!/usr/bin/env python3
"""Nominal ray/active-area check for the BPW34 replacement receiver."""
import importlib.util
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import trimesh
from trimesh.transformations import rotation_matrix

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
STL = REPO / "docs/system_3d/out/stl"
spec = importlib.util.spec_from_file_location("system_geometry", REPO / "docs/system_3d/build_system.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

SENSOR_X_RANGE = (134.2, 134.4)
ACTIVE_HALF_Y = 1.5
ACTIVE_HALF_Z = 1.25
ACTIVE_CORNER = math.hypot(ACTIVE_HALF_Y, ACTIVE_HALF_Z)
APERTURE_X = (g.AP_X0 + g.AP_X1) / 2
APERTURES = {"blank": 0.0, "d2": 1.0, "d5": 2.5, "d16": 8.0}
LED_HALF_ANGLE = {"red": 25.0, "ir": 15.0}


def segment_cylinder(a, b, radius=0.05):
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    vector = b - a
    length = float(np.linalg.norm(vector))
    direction = vector / length
    mesh = trimesh.creation.cylinder(radius=radius, height=length, sections=12)
    z_axis = np.array([0.0, 0.0, 1.0])
    axis = np.cross(z_axis, direction)
    dot = float(np.clip(np.dot(z_axis, direction), -1, 1))
    transform = np.eye(4)
    if np.linalg.norm(axis) > 1e-12:
        transform = rotation_matrix(math.acos(dot), axis)
    elif dot < 0:
        transform = rotation_matrix(math.pi, [1, 0, 0])
    transform[:3, 3] = (a + b) / 2
    mesh.apply_transform(transform)
    return mesh


def overlap(a, b):
    result = trimesh.boolean.intersection([a, b], engine="manifold")
    return 0.0 if result is None else float(abs(result.volume))


def shifted_aperture(kind, lane):
    mesh = trimesh.load(STL / f"aperture_red_{kind}.stl", force="mesh")
    if lane == "ir":
        mesh.apply_translation([0, 0, g.LANE_Z["ir"] - g.LANE_Z["red"]])
    return mesh


def led_tip_x(lane):
    return g.X_WIN - g.D_DEFAULT[lane]


def main():
    fixed = {name: trimesh.load(STL / f"{name}.stl", force="mesh") for name in ("body", "lid")}
    frame = trimesh.load(HERE / "frame_70x32_bpw34_assembly.stl", force="mesh")
    checks, lanes = [], {}

    def record(name, condition, **data):
        checks.append({"check": name, "pass": bool(condition), **data})

    for lane in ("red", "ir"):
        zc = g.LANE_Z[lane]
        source = np.array([led_tip_x(lane), g.Y_AX, zc])
        sensor = np.array([SENSOR_X_RANGE[0], g.Y_AX, zc])
        chief = segment_cylinder(source, sensor)
        record(f"{lane} LED and BPW34 are coaxial", source[1] == sensor[1] and source[2] == sensor[2])
        for kind in APERTURES:
            volume = overlap(chief, shifted_aperture(kind, lane))
            should_block = kind == "blank"
            record(f"{lane} chief ray " + ("blocked by blank" if should_block else f"passes {kind}"), (volume > 1e-7) == should_block, intersection_mm3=volume)
        for name, solid in {**fixed, "new_frame": frame, "d16_aperture": shifted_aperture("d16", lane)}.items():
            volume = overlap(chief, solid)
            record(f"{lane} chief ray clear of {name}", volume < 1e-7, intersection_mm3=volume)
        other = "ir" if lane == "red" else "red"
        cross = segment_cylinder(source, [SENSOR_X_RANGE[0], g.Y_AX, g.LANE_Z[other]])
        volume = overlap(cross, fixed["body"])
        record(f"{lane} cross-channel ray blocked by centre partition", volume > 1e-7, intersection_mm3=volume)

        projected = []
        for sensor_x in SENSOR_X_RANGE:
            scale = (APERTURE_X - source[0]) / (sensor_x - source[0])
            projected.append(ACTIVE_CORNER * scale)
        cone_radius = 1.5 + (APERTURE_X - source[0]) * math.tan(math.radians(LED_HALF_ANGLE[lane]))
        lanes[lane] = {
            "source_tip_x_mm": source[0],
            "sensor_surface_x_range_mm": list(SENSOR_X_RANGE),
            "axis_y_mm": g.Y_AX,
            "axis_z_mm": zc,
            "active_area_mm": [3.0, 2.5],
            "projected_active_corner_radius_at_aperture_mm": projected,
            "half_intensity_cone_radius_at_aperture_mm": cone_radius,
            "d2_covers_full_nominal_active_rectangle": bool(max(projected) <= 1.0),
            "d5_covers_full_nominal_active_rectangle": bool(max(projected) <= 2.5),
            "d16_covers_full_nominal_active_rectangle": bool(max(projected) <= 8.0),
        }

    report = {
        "method": "Boolean intersection of nominal rays with the actual enclosure/aperture STL meshes",
        "aperture_plane_x_mm": APERTURE_X,
        "lanes": lanes,
        "checks": checks,
        "passed": sum(item["pass"] for item in checks),
        "total": len(checks),
        "conclusion": {
            "nominal_alignment": "Both LED axes pass through their aperture centres and the nominal BPW34 active-area centres.",
            "separation": "The solid centre partition blocks a direct ray from either LED to the other photodiode.",
            "scope": "This is a geometric line-of-sight result, not a measured optical-sensitivity or leakage result.",
        },
        "limitations": [
            "No LED radiant-power, scattering, reflection, print translucency or assembly-gap model.",
            "Purchased BPW34 package and lead forming were not physically measured.",
            "A physical dark-box leakage and signal-range test is still required.",
        ],
    }
    (HERE / "optical_report.json").write_text(json.dumps(report, indent=2) + "\n")

    figure, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    for axis, lane in zip(axes, ("red", "ir")):
        source_x = led_tip_x(lane)
        axis.axvspan(g.AP_X0, g.AP_X1, color="#6b7280", alpha=0.35, label="Aperture plate")
        axis.axvspan(*SENSOR_X_RANGE, color="#16a34a", alpha=0.2, label="BPW34 sensitive surface")
        axis.plot([source_x, SENSOR_X_RANGE[1]], [0, 0], color="#dc2626" if lane == "red" else "#7c3aed", linewidth=2, label="Chief ray")
        for diameter, color in ((2, "#f59e0b"), (5, "#2563eb"), (16, "#059669")):
            radius = diameter / 2
            axis.plot([APERTURE_X, APERTURE_X], [-radius, radius], linewidth=5, solid_capstyle="round", color=color, label=f"diameter {diameter} mm")
        corner = max(lanes[lane]["projected_active_corner_radius_at_aperture_mm"])
        axis.plot([APERTURE_X, APERTURE_X], [-corner, corner], color="black", linewidth=2, label="Projected active corner")
        axis.set_title(f"{lane.upper()} lane")
        axis.set_xlabel("World X (mm)")
        axis.grid(alpha=0.25)
        axis.set_xlim(source_x - 4, 136)
        axis.set_ylim(-9, 9)
    axes[0].set_ylabel("Offset from optical axis (mm)")
    handles, labels = axes[1].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", ncol=4, frameon=False)
    figure.suptitle("BPW34 nominal optical alignment and aperture coverage")
    figure.tight_layout(rect=(0, 0.13, 1, 0.95))
    figure.savefig(HERE / "optical_alignment.png", dpi=180)
    plt.close(figure)
    print(f"Optical geometry: {report['passed']}/{report['total']}")
    if not all(item["pass"] for item in checks):
        print(json.dumps([item for item in checks if not item["pass"]], indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
