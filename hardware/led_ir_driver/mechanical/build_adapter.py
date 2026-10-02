#!/usr/bin/env python3
"""70x40 driver adapter for the existing 70x55 base mounting pattern.

Print coordinates X,Y are the old board coordinates; Z points upward.
The adapter rests on the existing 5 mm base standoffs. New PCB local (x,y)
maps to adapter (x,y+7), with its underside at adapter Z=6 mm.
"""
import json
from pathlib import Path
import numpy as np
import trimesh

HERE=Path(__file__).resolve().parent
def box(x0,x1,y0,y1,z0,z1):
    m=trimesh.creation.box(extents=(x1-x0,y1-y0,z1-z0))
    m.apply_translation(((x0+x1)/2,(y0+y1)/2,(z0+z1)/2)); return m
def cylinder(x,y,z0,z1,r):
    m=trimesh.creation.cylinder(radius=r,height=z1-z0,sections=64)
    m.apply_translation((x,y,(z0+z1)/2)); return m
def diff(a,others): return trimesh.boolean.difference([a,*others],engine='manifold')
def intersection(a,b):
    return abs(trimesh.boolean.intersection([a,b],engine='manifold').volume)

def bodies(mesh):
    adj={i:set() for i in range(len(mesh.faces))}
    for a,b in mesh.face_adjacency: adj[a].add(b); adj[b].add(a)
    remaining=set(adj); count=0
    while remaining:
        todo=[remaining.pop()]; count+=1
        while todo:
            fresh=adj[todo.pop()] & remaining; remaining-=fresh; todo.extend(fresh)
    return count

def main():
    frame=diff(box(0,70,0,55,0,2),[box(8,62,8,47,-1,3)])
    mounts=[(4,31),(66,31),(4,43),(66,43)]
    frame=trimesh.boolean.union([frame,*[cylinder(x,y,1.5,6,3.6) for x,y in mounts]],engine='manifold')
    # Four old-base through holes and four new PCB pilot holes.
    cuts=[cylinder(x,y,-.1,6.1,1.6) for x in (4,66) for y in (4,51)]
    cuts += [cylinder(x,y,-.1,6.1,1.3) for x,y in mounts]
    frame=diff(frame,cuts)
    frame.export(HERE/'driver_70x40_adapter_print.stl')
    import shutil
    shutil.copy2(HERE/'driver_70x40_adapter_print.stl', HERE.parents[2]/'docs/system_3d/out/print_bambu_180/16_ga_driver_70x40.stl')
    pcb=diff(box(0,70,7,47,6,7.6),[cylinder(x,y,5.9,7.7,1.6) for x,y in mounts])
    pcb.export(HERE/'driver_70x40_pcb_assembly.stl')
    # Long pin tails are limited to 2 mm, above the 2 mm adapter plate.
    solder=box(8,62,10,45,4,6)
    checks={'watertight':bool(frame.is_watertight),'single_body':bodies(frame)==1,
        'pcb_interference_mm3':intersection(frame,pcb),'solder_interference_mm3':intersection(frame,solder)}
    assert checks['watertight'] and checks['single_body']
    assert checks['pcb_interference_mm3']<1e-4 and checks['solder_interference_mm3']<1e-4
    report={'adapter_mm':frame.extents.tolist(),'pcb_mm':[70,40,1.6],
        'old_base_holes_mm':[(x,y) for x in (4,66) for y in (4,51)],
        'new_pcb_holes_mm':[(x,y-7) for x,y in mounts],
        'pcb_origin_on_adapter_mm':[0,7,6],'pcb_height_increase_mm':6,
        'checks':checks,'limits':['Nominal solids only, no physical print/cable test.',
        'MCP4725 module body dimensions are not measured; check actual modules before manufacture.']}
    (HERE/'fit_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Driver adapter: watertight single solid, no nominal PCB/solder collision.')

if __name__=='__main__': main()
