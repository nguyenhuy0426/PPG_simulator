#!/usr/bin/env python3
"""Replacement slide-in U for a 70 x 20 x 1.6 mm OPT101 PCB.

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
    shared_spec = importlib.util.spec_from_file_location('receiver_u_support', REPO/'docs/system_3d/receiver_u_support.py')
    shared = importlib.util.module_from_spec(shared_spec)
    shared_spec.loader.exec_module(shared)
    lower,upper=19.81,39.81
    frame = shared.build(g,lower,upper)
    frame.export(HERE/'frame_70x20_assembly.stl')
    # Flat back face on the print bed. No support needed inside the open recess.
    printed=frame.copy()
    # world (X,Y,Z) -> print (Z,Y,-X), determinant +1
    m=np.eye(4); m[:3,:3]=[[0,0,1],[0,1,0],[-1,0,0]]
    printed.apply_transform(m); printed.apply_translation(-printed.bounds[0])
    printed.export(HERE/'frame_70x20_print.stl')
    print_folder = REPO/'docs/system_3d/out/print_bambu_180'
    print_folder.mkdir(parents=True, exist_ok=True)
    printed.export(print_folder/'14_ga_chu_U_OPT101_70x20.stl')
    pcb=g.box(137.5,139.1,lower,upper,-35,35)
    pcb.export(HERE/'pcb_70x20_assembly.stl')
    # Conservative envelopes, not claimed to be manufacturer-accurate solids.
    parts={'frame':frame,'pcb':pcb}
    for ch,zc in g.LANE_Z.items():
        parts['socket_envelope_'+ch]=g.box(126.5,137.5,26.5,37.5,zc-5.5,zc+5.5)
        # PCB top view x->world Z and y->-world Y. Header is on the optical side.
        hz=(-23.3,-14.7) if ch=='red' else (14.7,23.3)
        parts['header_envelope_'+ch]=g.box(125.5,137.5,20.41,24.41,*hz)
        parts['capacitor_envelope_'+ch]=g.box(130.5,137.5,34.8,37.8,zc-5.1,zc)
        parts['output_rc_'+ch]=g.box(135.7,137.5,24.1,25.9,zc-1.8,zc+7.8)
        # Back-side solder protrusions; must be trimmed to <= 2 mm.
        parts['solder_envelope_'+ch]=g.box(139.1,141.1,26.7,37.3,zc-4.7,zc+4.7)
        parts['solder_header_'+ch]=g.box(139.1,141.1,21.11,23.71,*hz)
        parts['solder_cap_'+ch]=g.box(139.1,141.1,35.5,37.1,zc-4.61,zc-.51)
    parts['header_ads_envelope']=g.box(125.5,137.5,20.41,24.41,-10.5,-4.96)
    parts['solder_ads']=g.box(139.1,141.1,21.11,23.71,-9.5,-5.96)
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
        if name.startswith(('socket','header','capacitor','solder','output_rc')):
            vol=intersection(parts[name],frame)
            checks.append({'a':name,'b':'frame','intersection_mm3':vol,'pass':vol<1e-4})
    # Verify the vertical insertion path against the actual exported body mesh.
    for dy in np.arange(0,65,2):
        for name in ('frame','pcb','socket_envelope_red','socket_envelope_ir','header_envelope_red','header_envelope_ir','capacitor_envelope_red','capacitor_envelope_ir','header_ads_envelope'):
            moved=parts[name].copy(); moved.apply_translation([0,float(dy),0])
            vol=intersection(moved,fixed['body'])
            checks.append({'a':name,'b':'body insertion','dy_mm':float(dy),'intersection_mm3':vol,'pass':vol<1e-4})
    report={'board_mm':[70,20,1.6], 'print_bounds_mm':printed.extents.tolist(),
            'lane_centres_z_mm':[-19.25,19.25], 'axis_y_mm':32,
            'pcb_front_x_mm':137.5,
            'optical_window_x_mm':'137.5 - measured socket-plus-IC optical height',
            'socket_envelope_height_mm':11,'header_envelope_height_mm':12,
            'solder_trim_max_mm':2,
            'fasteners':'None; screwless U support, secure PCB edges with opaque tape',
            'watertight':bool(frame.is_watertight), 'connected_bodies':body_count(frame),
            'checks':checks,'passed':sum(x['pass'] for x in checks),'total':len(checks),
            'limitations':['Envelope check, not actual purchased socket or cable geometry.',
                          'Die offset not dimensioned in TI drawing; nominal package centre used.',
                          'Open U: opaque sealing required above PCB and across rear centre-divider gap; no physical fit/light-leak test.']}
    (HERE/'fit_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f"Mechanical: {report['passed']}/{len(checks)}, watertight={frame.is_watertight}")
    if not all(x['pass'] for x in checks):
        print(json.dumps([x for x in checks if not x['pass']],indent=2))
        raise SystemExit(1)

if __name__=='__main__': main()
