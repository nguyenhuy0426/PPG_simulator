"""Modern-Mac-style PPG enclosure (V2): screen tilted back, low forward base.

mm, X across / Y rearward / Z up.  The shell, rear door, tray, Pi case and optical
chamber keep their V1 assembly coordinates; only the front is new.  Front cap =
one hollow prism (low base + leaning slab), screen plane tilted TILT_DEG backward
(top edge further back).  Screen features are built in a local frame (x across,
y' = rearward along -normal, z' = up the slope) and rotated into the assembly.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import cadquery as cq
import numpy as np
import trimesh
from PIL import ImageColor

HERE=Path(__file__).resolve().parent
OUT=HERE/'out'
spec=importlib.util.spec_from_file_location('ppg_cyberdock',HERE.parent/'cyberdock_v3/build.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
b.HERE=HERE;b.OUT=OUT
box,cyl,hexhole,rounded,union,add=b.box,b.cyl,b.hexhole,b.rounded,b.union,b.add
PARTS,COLORS=b.PARTS,b.COLORS
R,AF=2.25,7.4
CREAM,ACCENT='#d9cbb0','#c6b99f'

TILT_DEG=10.
TH=math.radians(TILT_DEG);C,S,T=math.cos(TH),math.sin(TH),math.tan(TH)
HB=30.          # base height
YT=-9.          # slab front face at the roof line (z=170)
FRONT=50.       # base front face, forward of the shell front plane Y=0
WALL,SLAB=3.,10.
H_TOP=170.
YB=YT-(H_TOP-HB)*T            # slab front face meets base top here
Y0=YB+SLAB*C;Z0=HB-SLAB*S     # local->world offset
SCR_Z0,SCR_Z1,ZC=15.,120.,67.5   # screen / window centre, local z'
TAB_Z=(7.,128.)                 # cap seam tabs, local z'
CLIP_Z=(29.,104.)
CAP_BOLT_X,CAP_BOLT_Y=(40.,180.),7.


def yfront(z):return YT-(H_TOP-z)*T
def yin(z):return yfront(z)+SLAB/C


def L2W(s):
    """Local screen frame -> assembly frame."""
    return s.rotate((0,0,0),(1,0,0),-TILT_DEG).translate((0,Y0,Z0))


def L4():
    rot=trimesh.transformations.rotation_matrix(-TH,[1,0,0])
    return trimesh.transformations.translation_matrix([0,Y0,Z0])@rot


def prism(pts,x0,x1):
    return cq.Workplane('YZ',origin=(x0,0,0)).polyline(pts).close().extrude(x1-x0).val()


def window_wire(y,w,h,r):
    wire=cq.Workplane('XZ',origin=(110,y,ZC)).rect(w,h).val()
    return wire.fillet2D(r,wire.Vertices())


def shell():
    s=rounded(0,220,0,150,0,170,3).cut(rounded(3,217,-1,151,3,167,.8))
    for x in (12,208):
        for z in (12,158):
            s=union(s,box(x-9,x+9,136,146,z-9,z+9))
            s=s.cut(cyl('y',135,147,x,z,R),hexhole('y',135.9,139.6,x,z,AF))
    for z in (28,37,46,120,129):
        s=s.cut(box(-1,221,101,132,z,z+3))
    for xa,xb in ((22,40),(180,198)):s=union(s,box(xa,xb,27,143,3,9))
    s=union(s,box(22,24,27,143,3,15),box(196,198,27,143,3,15),
            box(22,27,27,143,13,15),box(193,198,27,143,13,15),
            box(25,195,27,30,3,12))
    for x in (33,187):s=s.cut(cyl('z',-2,16,x,130,R),hexhole('z',-.1,3.6,x,130,AF))
    # Front-cap retaining screws: vertical, through floor and roof at x=40/180.
    for x in CAP_BOLT_X:s=s.cut(cyl('z',-1,4,x,CAP_BOLT_Y,R),cyl('z',166,171,x,CAP_BOLT_Y,R))
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


def cap():
    outer=prism([(-FRONT,0),(-FRONT,HB),(YB,HB),(YT,H_TOP),(0,H_TOP),(0,0)],0,220)
    outer=outer.intersect(rounded(0,220,-80,1,0,170,3))
    cavity=prism([(-FRONT+WALL,WALL),(-FRONT+WALL,HB-WALL),(yin(HB-WALL),HB-WALL),
                  (yin(167),167),(1,167),(1,WALL)],WALL,220-WALL)
    c=outer.cut(cavity)
    for z in (8,13,18,23):c=c.cut(box(-1,4,-42,-12,z,z+2.5),box(216,221,-42,-12,z,z+2.5))
    # Front of the base: round badge recess, drive slot and eject-button recess.
    c=c.cut(cyl('y',-FRONT-1,-FRONT+.8,45,15,9),box(105,195,-FRONT-1,-FRONT+2,11,14),
            box(182,192,-FRONT-1,-FRONT+1,17.5,20.5))
    # Tapered window then straight aperture, in the tilted frame.
    loft=cq.Solid.makeLoft([window_wire(-10.1,174,101,5),window_wire(-4.4,170,97,3)],ruled=True)
    c=c.cut(L2W(loft),L2W(rounded(25,195,-5,1,ZC-48.5,ZC+48.5,3)))
    for x in (13.5,206.5):
        for z in CLIP_Z:
            boss=box(x-7,x+7,0,11,z-7,z+7).cut(cyl('y',-5,12,x,z,R),hexhole('y',2,5.6,x,z,AF))
            slot=box(x-7.1,x+.2,2,5.6,z-3.9,z+3.9) if x<110 else box(x-.2,x+7.1,2,5.6,z-3.9,z+3.9)
            c=union(c,L2W(boss.cut(slot))).cut(L2W(hexhole('y',2,5.6,x,z,AF)),L2W(slot))
    left=c.intersect(box(-1,110,-100,60,-1,171))
    right=c.intersect(box(110.25,221,-100,60,-1,171))
    for z in TAB_Z:
        tab=box(102,121,0,5.5,z-7,z+7).cut(cyl('y',-11,6,116,z,R),hexhole('y',1.9,5.6,116,z,AF))
        left=union(left,L2W(tab));right=right.cut(L2W(cyl('y',-11,6,116,z,R)))
    # Tabs that reach into the shell: floor tab (bolt from below) and roof tab (bolt from above).
    for part,x in ((0,CAP_BOLT_X[0]),(1,CAP_BOLT_X[1])):
        y=CAP_BOLT_Y
        floor=box(x-9,x+9,-10,14,3,8.5).cut(cyl('z',2,9.5,x,y,R),hexhole('z',4.9,8.6,x,y,AF))
        roof=box(x-9,x+9,-4,14,161.5,167).cut(cyl('z',160.5,168,x,y,R),hexhole('z',161.4,165.1,x,y,AF))
        if part==0:left=union(left,floor,roof)
        else:right=union(right,floor,roof)
    add('03_cap_left',left,CREAM);add('04_cap_right',right,CREAM)
    clip=union(box(6.5,30,11.5,14.5,CLIP_Z[0]-7,CLIP_Z[0]+7),box(21,25,10.5,11.5,CLIP_Z[0]-7,CLIP_Z[0]+7))
    clip=clip.cut(cyl('y',10,16,13.5,CLIP_Z[0],R))
    for side in (0,1):
        for high in (0,1):
            p=clip if side==0 else clip.mirror('YZ',(110,0,0))
            add(f'clip_{side}_{high}',L2W(p.translate((0,0,(CLIP_Z[1]-CLIP_Z[0])*high))),ACCENT)


def rear():
    b.rear()
    for name in ('05_door_left','06_door_right'):COLORS[name]=CREAM


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
    for y in (35,136):
        tab=box(102,121,y-8,y+8,12,17.5).cut(cyl('z',8,22,116,y,R),hexhole('z',13.9,17.6,116,y,AF))
        left=union(left,tab);right=right.cut(cyl('z',8,22,116,y,R))
    add('07_tray_left',left,'#72958a');add('08_tray_right',right,'#72958a')


def print_transform(name,mesh):
    """Rigid (det +1) assembly->print matrix; broad face down."""
    M=np.eye(4)
    if 'shell' in name:
        R3=np.array([[0,1,0],[0,0,1],[1,0,0]],float)
        if 'right' in name:R3[[0,2]]*=-1
        M[:3,:3]=R3
    elif 'door' in name:
        M[:3,:3]=np.array([[1,0,0],[0,0,1],[0,-1,0]],float)
    elif name.startswith('clip'):
        rx=np.array([[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1]],float)  # (x,y,z)->(x,-z,y)
        M=rx@np.linalg.inv(L4())
    pm=mesh.copy();pm.apply_transform(M)
    M[:3,3]+=-pm.bounds[0]
    assert np.isclose(np.linalg.det(M[:3,:3]),1),name
    return M


def build():
    (OUT/'print').mkdir(parents=True,exist_ok=True);(OUT/'step').mkdir(exist_ok=True)
    (OUT/'assembly_meshes').mkdir(exist_ok=True)
    for sub in ('print','step','assembly_meshes'):
        for p in (OUT/sub).glob('*'):p.unlink()
    shell();cap();rear();tray()
    assy=cq.Assembly(name='PPG_MacDesktop_V2');records=[];assembly_meshes={}
    for name,shape in PARTS.items():
        cq.exporters.export(shape,str(OUT/'step'/(name+'.step')))
        assy.add(shape,name=name,color=cq.Color(COLORS[name]))
        mesh=b.to_mesh(shape);assembly_meshes[name]=mesh.copy()
        M=print_transform(name,mesh);pm=mesh.copy();pm.apply_transform(M)
        assert pm.is_volume,name
        assert np.all(pm.extents<=180.001),(name,pm.extents)
        target=OUT/'print'/(name+'.stl');pm.export(target)
        records.append({'name':name,'print_file':target.name,'size_mm':pm.extents.tolist(),
                        'volume_mm3':mesh.volume,'assembly_to_print':M.tolist(),
                        'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    cq.exporters.export(assy.toCompound(),str(OUT/'enclosure_assembly.step'))
    references=b.optical_module()
    screen=b.to_mesh(L2W(box(21,199,.5,10.5,SCR_Z0,SCR_Z1)))
    references['screen_ENVELOPE_ONLY']=screen
    scene=trimesh.Scene();printable=trimesh.Scene()
    for name,mesh in {**assembly_meshes,**references}.items():
        col=COLORS.get(name,'#343b42' if 'optical' in name or 'hood' in name else '#667887')
        mesh.visual.face_colors=ImageColor.getrgb(col)+(255,)
        scene.add_geometry(mesh,geom_name=name,node_name=name)
        if name!='screen_ENVELOPE_ONLY':
            item=mesh.copy();item.process(validate=True)
            printable.add_geometry(item,geom_name=name,node_name=name)
    shift=[0,60,0];printable.apply_translation(shift)
    (OUT/'PPG_MacDesktop_V2_M4.3mf').write_bytes(trimesh.exchange.threemf.export_3MF(printable))
    g=scene.copy();g.apply_scale(.001);g.export(OUT/'assembly.glb')
    opt=OUT/'print/17_optical_body_fixed_LED.stl';pi=OUT/'print/18_pi_housing_m4.stl'
    manifest={'units':'mm','version':'Mac Desktop V2 (tilted)','tilt_deg':TILT_DEG,
        'screen_frame_confirmed_mm':[178,105,10],'screen_window_provisional_mm':[170,97],
        'body_shell_mm':[220,150,170],
        'overall_mm':[220,150+FRONT+0.5+10,170],
        'local_frame':{'origin_mm':[0,Y0,Z0],'tilt_deg':TILT_DEG,'screen_local_z':[SCR_Z0,SCR_Z1]},
        'base_height_mm':HB,'base_front_mm':FRONT,'slab_front_top_Y_mm':YT,
        'fixed_optical_distances_mm':{'red':25,'ir':85},'parts':records,
        'colors':COLORS,'single_assembly_file':'PPG_MacDesktop_V2_M4.3mf',
        'assembly_3mf_translation_mm':shift,'fasteners':'M4 only, structural joints',
        'layout':'Optical chamber stacked on Pi case behind the tilted screen; rear removable tray',
        'fixed_optical_body':{'print_file':opt.name,'sha256':hashlib.sha256(opt.read_bytes()).hexdigest()},
        'pi_housing_m4':{'print_file':pi.name,'sha256':hashlib.sha256(pi.read_bytes()).hexdigest()},
        'status':'Engineering prototype; physical screen/cables/loads not validated.'}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for name,mesh in {**assembly_meshes,**references}.items():mesh.export(OUT/'assembly_meshes'/(name+'.stl'))
    print(f'Built {len(PARTS)} CAD solids; run verify.py before use.')


if __name__=='__main__':build()
