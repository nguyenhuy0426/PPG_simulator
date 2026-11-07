"""Add two integral front mounting ears; preserve the Pi shell and rear mounts.

Run with the same numpy/trimesh/manifold3d environment as repair_display_stand.py.
"""
import hashlib
import json

import numpy as np
import trimesh
from shapely.geometry import Point, Polygon

from repair_display_stand import PRINT, ROOT, box


def main():
    original_path = ROOT / "assets/than_hop_pi4_before_front_tabs_20261105.stl"
    original = trimesh.load_mesh(original_path)
    # Remove only the external rear gussets, leaving the shell wall and flat ears intact.
    rear_cuts = [box([x - 6.76, -14, 58.99], [x + 6.76, 0, 66]) for x in (6, 114)]
    base = trimesh.boolean.difference([original, *rear_cuts], engine="manifold")
    stand_path, chamber_path = PRINT / "ga_do_man_hinh.stl", PRINT / "01_than_hop_toi.stl"
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (original_path, stand_path, chamber_path)}
    stand, chamber = trimesh.load_mesh(stand_path), trimesh.load_mesh(chamber_path)
    additions = []
    for x in (0, 108):
        additions.append(box([x, 77, 66], [x + 12, 91, 70]))
        # Two 2 mm side webs leave an 8 mm corridor for the front nut and washer.
        for edge in (x, x + 10):
            vertices = [[xx, y, z] for xx in (edge, edge + 2)
                        for y, z in ((79, 54), (79, 66), (91, 66))]
            additions.append(trimesh.convex.convex_hull(np.array(vertices)))
    pi = trimesh.boolean.union([base, *additions], engine="manifold")
    bores = [trimesh.creation.cylinder(radius=1.85, height=20, sections=96,
             transform=trimesh.transformations.translation_matrix([x, 85, 63]))
             for x in (6, 114)]
    pi = trimesh.boolean.difference([pi, *bores], engine="manifold")

    assert pi.is_volume and len(pi.split(only_watertight=False)) == 1
    assert np.all(pi.extents < 180)
    assert abs(trimesh.boolean.difference([base, pi], engine="manifold").volume) < .001
    removed = trimesh.boolean.difference([original, pi], engine="manifold")
    # Repeated float32 booleans leave sub-0.01 mm³ slivers on the original curved mesh.
    assert abs(trimesh.boolean.difference([removed, *rear_cuts], engine="manifold").volume) < .01
    added = trimesh.boolean.difference([pi, base], engine="manifold")
    allowed = trimesh.boolean.union([box([x, 77, 54], [x + 12, 91, 70])
                                     for x in (0, 108)], engine="manifold")
    assert abs(trimesh.boolean.difference([added, allowed], engine="manifold").volume) < .001
    interior_and_ports = [box([3, 3, 3], [117, 76.999, 70]),
                          box([25, 76.9, 0], [100, 81, 70])]
    for region in interior_and_ports:
        assert abs(trimesh.boolean.intersection([added, region], engine="manifold").volume) < .001
    assert np.allclose(pi.bounds[:, 0], original.bounds[:, 0], atol=.0001)
    assert np.allclose(pi.bounds[:, 2], original.bounds[:, 2], atol=.0001)
    assert abs(pi.bounds[1, 1] - 91) < .0001

    chamber.apply_translation([-33, -12, 70])
    parts = {"pi": pi, "stand": stand, "chamber": chamber}
    overlaps, shaft_overlaps, hardware_overlaps = {}, [], []
    for i, (name, a) in enumerate(parts.items()):
        for other, b in list(parts.items())[i + 1:]:
            volume = abs(trimesh.boolean.intersection([a, b], engine="manifold").volume)
            overlaps[f"{name}-{other}"] = volume
            assert volume < .001
    for x in (6, 114):
        for y in (-6, 85):
            shaft = trimesh.creation.cylinder(radius=1.5, height=28, sections=96,
                    transform=trimesh.transformations.translation_matrix([x, y, 66]))
            # OD 7.4 x 4 mm envelopes, above the ears and below the clamped stack.
            # These bound hardware clearance, not a model of a particular fastener.
            for part in parts.values():
                shaft_overlaps.append(abs(trimesh.boolean.intersection([shaft, part], engine="manifold").volume))
            for z in (76, 58 if y == -6 else 64):
                envelope = trimesh.creation.cylinder(radius=3.7, height=4, sections=96,
                           transform=trimesh.transformations.translation_matrix([x, y, z]))
                for part in parts.values():
                    hardware_overlaps.append(abs(trimesh.boolean.intersection([envelope, part], engine="manifold").volume))
    assert max(shaft_overlaps) < .001
    assert max(hardware_overlaps) < .001
    contact_profiles = []
    for mesh, z in ((pi, 69.999), (chamber, 70.001)):
        material = Polygon()
        for loop in mesh.section([0, 0, 1], [0, 0, z]).discrete:
            material = material.symmetric_difference(Polygon(loop[:, :2]))
        contact_profiles.append(material)
    bearing = contact_profiles[0].intersection(contact_profiles[1])
    ear_bearing = {f"{x},{y}": bearing.intersection(Point(x, y).buffer(6)).area
                   for x in (6, 114) for y in (-6, 85)}
    assert min(ear_bearing.values()) > 30
    # Check the new ears really contain two enclosed through-holes at the required centers.
    section = pi.section([0, 0, 1], [0, 0, 68])
    for x in (6, 114):
        loops = [p[:, :2] for p in section.discrete
                 if np.allclose((p[:, :2].min(0) + p[:, :2].max(0)) / 2, [x, 85], atol=.002)]
        assert len(loops) == 1
        assert np.allclose(np.ptp(loops[0], axis=0), [3.7, 3.7], atol=.003)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == hashes[p.name]
               for p in (original_path, stand_path, chamber_path))

    target = PRINT / "than_hop_pi4.stl"
    pi.export(target)
    actual = trimesh.load_mesh(target)
    assert actual.is_volume and len(actual.split(only_watertight=False)) == 1
    assert abs(actual.volume - pi.volume) < .001
    review = ROOT / "out/direct_mount_review"
    review.mkdir(exist_ok=True)
    report = {"units": "mm", "pi_size_mm": pi.extents.tolist(),
              "added_volume_mm3": added.volume, "front_ear_size_mm": [12, 14, 4],
              "gusset_thickness_mm": 2, "nut_corridor_width_mm": 8,
              "front_hole_diameter_mm": 3.7, "hole_pitch_mm": [108, 91],
              "hole_centers_xy": [[6, -6], [114, -6], [6, 85], [114, 85]],
              "chamber_translation_mm": [-33, -12, 70], "frame_required": False,
              "input_sha256": hashes, "pi_output_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
              "pair_intersection_mm3": overlaps,
              "m3_shaft_max_intersection_mm3": max(shaft_overlaps),
              "hardware_envelope_max_intersection_mm3": max(hardware_overlaps),
              "pi_chamber_bearing_area_mm2": bearing.area,
              "ear_bearing_area_mm2": ear_bearing,
              "validation": "STL geometry only; no slicer, physical fit, torque or load validation."}
    (review / "geometry_checks.json").write_text(json.dumps(report, indent=2) + "\n")
    scene = trimesh.Scene()
    for name, mesh in parts.items():
        mesh.visual.face_colors = {"pi": [137, 152, 173, 255], "stand": [33, 156, 138, 255],
                                   "chamber": [76, 83, 91, 255]}[name]
        scene.add_geometry(mesh, geom_name=name, node_name=name)
    scene.export(review / "assembly.glb")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
