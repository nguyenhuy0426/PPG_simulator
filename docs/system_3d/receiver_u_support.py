"""Shared screwless U support for both 70 x 30 mm receiver PCBs.

World coordinates match build_system.py. The PCB front remains X=137.5,
lower edge Y=17, optical axis Y=32. This is NOT a sealed optical bulkhead.
"""
def build(g):
    pieces = [
        # Bottom web: reaches floor, closes the region below the PCB and
        # supports its rear edge. Back face prints flat at X=141.5.
        g.box(139.1, 141.5, 3, 18, -36.7, 36.7),
        # Seat under the PCB's lower edge; front face stays at X=137.5.
        g.box(137.5, 139.1, 16, 17, -35.25, 35.25),
    ]
    for lo, hi, outer_lo, outer_hi in [(-36.7,-33.5,-36.7,-35.25),(33.5,36.7,35.25,36.7)]:
        # Rear ledge overlaps each PCB edge by 1.5 mm, without reaching pads.
        pieces.append(g.box(139.1,141.5,17,59.8,lo,hi))
        # Side guides provide 0.25 mm nominal clearance per side.
        pieces.append(g.box(137.5,139.1,3,59.8,outer_lo,outer_hi))
    return g.uni(pieces)
