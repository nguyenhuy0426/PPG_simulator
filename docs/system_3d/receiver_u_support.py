"""Screwless H support for a 70 x 20 mm receiver PCB.

OPT101 and BPW34 use different board seat heights to put both optical axes
at world Y=32. The open lower bay lets connector cables pass downward.
"""
def build(g, lower_edge, upper_edge):
    pieces = [
        # H crossbar supports the PCB while leaving the lower bay open.
        g.box(137.5, 141.3, lower_edge - 1, lower_edge, -36.5, 36.5),
    ]
    for lo, hi, outer_lo, outer_hi in [(-36.5,-33.5,-36.5,-35.25),(33.5,36.5,35.25,36.5)]:
        # Rear ledge overlaps each PCB edge by 1.5 mm, without reaching pads.
        pieces.append(g.box(139.1,141.3,lower_edge,upper_edge + 1,lo,hi))
        # Side guides provide 0.25 mm nominal clearance per side.
        pieces.append(g.box(137.5,139.1,3,upper_edge + 1,outer_lo,outer_hi))
        pieces.append(g.box(139.1,141.3,3,lower_edge - 1,lo,hi))
    return g.uni(pieces)


def fit_checks(g, frame, lower_edge):
    """Check the slide slot and the empty cable bay against the box CAD."""
    slot_front = g.FRM_X0 - 0.3
    slot_rear = g.FRM_X1
    bounds = frame.bounds
    bay = g.box(139.1, 141.3, 3, lower_edge - 1, -33.5, 33.5)
    import trimesh
    empty = trimesh.boolean.intersection([frame, bay], engine='manifold')
    return [
        {'label': 'support thickness fits 4.3 mm slide slot with 0.5 mm clearance',
         'pass': bool(slot_front <= bounds[0, 0] and bounds[1, 0] <= slot_rear
                      and slot_rear - slot_front - (bounds[1, 0] - bounds[0, 0]) >= 0.49)},
        {'label': 'side clearance at least 0.5 mm per side',
         'pass': bool(bounds[0, 2] >= g.Z_IN0 + 0.49 and bounds[1, 2] <= g.Z_IN1 - 0.49)},
        {'label': 'lower cable bay empty between side posts',
         'pass': bool(empty is None or abs(empty.volume) < 1e-4)},
    ]
