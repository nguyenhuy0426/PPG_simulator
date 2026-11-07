"""Original Cyberdock-style PPG enclosure, mm. No MakerWorld geometry is used.

X = width; Y = front to rear; Z = height. Parts remain in assembly coordinates
in STEP/GLB; print STL files have separate, recorded bed transforms.
"""
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

import cadquery as cq
import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "out"
SOURCE = ROOT / "out/print_bambu_180"
W, D, H = 220., 150., 170.
SCREEN_W, SCREEN_H, SCREEN_T = 178., 105., 10.  # measured
SCREEN_Z = 38.
PACK_SHIFT = [27,10,25]
BOLT_R, NUT_AF = 2.25, 7.4  # M4 clearance Ø4.5, nut AF +0.4 mm
PI_Z, OPT_Z = 19., 89.
PARTS = {}
COLORS = {}


def box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1-x0, y1-y0, z1-z0, cq.Vector(x0, y0, z0))


def cyl(axis, a0, a1, c1, c2, r):
    base = {"x": (a0,c1,c2), "y": (c1,a0,c2), "z": (c1,c2,a0)}[axis]
    direction = {"x": (1,0,0), "y": (0,1,0), "z": (0,0,1)}[axis]
    return cq.Solid.makeCylinder(r, a1-a0, cq.Vector(*base), cq.Vector(*direction))


def hexhole(axis, a0, a1, c1, c2, af):
    s = cq.Workplane("XY").polygon(6, af/math.cos(math.pi/6)).extrude(a1-a0).val()
    if axis == "y":
        return s.rotate((0,0,0),(1,0,0),-90).translate((c1,a0,c2))
    if axis == "x":
        return s.rotate((0,0,0),(0,1,0),90).translate((a0,c1,c2))
    return s.translate((c1,c2,a0))


def rounded(x0,x1,y0,y1,z0,z1,r):
    return cq.Workplane("XY").newObject([box(x0,x1,y0,y1,z0,z1)]).edges("|Y").fillet(r).val()


def union(*items):
    return items[0].fuse(*items[1:]).clean() if len(items)>1 else items[0]


def add(name, shape, color):
    shape = shape.clean()
    assert shape.isValid() and len(shape.Solids()) == 1, name
    PARTS[name] = shape
    COLORS[name] = color


def shell():
    s = rounded(0,W,0,D,0,H,8).cut(rounded(3,W-3,-1,D+1,3,H-3,5))
    # Corner bosses join the rim, but do not obstruct the full-width service opening.
    for x in (12,208):
        for z in (12,158):
            for ya,yb in ((0,10),(136,146)):
                s = union(s,box(x-9,x+9,ya,yb,z-9,z+9))
                s = s.cut(cyl("y",ya-1,yb+1,x,z,BOLT_R))
                na,nb = (6.4,10.1) if ya==0 else (135.9,139.6)
                s = s.cut(hexhole("y",na,nb,x,z,NUT_AF))
    for right in (False,True):
        xa,xb = (208,220) if right else (0,12)
        s = union(s,cyl("x",xa,xb,75,85,18))
        s = s.cut(cyl("x",xa-1,xb+1,75,85,BOLT_R))
        # Bolt head is retained inside the boss, accessible through the rear door.
        ha,hb = (207.9,212.5) if right else (7.5,12.1)
        s = s.cut(hexhole("x",ha,hb,75,85,NUT_AF))
        for y in (105,112,119,126):
            s = s.cut(box(xa-1,xb+1,y,y+3,28,45))
    # Integral guide ledges; 1 mm vertical and lateral working clearance around tray.
    for xa,xb in ((22,40),(180,198)):
        s = union(s,box(xa,xb,27,143,3,9))
    s = union(s,box(22,24,27,143,3,15),box(196,198,27,143,3,15),
              box(22,27,27,143,13,15),box(193,198,27,143,13,15),
              box(25,195,27,30,3,12))
    for x in (33,187):
        s=s.cut(cyl("z",-2,16,x,130,BOLT_R),hexhole("z",-.1,3.6,x,130,NUT_AF))
    left = s.intersect(box(-1,110,-1,151,-1,171))
    right = s.intersect(box(110.25,221,-1,151,-1,171))
    for ya,yb,za,zb in ((11,25,161.5,167),(125,139,161.5,167),(7,21,3,8.5)):
        tab = box(102,121,ya,yb,za,zb)
        y = (ya+yb)/2
        tab = tab.cut(cyl("z",za-1,zb+1,116,y,BOLT_R))
        hn0,hn1 = (za-.1,za+3.6) if za>100 else (zb-3.6,zb+.1)
        tab = tab.cut(hexhole("z",hn0,hn1,116,y,NUT_AF))
        left = union(left,tab)
        right = right.cut(cyl("z",-1,171,116,y,BOLT_R))
    add("01_shell_left",left,"#bd493f")
    add("02_shell_right",right,"#bd493f")


def bezel():
    f = rounded(0,W,-4.5,0,0,H,8).cut(rounded(25,195,-5,1,42,139,3))
    f = union(f,box(17,20.5,0,8,35,146),box(199.5,203,0,8,35,146),
              box(18,202,0,23,34,37.5),box(18,202,0,8,143.5,147))
    for x in (13.5,206.5):
        for z in (52,127):
            b=box(x-7,x+7,0,SCREEN_T+1,z-7,z+7)
            b=b.cut(cyl("y",-5,SCREEN_T+2,x,z,BOLT_R),
                    hexhole("y",2,5.6,x,z,NUT_AF))
            # Side-load the nut; a rear shoulder must resist pull towards the screw head.
            slot=box(x-7.1,x+.2,2,5.6,z-3.9,z+3.9) if x<W/2 else box(x-.2,x+7.1,2,5.6,z-3.9,z+3.9)
            b=b.cut(slot)
            f=union(f,b)
    for x in (12,208):
        for z in (12,158): f=f.cut(cyl("y",-5,1,x,z,BOLT_R))
    left=f.intersect(box(-1,110,-5,30,-1,171))
    right=f.intersect(box(110.25,221,-5,30,-1,171))
    for z in (18,155):
        tab=box(102,121,0,5.5,z-7,z+7)
        tab=tab.cut(cyl("y",-5,6,116,z,BOLT_R),hexhole("y",1.9,5.6,116,z,NUT_AF))
        left=union(left,tab)
        right=right.cut(cyl("y",-5,6,116,z,BOLT_R))
    add("03_bezel_left",left,"#a73e36")
    add("04_bezel_right",right,"#a73e36")
    # One clip geometry, mirrored for the opposite frame edge.
    clip=union(box(6.5,30,SCREEN_T+1.5,SCREEN_T+4.5,45,59),
               box(21,25,SCREEN_T+.5,SCREEN_T+1.5,45,59))
    clip=clip.cut(cyl("y",SCREEN_T,SCREEN_T+6,13.5,52,BOLT_R))
    for side in (0,1):
        for high in (0,1):
            p=clip if side==0 else clip.mirror("YZ",(W/2,0,0))
            add(f"clip_{side}_{high}",p.translate((0,0,75*high)),"#91a5b4")


def rear():
    door=rounded(3.4,216.6,146.5,150.5,3.4,166.6,4.5)
    lip=rounded(3.4,216.6,144.5,146.5,3.4,166.6,4.5).cut(
        rounded(5.4,214.6,144,147,5.4,164.6,2.5))
    for x in (12,208):
        for z in (12,158):
            lip=lip.cut(box(x-12,x+12,143,148,z-12,z+12))
            door=door.cut(cyl("y",145,152,x,z,BOLT_R))
    # Clear the bottom shell seam tab where the rear locating lip crosses the centre.
    lip=lip.cut(box(100,123,143,147,2,8))
    door=union(door,lip)
    for x in (42,52,62,72,82,132,142,152,162,172):
        for z in (32,120): door=door.cut(box(x,x+3,143,152,z,z+18))
    door=door.cut(box(174,186,143,152,25,33))  # cable opening, not an invented connector
    left=door.intersect(box(0,110,142,152,0,171))
    right=door.intersect(box(110.25,220,142,152,0,171))
    for z in (50,85,145):
        tab=box(102,121,141,146.5,z-7,z+7)
        tab=tab.cut(cyl("y",140,152,116,z,BOLT_R),hexhole("y",140.9,144.6,116,z,NUT_AF))
        left=union(left,tab)
        right=right.cut(cyl("y",140,152,116,z,BOLT_R))
    add("05_door_left",left,"#bd493f")
    add("06_door_right",right,"#bd493f")


def tray():
    t=box(25,195,30,139,9,12)
    for y in (62,104): t=union(t,box(32,188,y,y+4,12,15.5))
    for x in (64,156):
        for y in (68,102):
            t=union(t,cyl("z",12,PI_Z,x,y,6))
            t=t.cut(cyl("z",3,PI_Z+1,x,y,BOLT_R))
    for x in (33,187):
        t=union(t,box(x-5.5,x+5.5,124,136,9,15))
        t=t.cut(cyl("z",-2,16,x,130,BOLT_R))
    left=t.intersect(box(0,110,0,145,0,21))
    right=t.intersect(box(110.25,220,0,145,0,21))
    for y in (45,120):
        tab=box(102,121,y-8,y+8,12,17.5)
        tab=tab.cut(cyl("z",8,18,116,y,BOLT_R),hexhole("z",13.9,17.6,116,y,NUT_AF))
        left=union(left,tab)
        right=right.cut(cyl("z",8,18,116,y,BOLT_R))
    add("07_tray_left",left,"#399a88")
    add("08_tray_right",right,"#399a88")


def yoke():
    lower=union(box(-14,-6,-10,160,-25,-17),box(-14,-6,65,85,-25,145))
    lower=lower.cut(box(-14.1,-10,64,86,125,146))
    for z in (130,140): lower=lower.cut(cyl("x",-15,-5,75,z,2.25))
    lower=lower.cut(cyl("x",-15,-5,75,85,BOLT_R))
    upper=union(box(-14,-6,65,85,145,195),box(-14,-10,65,85,125,145),
                box(-14,120,65,85,187,195))
    for z in (130,140): upper=upper.cut(cyl("x",-15,-5,75,z,2.25))
    upper=upper.cut(box(100,121,64,86,191,196))
    for x in (105,115): upper=upper.cut(cyl("z",186,196,x,75,2.25))
    right_lower=lower.mirror("YZ",(W/2,0,0))
    # The right top crossbar has the complementary half lap at the centre.
    right_upper=union(box(226,234,65,85,145,195),box(230,234,65,85,125,145),
                      box(100,234,65,85,187,195))
    right_upper=right_upper.cut(box(99,120,64,86,186,191.25))
    for z in (130,140): right_upper=right_upper.cut(cyl("x",225,235,75,z,2.25))
    for x in (105,115): right_upper=right_upper.cut(cyl("z",186,196,x,75,2.25))
    add("09_yoke_lower_left",lower,"#91a5b4")
    add("10_yoke_lower_right",right_lower,"#91a5b4")
    add("11_yoke_upper_left",upper,"#91a5b4")
    add("12_yoke_upper_right",right_upper,"#91a5b4")
    spacer=cyl("x",-5,0,75,85,16).cut(cyl("x",-6,1,75,85,BOLT_R))
    add("spacer_left",spacer,"#677b8b")
    add("spacer_right",spacer.mirror("YZ",(W/2,0,0)),"#677b8b")
    knob=cyl("x",-27,-15,75,85,17).cut(cyl("x",-28,-14,75,85,BOLT_R),
                 hexhole("x",-27.1,-23.4,75,85,NUT_AF))
    for i in range(12):
        angle=2*math.pi*i/12
        knob=knob.cut(cyl("x",-28,-14,75+17*math.cos(angle),85+17*math.sin(angle),1.4))
    add("knob_left",knob,"#bd493f")
    add("knob_right",knob.mirror("YZ",(W/2,0,0)),"#bd493f")


def to_mesh(shape):
    verts,faces=shape.tessellate(.08,.12)
    return trimesh.Trimesh(np.array([v.toTuple() for v in verts]),np.array(faces),process=True)


def optical_module():
    """Reuse project light-tight body/interfaces, remove rods, fuse fixed LED sockets."""
    body=trimesh.load_mesh(SOURCE/"01_than_hop_toi.stl")
    def mb(*a): return to_mesh(box(*a))
    for cy in (32.25,70.75):
        cuts=[mb(-1,16,cy-6,cy+6,18.7,29.3),
              mb(21,25,cy-6,cy+6,3,21),mb(123,129,cy-6,cy+6,3,21)]
        body=trimesh.boolean.difference([body,*cuts],engine="manifold")
        plug=mb(16,21.5,cy-3.05,cy+3.05,20.95,27.05)
        body=trimesh.boolean.union([body,plug],engine="manifold")
    for name,front,cy in (("red",94.,32.25),("ir",34.,70.75)):
        # Preserve the old LED shoulder, bore and nominal tip position, without a shaft bore.
        f=front+18
        carrier=union(box(f-22,f,cy-9,cy+9,5,40),box(f-22,f,cy-12,cy+12,3,7),
                      cq.Solid.makeCone(5.2,2.1,3,cq.Vector(f,cy,32),cq.Vector(1,0,0)))
        carrier=carrier.cut(cyl("x",f-9,f+3.2,cy,32,1.65),
                            cyl("x",f-10.4,f-9,cy,32,2.05),
                            cyl("x",f-22.1,f-10.4,cy,32,2.6))
        for yy in (cy-9,cy+6.4): carrier=carrier.cut(box(f-20,f-16,yy,yy+2.6,29.4,34.6))
        body=trimesh.boolean.union([body,to_mesh(carrier)],engine="manifold")
    assert body.is_volume and len(body.split(only_watertight=False))==1
    fixed=OUT/"print/17_optical_body_fixed_LED.stl"
    for x in (39,147):
        for y in (6,97):
            body=trimesh.boolean.difference([body,to_mesh(cyl("z",-1,5,x,y,BOLT_R))],engine="manifold")
    # Keep the original print orientation; no mounting pattern or receiver geometry scaled.
    body.export(fixed)
    body.apply_translation([17,34,OPT_Z])
    refs={"optical_body":body}
    pi=trimesh.load_mesh(SOURCE/"than_hop_pi4.stl")
    # Replace the narrow M3 front ears by 16 mm M4 ears, with a 12 mm nut corridor.
    front_cuts=[mb(x-8,x+8,80,92,53.9,70.1) for x in (6,114)]
    pi=trimesh.boolean.difference([pi,*front_cuts],engine="manifold")
    for x in (6,114):
        pieces=[mb(x-8,x+8,77,91,66,70)]
        for edge in (x-8,x+6):
            v=np.array([[xx,y,z] for xx in (edge,edge+2)
                        for y,z in ((79,54),(79,66),(91,66))])
            pieces.append(trimesh.convex.convex_hull(v))
        pi=trimesh.boolean.union([pi,*pieces],engine="manifold")
    for x in (6,114):
        for y in (-6,85):
            pi=trimesh.boolean.difference([pi,to_mesh(cyl("z",53,71,x,y,BOLT_R))],engine="manifold")
    for x in (14,106):
        for y in (22,56):
            slot=union(cyl("z",-1,4,x,y-4.25,BOLT_R),
                       cyl("z",-1,4,x,y+4.25,BOLT_R),
                       box(x-BOLT_R,x+BOLT_R,y-4.25,y+4.25,-1,4))
            pi=trimesh.boolean.difference([pi,to_mesh(slot)],engine="manifold")
    assert pi.is_volume and len(pi.split(only_watertight=False))==1
    pi.export(OUT/"print/18_pi_housing_m4.stl")
    pi.apply_translation([50,46,PI_Z]);refs["pi_housing"]=pi
    # Reuse lid and hoods in original world coordinates to avoid guessing print transforms.
    sys.path.insert(0,str(ROOT))
    import build_system as legacy
    legacy.DETAIL="full"
    T=np.array([[1,0,0,35],[0,0,1,85.5],[0,1,0,OPT_Z],[0,0,0,1]],float)
    lid=legacy.build_lid();lid.apply_transform(T);refs["optical_lid"]=lid
    for sign in (-1,1):
        for channel,zc in legacy.LANE_Z.items():
            hood=legacy.build_hood(sign)
            hood.apply_translation([0 if sign<0 else 150,0,zc])
            hood.apply_transform(T)
            refs[f"hood_{sign}_{channel}"]=hood
    return refs


def build():
    (OUT/"print").mkdir(parents=True,exist_ok=True)
    (OUT/"step").mkdir(exist_ok=True)
    shell();bezel();rear();tray();yoke()
    records=[]
    assy=cq.Assembly(name="PPG_Cyberdock_M4")
    assembly_meshes={}
    for name,shape in PARTS.items():
        cq.exporters.export(shape,str(OUT/"step"/(name+".step")))
        assy.add(shape,name=name,color=cq.Color(COLORS[name]))
        mesh=to_mesh(shape);assembly_meshes[name]=mesh.copy()
        # Put the broad face down: shell/yoke/knobs normal to X; face/tray normal to Y/Z.
        if any(k in name for k in ("shell","yoke","spacer","knob")):
            R=np.array([[0,1,0],[0,0,1],[1,0,0]],float)
            if "right" in name: R[[0,2]]*=-1
            if "knob" in name: R[[0,2]]*=-1  # print nut pocket upward
        elif any(k in name for k in ("bezel","door","clip")):
            R=np.array([[1,0,0],[0,0,1],[0,-1,0]],float)
            if "bezel" in name: R[[0,2]]*=-1  # flat front face on bed, bosses upward
        else: R=np.eye(3)
        assert np.isclose(np.linalg.det(R),1),name  # rotate for printing; never mirror a part
        print_mesh=mesh.copy();T=np.eye(4);T[:3,:3]=R
        print_mesh.apply_transform(T)
        T[:3,3]=-print_mesh.bounds[0]
        print_mesh=mesh.copy();print_mesh.apply_transform(T)
        assert print_mesh.is_volume,name
        assert np.all(print_mesh.extents<=180.001),(name,print_mesh.extents)
        target=OUT/"print"/(name+".stl");print_mesh.export(target)
        records.append({"name":name,"print_file":target.name,"size_mm":print_mesh.extents.tolist(),
                        "volume_mm3":mesh.volume,"assembly_to_print":T.tolist(),
                        "sha256":hashlib.sha256(target.read_bytes()).hexdigest()})
    cq.exporters.export(assy.toCompound(),str(OUT/"enclosure_assembly.step"))
    references=optical_module()
    optical_print=OUT/"print/17_optical_body_fixed_LED.stl"
    optical_size=trimesh.load_mesh(optical_print).extents.tolist()
    pi_print=OUT/"print/18_pi_housing_m4.stl"
    screen=to_mesh(box((W-SCREEN_W)/2,(W+SCREEN_W)/2,.5,SCREEN_T+.5,SCREEN_Z,SCREEN_Z+SCREEN_H))
    references["screen_ENVELOPE_ONLY"]=screen
    scene=trimesh.Scene()
    for name,mesh in {**assembly_meshes,**references}.items():
        col=COLORS.get(name,"#343b42" if "optical" in name or "hood" in name else "#667887")
        from PIL import ImageColor
        mesh.visual.face_colors=ImageColor.getrgb(col)+(255,)
        scene.add_geometry(mesh,geom_name=name,node_name=name)
    # One assembly file, separate named objects; the purchased screen is not a print object.
    printable=trimesh.Scene()
    for name,mesh in {**assembly_meshes,**references}.items():
        if name!="screen_ENVELOPE_ONLY":
            item=mesh.copy();item.process(validate=True)
            printable.add_geometry(item,geom_name=name,node_name=name)
    printable.apply_translation(PACK_SHIFT)
    (OUT/"PPG_Cyberdock_M4.3mf").write_bytes(trimesh.exchange.threemf.export_3MF(printable))
    gltf_scene=scene.copy()
    gltf_scene.apply_scale(.001)  # glTF uses metres; STEP/STL and QA remain in mm
    gltf_scene.export(OUT/"assembly.glb")
    manifest={"units":"mm","screen_frame_confirmed_mm":[178,105],"screen_thickness_assumed_mm":SCREEN_T,
              "screen_window_provisional_mm":[170,97],"body_sleeve_mm":[W,H,D],
              "body_with_front_rear_mm":[W,H,155],"fixed_optical_distances_mm":{"red":25,"ir":85},
              "parts":records,"fasteners":"M4 only, structural joints",
              "single_assembly_file":"PPG_Cyberdock_M4.3mf",
              "assembly_3mf_translation_mm":PACK_SHIFT,
              "module_translations_mm":{"pi_housing":[50,46,PI_Z],"optical_body":[17,34,OPT_Z]},
              "fixed_optical_body":{"print_file":optical_print.name,"size_mm":optical_size,
                  "print_to_assembly_translation_mm":[17,34,OPT_Z],"native_step":False,
                  "sha256":hashlib.sha256(optical_print.read_bytes()).hexdigest()},
              "pi_housing_m4":{"print_file":pi_print.name,
                  "size_mm":trimesh.load_mesh(pi_print).extents.tolist(),
                  "print_to_assembly_translation_mm":[50,46,PI_Z],
                  "sha256":hashlib.sha256(pi_print.read_bytes()).hexdigest()},
              "source_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (SOURCE/"01_than_hop_toi.stl",SOURCE/"than_hop_pi4.stl",ROOT/"build_system.py")},
              "status":"Engineering prototype; physical screen/cables/loads not validated."}
    (OUT/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    # Save raw assembly meshes for geometric QA; these are NOT extra print files.
    (OUT/"assembly_meshes").mkdir(exist_ok=True)
    for name,mesh in {**assembly_meshes,**references}.items(): mesh.export(OUT/"assembly_meshes"/(name+".stl"))
    for name in ("02_nap_labyrinth.stl","06_chup_luon_day_trai.stl","07_chup_luon_day_phai.stl",
                 "13_khung_board_5x7.stl","14_ga_chu_U_OPT101_70x20.stl","15_ga_chu_U_BPW34_70x20.stl",
                 "16_ga_driver_70x40.stl","08_khau_do_biet.stl",
                 "09_khau_do_lo2mm.stl","10_khau_do_lo5mm.stl","11_khau_do_lo16mm.stl"):
        (OUT/"reuse").mkdir(exist_ok=True);shutil.copy2(SOURCE/name,OUT/"reuse"/name)
    # The former M3-only generated copy must not be mistaken for the new M4 housing.
    (OUT/"reuse/than_hop_pi4.stl").unlink(missing_ok=True)
    print(f"Built {len(PARTS)} CAD solids, fixed optical body and assembly; run verify.py before use.")





base_shell=shell
base_bezel=bezel
base_yoke=yoke
base_optical=optical_module

def shell():
    base_shell()
    for name in ('01_shell_left','02_shell_right'):
        s=PARTS.pop(name);COLORS.pop(name)
        front=s.intersect(box(-50,270,-1,100,-30,210))
        back=s.intersect(box(-50,270,100.25,151,-30,210))
        x=40 if 'left' in name else 180
        for za,zb in ((3,8.5),(161.5,167)):
            tab=box(x-7,x+7,92,115,za,zb).cut(cyl('z',za-1,zb+1,x,108,BOLT_R))
            na,nb=(4.9,8.6) if za<20 else (161.4,165.1)
            tab=tab.cut(hexhole('z',na,nb,x,108,NUT_AF))
            front=union(front,tab)
            back=back.cut(cyl('z',za-1,zb+1,x,108,BOLT_R),box(x-7.25,x+7.25,100,115.25,za-.25,zb+.25))
        add(name+'_front',front,'#bd493f');add(name+'_rear',back,'#bd493f')

def bezel():
    base_bezel()
    for z,label in ((12,'bottom'),(158,'top')):
        bar=rounded(5,215,-6,-4.5,z-5,z+5,3)
        for x in (12,208,116):bar=bar.cut(cyl('y',-7,-4,x,z,BOLT_R))
        # Centre bezel seam holes are at different Z; only corner screws retain trim.
        for side,xa,xb in (('left',0,110),('right',110.25,220)):
            add('trim_'+label+'_'+side,bar.intersect(box(xa,xb,-7,-4,0,171)),'#91a5b4')
    for x,label in ((12,'left'),(208,'right')):
        bar=rounded(x-2,x+2,-6,-4.5,30,140,1.8)
        # Pins locate the cosmetic strip without introducing another fastener size.
        for z in (40,135):
            bar=union(bar,cyl('y',-4.5,-2,x,z,1.1))
            name='03_bezel_left' if x<110 else '04_bezel_right'
            PARTS[name]=PARTS[name].cut(cyl('y',-4.6,-1.9,x,z,1.25))
        add('trim_side_'+label,bar,'#91a5b4')

def yoke():
    base_yoke()
    for label in ('left','right'):
        name='knob_'+label
        PARTS[name]=PARTS[name].translate((-6 if label=='left' else 6,0,0))
    gear=cyl('x',-20,-14,75,85,21)
    for i in range(32):gear=union(gear,box(-20,-14,95,100,83.6,86.4).rotate((0,75,85),(1,75,85),i*360/32))
    gear=gear.cut(cyl('x',-21,-13,75,85,BOLT_R))
    add('gear_left',gear,'#91a5b4');add('gear_right',gear.mirror('YZ',(110,0,0)),'#91a5b4')

def optical_module():
    refs=base_optical()
    bridge=to_mesh(box(38,182,84.875,86.125,OPT_Z+63.95,OPT_Z+64.2))
    refs['optical_lid']=trimesh.boolean.union([refs['optical_lid'],bridge],engine='manifold')
    for m in refs.values():m.process(validate=True)
    return refs

if __name__=='__main__':build()
