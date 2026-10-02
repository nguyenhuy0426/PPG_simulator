#!/usr/bin/env python3
"""70x48 driver adapter for the existing 70x55 base mounting pattern.

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
    mounts=[(4,32),(66,32),(4,51),(66,51)]
    frame=trimesh.boolean.union([frame,*[cylinder(x,y,1.5,6,3.6) for x,y in mounts]],engine='manifold')
    # Old upper mounts are through holes. The two lower mounts are coaxial
    # through-holes, taking longer screws into the old base. New upper PCB
    # mounts use M3 self-tapped pilot holes and short screws.
    cuts=[cylinder(x,y,-.1,6.1,1.6) for x in (4,66) for y in (4,51)]
    cuts += [cylinder(x,32,-.1,6.1,1.3) for x in (4,66)]
    frame=diff(frame,cuts)
    frame.export(HERE/'driver_70x48_adapter_print.stl')
    pcb=diff(box(0,70,7,55,6,7.6),[cylinder(x,y,5.9,7.7,1.6) for x,y in mounts])
    pcb.export(HERE/'driver_70x48_pcb_assembly.stl')
    # Long pin tails are limited to 2 mm, above the 2 mm adapter plate.
    solder=box(8,62,10,53,4,6)
    checks={'watertight':bool(frame.is_watertight),'single_body':bodies(frame)==1,
        'pcb_interference_mm3':intersection(frame,pcb),'solder_interference_mm3':intersection(frame,solder)}
    assert checks['watertight'] and checks['single_body']
    assert checks['pcb_interference_mm3']<1e-4 and checks['solder_interference_mm3']<1e-4
    report={'adapter_mm':frame.extents.tolist(),'pcb_mm':[70,48,1.6],
        'old_base_holes_mm':[(x,y) for x in (4,66) for y in (4,51)],
        'new_pcb_holes_mm':[(x,y-7) for x,y in mounts],
        'pcb_origin_on_adapter_mm':[0,7,6],'pcb_height_increase_mm':6,
        'checks':checks,'limits':['Nominal solids only, no physical print/cable test.',
        'MCP4725 module body dimensions are not measured; check actual modules before manufacture.']}
    (HERE/'fit_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Driver adapter: watertight single solid, no nominal PCB/solder collision.')

if __name__=='__main__': main()
