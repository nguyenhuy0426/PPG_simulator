#!/usr/bin/env python3
"""Regenerate a compact 70 x 20 mm dual-OPT101 board from its source PCB."""
from pathlib import Path
import pcbnew as p

HERE=Path(__file__).resolve().parent
FILE=HERE/'opt101_receiver.kicad_pcb'
mm=p.FromMM
def v(x,y):return p.VECTOR2I(mm(x),mm(y))
def xy(pt):return (p.ToMM(pt.x),p.ToMM(pt.y))
def compact(input_path=FILE):
    source=p.LoadBoard(str(input_path)); b=p.BOARD();b.GetDesignSettings().SetCopperLayerCount(2)
    b.GetDesignSettings().SetBoardThickness(mm(1.6))
    nets={}
    for old in source.GetNetsByNetcode().values():
        if old.GetNetCode():
            n=p.NETINFO_ITEM(b,old.GetNetname());b.Add(n);nets[old.GetNetname().lstrip('/')]=n
    placements={
      'U1':(111.94,104.0),'U2':(150.44,104.0),
      'C1':(126,103.5),'C2':(144,103.5),
      'R1':(115.75,113.7),'R2':(154.25,113.7),
      'C3':(124,113.7),'C4':(146,113.7),
      'J1':(113,117.4),'J2':(151,117.4),'J3':(126,117.4),
    }
    byref={}
    for old in source.GetFootprints():
        ref=old.GetReference();f=p.Cast_to_FOOTPRINT(old.Duplicate(False))
        f.SetPosition(v(*placements[ref]))
        if ref in ('R1','R2','C3','C4'):
            f.Flip(f.GetPosition(),False);f.SetOrientationDegrees(0 if ref in ('R1','C3') else 180)
        for pad in f.Pads():
            if pad.GetNetCode():pad.SetNet(nets[pad.GetNetname().lstrip('/')])
        f.Reference().SetTextSize(v(.8,.8));f.Reference().SetTextThickness(mm(.12))
        f.Reference().SetVisible(False)
        if not ref.startswith('H'):
            x,y=placements[ref];f.Reference().SetPosition(v(x+2,y-1.5))
        f.Value().SetVisible(False);b.Add(f);byref[ref]=f
    def pad(ref,pin):
        a=next(a for a in byref[ref].Pads() if a.GetNumber()==str(pin));return xy(a.GetPosition())
    def route(net,pts,layer=p.F_Cu,width=.35):
        for a,c in zip(pts,pts[1:]):
            if a==c:continue
            if abs(a[0]-c[0])>1e-5 and abs(a[1]-c[1])>1e-5:raise ValueError((net,a,c))
            t=p.PCB_TRACK(b);t.SetStart(v(*a));t.SetEnd(v(*c));t.SetLayer(layer);t.SetWidth(mm(width));t.SetNet(nets[net]);b.Add(t)
    def via(net,pos):
        t=p.PCB_VIA(b);t.SetPosition(v(*pos));t.SetWidth(mm(.8));t.SetDrill(mm(.4));t.SetLayerPair(p.F_Cu,p.B_Cu);t.SetNet(nets[net]);b.Add(t)
    def silk(value,x,y,size=.75,back=False,angle=0):
        t=p.PCB_TEXT(b);t.SetText(value);t.SetPosition(v(x,y));t.SetTextSize(v(size,size));t.SetTextThickness(mm(.11))
        t.SetLayer(p.B_SilkS if back else p.F_SilkS);t.SetMirrored(back);t.SetTextAngle(p.EDA_ANGLE(angle,p.DEGREES_T));b.Add(t)
    def line(a,c,layer,width=.12):
        t=p.PCB_SHAPE();t.SetShape(p.SHAPE_T_SEGMENT);t.SetStart(v(*a));t.SetEnd(v(*c));t.SetLayer(layer);t.SetWidth(mm(width));b.Add(t)
    for a,c in [((100,100),(170,100)),((170,100),(170,120)),((170,120),(100,120)),((100,120),(100,100))]:line(a,c,p.Edge_Cuts,.05)
    for i,(ch,cx,left,jx,cfront) in enumerate((('RED',115.75,True,113,126),('IR',154.25,False,151,144)),1):
        raw=f'RAW_{ch}';out=f'OUT_{ch}';power=f'3V3_{ch}';gnd=f'GND_{ch}'
        u=f'U{i}';r=f'R{i}';c=f'C{i}';co=f'C{i+2}';j=f'J{i}'
        # 4--5 uses the OPT101 internal 1 M feedback. The filter is on B.Cu.
        route(raw,[pad(u,4),pad(u,5)],p.F_Cu,.35)
        if left:
            route(raw,[pad(u,4),(pad(u,4)[0],113.7),pad(r,1)],p.B_Cu)
            route(out,[pad(r,2),pad(co,1)],p.B_Cu)
            route(out,[pad(r,2),(pad(r,2)[0],115.3),(jx,115.3),pad(j,1)],p.B_Cu)
            route(out,[pad(co,1),(pad(co,1)[0],115.3),(126,115.3),pad('J3',1)],p.B_Cu)
            route(power,[pad(j,3),(pad(j,3)[0],119),(108.5,119),(108.5,104),pad(u,1)],p.F_Cu,.5)
            route(power,[pad(u,1),(pad(u,1)[0],101.7),(pad(c,1)[0],101.7),pad(c,1)],p.F_Cu,.35)
            route(gnd,[pad(c,2),(129,103.5)],p.F_Cu,.35);via(gnd,(129,103.5))
        else:
            route(raw,[pad(u,5),(pad(u,5)[0],113.7),pad(r,1)],p.B_Cu)
            route(out,[pad(r,2),pad(co,1)],p.B_Cu)
            route(out,[pad(r,2),(pad(r,2)[0],115.3),(jx,115.3),pad(j,1)],p.B_Cu)
            route(out,[pad(co,1),(pad(co,1)[0],115.3),(pad('J3',2)[0],115.3),pad('J3',2)],p.B_Cu)
            route(power,[pad(j,3),(pad(j,3)[0],119),(161.5,119),(161.5,102.2),(pad(u,1)[0],102.2),pad(u,1)],p.F_Cu,.5)
            route(power,[pad(u,1),(pad(u,1)[0],101.7),(pad(c,1)[0],101.7),pad(c,1)],p.F_Cu,.35)
            route(gnd,[pad(c,2),(147,103.5)],p.F_Cu,.35);via(gnd,(147,103.5))
        # The 2-mm Grove header supply and OPT101 ground pins use an isolated rear plane.
        z=p.ZONE(b);z.SetLayer(p.B_Cu);z.SetNet(nets[gnd]);z.SetLocalClearance(mm(.3))
        z.SetPadConnection(p.ZONE_CONNECTION_THERMAL);z.SetThermalReliefGap(mm(.3));z.SetThermalReliefSpokeWidth(mm(.4));z.SetMinThickness(mm(.25))
        poly=z.Outline();poly.NewOutline()
        xa,xb=(100.6,133.0) if left else (137.0,169.4)
        for x,y in ((xa,100.6),(xb,100.6),(xb,119.4),(xa,119.4)):poly.Append(v(x,y).x,v(x,y).y)
        b.Add(z)
        silk(ch+' / '+('A2' if left else 'A0'),cx,101.6,.85)
        for pin,label in ((1,'V'),(2,'NC'),(3,'G'),(4,'FB')):
            px,py=pad(u,pin);silk(label,px-2.6,py,.8,True)
        for pin,label in ((8,'G'),(7,'NC'),(6,'NC'),(5,'OUT')):
            px,py=pad(u,pin);silk(label,px+2.6,py,.8,True)
        for k,label in enumerate(('S','NC','V','G'),1):
            x,_=pad(j,k);silk(label,x,119.0,.8,True)

    for k,label in ((1,'R'),(2,'I')):
        x,_=pad('J3',k);silk(label,x,119.0,.8,True)
    silk('PPG OPT101 RX 70x20',135,108.0,.8)
    silk('3V3 ONLY',135,109.7,.8)
    silk('DATN: PPG-Simulator',135,101.5,.8,True)
    silk('Nguyen Nhat Huy - Pham Thanh Vy',135,103.1,.8,True)
    # Sensor axes and the reserved 3 mm optical partition.
    for cx in (115.75,154.25):
        line((cx-1,107.81),(cx+1,107.81),p.Dwgs_User,.1)
        line((cx,106.81),(cx,108.81),p.Dwgs_User,.1)
    for x in (133.5,136.5):line((x,100.5),(x,119.5),p.Dwgs_User,.1)
    p.ZONE_FILLER(b).Fill(b.Zones())
    p.SaveBoard(str(FILE),b)
if __name__=='__main__':
    import sys
    compact(Path(sys.argv[1]) if len(sys.argv)>1 else FILE)
