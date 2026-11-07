"""Cyberdock silhouette adapted to the existing Pi case and optical chamber.

Original CAD, mm; X width, Y depth, Z height. V1 supplies checked mesh/export
helpers and the existing optical interfaces, never the rejected outer shape.
"""
import importlib.util
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import cadquery as cq
import numpy as np
import trimesh

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("cyberdock_base",HERE.parent/"cyberdock_v1/build.py")
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
box,cyl,hexhole,rounded,union,add=b.box,b.cyl,b.hexhole,b.rounded,b.union,b.add
W,D,H=230.,245.,130.
R,AF=2.25,7.4
RED,GRAY="#ba433c","#8da9b6"


def section(x0,x1,y,z0,z1,r):
    w=cq.Workplane("XZ",origin=((x0+x1)/2,y,(z0+z1)/2)).rect(x1-x0,z1-z0).val()
    return w.fillet2D(r,w.Vertices())


def envelopes():
    outer=cq.Solid.makeLoft([section(0,230,0,0,130,14),section(1,229,75,0,128,20),
                              section(5,225,245,0,112,20)],ruled=True)
    inner=cq.Solid.makeLoft([section(3,227,-1,3,127,11),section(4,226,75,3,125,17),
                              section(8,222,246,3,109,17)],ruled=True)
    return outer,inner


def shell():
    outer,inner=envelopes();s=outer.cut(inner)
    for x in (16,214):
        for z in (9,121):
            boss=box(x-9,x+9,4.5,14.5,z-7,z+7).intersect(outer)
            s=union(s,boss).cut(cyl("y",3,16,x,z,R))
            s=s.cut(box(x-7.25,x+7.25,-1,4.25,z-6.25,z+6.25))
    for clearance in (box(21.75,25.75,-.1,8.25,11.75,118.25),
                      box(204.25,208.25,-.1,8.25,11.75,118.25),
                      box(22.75,207.25,-.1,23.25,8.25,12.25),
                      box(22.75,207.25,-.1,8.25,117.75,121.25)):
        s=s.cut(clearance)
    for x in (19,211):
        for z in (9,99):
            boss=box(x-9,x+9,231,241,z-9,z+9).intersect(outer)
            s=union(s,boss).cut(cyl("y",230,247,x,z,R),hexhole("y",230.9,234.6,x,z,AF))
    for right in (False,True):
        xa,xb=(218,230) if right else (0,12)
        s=union(s,cyl("x",xa,xb,70,65,28)).cut(cyl("x",xa-1,xb+1,70,65,R))
        ha,hb=(217.9,222.5) if right else (7.5,12.1)
        s=s.cut(hexhole("x",ha,hb,70,65,AF))
        for y in (175,184,193,202,211):
            s=s.cut(box(-1,231,y,y+3,26,54))
    # The rails carry both modules independently; no tall stacked load path.
    for xa,xb in ((27,45),(185,203)):
        s=union(s,box(xa,xb,27,239,3,10.5))
    s=union(s,box(27,29,27,239,3,16.5),box(201,203,27,239,3,16.5),
            box(27,32,27,239,14.5,16.5),box(198,203,27,239,14.5,16.5),
            box(30,200,27,30,3,13.5))
    for x in (38,192):
        s=s.cut(cyl("z",-2,18,x,230,R),hexhole("z",-.1,3.6,x,230,AF))
    roof=inner.cut(inner.translate((0,0,-5.5)))
    # Bottom tabs have top-loaded nuts; roof tabs have nuts loaded from inside.
    left=s.intersect(box(-1,115,-1,246,-1,131))
    right=s.intersect(box(115.25,231,-1,246,-1,131))
    for y in (40,232):
        tab=box(106,127,y-7,y+7,3,8.5)
        tab=tab.cut(cyl("z",2,10,121,y,R),hexhole("z",4.9,8.6,121,y,AF))
        left=union(left,tab);right=right.cut(cyl("z",-1,12,121,y,R))
    tab=roof.intersect(box(106,127,14,28,115,130))
    tab=tab.cut(cyl("z",110,132,121,21,R),hexhole("z",119,123.6,121,21,AF))
    left=union(left,tab);right=right.cut(cyl("z",110,132,121,21,R))
    for label,half in (("left",left),("right",right)):
        front=half.intersect(box(-1,231,-1,122.5,-1,131))
        back=half.intersect(box(-1,231,122.75,246,-1,131))
        x=35 if label=="left" else 195
        floor=box(x-7,x+7,114,138,3,8.5)
        floor=floor.cut(cyl("z",2,10,x,131,R),hexhole("z",4.9,8.6,x,131,AF))
        top=roof.intersect(box(x-7,x+7,114,138,100,130))
        # Local roof is ~119 mm here; pocket enters from the cavity side.
        top=top.cut(cyl("z",100,132,x,131,R),hexhole("z",112,117.8,x,131,AF))
        front=union(front,floor,top)
        back=back.cut(cyl("z",-1,132,x,131,R),box(x-7.25,x+7.25,122.5,138.25,2.75,8.75))
        add("01_shell_front_"+label,front,RED)
        add("02_shell_rear_"+label,back,RED)


def bezel():
    f=rounded(0,W,-4.5,0,0,H,14).cut(rounded(30,200,-5,1,16.5,113.5,8))
    f=union(f,box(22,25.5,0,8,12,118),box(204.5,208,0,8,12,118),
            box(23,207,0,23,8.5,12),box(23,207,0,8,118,121))
    for x in (18.5,211.5):
        for z in (26.5,101.5):
            boss=box(x-7,x+7,0,21,z-7,z+7).cut(cyl("y",-1,23,x,z,R),hexhole("y",6,9.6,x,z,AF))
            slot=box(x-7.1,x+.2,6,9.6,z-3.9,z+3.9) if x<115 else box(x-.2,x+7.1,6,9.6,z-3.9,z+3.9)
            f=union(f,boss.cut(slot))
    for x in (16,214):
        for z in (9,121):f=f.cut(box(x-7.25,x+7.25,-4.6,4.1,z-6.25,z+6.25))
    # Decorative side rails use short press-fit pins, with no additional screw size.
    for x in (11,219):
        for z in (34,96):f=f.cut(cyl("y",-4.6,-1.9,x,z,1.25))
    add("03_bezel_left",f.intersect(box(-1,115,-5,30,-1,131)),RED)
    add("03_bezel_right",f.intersect(box(115.25,231,-5,30,-1,131)),RED)
    clip=union(box(11.5,35,21.5,24.5,19.5,33.5),box(26,30,20.5,21.5,19.5,33.5))
    clip=clip.cut(cyl("y",20,26,18.5,26.5,R))
    for side in (0,1):
        for high in (0,1):
            p=clip if side==0 else clip.mirror("YZ",(115,0,0))
            add(f"clip_{side}_{high}",p.translate((0,0,75*high)),GRAY)
    for top in (False,True):
        z=121 if top else 9
        t=rounded(9,221,-6,-4.5,z-6,z+6,4)
        for x in (16,214):
            boss=box(x-7,x+7,-4.5,4,z-6,z+6)
            slot=box(x-4.4,x+4.4,-4.6,-.9,z if top else z-6.1,z+6.1 if top else z)
            boss=boss.cut(cyl("y",-5.2,5,x,z,R),hexhole("y",-4.6,-.9,x,z,AF),slot)
            t=union(t,boss)
            t=t.cut(cyl("y",-5.2,5,x,z,R))
        for side in ("left","right"):
            clipbox=box(-1,115,-7,5,-1,131) if side=="left" else box(115.25,231,-7,5,-1,131)
            add(f"trim_{'top' if top else 'bottom'}_{side}",t.intersect(clipbox),GRAY)
    for x,label in ((11,"left"),(219,"right")):
        t=rounded(x-2,x+2,-6,-4.5,22,108,1.8)
        for z in (34,96):t=union(t,cyl("y",-4.5,-2,x,z,1.1))
        add("trim_side_"+label,t,GRAY)


def rear():
    door=rounded(8.4,221.6,241.5,245.5,3.4,108.6,16.6)
    lip=rounded(8.4,221.6,239.5,241.5,3.4,108.6,16.6).cut(
        rounded(10.4,219.6,239,242,5.4,106.6,14.6))
    for x in (19,211):
        for z in (9,99):
            lip=lip.cut(box(x-12,x+12,239,242,z-12,z+12))
            door=door.cut(cyl("y",240,247,x,z,R))
    lip=lip.cut(box(104,130,239,242,2,10))
    door=union(door,lip)
    for x in (44,54,64,74,84,144,154,164,174,184):
        door=door.cut(box(x,x+3,238,247,28,52))
    door=door.cut(box(187,199,238,247,18,26))
    # Each door leaf has two M4 fasteners; no splice projects into the Pi bay.
    left=door.intersect(box(0,115,238,252,0,131))
    right=door.intersect(box(115.25,230,238,252,0,131))
    add("05_door_left",left,RED);add("06_door_right",right,RED)


def tray():
    t=box(30,200,30,240,8.5,11.5)
    for x,ys in ((61,(40,131)),(169,(40,131)),(69,(171,205)),(161,(171,205))):
        for y in ys:
            t=union(t,cyl("z",11.5,16,x,y,6))
            t=t.cut(cyl("z",7,17,x,y,R))
    for x in (38,192):t=t.cut(cyl("z",7,17,x,230,R))
    front=t.intersect(box(0,231,0,140,0,21))
    rear=t.intersect(box(0,231,140.25,246,0,21))
    for x in (90,140):
        tab=box(x-7,x+7,132,148,11.5,17)
        tab=tab.cut(cyl("z",7,18,x,144,R),hexhole("z",13.4,17.1,x,144,AF))
        front=union(front,tab);rear=rear.cut(cyl("z",7,18,x,144,R))
    # Large openings save plastic without weakening the mounting annuli or outer rails.
    for x0,x1,ya,yb in ((80,145,52,115),(80,145,178,198),(45,185,216,220)):
        cutter=rounded(x0,x1,ya,yb,8,12,1.8)
        front=front.cut(cutter);rear=rear.cut(cutter)
    add("07_tray_front",front.translate((0,0,2)),"#399a88")
    add("08_tray_rear",rear.translate((0,0,2)),"#399a88")


def yoke():
    left=union(box(-16,-6,-10,162,-20,-12),box(-16,-6,60,80,-20,155),
               box(-16,125,60,80,147,155))
    left=left.cut(cyl("x",-17,-5,70,65,R),box(104.9,126,59,81,151,156),
                  box(-17,-5,138,163,-16, -11))
    right=union(box(236,246,-10,162,-20,-12),box(236,246,60,80,-20,155),
                box(105,246,60,80,147,155))
    right=right.cut(cyl("x",235,247,70,65,R),box(104,125.1,59,81,146,151.25),
                    box(235,247,138,163,-16,-11))
    for x in (110,120):
        left=left.cut(cyl("z",146,156,x,70,R))
        right=right.cut(cyl("z",146,156,x,70,R))
    for label,p,x in (("left",left,-11),("right",right,241)):
        for y in (144,156):p=p.cut(cyl("z",-21,-11,x,y,R))
        add("09_yoke_"+label,p,GRAY)
        foot=union(box(x-5,x+5,162,250,-20,-12),box(x-5,x+5,138,162,-15.75,-12))
        for y in (144,156):foot=foot.cut(cyl("z",-21,-11,x,y,R))
        add("10_yoke_rear_foot_"+label,foot,GRAY)
    spacer=cyl("x",-5,0,70,65,16).cut(cyl("x",-6,1,70,65,R))
    gear=cyl("x",-22,-16,70,65,21.5)
    for i in range(32):
        tooth=box(-22,-16,90.5,96,63.5,66.5).rotate((0,70,65),(1,70,65),i*360/32)
        gear=union(gear,tooth)
    gear=gear.cut(cyl("x",-23,-15,70,65,R))
    knob=cyl("x",-34,-23,70,65,15)
    for i in range(3):
        a=i*2*math.pi/3
        knob=union(knob,cyl("x",-34,-23,70+14*math.cos(a),65+14*math.sin(a),7))
    knob=knob.cut(cyl("x",-35,-22,70,65,R),hexhole("x",-34.1,-27.3,70,65,AF))
    for name,p,color in (("spacer",spacer,"#607c89"),("gear",gear,GRAY),("knob",knob,RED)):
        add(name+"_left",p,color);add(name+"_right",p.mirror("YZ",(115,0,0)),color)


old_optical=b.optical_module
def optical_module():
    refs=old_optical()
    for name,m in refs.items():
        m.process(validate=True)
        m.apply_translation([5,103 if name=="pi_housing" else 0,0])
    # Legacy lid cavity extends 0.01 mm beyond its rib: bridge that accidental gap.
    bridge=b.to_mesh(box(43,187,84.875,86.125,81.95,82.2))
    refs["optical_lid"]=trimesh.boolean.union([refs["optical_lid"],bridge],engine="manifold")
    return refs


def assembly_colors():
    path=b.OUT/"PPG_Cyberdock_M4.3mf"
    with zipfile.ZipFile(path) as z:files={n:z.read(n) for n in z.namelist()}
    ns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    ET.register_namespace("",ns)
    ET.register_namespace("p","http://schemas.microsoft.com/3dmanufacturing/production/2015/06")
    model=ET.fromstring(files["3D/3dmodel.model"]);resources=model.find("{"+ns+"}resources")
    rid=str(max(int(c.attrib["id"]) for c in resources)+1)
    palette=ET.SubElement(resources,"{"+ns+"}basematerials",id=rid);colors=[]
    for obj in resources.findall("{"+ns+"}object"):
        name=obj.attrib["name"]
        color=b.COLORS.get(name,"#313941" if name.startswith(("optical_","hood_")) else "#8798a8")
        if color not in colors:
            colors.append(color);ET.SubElement(palette,"{"+ns+"}base",name=color,displaycolor=color.upper()+"FF")
        obj.set("pid",rid);obj.set("pindex",str(colors.index(color)))
    files["3D/3dmodel.model"]=ET.tostring(model,encoding="utf-8",xml_declaration=True)
    with zipfile.ZipFile(path,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)


def build():
    b.HERE=HERE;b.OUT=HERE/"out";b.W,b.D,b.H=W,D,H
    b.SCREEN_Z=12.5;b.PI_Z=b.OPT_Z=18.;b.PACK_SHIFT=[35,10,25]
    b.shell,b.bezel,b.rear,b.tray,b.yoke=shell,bezel,rear,tray,yoke
    b.optical_module=optical_module
    b.build()
    path=b.OUT/"manifest.json";m=json.loads(path.read_text())
    m.update(version="V2 - Cyberdock silhouette, existing Pi case retained",
             colors=b.COLORS,body_with_front_rear_mm=[230,130,251.5],
             module_translations_mm={"pi_housing":[55,149,18],"optical_body":[22,34,18]},
             layout="Optical chamber in front, existing Pi case behind; common removable tray")
    for key,pos in (("fixed_optical_body",[22,34,18]),("pi_housing_m4",[55,149,18])):
        m[key]["print_to_assembly_translation_mm"]=pos
    path.write_text(json.dumps(m,indent=2)+"\n")
    assembly_colors()


if __name__=="__main__":build()
