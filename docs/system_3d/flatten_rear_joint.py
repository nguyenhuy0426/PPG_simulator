"""Replace the rear interlocking sockets by flat, drilled mounting pads."""
import numpy as np
import trimesh
from repair_display_stand import ROOT, PRINT, box


def main():
    stand = trimesh.load_mesh(ROOT / "assets/ga_do_man_hinh_before_flat_joint_20261105.stl")
    for x in (6, 114):
        cut = box([x - 7.01, -14, 59.99], [x + 7.01, 0, 67])
        pad = box([x - 7, -14, 60], [x + 7, -1, 66])
        bore = trimesh.creation.cylinder(radius=1.85, height=10, sections=96,
               transform=trimesh.transformations.translation_matrix([x, -6, 63]))
        stand = trimesh.boolean.difference([stand, cut], engine="manifold")
        stand = trimesh.boolean.union([stand, pad], engine="manifold")
        stand = trimesh.boolean.difference([stand, bore], engine="manifold")
    assert stand.is_volume and len(stand.split(only_watertight=False)) == 1
    stand.export(PRINT / "ga_do_man_hinh.stl")


if __name__ == "__main__":
    main()
