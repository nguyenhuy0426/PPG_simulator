#!/usr/bin/env python3
"""Repack the two BPW34 receivers into a 70 x 20 mm V-score-compatible PCB."""
from pathlib import Path
import json
import pcbnew as p
HERE=Path(__file__).resolve().parent
FILE=HERE/'bpw34_receiver.kicad_pcb'
mm=p.FromMM
def v(x,y):return p.VECTOR2I(mm(x),mm(y))
def xy(q):return (p.ToMM(q.x),p.ToMM(q.y))
def compact(input_path=FILE):
    src=p.LoadBoard(str(input_path));b=p.BOARD();b.GetDesignSettings().SetCopperLayerCount(2)
    b.GetDesignSettings().SetBoardThickness(mm(1.6));scale=2/3
    def mapped(pt):return p.VECTOR2I(pt.x,mm(100+(p.ToMM(pt.y)-100)*scale))
    overrides={
      'C1':(119,103.95),'C2':(151,103.95),
      'C5':(105.5,101.4),'C6':(164.5,101.4),
      'R1':(119,101.65),'R2':(151,101.65),
      'R7':(108.5,108.2),'R8':(161.5,108.2),
      'C3':(105.5,108.2),'C4':(164.5,108.2),
    }
    nets={}
    for n in src.GetNetsByNetcode().values():
        if n.GetNetCode():
            new=p.NETINFO_ITEM(b,n.GetNetname());b.Add(new);nets[n.GetNetCode()]=new
    anchors={}
    for f0 in src.GetFootprints():
        f=p.Cast_to_FOOTPRINT(f0.Duplicate(False));ref=f.GetReference()
        if ref.startswith('H'):
            continue
        oldpads={a.GetNumber():(a.GetPosition(),a.GetNetCode()) for a in f0.Pads()}
        f.SetPosition(v(*overrides[ref]) if ref in overrides else mapped(f.GetPosition()))
        for pad in f.Pads():
            oldpos,code=oldpads[pad.GetNumber()]
            anchors[(oldpos.x,oldpos.y,code)]=pad.GetPosition()
            if code:pad.SetNet(nets[code])
        f.Reference().SetVisible(False);f.Value().SetVisible(False);b.Add(f)
    def point(pt,code):
        if code and nets[code].GetNetname()=='/VREF_IR' and abs(p.ToMM(pt.x)-159.5)<.001 and abs(p.ToMM(pt.y)-106.5)<.001:
            return v(155.0,103.5)
        return anchors.get((pt.x,pt.y,code),mapped(pt))
    for t0 in src.GetTracks():
        if not isinstance(t0,p.PCB_VIA) and t0.GetNetname()=='/VREF_IR' and t0.GetLayer()==p.F_Cu and abs(p.ToMM(t0.GetStart().x)-159.5)<.001:
            continue
        if t0.GetNetname()=='/VREF_IR' and t0.GetLayer()==p.B_Cu and abs(p.ToMM(t0.GetStart().x)-159.5)<.001 and abs(p.ToMM(t0.GetStart().y)-109.9625)<.001 and abs(p.ToMM(t0.GetEnd().y)-106.5)<.001:
            continue
        t=p.Cast_to_PCB_VIA(t0.Duplicate()) if isinstance(t0,p.PCB_VIA) else p.Cast_to_PCB_TRACK(t0.Duplicate())
        code=t0.GetNetCode();t.SetNet(nets[code])
        if isinstance(t,p.PCB_VIA):t.SetPosition(point(t0.GetPosition(),code))
        else:t.SetStart(point(t0.GetStart(),code));t.SetEnd(point(t0.GetEnd(),code))
        if t.GetNetname()=='/FB_IR':t.SetWidth(mm(.20))
        if t.GetNetname()=='/VREF_IR' and t.GetLayer()==p.F_Cu and not isinstance(t,p.PCB_VIA) and abs(p.ToMM(t.GetStart().x)-153.5)<.001 and abs(p.ToMM(t.GetStart().y)-102.666667)<.001:
            t.SetStart(v(153.5,103.5))
        b.Add(t)
    def trace(net,points,layer=p.B_Cu,width=.22):
        n=next(q for q in nets.values() if q.GetNetname()==net)
        for a,c in zip(points,points[1:]):
            t=p.PCB_TRACK(b);t.SetStart(v(*a));t.SetEnd(v(*c));t.SetWidth(mm(width));t.SetLayer(layer);t.SetNet(n);b.Add(t)
    trace('/VREF_IR',[(155,103.5),(153.5,103.5)],p.F_Cu)
    trace('/VREF_IR',[(155,103.5),(155,103.85),(159.5,103.85),(159.5,106.641667)])
    def via(net,pos):
        t=p.PCB_VIA(b);t.SetPosition(v(*pos));t.SetWidth(mm(.65));t.SetDrill(mm(.3));t.SetLayerPair(p.F_Cu,p.B_Cu)
        t.SetNet(next(q for q in nets.values() if q.GetNetname()==net));b.Add(t)
    for net,x in (('/GND_RED',103.5),('/GND_IR',166.5)):
        via(net,(x,102));via(net,(x,110));trace(net,[(x,102),(x,110)],p.F_Cu,.25)
    def line(a,c,layer,width=.12):
        d=p.PCB_SHAPE();d.SetShape(p.SHAPE_T_SEGMENT);d.SetStart(v(*a));d.SetEnd(v(*c));d.SetLayer(layer);d.SetWidth(mm(width));b.Add(d)
    def silk(value,x,y,size=.8,back=False):
        t=p.PCB_TEXT(b);t.SetText(value);t.SetPosition(v(x,y));t.SetTextSize(v(size,size))
        t.SetTextThickness(mm(.1));t.SetLayer(p.B_SilkS if back else p.F_SilkS)
        t.SetMirrored(back);b.Add(t)
    for a,c in [((100,100),(170,100)),((170,100),(170,120)),((170,120),(100,120)),((100,120),(100,100))]:line(a,c,p.Edge_Cuts,.05)
    silk('RED / A2',115.75,102.2,.8)
    silk('IR / A0',154.25,102.2,.8)
    silk('PPG BPW34 RX 70x20',135,103.2,.8)
    silk('3V3 ONLY',135,105.0,.8)
    silk('BPW34 MARK = K',135,110.5,.8)
    silk('DATN: PPG-Simulator',135,102.0,.8,True)
    silk('Nguyen Nhat Huy - Pham Thanh Vy',135,103.6,.8,True)
    for ref in ('D1','D2'):
        f=next(q for q in b.GetFootprints() if q.GetReference()==ref)
        for number,label,offset in ((1,'K',-2),(2,'A',2)):
            pad=next(q for q in f.Pads() if q.GetNumber()==str(number))
            silk(label,p.ToMM(pad.GetPosition().x)+offset,p.ToMM(pad.GetPosition().y),.8,True)
    for ref,labels in (('J1',('R','NC','V','GR')),('J3',('R','GR','I','GI')),('J2',('I','NC','V','GI'))):
        f=next(q for q in b.GetFootprints() if q.GetReference()==ref)
        for number,label in enumerate(labels,1):
            pad=next(q for q in f.Pads() if q.GetNumber()==str(number))
            silk(label,p.ToMM(pad.GetPosition().x),118.9,.8,True)
    for prefix,net,x0,x1 in [('RED','GND_RED',100.6,133),('IR','GND_IR',137,169.4)]:
        z=p.ZONE(b);z.SetLayer(p.B_Cu);z.SetNet(next(n for n in nets.values() if n.GetNetname().lstrip('/')==net))
        z.SetLocalClearance(mm(.3));z.SetPadConnection(p.ZONE_CONNECTION_THERMAL)
        z.SetIslandRemovalMode(p.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetThermalReliefGap(mm(.3));z.SetThermalReliefSpokeWidth(mm(.4));z.SetMinThickness(mm(.25))
        poly=z.Outline();poly.NewOutline()
        for x,y in ((x0,100.6),(x1,100.6),(x1,119.4),(x0,119.4)):poly.Append(v(x,y).x,v(x,y).y)
        b.Add(z)
    # Deterministic, DRC-checked orthogonal fanouts; all source nets are preserved.
    def signature(t):
        return [t.GetNetname(),t.GetLayer(),[round(p.ToMM(t.GetStart().x),6),round(p.ToMM(t.GetStart().y),6)],
                [round(p.ToMM(t.GetEnd().x),6),round(p.ToMM(t.GetEnd().y),6)],round(p.ToMM(t.GetWidth()),6)]
    for edit in json.loads((HERE/'orthogonal_routes.json').read_text()):
        t=next(t for t in b.GetTracks() if not isinstance(t,p.PCB_VIA) and signature(t)==edit['original'])
        net=t.GetNet();layer=t.GetLayer();width=t.GetWidth();b.Remove(t)
        for a,c in zip(edit['points'],edit['points'][1:]):
            t=p.PCB_TRACK(b);t.SetNet(net);t.SetLayer(layer);t.SetWidth(width)
            t.SetStart(v(*a));t.SetEnd(v(*c));b.Add(t)
    # Move the upper analog block inward without shrinking its pad pitch or loops.
    # Preserve both optical axes in world coordinates by updating the U support.
    def inset_y(y):
        if y <= 111: return y + 1.7
        if y < 113.333333: return 112.7 + (y-111)*(0.633333/2.333333)
        if y >= 118: return y - .766666
        return y
    def inset_point(q): return v(p.ToMM(q.x), inset_y(p.ToMM(q.y)))
    for f in b.GetFootprints(): f.SetPosition(inset_point(f.GetPosition()))
    for t in b.GetTracks():
        if isinstance(t,p.PCB_VIA): t.SetPosition(inset_point(t.GetPosition()))
        else:
            t.SetStart(inset_point(t.GetStart()));t.SetEnd(inset_point(t.GetEnd()))
    for d in b.GetDrawings():
        if isinstance(d,p.PCB_TEXT) and d.GetLayer()==p.B_SilkS:
            if d.GetText() in ('K','A'): d.Move(v(0,1.7))
            elif p.ToMM(d.GetPosition().y)>118: d.Move(v(0,-.5))
    for z in b.Zones():
        poly=z.Outline()
        for k in range(poly.OutlineCount()):
            chain=poly.Outline(k)
            for j in range(chain.PointCount()):
                q=chain.CPoint(j)
                if p.ToMM(q.y)<110: q.y=mm(101.5)
                else: q.y=mm(118.5)
                chain.SetPoint(j,q)
    # Dedicated anode return prevents isolation by the adjacent signal routes.
    trace('/GND_RED',[(118.3,111.7),(124,111.7),(124,116.666666),(124.54,116.666666)],p.F_Cu,.25)
    p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(FILE),b)
if __name__=='__main__':
    import sys
    compact(Path(sys.argv[1]) if len(sys.argv)>1 else FILE)
