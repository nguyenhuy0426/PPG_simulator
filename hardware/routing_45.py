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

def clean_segments(board):
    """Split at real junctions, remove duplicate copper, merge straight runs."""
    tracks=[t for t in board.GetTracks() if not isinstance(t,p.PCB_VIA)]
    anchors=defaultdict(set)
    for t in tracks:
        anchors[t.GetNetCode(),t.GetLayer()].update((point(t.GetStart()),point(t.GetEnd())))
    for t in tracks:
        a,b=point(t.GetStart()),point(t.GetEnd());dx,dy=b[0]-a[0],b[1]-a[1]
        length=dx*dx+dy*dy
        if not length: board.Delete(t);continue
        cuts=sorted((q for q in anchors[t.GetNetCode(),t.GetLayer()]
                     if abs((q[0]-a[0])*dy-(q[1]-a[1])*dx)<=2*math.sqrt(length)
                     and 0<=((q[0]-a[0])*dx+(q[1]-a[1])*dy)<=length),
                    key=lambda q:(q[0]-a[0])*dx+(q[1]-a[1])*dy)
        if len(cuts)<=2:continue
        for start,end in zip(cuts,cuts[1:]):
            segment=p.PCB_TRACK(board);segment.SetNet(t.GetNet());segment.SetLayer(t.GetLayer());segment.SetWidth(t.GetWidth())
            segment.SetStart(p.VECTOR2I(*start));segment.SetEnd(p.VECTOR2I(*end));board.Add(segment)
        board.Delete(t)
    seen={}
    for t in list(board.GetTracks()):
        if isinstance(t,p.PCB_VIA):continue
        key=(t.GetNetCode(),t.GetLayer(),*sorted((point(t.GetStart()),point(t.GetEnd()))))
        if key in seen:
            seen[key].SetWidth(max(seen[key].GetWidth(),t.GetWidth()));board.Delete(t)
        else:seen[key]=t
    pads=[a for f in board.GetFootprints() for a in f.Pads()]
    plane_nets={z.GetNetCode() for z in board.Zones() if not z.GetIsRuleArea()}
    vias=[(t.GetNetCode(),point(t.GetPosition())) for t in board.GetTracks() if isinstance(t,p.PCB_VIA)]
    while True:
        nodes,protected=topology(board);removed=False
        for (net,layer,q),ends in nodes.items():
            if len(ends)!=1 or q in protected or net in plane_nets:continue
            if any(n==net and math.dist(q,pt)<=2 for n,pt in vias):continue
            if any(a.GetNetCode()==net and a.IsOnLayer(layer) and a.HitTest(p.VECTOR2I(*q)) for a in pads):continue
            board.Delete(ends[0][0]);removed=True;break
        if not removed:break
    while True:
        nodes,protected=topology(board);merged=False
        for (_,_,q),ends in nodes.items():
            if len(ends)!=2 or q in protected:continue
            (a,ae),(b,be)=ends
            if a.GetWidth()!=b.GetWidth():continue
            x=point(a.GetStart() if ae else a.GetEnd());y=point(b.GetStart() if be else b.GetEnd())
            if (x[0]-q[0])*(y[1]-q[1])!=(x[1]-q[1])*(y[0]-q[0]):continue
            a.SetStart(p.VECTOR2I(*x));a.SetEnd(p.VECTOR2I(*y));board.Delete(b);merged=True;break
        if not merged:break

def chamfer(path, setback=1.2):
    board=p.LoadBoard(str(path)); changed=0
    clean_segments(board)
    nodes,_=topology(board)
    for q,ends,vectors in list(bends(board)):
        # Endpoints may have been shortened by the neighbouring chamfer.
        vectors=[(point(t.GetStart() if end else t.GetEnd())[0]-q[0],
                  point(t.GetStart() if end else t.GetEnd())[1]-q[1]) for t,end in ends]
        d=min(p.FromMM(setback),*(max(abs(x),abs(y))*2//5 for x,y in vectors))
        # Stop at branch landings inside a segment; a longer bevel must not
        # remove the copper on which another same-net track terminates.
        for (t,end),(x,y) in zip(ends,vectors):
            length=math.hypot(x,y)
            for (net,layer,landing) in nodes:
                if net!=t.GetNetCode() or layer!=t.GetLayer() or landing==q: continue
                rx,ry=landing[0]-q[0],landing[1]-q[1]
                along=(rx*x+ry*y)/length
                if 0<along<length and abs(rx*y-ry*x)/length<t.GetWidth()/2:
                    d=min(d,int(along))
        if d<1: continue
        pts=[]
        for (t,end),(x,y) in zip(ends,vectors):
            norm=max(abs(x),abs(y))
            pos=p.VECTOR2I(q[0]+round(d*x/norm),q[1]+round(d*y/norm))
            (t.SetEnd if end else t.SetStart)(pos);pts.append(pos)
        t=p.PCB_TRACK(board);t.SetNet(ends[0][0].GetNet());t.SetLayer(ends[0][0].GetLayer())
        t.SetWidth(min(e[0].GetWidth() for e in ends));t.SetStart(pts[0]);t.SetEnd(pts[1]);board.Add(t)
        changed+=1
    route_plan=path.parent/'routing_paths.json'
    if route_plan.exists():
        for route in json.loads(route_plan.read_text()):
            layer=board.GetLayerID(route['layer']);net=board.FindNet(route['net'])
            assert net is not None, route['net']
            remove_vias={tuple(p.FromMM(x) for x in pos) for pos in route.get('remove_vias',[])}
            for track in list(board.GetTracks()):
                if isinstance(track,p.PCB_VIA) and track.GetNetname()==route['net'] and point(track.GetPosition()) in remove_vias:
                    board.Delete(track)
                elif not isinstance(track,p.PCB_VIA) and track.GetNetname()==route['net'] and track.GetLayer()==layer:
                    board.Delete(track)
            for width,points in route['paths']:
                for a,b in zip(points,points[1:]):
                    track=p.PCB_TRACK(board);track.SetNet(net);track.SetLayer(layer);track.SetWidth(p.FromMM(width))
                    track.SetStart(p.VECTOR2I(*(p.FromMM(x) for x in a)))
                    track.SetEnd(p.VECTOR2I(*(p.FromMM(x) for x in b)));board.Add(track)
    clean_segments(board)
    p.ZONE_FILLER(board).Fill(board.Zones());p.SaveBoard(str(path),board)
    print(path.name,changed,'chamfered bends')

def audit(path):
    board=p.LoadBoard(str(path)); tracks=[t for t in board.GetTracks() if not isinstance(t,p.PCB_VIA)]
    invalid=[]
    segments=set()
    for t in tracks:
        key=(t.GetNetname(),t.GetLayer(),*sorted((point(t.GetStart()),point(t.GetEnd()))))
        assert key not in segments, (path,'duplicate copper segment',key)
        segments.add(key)
        dx=abs(t.GetStart().x-t.GetEnd().x);dy=abs(t.GetStart().y-t.GetEnd().y)
        if dx and dy and abs(dx-dy)>2: invalid.append(str(t.m_Uuid))
    corners=list(bends(board))
    assert not invalid, (path, 'non-45-degree segments', invalid)
    assert not corners, (path, 'un-chamfered free bends', [q for q,_,_ in corners])
    result={'tracks':len(tracks),'diagonal_tracks':sum(t.GetStart().x!=t.GetEnd().x and t.GetStart().y!=t.GetEnd().y for t in tracks),
            'non_octilinear_segments':0,'free_90_degree_bends':0,
            'duplicate_segments':0,
            'nominal_corner_setback_mm':1.2,
            'note':'Pad entries, via transitions and electrical branch junctions are not free routing bends.'}
    (path.parent/'reports/routing_45_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(path.name,result)

if __name__=='__main__':
    import sys
    for path in BOARDS:
        if '--audit' not in sys.argv: chamfer(path)
        audit(path)
