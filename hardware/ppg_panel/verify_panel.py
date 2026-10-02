#!/usr/bin/env python3
"""Independent panel isolation, source parity and physical clearance audit."""
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
import pcbnew as p

HERE=Path(__file__).resolve().parent
def mm(a): return p.ToMM(a)
def xy(a): return (round(mm(a.x),6),round(mm(a.y),6))
def width(t): return mm(t.GetWidth(t.GetLayer()) if isinstance(t,p.PCB_VIA) else t.GetWidth())
def distance(point,a,b):
    px,py=point; ax,ay=a; bx,by=b; dx,dy=bx-ax,by-ay
    t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy))) if dx or dy else 0
    return math.hypot(px-ax-t*dx,py-ay-t*dy)
def interval_distance(lo,hi,target): return max(lo-target,target-hi,0)

def main():
    manifest=json.loads((HERE/'reports/manifest.json').read_text())
    b=p.LoadBoard(str(HERE/'ppg_panel.kicad_pcb'))
    sources=manifest['sources']; checks=[]; reports={}
    def check(name,condition):
        checks.append({'check':name,'pass':bool(condition)})
        if not condition: raise AssertionError(name)
    check('2 copper layers',b.GetCopperLayerCount()==2)
    edges=[d for d in b.GetDrawings() if d.GetLayer()==p.Edge_Cuts]
    check('Only outer rectangle is routed; no milling on score lines',len(edges)==4)
    cuts=[d for d in b.GetDrawings() if d.GetLayer()==p.Cmts_User]
    check('Exactly two full-width score centre-lines',len(cuts)==2 and
        {tuple(xy(d.GetStart())+xy(d.GetEnd())) for d in cuts}=={(50,70,120,70),(50,90,120,90)})
    for item in sources:
        source=HERE.parent/item['source']; src=p.LoadBoard(str(source)); prefix=item['prefix']
        check(prefix+' current source hash',hashlib.sha256(source.read_bytes()).hexdigest()==item['sha256'])
        original={f.GetReference():f for f in src.GetFootprints()}
        clones={f.GetReference().removeprefix(prefix+'_'):f for f in b.GetFootprints() if f.GetReference().startswith(prefix+'_')}
        check(prefix+' exact footprint inventory',original.keys()==clones.keys())
        delta=(-50,-50+item['offset_mm'][1])
        for ref,fp in original.items():
            clone=clones[ref]
            check(prefix+' '+ref+' fitted value',fp.GetValue()==clone.GetValue())
            check(prefix+' '+ref+' placement',all(abs(a+c-z)<1e-6 for a,c,z in zip(xy(fp.GetPosition()),delta,xy(clone.GetPosition()))))
            oldpads={x.GetNumber():x for x in fp.Pads()}; newpads={x.GetNumber():x for x in clone.Pads()}
            check(prefix+' '+ref+' pad inventory',oldpads.keys()==newpads.keys())
            for num,pad in oldpads.items():
                other=newpads[num]
                expected=prefix+pad.GetNetname() if pad.GetNetCode() else ''
                check(prefix+' '+ref+'.'+num+' isolated net',other.GetNetname()==expected)
                check(prefix+' '+ref+'.'+num+' physical pad/drill',pad.GetSize()==other.GetSize() and pad.GetDrillSize()==other.GetDrillSize())
        def signature(t,shift=(0,0),strip=''):
            a=tuple(round(x+d,6) for x,d in zip(xy(t.GetStart()),shift))
            z=tuple(round(x+d,6) for x,d in zip(xy(t.GetEnd()),shift))
            return (t.GetNetname().removeprefix(strip),t.GetLayer(),a,z,round(width(t),6),isinstance(t,p.PCB_VIA))
        old=sorted(signature(t,delta) for t in src.GetTracks())
        new=sorted(signature(t,strip=prefix) for t in b.GetTracks() if t.GetNetname().startswith(prefix))
        check(prefix+' all tracks/vias match source exactly',old==new)
        widths=defaultdict(set); holes={}
        for t in src.GetTracks():
            if not isinstance(t,p.PCB_VIA): widths[t.GetNetname()].add(round(width(t),3))
        for f in src.GetFootprints():
            for pad in f.Pads():
                if pad.GetAttribute()!=p.PAD_ATTRIB_NPTH: continue
                clear=min(distance(xy(pad.GetPosition()),xy(t.GetStart()),xy(t.GetEnd()))-mm(pad.GetDrillSize().x)/2-width(t)/2 for t in src.GetTracks())
                holes[f.GetReference()]=round(clear,4)
                check(prefix+' '+f.GetReference()+' no track/via crosses drill',clear>=.25)
        reports[prefix]={'widths_mm':{k:sorted(v) for k,v in widths.items()},'track_to_mounting_drill_edge_mm':holes}
    # Check real copper extents, including filled zones, against both scores.
    margins=[]
    for t in b.GetTracks():
        lo,hi=sorted((mm(t.GetStart().y),mm(t.GetEnd().y))); r=width(t)/2
        for cut in (70,90): margins.append(interval_distance(lo-r,hi+r,cut))
    for f in b.GetFootprints():
        for pad in f.Pads():
            if pad.GetAttribute()==p.PAD_ATTRIB_NPTH: continue
            bb=pad.GetBoundingBox()
            for cut in (70,90): margins.append(interval_distance(mm(bb.GetY()),mm(bb.GetBottom()),cut))
    for z in b.Zones():
        if z.GetIsRuleArea(): continue
        poly=z.GetFilledPolysList(z.GetLayer())
        check(z.GetNetname()+' zone filled',poly.OutlineCount()>0)
        for i in range(poly.OutlineCount()):
            chain=poly.COutline(i); ys=[mm(chain.CPoint(j).y) for j in range(chain.PointCount())]
            for cut in (70,90): margins.append(interval_distance(min(ys),max(ys),cut))
    check('All copper >=0.6mm from score centre-lines',min(margins)>=.6-1e-5)
    check('No panel net touches more than one source board',all(
        len({f.GetReference().split('_')[0] for f in b.GetFootprints() for pad in f.Pads() if pad.GetNetCode()==net.GetNetCode()})<=1
        for net in b.GetNetsByNetcode().values() if net.GetNetCode()))
    report={'checks':checks,'passed':len(checks),'source_geometry':reports,
        'copper_to_vcut_min_mm':round(min(margins),6),'panel_mm':[70,80],
        'original_area_mm2':7560,'new_area_mm2':5600,'area_reduction_percent':100*(7560-5600)/7560,
        'limitations':'CAD and nominal component checks only; not physical electrical or manufacturing qualification.'}
    (HERE/'reports/panel_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'{len(checks)} checks passed; minimum copper-to-V-cut {min(margins):.3f} mm.')

if __name__=='__main__': main()
