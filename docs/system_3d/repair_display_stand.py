"""Repair the supplied STL; add a separate, flat four-hole chamber mounting frame.

Run with numpy, trimesh, manifold3d and shapely installed. Dimensions are mm.
The archived input and both mating parts are immutable inputs, not regenerated.
"""
import hashlib
import json
from pathlib import Path

import manifold3d as mf
import numpy as np
import trimesh
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

ROOT = Path(__file__).resolve().parent
PRINT = ROOT / "out/print_bambu_180"
REVIEW = ROOT / "out/stand_review"


def box(lo, hi):
    lo, hi = np.array(lo), np.array(hi)
    return trimesh.creation.box(hi - lo, trimesh.transformations.translation_matrix((lo + hi) / 2))


def main():
    original = trimesh.load_mesh(ROOT / "assets/ga_do_man_hinh_original_20261105.stl")
    pi_path, chamber_path = PRINT / "than_hop_pi4.stl", PRINT / "01_than_hop_toi.stl"
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (pi_path, chamber_path)}
    pi, chamber = trimesh.load_mesh(pi_path), trimesh.load_mesh(chamber_path)
    stand = original.copy()
    # Fill the reentrant foot corner with R4; keep the existing screen stops and upper mounts.
    profile = Polygon([(-122.5, 0), (-108, 0), (-78, 35), (-77.5, 35.5),
                       (-77.5, 44.007), (-116.5, 4.8), (-122.5, 4.8)])
    profile = orient(profile.buffer(4, quad_segs=12).buffer(-4, quad_segs=12), sign=1)
    mesh = mf.CrossSection([np.array(profile.exterior.coords[:-1])]).extrude(19).to_mesh()
    rib = trimesh.Trimesh(np.array(mesh.vert_properties)[:, :3], mesh.tri_verts)
    rib.vertices = rib.vertices[:, [2, 0, 1]]
    for x in (29, 99):
        stand = trimesh.boolean.difference(
            [stand, box([x - .01, -116.5, 0], [x + 19.01, -98, 40])], engine="manifold")
        placed = rib.copy()
        placed.apply_translation([x, 0, 0])
        stand = trimesh.boolean.union([stand, placed], engine="manifold")

    # Close the existing 1 mm gap under the Pi tabs, following their sloping underside.
    collars = []
    for x in (6, 114):
        placement = trimesh.transformations.translation_matrix([x, -6, 65.5])
        outer = trimesh.creation.cylinder(radius=3.5, height=1, sections=96, transform=placement)
        bore = trimesh.creation.cylinder(radius=2.15, height=3, sections=96, transform=placement)
        collars.append(trimesh.boolean.difference([outer, bore, pi], engine="manifold"))
    stand = trimesh.boolean.union([stand, *collars], engine="manifold")

    # U frame rests on the Pi rim: two rails and one narrow rear crosspiece.
    frame = trimesh.boolean.union([box([0, -12, 0], [12, 91, 4]),
                                   box([108, -12, 0], [120, 91, 4]),
                                   box([12, -10, 0], [108, -2, 4])], engine="manifold")
    holes = [(x, y) for x in (6, 114) for y in (-6, 85)]
    bores = [trimesh.creation.cylinder(radius=1.85, height=6, sections=96,
             transform=trimesh.transformations.translation_matrix([x, y, 2])) for x, y in holes]
    frame = trimesh.boolean.difference([frame, *bores], engine="manifold")

    for part in (stand, frame):
        assert part.is_volume and len(part.split(only_watertight=False)) == 1
        assert np.all(part.extents < 180)
    assert np.allclose(stand.bounds, original.bounds, atol=1e-5)
    # A section through the old shoulder previously broke into three disconnected outlines.
    assert len(original.section([1, 0, 0], [30, 0, 0]).discrete) == 3
    assert len(stand.section([1, 0, 0], [30, 0, 0]).discrete) == 2
    upper = box([-30, -27, 59], [150, 1, 76])
    old_upper = trimesh.boolean.intersection([original, upper], engine="manifold")
    new_upper = trimesh.boolean.intersection([stand, upper], engine="manifold")
    assert abs(trimesh.boolean.difference([old_upper, new_upper], engine="manifold").volume) < .001
    extra_upper = trimesh.boolean.difference([new_upper, old_upper], engine="manifold")
    assert abs(extra_upper.volume - sum(c.volume for c in collars)) < .001

    assembled_frame, assembled_chamber = frame.copy(), chamber.copy()
    assembled_frame.apply_translation([0, 0, 70])
    assembled_chamber.apply_translation([-33, -12, 74])
    parts = [stand, pi, assembled_frame, assembled_chamber]
    overlaps = {}
    for i, a in enumerate(parts):
        for j in range(i + 1, len(parts)):
            overlap = abs(trimesh.boolean.intersection([a, parts[j]], engine="manifold").volume)
            overlaps[f"{i}-{j}"] = overlap
            assert overlap < .001, (i, j, overlap)

    # Verify an M3 shaft clears the complete rear stack and both front mounting ears.
    for x, y in holes:
        shaft = trimesh.creation.cylinder(radius=1.5, height=20, sections=96,
                 transform=trimesh.transformations.translation_matrix([x, y, 69]))
        for part in parts:
            assert abs(trimesh.boolean.intersection([shaft, part], engine="manifold").volume) < .001
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == hashes[p.name]
               for p in (pi_path, chamber_path))

    REVIEW.mkdir(exist_ok=True)
    stand.export(PRINT / "ga_do_man_hinh.stl")
    frame.export(PRINT / "khung_ghep_buong_den_pi4.stl")
    # Reload actual exported files rather than certifying only the in-memory meshes.
    for name in ("ga_do_man_hinh.stl", "khung_ghep_buong_den_pi4.stl"):
        actual = trimesh.load_mesh(PRINT / name)
        assert actual.is_volume and len(actual.split(only_watertight=False)) == 1
    report = {"units": "mm", "original_stand_mm3": original.volume,
              "repaired_stand_mm3": stand.volume, "frame_mm3": frame.volume,
              "stand_size_mm": stand.extents.tolist(), "frame_size_mm": frame.extents.tolist(),
              "chamber_hole_pitch_mm": [108, 91], "hole_centers_assembly_xy": holes,
              "frame_hole_diameter_mm": 3.7, "chamber_translation": [-33, -12, 74],
              "rear_tab_gap_filled_mm": 1,
              "frame_translation": [0, 0, 70], "mating_input_sha256": hashes,
              "pair_intersection_mm3": overlaps,
              "validation": "Geometry and M3 shaft clearance only; no physical load test or FEA."}
    (REVIEW / "geometry_checks.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
