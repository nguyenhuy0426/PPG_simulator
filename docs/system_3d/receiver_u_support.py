"""Minimal screwless U support for a 70 x 20 mm receiver PCB.

OPT101 and BPW34 use different board seat heights to put both optical axes
at world Y=32. This open support still needs opaque edge sealing.
"""
def build(g, lower_edge, upper_edge):
    pieces = [
        # Bottom web: reaches floor, closes the region below the PCB and
        # supports its rear edge. Back face prints flat at X=141.5.
        g.box(139.1, 141.5, 3, lower_edge + 1, -36.7, 36.7),
        # Seat under the PCB's lower edge; front face stays at X=137.5.
        g.box(137.5, 139.1, lower_edge - 1, lower_edge, -35.25, 35.25),
    ]
    for lo, hi, outer_lo, outer_hi in [(-36.7,-33.5,-36.7,-35.25),(33.5,36.7,35.25,36.7)]:
        # Rear ledge overlaps each PCB edge by 1.5 mm, without reaching pads.
        pieces.append(g.box(139.1,141.5,lower_edge,upper_edge + 1,lo,hi))
        # Side guides provide 0.25 mm nominal clearance per side.
        pieces.append(g.box(137.5,139.1,3,upper_edge + 1,outer_lo,outer_hi))
    return g.uni(pieces)
