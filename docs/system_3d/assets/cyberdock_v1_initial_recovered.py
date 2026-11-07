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
SCREEN_W, SCREEN_H, SCREEN_T = 178., 105., 20.  # thickness still unmeasured
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
                s = s.cut(cyl("y",ya-1,yb+1,x,z,1.75))
                na,nb = (7.3,10.1) if ya==0 else (135.9,138.7)
                s = s.cut(hexhole("y",na,nb,x,z,5.8))
    for right in (False,True):
        xa,xb = (208,220) if right else (0,12)
        s = union(s,cyl("x",xa,xb,75,85,18))
        s = s.cut(cyl("x",xa-1,xb+1,75,85,3.3))
        # Bolt head is retained inside the boss, accessible through the rear door.
        ha,hb = (207.9,212.5) if right else (7.5,12.1)
        s = s.cut(hexhole("x",ha,hb,75,85,10.4))
        for y in (105,112,119,126):
            s = s.cut(box(xa-1,xb+1,y,y+3,28,45))
    # Integral guide ledges; 1 mm vertical and lateral working clearance around tray.
    for x in (22,189):
        s = union(s,box(x,x+9,27,143,3,7))
    s = union(s,box(22,24,27,143,3,13),box(196,198,27,143,3,13),
              box(22,27,27,143,11,13),box(193,198,27,143,11,13),
              box(25,195,27,30,3,10))
    for x in (40,180):
        b = box(x-6,x+6,137,143,3,20)
        b = b.cut(cyl("y",136,144,x,14,1.75),cyl("y",140,144,x,14,3.25))
        s = union(s,b)
    left = s.intersect(box(-1,110,-1,151,-1,171))
    right = s.intersect(box(110.25,221,-1,151,-1,171))
    for ya,yb,za,zb in ((12,24,163,167),(126,138,163,167),(8,20,3,7)):
        tab = box(102,121,ya,yb,za,zb)
        y = (ya+yb)/2
        tab = tab.cut(cyl("z",za-1,zb+1,116,y,1.75))
        hn0,hn1 = (za-.1,za+2.7) if za>100 else (zb-2.7,zb+.1)
        tab = tab.cut(hexhole("z",hn0,hn1,116,y,5.8))
        left = union(left,tab)
        right = right.cut(cyl("z",-1,171,116,y,1.75))
    add("01_shell_left",left,"#bd493f")
    add("02_shell_right",right,"#bd493f")


def bezel():
    f = rounded(0,W,-4.5,0,0,H,8).cut(rounded(25,195,-5,1,42,139,3))
    f = union(f,box(17,20.5,0,8,35,146),box(199.5,203,0,8,35,146),
              box(18,202,0,23,34,37.5),box(18,202,0,8,143.5,147))
    for x in (14.5,205.5):
        for z in (52,127):
            b=box(x-5.5,x+5.5,0,SCREEN_T+1,z-6,z+6)
            b=b.cut(cyl("y",-5,SCREEN_T+2,x,z,1.75),
                    hexhole("y",-0.1,2.7,x,z,5.8))
            f=union(f,b)
    for x in (12,208):
        for z in (12,158): f=f.cut(cyl("y",-5,1,x,z,1.75))
    left=f.intersect(box(-1,110,-5,30,-1,171))
    right=f.intersect(box(110.25,221,-5,30,-1,171))
    for z in (18,155):
        tab=box(102,121,0,4,z-6,z+6)
        tab=tab.cut(cyl("y",-5,5,116,z,1.75),hexhole("y",1.3,4.1,116,z,5.8))
        left=union(left,tab)
        right=right.cut(cyl("y",-5,5,116,z,1.75))
    add("03_bezel_left",left,"#a73e36")
    add("04_bezel_right",right,"#a73e36")
    # One clip geometry, mirrored for the opposite frame edge.
    clip=union(box(9,30,SCREEN_T+1.5,SCREEN_T+4.5,47,57),
               box(21,25,SCREEN_T+.5,SCREEN_T+1.5,47,57))
    clip=clip.cut(cyl("y",SCREEN_T,SCREEN_T+6,14.5,52,1.75))
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
            door=door.cut(cyl("y",145,152,x,z,1.75))
    # Clear the bottom shell seam tab where the rear locating lip crosses the centre.
    lip=lip.cut(box(100,123,143,147,2,8))
    door=union(door,lip)
    for x in (42,52,62,72,82,132,142,152,162,172):
        for z in (32,120): door=door.cut(box(x,x+3,143,152,z,z+18))
    door=door.cut(box(174,186,143,152,25,33))  # cable opening, not an invented connector
    left=door.intersect(box(0,110,142,152,0,171))
    right=door.intersect(box(110.25,220,142,152,0,171))
    for z in (50,85,145):
        tab=box(102,121,142.5,146.5,z-6,z+6)
        tab=tab.cut(cyl("y",142,152,116,z,1.75),hexhole("y",142.4,145.2,116,z,5.8))
        left=union(left,tab)
        right=right.cut(cyl("y",142,152,116,z,1.75))
    add("05_door_left",left,"#bd493f")
    add("06_door_right",right,"#bd493f")


def tray():
    t=box(25,195,30,139,7,10)
    for y in (57,109): t=union(t,box(32,188,y,y+4,3.5,7))
    for x in (64,156):
        for y in (68,102):
            t=union(t,cyl("z",10,14,x,y,4.5))
            t=t.cut(cyl("z",3,15,x,y,1.75))
    for x in (40,180):
        tab=box(x-6,x+6,132,136,7,20)
        tab=tab.cut(cyl("y",131,144,x,14,1.75),hexhole("y",131.9,134.7,x,14,5.8))
        t=union(t,tab)
    left=t.intersect(box(0,110,0,145,0,21))
    right=t.intersect(box(110.25,220,0,145,0,21))
    for y in (45,120):
        tab=box(102,121,y-8,y+8,10,13)
        tab=tab.cut(cyl("z",6,14,116,y,1.75),hexhole("z",10.3,13.1,116,y,5.8))
        left=union(left,tab)
        right=right.cut(cyl("z",6,14,116,y,1.75))
    add("07_tray_left",left,"#399a88")
    add("08_tray_right",right,"#399a88")


def yoke():
    lower=union(box(-14,-6,-10,160,-25,-17),box(-14,-6,65,85,-25,145))
    lower=lower.cut(box(-14.1,-10,64,86,125,146))
    for z in (131,139): lower=lower.cut(cyl("x",-15,-5,75,z,2.25))
    lower=lower.cut(cyl("x",-15,-5,75,85,3.3))
    upper=union(box(-14,-6,65,85,145,195),box(-14,-10,65,85,125,145),
                box(-14,120,65,85,187,195))
    for z in (131,139): upper=upper.cut(cyl("x",-15,-5,75,z,2.25))
    upper=upper.cut(box(100,121,64,86,191,196))
    for x in (106,114): upper=upper.cut(cyl("z",186,196,x,75,2.25))
    right_lower=lower.mirror("YZ",(W/2,0,0))
    # The right top crossbar has the complementary half lap at the centre.
    right_upper=union(box(226,234,65,85,145,195),box(230,234,65,85,125,145),
                      box(100,234,65,85,187,195))
    right_upper=right_upper.cut(box(99,120,64,86,186,191.25))
    for z in (131,139): right_upper=right_upper.cut(cyl("x",225,235,75,z,2.25))
    for x in (106,114): right_upper=right_upper.cut(cyl("z",186,196,x,75,2.25))
    add("09_yoke_lower_left",lower,"#91a5b4")
    add("10_yoke_lower_right",right_lower,"#91a5b4")
    add("11_yoke_upper_left",upper,"#91a5b4")
    add("12_yoke_upper_right",right_upper,"#91a5b4")
    spacer=cyl("x",-5,0,75,85,16).cut(cyl("x",-6,1,75,85,3.3))
    add("spacer_left",spacer,"#677b8b")
    add("spacer_right",spacer.mirror("YZ",(W/2,0,0)),"#677b8b")
    knob=cyl("x",-27,-15,75,85,17).cut(cyl("x",-28,-14,75,85,3.3),
                 hexhole("x",-27.1,-21.5,75,85,10.4))
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
    # Keep the original print orientation; no mounting pattern or receiver geometry scaled.
    body.export(fixed)
    body.apply_translation([17,34,84])
    refs={"optical_body":body}
    pi=trimesh.load_mesh(SOURCE/"than_hop_pi4.stl");pi.apply_translation([50,46,14]);refs["pi_housing"]=pi
    # Reuse lid and hoods in original world coordinates to avoid guessing print transforms.
    sys.path.insert(0,str(ROOT))
    import build_system as legacy
    legacy.DETAIL="full"
    T=np.array([[1,0,0,35],[0,0,1,85.5],[0,1,0,84],[0,0,0,1]],float)
    lid=legacy.build_lid();lid.apply_transform(T);lid.invert();refs["optical_lid"]=lid
    for sign in (-1,1):
        for channel,zc in legacy.LANE_Z.items():
            hood=legacy.build_hood(sign)
            hood.apply_translation([0 if sign<0 else 150,0,zc])
            hood.apply_transform(T);hood.invert()
            refs[f"hood_{sign}_{channel}"]=hood
    return refs


def build():
    (OUT/"print").mkdir(parents=True,exist_ok=True)
    (OUT/"step").mkdir(exist_ok=True)
    shell();bezel();rear();tray();yoke()
    records=[]
    assy=cq.Assembly(name="PPG_Cyberdock_v1")
    assembly_meshes={}
    for name,shape in PARTS.items():
        cq.exporters.export(shape,str(OUT/"step"/(name+".step")))
        assy.add(shape,name=name,color=cq.Color(COLORS[name]))
        mesh=to_mesh(shape);assembly_meshes[name]=mesh.copy()
        # Put the broad face down: shell/yoke/knobs normal to X; face/tray normal to Y/Z.
        if any(k in name for k in ("shell","yoke","spacer","knob")):
            R=np.array([[0,1,0],[0,0,1],[1,0,0]],float)
            if "right" in name: R[2]*=-1
        elif any(k in name for k in ("bezel","door","clip")):
            R=np.array([[1,0,0],[0,0,1],[0,-1,0]],float)
        else: R=np.eye(3)
        print_mesh=mesh.copy();T=np.eye(4);T[:3,:3]=R
        print_mesh.apply_transform(T)
        T[:3,3]=-print_mesh.bounds[0]
        print_mesh=mesh.copy();print_mesh.apply_transform(T)
        # Reflections reverse triangle winding; Trimesh apply_transform handles this.
        assert print_mesh.is_volume,name
        assert np.all(print_mesh.extents<=180.001),(name,print_mesh.extents)
        target=OUT/"print"/(name+".stl");print_mesh.export(target)
        records.append({"name":name,"print_file":target.name,"size_mm":print_mesh.extents.tolist(),
                        "volume_mm3":mesh.volume,"assembly_to_print":T.tolist(),
                        "sha256":hashlib.sha256(target.read_bytes()).hexdigest()})
    cq.exporters.export(assy.toCompound(),str(OUT/"enclosure_assembly.step"))
    references=optical_module()
    screen=to_mesh(box(21,199,.5,SCREEN_T+.5,38,143))
    references["screen_ENVELOPE_ONLY"]=screen
    scene=trimesh.Scene()
    for name,mesh in {**assembly_meshes,**references}.items():
        col=COLORS.get(name,"#343b42" if "optical" in name or "hood" in name else "#667887")
        from PIL import ImageColor
        mesh.visual.face_colors=ImageColor.getrgb(col)+(255,)
        scene.add_geometry(mesh,geom_name=name,node_name=name)
    scene.export(OUT/"assembly.glb")
    manifest={"units":"mm","screen_frame_confirmed_mm":[178,105],"screen_thickness_assumed_mm":SCREEN_T,
              "screen_window_provisional_mm":[170,97],"body_sleeve_mm":[W,H,D],
              "body_with_front_rear_mm":[W,H,155],"fixed_optical_distances_mm":{"red":25,"ir":85},
              "parts":records,"status":"Engineering prototype; physical screen/cables/loads not validated."}
    (OUT/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    # Save raw assembly meshes for geometric QA; these are NOT extra print files.
    (OUT/"assembly_meshes").mkdir(exist_ok=True)
    for name,mesh in {**assembly_meshes,**references}.items(): mesh.export(OUT/"assembly_meshes"/(name+".stl"))
    for name in ("02_nap_labyrinth.stl","06_chup_luon_day_trai.stl","07_chup_luon_day_phai.stl",
                 "13_khung_board_5x7.stl","14_ga_chu_U_OPT101_70x20.stl","15_ga_chu_U_BPW34_70x20.stl",
                 "16_ga_driver_70x40.stl"):
        (OUT/"reuse").mkdir(exist_ok=True);shutil.copy2(SOURCE/name,OUT/"reuse"/name)
    print(f"Built {len(PARTS)} CAD solids, fixed optical body and assembly; run verify.py before use.")


if __name__=="__main__": build()
