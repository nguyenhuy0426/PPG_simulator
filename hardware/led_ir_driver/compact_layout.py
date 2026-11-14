#!/usr/bin/env python3
"""Compact the verified two-channel LED driver to a 70 x 40 mm outline."""
from pathlib import Path
import json
import pcbnew as p

HERE = Path(__file__).resolve().parent
FILE = HERE / 'led_ir_driver.kicad_pcb'
mm = p.FromMM


def vec(x, y):
    return p.VECTOR2I(mm(x), mm(y))


def compact(input_path=FILE):
    src = p.LoadBoard(str(input_path))
    board = p.BOARD()
    board.GetDesignSettings().SetCopperLayerCount(2)
    board.GetDesignSettings().SetBoardThickness(mm(1.6))
    points = ((100, 100), (117.7, 117.7), (121, 119), (125, 122),
              (132, 128), (136, 131.5), (140, 134.5), (145, 137), (148, 140))

    def ymap(y):
        for (a, b), (c, d) in zip(points, points[1:]):
            if y <= c:
                return b + (y-a)*(d-b)/(c-a)
        return 140 + (y-148)

    def mapped(pt):
        return vec(p.ToMM(pt.x), ymap(p.ToMM(pt.y)))

    positions = {
        'J1': (107, 105), 'J2': (129, 105), 'J3': (140, 105), 'J4': (162, 105),
        'H1': (104, 124), 'H2': (166, 124), 'H3': (104, 136), 'H4': (166, 136),
        'U1': (131.19, 122.19),
        'Q1': (118, 131.5), 'Q2': (147, 131.5),
        'J5': (123, 137), 'J6': (146, 137), 'J7': (134, 137),
        'R1': (112.81, 119), 'R2': (112.81, 122),
        'R3': (123, 125.31), 'R4': (111, 137),
        'R6': (149.81, 119), 'R7': (149.81, 122),
        'R8': (149.81, 127), 'R9': (161, 132.5),
        'C2': (127, 130.5), 'C4': (143, 130.5),
        'C5': (144, 121.5), 'C7': (134.3, 116.35),
    }
    nets = {}
    for net in src.GetNetsByNetcode().values():
        if net.GetNetCode():
            new = p.NETINFO_ITEM(board, net.GetNetname())
            board.Add(new)
            nets[net.GetNetCode()] = new
    anchors = {}
    for original in src.GetFootprints():
        footprint = p.Cast_to_FOOTPRINT(original.Duplicate(False))
        ref = footprint.GetReference()
        old = {pad.GetNumber(): (pad.GetPosition(), pad.GetNetCode()) for pad in original.Pads()}
        footprint.SetPosition(vec(*positions[ref]) if ref in positions else mapped(footprint.GetPosition()))
        if ref == 'C7':
            footprint.Flip(footprint.GetPosition(), False)
            footprint.SetOrientation(p.EDA_ANGLE(90, p.DEGREES_T))
        for pad in footprint.Pads():
            pos, code = old[pad.GetNumber()]
            anchors[(pos.x, pos.y, code)] = pad.GetPosition()
            if code:
                pad.SetNet(nets[code])
        footprint.Reference().SetVisible(False)
        footprint.Value().SetVisible(False)
        board.Add(footprint)

    def point(pos, code):
        return anchors.get((pos.x, pos.y, code), mapped(pos))

    for original in src.GetTracks():
        if original.GetNetname()=='/GND':
            continue
        if original.GetNetname() in ('/DAC_IR','/DAC_RED') and original.GetLayer()==p.B_Cu and max(p.ToMM(original.GetStart().y),p.ToMM(original.GetEnd().y))>107.01:
            continue
        if original.GetNetname()=='/5V' and not isinstance(original,p.PCB_VIA) and original.GetLayer()==p.F_Cu:
            continue
        if original.GetNetname()=='/5V' and isinstance(original,p.PCB_VIA):
            continue
        if original.GetNetname()=='/5V' and original.GetLayer()==p.B_Cu and (abs(p.ToMM(original.GetStart().y)-121.0)<.001 or abs(p.ToMM(original.GetEnd().y)-121.0)<.001) and abs(p.ToMM(original.GetStart().x)-138.81)<.001:
            continue
        if original.GetNetname()=='/SENSE_RED' and original.GetLayer()==p.F_Cu and abs(p.ToMM(original.GetStart().x)-148)<.001 and abs(p.ToMM(original.GetEnd().x)-150.26)<.001:
            continue
        track = (p.Cast_to_PCB_VIA(original.Duplicate()) if isinstance(original, p.PCB_VIA)
                 else p.Cast_to_PCB_TRACK(original.Duplicate()))
        code = original.GetNetCode()
        track.SetNet(nets[code])
        if isinstance(track, p.PCB_VIA):
            track.SetPosition(point(original.GetPosition(), code))
        else:
            track.SetStart(point(original.GetStart(), code))
            track.SetEnd(point(original.GetEnd(), code))
        board.Add(track)

    def trace(net, coords, layer, width=.3):
        item=next(n for n in nets.values() if n.GetNetname()==net)
        for a,b in zip(coords,coords[1:]):
            track=p.PCB_TRACK(board)
            track.SetStart(vec(*a));track.SetEnd(vec(*b));track.SetLayer(layer)
            track.SetWidth(mm(width));track.SetNet(item);board.Add(track)

    def via(net, pos):
        item=next(n for n in nets.values() if n.GetNetname()==net)
        track=p.PCB_VIA(board)
        track.SetPosition(vec(*pos));track.SetWidth(mm(.8));track.SetDrill(mm(.4))
        track.SetLayerPair(p.F_Cu,p.B_Cu);track.SetNet(item);board.Add(track)

    trace('/DAC_IR',[(105,107),(105,119.75),(109,119.75)],p.B_Cu,.3)
    trace('/DAC_RED',[(138,107),(138,119.75),(146,119.75)],p.B_Cu,.3)
    trace('/5V',[(138.81,122.19),(139.8,122.2)],p.B_Cu,.6)
    via('/5V',(139.8,122.2))
    trace('/5V',[(139.8,122.2),(142.9625,121.5)],p.F_Cu,.6)
    cap=next(f for f in board.GetFootprints() if f.GetReference()=='C7')
    cap_supply=next(pad.GetPosition() for pad in cap.Pads() if pad.GetNumber()=='1')
    trace('/5V',[(p.ToMM(cap_supply.x),p.ToMM(cap_supply.y)),(135,120.5)],p.B_Cu,.6)
    trace('/SENSE_RED',[(148,135),(159.45,135),(159.45,134.5)],p.B_Cu,.28)
    via('/SENSE_RED',(159.45,134.5))
    trace('/SENSE_RED',[(159.45,134.5),(159.45,132.5)],p.F_Cu,.25)

    def line(a, b, layer, width=.05):
        shape = p.PCB_SHAPE()
        shape.SetShape(p.SHAPE_T_SEGMENT)
        shape.SetStart(vec(*a))
        shape.SetEnd(vec(*b))
        shape.SetLayer(layer)
        shape.SetWidth(mm(width))
        board.Add(shape)

    def silk(value,x,y,size=.8,back=False):
        label=p.PCB_TEXT(board)
        label.SetText(value);label.SetPosition(vec(x,y));label.SetTextSize(vec(size,size))
        label.SetTextThickness(mm(.1));label.SetLayer(p.B_SilkS if back else p.F_SilkS)
        label.SetMirrored(back);board.Add(label)

    silk('PPG LED/IR TX 70x40',135,101.5,.8)
    silk('IR',119,101.5,.8)
    silk('RED',151,101.5,.8)
    silk('DATN: PPG-Simulator',135,101.4,.8,True)
    silk('Nguyen Nhat Huy - Pham Thanh Vy',135,102.9,.8,True)
    for ref,x in (('J1',110.7),('J2',125.0),('J3',143.7),('J4',165.5)):
        f=next(q for q in board.GetFootprints() if q.GetReference()==ref)
        names={'J1':('IR','GND','SCL','SDA','3V3','GND'),
               'J2':('IR','GND','SCL','SDA','3V3','GND'),
               'J3':('RED','GND','SCL','SDA','3V3','GND'),
               'J4':('RED','GND')}[ref]
        for number,name in enumerate(names,1):
            pad=next(q for q in f.Pads() if q.GetNumber()==str(number))
            silk(name,x,p.ToMM(pad.GetPosition().y),.8,True)
    for ref,names in (('J5',('5V','IR-')),('J6',('5V','RED-')),('J7',('5V','GND'))):
        f=next(q for q in board.GetFootprints() if q.GetReference()==ref)
        for number,name in enumerate(names,1):
            pad=next(q for q in f.Pads() if q.GetNumber()==str(number))
            silk(name,p.ToMM(pad.GetPosition().x),138.85,.8,True)
    op=next(f for f in board.GetFootprints() if f.GetReference()=='U1')
    for number,name in ((1,'AMP_I'),(2,'SNS_I'),(3,'CMD_I'),(4,'GND'),(5,'CMD_R'),(6,'SNS_R'),(7,'AMP_R'),(8,'5V')):
        pad=next(q for q in op.Pads() if q.GetNumber()==str(number))
        silk(name,127.7 if number<=4 else 143.2,p.ToMM(pad.GetPosition().y),.8,True)
    for ref in ('Q1','Q2'):
        transistor=next(f for f in board.GetFootprints() if f.GetReference()==ref)
        for number,name in enumerate(('E','B','C'),1):
            pad=next(q for q in transistor.Pads() if q.GetNumber()==str(number))
            silk(name,p.ToMM(pad.GetPosition().x),133.55,.8,True)

    for a, b in [((100, 100), (170, 100)), ((170, 100), (170, 140)),
                 ((170, 140), (100, 140)), ((100, 140), (100, 100))]:
        line(a, b, p.Edge_Cuts)
    ground = next(n for n in nets.values() if n.GetNetname() == '/GND')
    zone = p.ZONE(board)
    zone.SetLayer(p.F_Cu)
    zone.SetNet(ground)
    zone.SetLocalClearance(mm(.3))
    zone.SetPadConnection(p.ZONE_CONNECTION_THERMAL)
    zone.SetThermalReliefGap(mm(.3))
    zone.SetThermalReliefSpokeWidth(mm(.4))
    zone.SetMinThickness(mm(.25))
    zone.SetIslandRemovalMode(p.ISLAND_REMOVAL_MODE_ALWAYS)
    zone.Outline().NewOutline()
    for x, y in ((100.6, 100.6), (169.4, 100.6), (169.4, 139.4), (100.6, 139.4)):
        pos = vec(x, y)
        zone.Outline().Append(pos.x, pos.y)
    board.Add(zone)
    back=p.ZONE(board)
    back.SetLayer(p.B_Cu);back.SetNet(ground);back.SetLocalClearance(mm(.3))
    back.SetPadConnection(p.ZONE_CONNECTION_THERMAL)
    back.SetThermalReliefGap(mm(.3));back.SetThermalReliefSpokeWidth(mm(.4))
    back.SetMinThickness(mm(.25));back.SetIslandRemovalMode(p.ISLAND_REMOVAL_MODE_ALWAYS)
    back.Outline().NewOutline()
    for x,y in ((100.6,100.6),(169.4,100.6),(169.4,139.4),(100.6,139.4)):
        pos=vec(x,y);back.Outline().Append(pos.x,pos.y)
    board.Add(back)
    def signature(t):
        return [t.GetNetname(),t.GetLayer(),[round(p.ToMM(t.GetStart().x),6),round(p.ToMM(t.GetStart().y),6)],
                [round(p.ToMM(t.GetEnd().x),6),round(p.ToMM(t.GetEnd().y),6)],round(p.ToMM(t.GetWidth()),6)]
    for edit in json.loads((HERE/'orthogonal_routes.json').read_text()):
        t=next(t for t in board.GetTracks() if not isinstance(t,p.PCB_VIA) and signature(t)==edit['original'])
        net=t.GetNet();layer=t.GetLayer();width=t.GetWidth();board.Remove(t)
        for a,b in zip(edit['points'],edit['points'][1:]):
            t=p.PCB_TRACK(board);t.SetNet(net);t.SetLayer(layer);t.SetWidth(width)
            t.SetStart(vec(*a));t.SetEnd(vec(*b));board.Add(t)
    p.ZONE_FILLER(board).Fill(board.Zones())
    p.SaveBoard(str(FILE), board)


    import sys
    sys.path.insert(0,str(next(parent for parent in HERE.parents if (parent/'routing_45.py').is_file())))
    from routing_45 import chamfer
    chamfer(FILE)
if __name__ == '__main__':
    import sys
    compact(Path(sys.argv[1]) if len(sys.argv) > 1 else FILE)
