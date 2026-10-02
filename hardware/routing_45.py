#!/usr/bin/env python3
"""Chamfer track bends without moving pads, vias, branches or changing nets.

Run with KiCad's Python; then run source DRC/parity and rebuild the panel.
"""
from collections import defaultdict
from pathlib import Path
import json
import math
import pcbnew as p

HERE = Path(__file__).resolve().parent
BOARDS = [HERE/'opt101_receiver_kicad/opt101_receiver/opt101_receiver.kicad_pcb',
          HERE/'bpw34_receiver/bpw34_receiver.kicad_pcb',
          HERE/'led_ir_driver/led_ir_driver.kicad_pcb']

def point(q): return q.x, q.y

def topology(board):
    nodes = defaultdict(list)
    protected = {point(a.GetPosition()) for f in board.GetFootprints() for a in f.Pads()}
    for t in board.GetTracks():
        if isinstance(t, p.PCB_VIA):
            protected.add(point(t.GetPosition()))
        else:
            for end, q in ((0,t.GetStart()),(1,t.GetEnd())):
                nodes[(t.GetNetCode(),t.GetLayer(),point(q))].append((t,end))
    # A branch may end in the middle of another segment rather than at its endpoint.
    tracks=[t for t in board.GetTracks() if not isinstance(t,p.PCB_VIA)]
    for (net,layer,q) in nodes:
        for t in tracks:
            if t.GetNetCode()!=net or t.GetLayer()!=layer: continue
            a,b=point(t.GetStart()),point(t.GetEnd())
            if q in (a,b): continue
            dx,dy=b[0]-a[0],b[1]-a[1]
            length=dx*dx+dy*dy
            if not length: continue
            along=max(0,min(1,((q[0]-a[0])*dx+(q[1]-a[1])*dy)/length))
            if math.hypot(q[0]-a[0]-along*dx,q[1]-a[1]-along*dy)<t.GetWidth()/2:
                protected.add(q)
    return nodes, protected

def bends(board):
    nodes, protected = topology(board)
    for (_,_,q), ends in nodes.items():
        if len(ends)!=2 or q in protected: continue
        vectors=[]
        for t,end in ends:
            far=point(t.GetStart() if end else t.GetEnd())
            vectors.append((far[0]-q[0],far[1]-q[1]))
        a,b=vectors
        if a[0]*b[0]+a[1]*b[1]==0:
            yield q,ends,vectors

def chamfer(path, setback=.4):
    board=p.LoadBoard(str(path)); changed=0
    for q,ends,vectors in list(bends(board)):
        # Endpoints may have been shortened by the neighbouring chamfer.
        vectors=[(point(t.GetStart() if end else t.GetEnd())[0]-q[0],
                  point(t.GetStart() if end else t.GetEnd())[1]-q[1]) for t,end in ends]
        d=min(p.FromMM(setback),*(max(abs(x),abs(y))//3 for x,y in vectors))
        if d<1: continue
        pts=[]
        for (t,end),(x,y) in zip(ends,vectors):
            norm=max(abs(x),abs(y))
            pos=p.VECTOR2I(q[0]+round(d*x/norm),q[1]+round(d*y/norm))
            (t.SetEnd if end else t.SetStart)(pos);pts.append(pos)
        t=p.PCB_TRACK(board);t.SetNet(ends[0][0].GetNet());t.SetLayer(ends[0][0].GetLayer())
        t.SetWidth(min(e[0].GetWidth() for e in ends));t.SetStart(pts[0]);t.SetEnd(pts[1]);board.Add(t)
        changed+=1
    p.ZONE_FILLER(board).Fill(board.Zones());p.SaveBoard(str(path),board)
    print(path.name,changed,'chamfered bends')

def audit(path):
    board=p.LoadBoard(str(path)); tracks=[t for t in board.GetTracks() if not isinstance(t,p.PCB_VIA)]
    invalid=[]
    for t in tracks:
        dx=abs(t.GetStart().x-t.GetEnd().x);dy=abs(t.GetStart().y-t.GetEnd().y)
        if dx and dy and abs(dx-dy)>2: invalid.append(str(t.m_Uuid))
    corners=list(bends(board))
    assert not invalid, (path, 'non-45-degree segments', invalid)
    assert not corners, (path, 'un-chamfered free bends', [q for q,_,_ in corners])
    result={'tracks':len(tracks),'diagonal_tracks':sum(t.GetStart().x!=t.GetEnd().x and t.GetStart().y!=t.GetEnd().y for t in tracks),
            'non_octilinear_segments':0,'free_90_degree_bends':0,
            'note':'Pad entries, via transitions and electrical branch junctions are not free routing bends.'}
    (path.parent/'reports/routing_45_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(path.name,result)

if __name__=='__main__':
    import sys
    for path in BOARDS:
        if '--audit' not in sys.argv: chamfer(path)
        audit(path)
