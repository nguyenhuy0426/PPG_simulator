#!/usr/bin/env python3
"""Independent pin-contract and board-dimension audit; run using KiCad Python.

Run ERC, DRC with --schematic-parity, and export the XML netlist first.
This audit checks intended connectivity, which ERC/DRC alone cannot infer.
"""
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import pcbnew as p

HERE=Path(__file__).resolve().parent
b=p.LoadBoard(str(HERE/'opt101_receiver.kicad_pcb'))
xml=ET.parse(HERE/'reports/opt101_receiver.net')
nets={n.attrib['name']:{(v.attrib['ref'],v.attrib['pin']) for v in n.findall('node') if not v.attrib['ref'].startswith('#')} for n in xml.findall('.//nets/net')}
checks=[]
def check(name,condition):
    checks.append({'check':name,'pass':bool(condition)})
    if not condition: raise AssertionError(name)
for i,ch in [(1,'RED'),(2,'IR')]:
    for net,expected in {
        f'/3V3_{ch}':{(f'U{i}','1'),(f'C{i}','1'),(f'J{i}','3')},
        f'/GND_{ch}':{(f'U{i}','3'),(f'U{i}','8'),(f'C{i}','2'),(f'J{i}','4')},
        f'/OUT_{ch}':{(f'U{i}','4'),(f'U{i}','5'),(f'J{i}','1'),('J3',str(i))},
    }.items(): check(net+' exact pin set',nets.get(net)==expected)
    for ref,pin in [(f'U{i}','2'),(f'U{i}','6'),(f'U{i}','7'),(f'J{i}','2')]:
        check(f'{ref}.{pin} intentionally isolated',any(s=={(ref,pin)} for n,s in nets.items() if n.startswith('unconnected-')))
fps={fp.GetReference():fp for fp in b.GetFootprints()}
check('11 physical footprints',len(fps)==11)
check('2 copper layers',b.GetCopperLayerCount()==2)
check('1.6mm substrate',abs(p.ToMM(b.GetDesignSettings().GetBoardThickness())-1.6)<1e-6)
edges=[x for x in b.GetDrawings() if x.GetLayer()==p.Edge_Cuts]
vertices=[pt for e in edges for pt in (e.GetStart(),e.GetEnd())]
check('four closed straight board edges',len(edges)==4 and len({(pt.x,pt.y) for pt in vertices})==4)
check('70mm length',abs(p.ToMM(max(pt.x for pt in vertices)-min(pt.x for pt in vertices))-70)<.001)
check('32mm width (<50mm)',abs(p.ToMM(max(pt.y for pt in vertices)-min(pt.y for pt in vertices))-32)<.001)
for ref in ('U1','U2'):
    pads={x.GetNumber():x for x in fps[ref].Pads()}
    a=pads['1'].GetPosition(); z=pads['8'].GetPosition(); c=pads['2'].GetPosition()
    check(ref+' DIP row spacing 7.62mm',abs(p.ToMM(z.x-a.x)-7.62)<1e-6)
    check(ref+' DIP lead pitch 2.54mm',abs(p.ToMM(c.y-a.y)-2.54)<1e-6)
    check(ref+' eight socket holes',len(pads)==8)
check('lane separation 38.5mm',abs(p.ToMM(fps['U2'].GetPosition().x-fps['U1'].GetPosition().x)-38.5)<1e-6)
for ref,pitch in [('J1',2),('J2',2),('J3',2.54)]:
    pads={x.GetNumber():x for x in fps[ref].Pads()}
    a=pads['1'].GetPosition(); z=pads['2'].GetPosition()
    actual=math.hypot(p.ToMM(z.x-a.x),p.ToMM(z.y-a.y))
    check(ref+' header pitch',abs(actual-pitch)<1e-6)
    check(ref+' moved to lower edge',abs(p.ToMM(a.y)-127.0)<1e-6)

# Layout-quality contract: all manually routed copper is Manhattan geometry,
# and every trace stays at least 1 mm beyond the edge of each M3 drill.
tracks=[track for track in b.GetTracks() if isinstance(track,p.PCB_TRACK)]
for index,track in enumerate(tracks,1):
    a,z=track.GetStart(),track.GetEnd()
    check(f'track {index} is horizontal or vertical',a.x==z.x or a.y==z.y)

def point_segment_distance(px,py,ax,ay,bx,by):
    dx,dy=bx-ax,by-ay
    if dx==0 and dy==0:
        return math.hypot(px-ax,py-ay)
    t=max(0.0,min(1.0,((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy)))
    return math.hypot(px-(ax+t*dx),py-(ay+t*dy))

for ref in ('H1','H2','H3','H4'):
    hole=next(iter(fps[ref].Pads()))
    hp=hole.GetPosition(); hx,hy=p.ToMM(hp.x),p.ToMM(hp.y)
    radius=p.ToMM(hole.GetDrillSize().x)/2
    clearances=[]
    for track in tracks:
        a,z=track.GetStart(),track.GetEnd()
        centerline=point_segment_distance(
            hx,hy,p.ToMM(a.x),p.ToMM(a.y),p.ToMM(z.x),p.ToMM(z.y)
        )
        clearances.append(centerline-radius-p.ToMM(track.GetWidth())/2)
    check(ref+' local copper clearance is 1.0mm',p.ToMM(hole.GetLocalClearance())>=1.0-1e-6)
    check(ref+' routed copper stays >=1.0mm from drill edge',min(clearances)>=1.0-1e-6)
for ref,fp in fps.items():
    for pad in fp.Pads():
        if not pad.GetNumber(): continue
        n=pad.GetNetname()
        check(f'{ref}.{pad.GetNumber()} PCB agrees with audited netlist',(ref,pad.GetNumber()) in nets.get(n,set()))
for ref in ('H1','H2','H3','H4'):
    pads=list(fps[ref].Pads())
    check(ref+' 3.2mm non-plated hole',len(pads)==1 and pads[0].GetAttribute()==p.PAD_ATTRIB_NPTH and abs(p.ToMM(pads[0].GetDrillSize().x)-3.2)<1e-6)
texts=[x for x in b.GetDrawings() if isinstance(x,p.PCB_TEXT) and x.GetLayer()==p.B_SilkS]
rear={x.GetText() for x in texts}
for label in ('DATN: PPG-Simulator','Nguyen Nhat Huy - Pham Thanh Vy','J1 A2 RED','J2 A0 IR','J3 ADS','R','I','NC','V','GR','GI','G','FB','OUT','U1 RED OPT101','U2 IR OPT101'):
    check('rear marking '+label,label in rear)
import re
for item in texts:
    check('rear pin label has no numeric prefix: '+item.GetText(),not re.match(r'^[1-4](?:\s|[A-Z])',item.GetText()))
report={'kicad_version':p.Version(),'checks':checks,'passed':len(checks)}
(HERE/'reports/pin_contract.json').write_text(json.dumps(report,indent=2)+'\n')
print(f'Pin contract and geometry: {len(checks)} checks passed')
