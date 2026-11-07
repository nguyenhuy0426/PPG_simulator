"""Macintosh-inspired PPG desktop enclosure; mm, X across/Y rearward/Z up."""
import importlib.util
import json
from pathlib import Path

import cadquery as cq

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('ppg_cyberdock',HERE.parent/'cyberdock_v3/build.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
box,cyl,hexhole,rounded,union,add=b.box,b.cyl,b.hexhole,b.rounded,b.union,b.add
R,AF=2.25,7.4
CREAM,ACCENT='#d9cbb0','#c6b99f'
old_rear=b.rear


def rear():
    old_rear()
    for name in ('05_door_left','06_door_right'):b.COLORS[name]=CREAM


def shell():
    s=rounded(0,220,0,150,0,170,3).cut(rounded(3,217,-1,151,3,167,.8))
    for x in (10,210):
        for z in (12,158):
            s=union(s,box(x-9,x+9,0,10,z-9,z+9))
            s=s.cut(cyl('y',-1,11,x,z,R),hexhole('y',6.4,10.1,x,z,AF))
    for x in (12,208):
        for z in (12,158):
            s=union(s,box(x-9,x+9,136,146,z-9,z+9))
            s=s.cut(cyl('y',135,147,x,z,R),hexhole('y',135.9,139.6,x,z,AF))
    for guide in (box(16.75,20.75,-.1,8.25,44.75,156.25),
                  box(199.25,203.25,-.1,8.25,44.75,156.25),
                  box(17.75,202.25,-.1,8.25,153.25,157.25)):
        s=s.cut(guide)
    for z in (28,37,46,120,129):
        s=s.cut(box(-1,221,101,132,z,z+3))
    for xa,xb in ((22,40),(180,198)):s=union(s,box(xa,xb,27,143,3,9))
    s=union(s,box(22,24,27,143,3,15),box(196,198,27,143,3,15),
            box(22,27,27,143,13,15),box(193,198,27,143,13,15),
            box(25,195,27,30,3,12))
    for x in (33,187):s=s.cut(cyl('z',-2,16,x,130,R),hexhole('z',-.1,3.6,x,130,AF))
    left=s.intersect(box(-1,110,-1,151,-1,171))
    right=s.intersect(box(110.25,221,-1,151,-1,171))
    for ya,yb,za,zb in ((11,25,161.5,167),(125,139,161.5,167),(7,21,3,8.5)):
        y=(ya+yb)/2;tab=box(102,121,ya,yb,za,zb)
        hn0,hn1=(za-.1,za+3.6) if za>100 else (zb-3.6,zb+.1)
        tab=tab.cut(cyl('z',za-1,zb+1,116,y,R),hexhole('z',hn0,hn1,116,y,AF))
        left=union(left,tab);right=right.cut(cyl('z',-1,171,116,y,R))
    for label,s in (('left',left),('right',right)):
        front=s.intersect(box(-1,221,-1,100,-1,171))
        rear=s.intersect(box(-1,221,100.25,151,-1,171));x=16 if label=='left' else 204
        for za,zb in ((3,8.5),(161.5,167)):
            na,nb=(4.9,8.6) if za<20 else (161.4,165.1)
            tab=box(x-7,x+7,92,115,za,zb).cut(cyl('z',za-1,zb+1,x,108,R),
                                                    hexhole('z',na,nb,x,108,AF))
            front=union(front,tab)
            rear=rear.cut(cyl('z',-1,171,x,108,R),box(x-7.25,x+7.25,100,115.25,za-.25,zb+.25))
        add('01_shell_'+label+'_front',front,CREAM)
        add('02_shell_'+label+'_rear',rear,CREAM)


def window_wire(y,w,h,r):
    wire=cq.Workplane('XZ',origin=(110,y,100.5)).rect(w,h).val()
    return wire.fillet2D(r,wire.Vertices())


def bezel():
    f=rounded(0,220,-4.5,0,0,170,3).cut(rounded(25,195,-5,1,52,149,3))
    f=union(f,box(17,20.5,0,8,45,156),box(199.5,203,0,8,45,156),
            box(18,202,0,23,44,47.5),box(18,202,0,8,153.5,157))
    for x in (13.5,206.5):
        for z in (62,137):
            boss=box(x-7,x+7,0,11,z-7,z+7).cut(cyl('y',-5,12,x,z,R),hexhole('y',2,5.6,x,z,AF))
            slot=box(x-7.1,x+.2,2,5.6,z-3.9,z+3.9) if x<110 else box(x-.2,x+7.1,2,5.6,z-3.9,z+3.9)
            f=union(f,boss.cut(slot)).cut(hexhole('y',2,5.6,x,z,AF),slot)
    # A real tapered aperture creates the recessed screen surround seen in the reference.
    opening=cq.Solid.makeLoft([window_wire(-10.1,174,101,5),window_wire(-4.4,170,97,3)],ruled=True)
    fascia=rounded(0,220,-10,-4.5,40,170,3).cut(opening)
    chin=rounded(0,220,-8,-4.5,0,170,3).intersect(box(-1,221,-9,-4,0,39))
    chin=chin.cut(box(65,194,-8.1,-6.7,25,27.5),box(181,194,-8.1,-7.2,22,31),
                  box(22,33,-8.1,-7.2,21,32))
    f=union(f,fascia,chin)
    for x in (10,210):
        for z in (12,158):f=f.cut(cyl('y',-11,1,x,z,R))
    left=f.intersect(box(-1,110,-11,30,-1,171))
    right=f.intersect(box(110.25,221,-11,30,-1,171))
    right=right.cut(box(110,121.25,-.1,5.75,152.75,167.25))
    for z in (18,160):
        tab=box(102,121,0,5.5,z-7,z+7).cut(cyl('y',-11,6,116,z,R),hexhole('y',1.9,5.6,116,z,AF))
        left=union(left,tab).cut(cyl('y',-11,6,116,z,R))
        right=right.cut(cyl('y',-11,6,116,z,R))
    add('03_bezel_left',left,CREAM);add('04_bezel_right',right,CREAM)
    clip=union(box(6.5,30,11.5,14.5,55,69),box(21,25,10.5,11.5,55,69))
    clip=clip.cut(cyl('y',10,16,13.5,62,R))
    for side in (0,1):
        for high in (0,1):
            p=clip if side==0 else clip.mirror('YZ',(110,0,0))
            add(f'clip_{side}_{high}',p.translate((0,0,75*high)),ACCENT)


def tray():
    s=box(25,195,30,139,9,12)
    for y in (62,104):s=union(s,box(32,188,y,y+4,12,15.5))
    for x in (64,156):
        for y in (68,102):
            s=union(s,cyl('z',12,19,x,y,6)).cut(cyl('z',3,20,x,y,R))
    for x in (33,187):
        s=union(s,box(x-5.5,x+5.5,124,136,9,15)).cut(cyl('z',-2,16,x,130,R))
    left=s.intersect(box(0,110,0,145,0,21))
    right=s.intersect(box(110.25,220,0,145,0,21))
    # Keep projecting M4 threads outside the Pi floor, not merely below its shell.
    for y in (35,136):
        tab=box(102,121,y-8,y+8,12,17.5).cut(cyl('z',8,22,116,y,R),
                                              hexhole('z',13.9,17.6,116,y,AF))
        left=union(left,tab);right=right.cut(cyl('z',8,22,116,y,R))
    add('07_tray_left',left,'#72958a');add('08_tray_right',right,'#72958a')


def build():
    b.HERE=HERE;b.OUT=HERE/'out';b.SCREEN_Z=48.;b.PACK_SHIFT=[0,10,0]
    b.shell,b.bezel,b.rear,b.tray=shell,bezel,rear,tray
    b.yoke=lambda:None
    # Remove only the obsolete generated plinth parts from the previous export.
    for folder,suffix in (('print','.stl'),('step','.step'),('assembly_meshes','.stl')):
        for name in ('base_left','base_right'):(b.OUT/folder/(name+suffix)).unlink(missing_ok=True)
    b.build()
    path=b.OUT/'manifest.json';m=json.loads(path.read_text())
    old=b.OUT/'PPG_Cyberdock_M4.3mf';new=b.OUT/'PPG_MacDesktop_M4.3mf';old.replace(new)
    m.update(version='Mac Desktop V1',single_assembly_file=new.name,
             screen_thickness_confirmed_mm=10,screen_window_provisional_mm=[170,97],
             body_with_front_rear_mm=[220,170,160.5],colors=b.COLORS,base_removed=True,
             layout='Existing Pi housing below optical chamber; rear removable tray')
    m.pop('screen_thickness_assumed_mm',None)
    path.write_text(json.dumps(m,indent=2)+'\n')


if __name__=='__main__':build()
