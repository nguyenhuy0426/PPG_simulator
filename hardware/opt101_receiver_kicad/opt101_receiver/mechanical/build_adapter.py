#!/usr/bin/env python3
"""Replacement slide-in frame for a 70 x 32 x 1.6 mm PCB.

Run from repository root with .cad_venv/bin/python. The existing enclosure,
lid, and original frame files are not modified. Coordinates match build_system.
"""
import importlib.util
import json
from pathlib import Path
import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
spec = importlib.util.spec_from_file_location('system_geometry', REPO/'docs/system_3d/build_system.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

def intersection(a,b):
    return float(abs(trimesh.boolean.intersection([a,b],engine='manifold').volume))

def body_count(mesh):
    neighbours={i:set() for i in range(len(mesh.faces))}
    for a,b in mesh.face_adjacency:
        neighbours[a].add(b); neighbours[b].add(a)
    remaining=set(neighbours); count=0
    while remaining:
        todo=[remaining.pop()]; count+=1
        while todo:
            fresh=neighbours[todo.pop()] & remaining
            remaining-=fresh; todo.extend(fresh)
    return count

def main():
    # Preserve the old frame exterior so it uses the same enclosure slide stops.
    frame = g.box(137.5,141.5,3,59.8,-36.7,36.7)
    cuts = [g.box(137.4,139.1,15.75,48.25,-35.25,35.25)]
    for lo,hi in [(-29,-4),(4,29)]:
        cuts += [g.box(139.0,141.6,18,42,lo,hi)]
    # M3 pilot holes in plastic. M3x4 screws through 1.6 mm PCB engage 2.4 mm;
    # no rear nut/protrusion, which would foul the enclosure's lower cable bosses.
    for y in (19.5,44.5):
        for z in (-30.5,30.5):
            cuts.append(g.cyl_x(137.4,141.6,y,z,1.3,48))
    frame = g.dif(frame,cuts)
    frame.export(HERE/'frame_70x32_assembly.stl')
    # Flat back face on the print bed. No support needed inside the open recess.
    printed=frame.copy()
    # world (X,Y,Z) -> print (Z,Y,-X), determinant +1
    m=np.eye(4); m[:3,:3]=[[0,0,1],[0,1,0],[-1,0,0]]
    printed.apply_transform(m); printed.apply_translation(-printed.bounds[0])
    printed.export(HERE/'frame_70x32_print.stl')
    pcb=g.box(137.5,139.1,16,48,-35,35)
    holes=[g.cyl_x(137.4,139.2,y,z,1.6,48) for y in (19.5,44.5) for z in (-30.5,30.5)]
    pcb=g.dif(pcb,holes); pcb.export(HERE/'pcb_70x32_assembly.stl')
    # Conservative envelopes, not claimed to be manufacturer-accurate solids.
    parts={'frame':frame,'pcb':pcb}
    for ch,zc in g.LANE_Z.items():
        parts['socket_envelope_'+ch]=g.box(126.5,137.5,26.5,37.5,zc-5.5,zc+5.5)
        # PCB top view x->world Z and y->-world Y. Header is on the optical side.
        hz=(-23.0,-15.5) if ch=='red' else (17.0,23.5)
        parts['header_envelope_'+ch]=g.box(125.5,137.5,19.0,23.0,*hz)
        parts['capacitor_envelope_'+ch]=g.box(130.5,137.5,38.5,41.5,zc-5.1,zc)
        # Back-side solder protrusions; must be trimmed to <= 2 mm.
        parts['solder_envelope_'+ch]=g.box(139.1,141.1,26.7,37.3,zc-4.7,zc+4.7)
        parts['solder_header_'+ch]=g.box(139.1,141.1,19.7,22.3,*hz)
        parts['solder_cap_'+ch]=g.box(139.1,141.1,39.2,40.8,zc-4.61,zc-.51)
    for y in (19.5,44.5):
        for z in (-30.5,30.5):
            parts[f'screw_head_{y}_{z}']=g.cyl_x(134.5,137.5,y,z,3.2,48)
    parts['header_ads_envelope']=g.box(125.5,137.5,19.0,23.0,-9.2,-5.5)
    parts['solder_ads']=g.box(139.1,141.1,19.7,22.3,-8.9,-5.8)
    exported=REPO/'docs/system_3d/out/stl'
    fixed={name:trimesh.load(exported/f'{name}.stl',force='mesh') for name in ('body','lid','aperture_red_d16')}
    aperture_ir=fixed['aperture_red_d16'].copy(); aperture_ir.apply_translation([0,0,38.5]); fixed['aperture_ir_d16']=aperture_ir
    checks=[]
    for an,a in parts.items():
        for bn,b in fixed.items():
            vol=intersection(a,b)
            checks.append({'a':an,'b':bn,'intersection_mm3':vol,'pass':vol<1e-4})
    checks.append({'a':'frame','b':'pcb','intersection_mm3':intersection(frame,pcb),'pass':intersection(frame,pcb)<1e-4})
    for name in parts:
        if name.startswith(('socket','header','capacitor','solder')):
            vol=intersection(parts[name],frame)
            checks.append({'a':name,'b':'frame','intersection_mm3':vol,'pass':vol<1e-4})
    # Verify the vertical insertion path against the actual exported body mesh.
    for dy in np.arange(0,65,2):
        for name in ('frame','pcb','socket_envelope_red','socket_envelope_ir','header_envelope_red','header_envelope_ir','capacitor_envelope_red','capacitor_envelope_ir','header_ads_envelope'):
            moved=parts[name].copy(); moved.apply_translation([0,float(dy),0])
            vol=intersection(moved,fixed['body'])
            checks.append({'a':name,'b':'body insertion','dy_mm':float(dy),'intersection_mm3':vol,'pass':vol<1e-4})
    report={'board_mm':[70,32,1.6], 'print_bounds_mm':printed.extents.tolist(),
            'lane_centres_z_mm':[-19.25,19.25], 'axis_y_mm':32,
            'pcb_front_x_mm':137.5,
            'optical_window_x_mm':'137.5 - measured socket-plus-IC optical height',
            'socket_envelope_height_mm':11,'header_envelope_height_mm':12,
            'solder_trim_max_mm':2,
            'fasteners':'4 x M3x4, 2.6 mm pilot holes in plastic, no rear nuts',
            'watertight':bool(frame.is_watertight), 'connected_bodies':body_count(frame),
            'checks':checks,'passed':sum(x['pass'] for x in checks),'total':len(checks),
            'limitations':['Envelope check, not actual purchased socket or cable geometry.',
                          'Die offset not dimensioned in TI drawing; nominal package centre used.',
                          'No physical fit, print shrinkage or optical leakage test.']}
    (HERE/'fit_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f"Mechanical: {report['passed']}/{len(checks)}, watertight={frame.is_watertight}")
    if not all(x['pass'] for x in checks):
        print(json.dumps([x for x in checks if not x['pass']],indent=2))
        raise SystemExit(1)

if __name__=='__main__': main()
