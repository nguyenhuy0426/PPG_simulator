"""Mac Desktop V2-side: chamber (rotated 90 deg) and Pi case side by side on one wide sled.

Based on ../mac_desktop_v2 (tilted screen, low base). Body is deeper (D) so the 186 mm
long optical chamber fits along Y; both modules sit at the same level on a 210 mm tray.

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
WALL,SLAB=2.,4.        # thinned for filament: 2 mm walls/floor/roof/doors, 6 mm screen plate
H_TOP=170.
D=205.;DY=D-150.       # body depth, rear shift vs V2
YB=YT-(H_TOP-HB)*T            # slab front face meets base top here
Y0=YB+SLAB*C;Z0=HB-SLAB*S     # local->world offset
SCR_Z0,SCR_Z1,ZC=15.,120.,67.5   # screen / window centre, local z'
TAB_Z=(7.,128.)                 # cap seam tabs, local z'
CLIP_Z=(7.5,127.5)   # clips sit above and below the screen, not at its sides
CLIP_X=(75.,145.)
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


def xz_prism(pts,y0,y1):
    """Prism of the (x,z) polygon pts between y0 and y1."""
    s=cq.Workplane('XZ').polyline(pts).close().extrude(y1-y0).val()
    return s.translate((0,y0-s.BoundingBox().ymin,0))


def louvre_x(x_out,x_in,y0,y1,z,h):
    """Vent slot through a wall normal to X: opening z..z+h on the inner face, 2 mm lower on the outer face,
    so the slot ceiling slopes 45 deg across the wall (no bridge, no support)."""
    o=x_out+(-1 if x_in>x_out else 1);i=x_in+(1 if x_in>x_out else -1);dz=abs(x_in-x_out)
    return xz_prism([(o,z-dz-1),(o,z+h-dz-1),(i,z+h+1),(i,z+1)],y0,y1)


def louvre_y(y_out,y_in,x0,x1,z,h):
    """Same as louvre_x for a wall normal to Y."""
    o=y_out+(-1 if y_in>y_out else 1);i=y_in+(1 if y_in>y_out else -1);dz=abs(y_in-y_out)
    return prism([(o,z-dz-1),(o,z+h-dz-1),(i,z+h+1),(i,z+1)],x0,x1)


def gusset(x_wall,x_tip,z_top,y0,y1,embed=.3):
    """45 deg triangular brace under a block that hangs from a side wall (inner face x_wall); embed = overlap into the wall."""
    s=1 if x_tip>x_wall else -1
    return xz_prism([(x_wall-embed*s,z_top),(x_tip,z_top),(x_wall-embed*s,z_top-abs(x_tip-x_wall)-embed)],y0,y1)


def window_wire(y,w,h,r):
    wire=cq.Workplane('XZ',origin=(110,y,ZC)).rect(w,h).val()
    return wire.fillet2D(r,wire.Vertices())


# ---- Layout (assembly coords, built at 220 mm width then widened to W_OUT) ----
W_OUT=280.
STRETCH={'shell':[(30,22),(194,38)],'cap':[(18,30),(205,30)]}
BIG=1e3
OPEN_Y=(WALL,D-WALL);OPEN_Z=(WALL,H_TOP-WALL)      # whole right wall (x 0-3) is the removable side panel; 3 mm rim stays all round
PANEL_Y=(15.,190.);TOP_Z,BOT_Z=162.,14.   # side-panel M4 bolts: 4 corners (2 into roof bosses, 2 into floor ears)
SLAB_X=(30.,110.,190.);SLAB_ZB,SLAB_ZT=8.25,128.   # screen-plate press-fit pegs (local frame, before widening)
PEG_R,PEG_L=3.0,9.0                                  # peg D6 x 9, same nominal D6 hole (FDM holes print small -> friction fit)
CH_C=(222.5,97.);PI_C=(105.,97.)   # chamber | Pi (ports toward the right wall, -X); u from right wall: 171..274 | 43..167
SO_Z=(WALL,WALL)                  # module bottoms sit on the floor top, no standoffs
def chamber_holes():return [(CH_C[0]+sx*45.5,CH_C[1]+sy*54.) for sx in(-1,1) for sy in(-1,1)]
def pi_slots():return [(PI_C[0]+sy*17.,PI_C[1]+sx*46.) for sx in(-1,1) for sy in(-1,1)]


def shell():
    """One piece: floor, roof, both side walls and a CLOSED rear wall. No seams, no door, no bolts."""
    return rounded(0,220,0,D,0,170,3).cut(rounded(WALL,220-WALL,-1,D-WALL,WALL,170-WALL,.8))   # side vents are cut later as 45 deg louvres


def cap_parts():
    """Front: (screen plate, front body). The plate is the 10 mm tilted slab with the window and the screen clips."""
    outer=prism([(-FRONT,0),(-FRONT,HB),(YB,HB),(YT,H_TOP),(0,H_TOP),(0,0)],0,220)
    outer=outer.intersect(rounded(0,220,-80,1,0,170,3))
    cavity=prism([(-FRONT+WALL,WALL),(-FRONT+WALL,HB-WALL),(yin(HB-WALL),HB-WALL),
                  (yin(H_TOP-WALL),H_TOP-WALL),(1,H_TOP-WALL),(1,WALL)],WALL,220-WALL)
    c=outer.cut(cavity)
    for z in (6.,11.):   # base side vents as 45 deg louvres (slot top slopes across the 2 mm wall, prints without support)
        c=c.cut(louvre_x(0.,WALL,-42,-12,z,2.5),louvre_x(220.,220-WALL,-42,-12,z,2.5))
    c=c.cut(cyl('y',-FRONT-1,-FRONT+.8,45,15,9),louvre_y(-FRONT,-FRONT+WALL,105,195,11,3),
            box(182,192,-FRONT-1,-FRONT+1,17.5,20.5))
    loft=cq.Solid.makeLoft([window_wire(-SLAB-.1,174,101,5),window_wire(-SLAB+1.6,170,97,3)],ruled=True)
    c=c.cut(L2W(loft),L2W(rounded(25,195,-5,1,ZC-48.5,ZC+48.5,3)))
    SR=L2W(box(-10,230,-SLAB,0,0,200)).intersect(box(-10,230,-100,100,HB,H_TOP))
    slab=c.intersect(SR);front=c.cut(SR)
    # Screen clip bosses belong to the plate (clips hold the screen against it).
    for x in CLIP_X:
        for z in CLIP_Z:
            boss=box(x-7,x+7,0,11,z-7,z+7).cut(cyl('y',-5,12,x,z,R),hexhole('y',2,5.6,x,z,AF))
            slot=box(x-7.1,x+.2,2,5.6,z-3.9,z+3.9) if x<110 else box(x-.2,x+7.1,2,5.6,z-3.9,z+3.9)
            slab=union(slab,L2W(boss.cut(slot))).cut(L2W(hexhole('y',2,5.6,x,z,AF)),L2W(slot))
    return slab,front


def stretch(shape,planes):
    bb=shape.BoundingBox();cuts=[-BIG]+[p for p,_ in planes]+[BIG];out=[];shift=0.
    for k in range(len(planes)+1):
        seg=shape.intersect(box(cuts[k],cuts[k+1],-BIG,BIG,-BIG,BIG))
        if seg.Volume()>1e-3:out.append(seg.translate((shift,0,0)))
        if k<len(planes):
            xp,dx=planes[k]
            if bb.xmin<xp<bb.xmax:
                sl=shape.intersect(box(xp,xp+.5,-BIG,BIG,-BIG,BIG))
                for f in sl.Faces():
                    if abs(f.Center().x-xp)<1e-4 and f.normalAt().x<-.999:
                        out.append(cq.Solid.extrudeLinear(f,cq.Vector(dx,0,0)).translate((shift,0,0)))
            shift+=dx
    return union(*out)


def clips():
    lo=union(box(-7,7,11.5,14.5,-7,16.5),box(-7,7,10.5,11.5,7.5,11.5)).translate((0,0,CLIP_Z[0]))
    lo=lo.cut(cyl('y',10,16,0,CLIP_Z[0],R))
    hi=lo.mirror('XY',(0,0,ZC))
    for xi,x in enumerate(CLIP_X):
        for high,p in ((0,lo),(1,hi)):
            add(f'clip_{xi}_{high}',L2W(p.translate((x+30,0,0))),ACCENT)


# ---- Modern-Mac silhouette: tall screen housing in front, low body behind ----
Y_STEP=47.            # rear face of the tall screen housing
Z_LID=88.             # top of the low-body walls; the roof panel sits on them
H_LOW=Z_LID+WALL      # outside height of the low body (roof panel top)
BEAM_Z=76.            # bottom of the corner bolt blocks under the roof panel, clear of the Pi top (z 72)
FB_Y,RB_Y=(43.,55.),(191.,D-WALL)          # front / rear corner blocks (y); no cross rails (a 276 mm bridge needs support)
LB_X=W_OUT-WALL-12.   # left-side blocks stay outside x 266 so their 45 deg braces clear the chamber (x<=274, z<=68.5)
SD_Y=(4.,189.)                             # side door opening (y), z WALL..Z_LID: whole right side of the low body + the lower screen housing
SD_BOLTS=[(10.,12.),(10.,70.),(183.,12.),(183.,70.)]          # side door M4, axis x
RL_BOLTS=[(20.,82.),(W_OUT-8.,82.),(22.,15.)]  # lower rear panel M4, axis y; no bottom-left boss so the chamber slides in from the rear
RF_BOLTS=[(8.,49.),(W_OUT-8.,49.),(8.,197.),(W_OUT-8.,176.)]  # roof panel M4, axis z, in wall-corner blocks; rear-left moved forward to keep the RL nut reachable
LID_Z=H_TOP-WALL      # the roof of the screen housing is part of the upper rear panel (L-shaped lid): no 276 mm overhang in the body
RT_BOLTS=[(15.,100.),(15.,158.),(W_OUT-15.,100.),(W_OUT-15.,158.)]  # upper rear panel M4, axis y
PW_Y=102.5            # power slot centre (y 72.5-132.5), unchanged
FLOOR_WIN=[(63.,147.,45.,149.),(181.,264.,30.,164.),(20.,43.,16.,186.),(20.,170.,169.,186.),(55.,170.,12.,25.)]   # floor regions (x0,x1,y0,y1), cut as strips
BASE_WIN=(10.,W_OUT-10.,-44.,-10.)   # underside of the front base, cut as strips
STRIP_W,STRIP_RIB=20.,4.             # strips run along x (vertical when printed on the right side) -> bridges <= 20 mm
SKIN=.6                   # closed outer skin of every panel (3 layers at 0.2); the panel weight is cut by blind pockets behind it
POCKET_PITCH,POCKET_RIB=22.,2.
ROOF_VENT_X=[62.+k*9. for k in range(10)];ROOF_VENT_Y=(70.,150.)   # 10 slots 4 x 80 above the Pi (x 53-157, y 35-159)
VENT_PITCH,VENT_W=9.,4.   # vent slots in the roof panel and the lower rear panel
ROOF_RIB_Z=81.            # bottom of the roof-panel ribs (Pi top z 72, chamber top z 68.5)


def strips(y0,y1):
    """Split [y0,y1] into equal openings no wider than STRIP_W with STRIP_RIB ribs between them."""
    n=max(1,math.ceil((y1-y0+STRIP_RIB)/(STRIP_W+STRIP_RIB)))
    w=(y1-y0-(n-1)*STRIP_RIB)/n
    return [(y0+k*(w+STRIP_RIB),y0+k*(w+STRIP_RIB)+w) for k in range(n)]


def pockets(face,u0,u1,v0,v1,keep=()):
    """Blind pockets open on the INNER face of a 2 mm panel, leaving SKIN on the outer face (printed first, on the bed).
    face=(axis,inner,outer): panel normal axis 'x'/'y'/'z', inner face coord, outer face coord. (u,v) are the other two axes
    in x,y,z order. Cells of POCKET_PITCH with POCKET_RIB ribs; keep = solids left uncut (bolt bosses, seats, slots)."""
    ax,inner,outer=face;s=1 if outer>inner else -1
    d0,d1=sorted((inner-s*1.,outer-s*SKIN))
    nu=max(1,round((u1-u0+POCKET_RIB)/POCKET_PITCH));nv=max(1,round((v1-v0+POCKET_RIB)/POCKET_PITCH))
    wu=(u1-u0-(nu-1)*POCKET_RIB)/nu;wv=(v1-v0-(nv-1)*POCKET_RIB)/nv
    out=[]
    for i in range(nu):
        for j in range(nv):
            a0=u0+i*(wu+POCKET_RIB);b0=v0+j*(wv+POCKET_RIB);a=(a0,a0+wu);b=(b0,b0+wv)
            out.append(box(d0,d1,*a,*b) if ax=='x' else box(*a,d0,d1,*b) if ax=='y' else box(*a,*b,d0,d1))
    pk=union(*out)
    return pk.cut(*keep) if keep else pk


def side_panel():
    """Right side door of the low body: 0.4 mm clearance, 4 corner M4, power slot and tie slots."""
    p=box(0,WALL,SD_Y[0]+.4,SD_Y[1]-.4,WALL+.4,Z_LID-.4)
    for y,z in SD_BOLTS:p=p.cut(cyl('x',-1,4,y,z,R))
    p=p.cut(pockets(('x',WALL,0.),20.,172.,8.,82.,keep=[box(-1,5,PW_Y-46,PW_Y+46,16,49),box(-1,5,FB_Y[0]-2,FB_Y[1]+3,73,90)]))
    p=p.cut(box(-1,4,PW_Y-30,PW_Y+30,20,45))   # power slot stays open (cable)
    for y,z in ((PW_Y-42,25),(PW_Y-42,37),(PW_Y+34,25),(PW_Y+34,37)):p=p.cut(box(-1,4,y,y+8,z,z+3))
    # front-right roof bolt goes into a block on the door (the wall it used to hang from is now the door opening);
    # the door prints flat, so the block needs no brace; nut slides in from below
    x,y=RF_BOLTS[0]
    blk=box(WALL,16.,FB_Y[0]+.6,FB_Y[1],BEAM_Z,Z_LID-.4).cut(cyl('z',BEAM_Z-1,Z_LID,x,y,R),hexhole('z',BEAM_Z-1,BEAM_Z+3.6,x,y,AF))
    p=union(p,blk)
    add('09_side_panel',p,CREAM)


def rear_panels(lid_top):
    """Rear split in three: lower rear wall, horizontal roof of the low body, upper rear of the screen housing
    joined with the screen-housing roof (lid_top) into one L-shaped lid."""
    lo=box(WALL+.4,W_OUT-WALL-.4,D-WALL,D,WALL+.4,Z_LID-.4)
    for x,z in RL_BOLTS:lo=lo.cut(cyl('y',D-4,D+1,x,z,R))
    lo=lo.cut(pockets(('y',D-WALL,D),34.,W_OUT-34.,8.,74.))   # closed outside, pockets inside
    add('08_rear_low',lo,CREAM)
    roof=union(box(0,W_OUT,Y_STEP+.4,D,Z_LID,H_LOW),box(WALL+.4,W_OUT-WALL-.4,FB_Y[0]+.4,Y_STEP+.5,Z_LID,H_LOW))
    for x,y in RF_BOLTS:roof=roof.cut(cyl('z',Z_LID-1,H_LOW+1,x,y,R))
    keep=[cyl('z',Z_LID-2,H_LOW+1,x,y,8.) for x,y in RF_BOLTS]+[box(LB_X-2,W_OUT+1,RF_BOLTS[3][1]-8,RF_BOLTS[3][1]+8,Z_LID-2,H_LOW+1)]
    roof=roof.cut(pockets(('z',Z_LID,H_LOW),8.,W_OUT-8.,56.,189.,keep=keep))   # closed top skin, pockets underneath
    for x in ROOF_VENT_X:roof=roof.cut(box(x,x+VENT_W,ROOF_VENT_Y[0],ROOF_VENT_Y[1],Z_LID-1,H_LOW+1))   # through slots over the Pi only (hot air out)
    # stiffening ribs under the front and rear edge (they replace the old cross rails); roof prints upside down
    roof=union(roof,box(16.5,W_OUT-16.5,49.,51.4,ROOF_RIB_Z,Z_LID+.01),box(28.5,W_OUT-16.5,193.,195.4,ROOF_RIB_Z,Z_LID+.01))
    add('11_roof',roof,CREAM)
    top=union(box(WALL+.4,W_OUT-WALL-.4,Y_STEP-WALL,Y_STEP,H_LOW+.4,LID_Z+.01),lid_top)
    for x,z in RT_BOLTS:top=top.cut(cyl('y',Y_STEP-WALL-1,Y_STEP+1,x,z,R))
    top=top.cut(pockets(('y',Y_STEP-WALL,Y_STEP),30.,W_OUT-30.,96.,162.))   # closed rear face, pockets inside
    add('10_rear_top',top,CREAM)


def assemble():
    sh=stretch(shell(),STRETCH['shell'])
    slab,front=cap_parts()
    slab=stretch(slab,STRETCH['cap']);front=stretch(front,STRETCH['cap'])
    body=union(sh,front,slab)   # screen plate is part of the one-piece body
    W=W_OUT
    body=body.cut(box(-1,W+1,Y_STEP,D+1,Z_LID,H_TOP+1))            # drop the body behind the screen housing to Z_LID
    body=body.cut(box(WALL,W-WALL,D-WALL-.1,D+1,WALL,Z_LID+.1))     # open rear of the low body (lower rear panel)
    body=body.cut(box(-1,WALL+.05,SD_Y[0],SD_Y[1],WALL,Z_LID+.1))   # side door opening
    body=body.cut(box(WALL-.01,WALL+1.,SD_Y[0]+14.,SD_Y[1]-14.,WALL,WALL+1.))   # inner floor fillet along the sill: Pi slides out flat
    # Upright print without support: nothing hangs flat. Every block that hangs from a side wall gets a 45 deg brace
    # under it; bolts that need a nut from below get a hex channel through the brace.
    def corner(x0,x1,y0,y1,z0,z1):
        right=x0<W/2
        return union(box(x0,x1,y0,y1,z0,z1),gusset(WALL if right else W-WALL,x1 if right else x0,z0,y0,y1))
    # roof panel + top bolts of the lower rear panel: blocks in the wall corners only (no cross rails)
    blocks=[(LB_X,W-WALL,*FB_Y),(WALL,28.,*RB_Y),(LB_X,W-WALL,*RB_Y),(LB_X,W-WALL,RF_BOLTS[3][1]-6,RF_BOLTS[3][1]+6)]
    for x0,x1,y0,y1 in blocks:body=union(body,corner(x0,x1,y0,y1,BEAM_Z,Z_LID))
    # side door bosses (axis x), nut pocket at the inner end
    for y,z in SD_BOLTS:
        ylo,yhi=(y-13,y+7) if y<100 else (y-7,y+12)
        zlo,zhi=(WALL-.3,z+7) if z<40 else (z-7,Z_LID+(4. if y<Y_STEP else 0.))   # front top boss grows into the screen-housing wall above
        blk=box(WALL,14,ylo,yhi,zlo,zhi)
        if z>40:blk=union(blk,gusset(WALL,14.,zlo,ylo,yhi,embed=0.))   # the door opening is at x<WALL
        body=union(body,blk.cut(cyl('x',-1,15,y,z,R),hexhole('x',10.4,14.1,y,z,AF)))
    # lower rear panel: top bolts into the rear corner blocks, bottom bolt into a floor boss
    for x,z in RL_BOLTS:
        if z<40:body=union(body,box(x-7,x+7,RB_Y[0],RB_Y[1],WALL-.3,z+7))
        body=body.cut(cyl('y',RB_Y[0]-1,D+1,x,z,R),hexhole('y',RB_Y[0]-.1,RB_Y[0]+3.6,x,z,AF))
    # upper rear panel: bosses on the screen-housing side walls, braced
    for x,z in RT_BOLTS:
        xlo,xhi=(1.,x+7) if x<100 else (x-7,W-1.)
        zhi=z+7 if z<130 else LID_Z
        blk=union(box(xlo,xhi,Y_STEP-WALL-12,Y_STEP-WALL-.05,z-7,zhi),   # 0.05 off the lid plate (contact face)
                  gusset(WALL if x<100 else W-WALL,xhi if x<100 else xlo,z-7,Y_STEP-WALL-12,Y_STEP-WALL-2.)   # brace stops at y 43: roof tongue y 43.4-47.5
                  .intersect(box(-BIG,BIG,-BIG,BIG,Z_LID+.1 if x<100 else -BIG,BIG)))   # right side: no wall below z 88 (door opening)
        body=union(body,blk.cut(cyl('y',Y_STEP-WALL-13,Y_STEP+1,x,z,R),hexhole('y',Y_STEP-WALL-12.1,Y_STEP-WALL-8.4,x,z,AF)))
    # roof panel bolts: hole, nut pocket on the block underside and a hex channel down through the brace to insert the nut
    for x,y in RF_BOLTS[1:]:   # RF_BOLTS[0] goes into the side door block
        body=body.cut(cyl('z',BEAM_Z-1,Z_LID+1,x,y,R),hexhole('z',BEAM_Z-40.,BEAM_Z+3.6,x,y,AF))
    # front base: its ceiling (y -48..-30, z 28) becomes a 45 deg gable so it prints without support
    ya,yb=-FRONT+WALL,yin(HB-WALL);ym=(ya+yb)/2;h=(yb-ya)/2
    body=union(body,prism([(ya-.3,HB-WALL+.01),(ym,HB-WALL+.01),(ya-.3,HB-WALL-h-.3)],WALL-.3,W-WALL+.3),
               prism([(ym,HB-WALL+.01),(yb+.5,HB-WALL+.01),(yb+.5,HB-WALL-h-.5)],WALL-.3,W-WALL+.3))
    for x in CLIP_X:   # blind hole in the screen plate for the tip of the clip M4x16 (3 mm front skin left)
        for z in CLIP_Z:body=body.cut(L2W(cyl('y',-2.,1.,x+30,z,R)))
    # filament saving: floor windows under the modules (10 mm ledge left all round each module) and beside the Pi
    for x0,x1,y0,y1 in FLOOR_WIN+[BASE_WIN]:
        for ya,yb in strips(y0,y1):body=body.cut(box(x0,x1,ya,yb,-1,WALL+.1))
    # Mac-style side vents on the left wall of the low body (left wall prints as the top face)
    for z in np.arange(16.,72.,7.):body=body.cut(louvre_x(W,W-WALL,80.,185.,z,3.))   # 45 deg louvres, no bridges
    body=body.cut(box(WALL+.01,W-WALL-.01,Y_STEP-WALL,Y_STEP+.1,H_LOW,LID_Z+.1))   # inner roof fillet in the lid plate's path
    lid=box(-1,W+1,-BIG,Y_STEP,LID_Z,H_TOP+1)      # screen-housing roof goes to the L-shaped upper rear lid
    lid_top=body.intersect(lid);body=body.cut(lid)
    add('01_body',body,CREAM)
    clips();side_panel();rear_panels(lid_top)


def print_transform(name,mesh):
    """Rigid (det +1) assembly->print matrix; broad face down."""
    M=np.eye(4)
    if name.startswith('01_body'):
        pass   # upright, floor on the bed (least support)
    elif 'shell' in name:
        R3=np.array([[0,1,0],[0,0,1],[1,0,0]],float)
        if 'right' in name:R3[[0,2]]*=-1
        M[:3,:3]=R3
    elif 'door' in name:
        M[:3,:3]=np.array([[1,0,0],[0,0,1],[0,-1,0]],float)
    elif name.startswith(('08_rear','10_rear')):
        M[:3,:3]=np.array([[1,0,0],[0,0,1],[0,-1,0]],float)
    elif name.startswith('11_roof'):
        M[:3,:3]=np.array([[1,0,0],[0,-1,0],[0,0,-1]],float)   # top face down, ribs up
    elif name.startswith('09_'):
        M[:3,:3]=np.array([[0,1,0],[0,0,1],[1,0,0]],float)
    elif name.startswith(('clip','02_screen')):
        rx=np.array([[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1]],float)  # (x,y,z)->(x,-z,y)
        M=rx@np.linalg.inv(L4())
    pm=mesh.copy();pm.apply_transform(M)
    M[:3,3]+=-pm.bounds[0]
    assert np.isclose(np.linalg.det(M[:3,:3]),1),name
    return M


def modules():
    """Chamber (body, lid, hoods) and Pi case, rotated 90 deg about Z and moved onto the sled."""
    refs=b.optical_module()
    out={}
    for name,m in refs.items():
        m=m.copy()
        pi=name=='pi_housing'
        c0=refs['pi_housing'].bounds.mean(0)[:2] if pi else refs['optical_body'].bounds.mean(0)[:2]
        m.apply_translation([-c0[0],-c0[1],0])
        m.apply_transform(trimesh.transformations.rotation_matrix(math.pi/2 if not pi else -math.pi/2,[0,0,1]))  # Pi long axis along Y like the chamber; big 64x42 window faces the front (-Y), small 55x16 window the rear (+Y)
        tgt=PI_C if pi else CH_C
        m.apply_translation([tgt[0],tgt[1],0 if pi else SO_Z[1]-refs['optical_body'].bounds[0,2]])
        if pi:m.apply_translation([0,0,SO_Z[1]-refs['pi_housing'].bounds[0,2]])
        out[name]=m
    return out


def build():
    (OUT/'print').mkdir(parents=True,exist_ok=True);(OUT/'step').mkdir(exist_ok=True)
    (OUT/'assembly_meshes').mkdir(exist_ok=True)
    for sub in ('print','step','assembly_meshes'):
        for p in (OUT/sub).glob('*'):p.unlink()
    assemble()
    assy=cq.Assembly(name='PPG_MacDesktop_V2');records=[];assembly_meshes={}
    for name,shape in PARTS.items():
        cq.exporters.export(shape,str(OUT/'step'/(name+'.step')))
        assy.add(shape,name=name,color=cq.Color(COLORS[name]))
        mesh=b.to_mesh(shape);assembly_meshes[name]=mesh.copy()
        M=print_transform(name,mesh);pm=mesh.copy();pm.apply_transform(M)
        assert pm.is_volume,name
        assert np.all(pm.extents<=420.001),(name,pm.extents)
        target=OUT/'print'/(name+'.stl');pm.export(target)
        records.append({'name':name,'print_file':target.name,'size_mm':pm.extents.tolist(),
                        'volume_mm3':mesh.volume,'assembly_to_print':M.tolist(),
                        'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    cq.exporters.export(assy.toCompound(),str(OUT/'enclosure_assembly.step'))
    references=modules()
    screen=b.to_mesh(L2W(box(51,229,.5,10.5,SCR_Z0,SCR_Z1)))
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
        'overall_mm':[220,D+FRONT+0.5+10,170],
        'local_frame':{'origin_mm':[0,Y0,Z0],'tilt_deg':TILT_DEG,'screen_local_z':[SCR_Z0,SCR_Z1]},
        'base_height_mm':HB,'base_front_mm':FRONT,'slab_front_top_Y_mm':YT,
        'fixed_optical_distances_mm':{'red':25,'ir':85},'parts':records,
        'colors':COLORS,'single_assembly_file':'PPG_MacDesktop_V2_M4.3mf',
        'assembly_3mf_translation_mm':shift,'fasteners':'M4 only, structural joints',
        'layout':'Optical chamber (rotated 90 deg) and Pi case side by side on one 210 mm sled',
        'fixed_optical_body':{'print_file':opt.name,'sha256':hashlib.sha256(opt.read_bytes()).hexdigest()},
        'pi_housing_m4':{'print_file':pi.name,'sha256':hashlib.sha256(pi.read_bytes()).hexdigest()},
        'status':'Engineering prototype; physical screen/cables/loads not validated.'}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for name,mesh in {**assembly_meshes,**references}.items():mesh.export(OUT/'assembly_meshes'/(name+'.stl'))
    print(f'Built {len(PARTS)} CAD solids; run verify.py before use.')


if __name__=='__main__':build()
