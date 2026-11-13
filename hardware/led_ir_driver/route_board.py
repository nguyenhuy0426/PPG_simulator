"""Explicit, reviewable routing: coordinates in mm from board top-left.

Signals 0.35 mm; 3V3 bus 0.6 mm; 5V branches 0.6/0.8 mm.
Feedback is a separate branch ending on the sense resistor's upper pad.
The bottom GND pour supplies the return path without routing LED return
current through the receiver board.
"""
import pcbnew as p

def route_board(b, parts):
    nets={n.GetNetname().lstrip('/'):n for n in b.GetNetsByNetcode().values()}
    def vec(x,y): return p.VECTOR2I(p.FromMM(100+x),p.FromMM(100+y))
    def trace(net,pts,layer=p.F_Cu,width=.35):
        for a,c in zip(pts,pts[1:]):
            t=p.PCB_TRACK(b); t.SetStart(vec(*a)); t.SetEnd(vec(*c)); t.SetLayer(layer); t.SetWidth(p.FromMM(width)); t.SetNet(nets[net]); b.Add(t)
    # Straight parallel buses in the module area; no zig-zag between headers.
    for net,y,width in [('SCL',15.08,.35),('SDA',17.62,.35),('3V3',20.16,.6)]:
        target={'SCL':16.5,'SDA':18.5,'3V3':20.5}[net]
        trace(net,[(7,y),(26,y),(26,target),(29,target),(31,target),(31,y),(40,y)],width=width)
    trace('DAC_IR',[(7,10),(29,10)],p.B_Cu)
    trace('DAC_IR',[(7,10),(5,12),(5,23),(9,27)],p.B_Cu)
    trace('DAC_RED',[(40,10),(62,10)],p.B_Cu)
    trace('DAC_RED',[(40,10),(38,12),(38,24.3),(44,24.3),(46,26.3),(46,27)],p.B_Cu)

    # Left/IR command, base drive, emitter current and Kelvin feedback branch.
    trace('CMD_IR',[(16.62,27),(16.62,31),(16.62,33)])
    trace('CMD_IR',[(16.62,33),(25,33)],p.B_Cu)
    trace('CMD_IR',[(25,33),(27,33),(29,35),(29,35.27),(31.19,35.27)])
    for x in (16.62,25):
        via=p.PCB_VIA(b); via.SetPosition(vec(x,33)); via.SetWidth(p.FromMM(.8)); via.SetDrill(p.FromMM(.4))
        via.SetLayerPair(p.F_Cu,p.B_Cu); via.SetNet(nets['CMD_IR']); b.Add(via)
    trace('AMP_IR',[(31.19,30.19),(29,30.19),(27.81,29),(23,29),(23,29.5)])
    trace('AMP_IR',[(31.19,30.19),(27,30.19),(27,38)],p.B_Cu)
    trace('BASE_IR',[(23,37.12),(23,38.5),(20.54,38.5),(20.54,41)])
    trace('SENSE_IR',[(18,41),(12,41),(12,46)],width=.6)
    trace('SENSE_IR',[(31.19,32.73),(29.2,32.73),(29.2,43.2),(12,43.2),(12,46)],p.B_Cu)
    trace('SENSE_IR',[(27,40.5),(27,43.2)],p.B_Cu)
    trace('LED_K_IR',[(23.08,41),(24.8,42.72),(24.8,48.5),(25.54,49.24),(25.54,50)],width=.6)

    # Right/RED has the same functional ordering, with LM358B pin numbering.
    trace('CMD_RED',[(53.62,27),(53.62,31)])
    trace('CMD_RED',[(53.62,31),(53.62,29),(41.2,29),(41.2,37.81),(38.81,37.81)],p.B_Cu)
    trace('AMP_RED',[(38.81,32.73),(44,32.73),(46,34.73),(46,35)])
    trace('AMP_RED',[(46,35),(43,35),(43,38)])
    trace('BASE_RED',[(53.62,35),(53.62,38.5),(49.54,38.5),(49.54,41)])
    trace('SENSE_RED',[(47,41),(48,42),(48,46)],width=.6)
    trace('SENSE_RED',[(38.81,35.27),(40.8,35.27),(40.8,46),(48,46)])
    trace('SENSE_RED',[(43,40.5),(43,46),(48,46)],p.B_Cu)
    trace('LED_K_RED',[(52.08,41),(55,41),(58,44),(58,49),(48.54,49),(48.54,50)],width=.6)

    # Bulk -> op-amp branch separate from the two LED anode branches.
    trace('5V',[(34,50),(34,52),(23,52),(23,50)],p.B_Cu,.8)
    trace('5V',[(34,52),(46,52),(46,50)],p.B_Cu,.8)
    trace('5V',[(34,50),(34,47),(30,47),(30,45)],p.F_Cu,.8)
    trace('5V',[(34,50),(35,49),(35,28),(38.81,28),(38.81,30.19)],p.B_Cu,.6)
    trace('5V',[(38.81,26),(38.81,28)],p.B_Cu,.6)
    zone=p.ZONE(b); zone.SetLayer(p.B_Cu); zone.SetNet(nets['GND'])
    zone.SetLocalClearance(p.FromMM(.3)); zone.SetPadConnection(p.ZONE_CONNECTION_THERMAL)
    zone.SetThermalReliefGap(p.FromMM(.3)); zone.SetThermalReliefSpokeWidth(p.FromMM(.5)); zone.SetMinThickness(p.FromMM(.25))
    poly=zone.Outline(); poly.NewOutline()
    for x,y in [(.6,.6),(69.4,.6),(69.4,54.4),(.6,54.4)]: poly.Append(vec(x,y).x,vec(x,y).y)
    b.Add(zone)

    # SMD pads connect on F.Cu. Add plated vias only at former THT anchors
    # that need B.Cu routing or the ground plane; no passive component holes.
    import math
    fps={f.GetReference():f for f in b.GetFootprints()}
    original_tracks=list(b.GetTracks())
    for d in parts:
        if d['kind'] not in ('R','C','CP'): continue
        pitch={'R':7.62,'C':2.5,'CP':2.0}[d['kind']]
        angle=math.radians(d['angle'])
        for pad in fps[d['ref']].Pads():
            n=int(pad.GetNumber())-1
            x=d['xy'][0]+n*pitch*math.cos(angle)
            y=d['xy'][1]-n*pitch*math.sin(angle)
            old=vec(x,y); new=pad.GetPosition(); net=pad.GetNetname().lstrip('/')
            needs_via=net=='GND' or any(t.GetLayer()==p.B_Cu and
                (t.GetStart()==old or t.GetEnd()==old) for t in original_tracks)
            if needs_via:
                via=p.PCB_VIA(b); via.SetPosition(old); via.SetWidth(p.FromMM(.8)); via.SetDrill(p.FromMM(.4))
                via.SetLayerPair(p.F_Cu,p.B_Cu); via.SetNet(nets[net]); b.Add(via)
            trace(net,[(x,y),(p.ToMM(new.x)-100,p.ToMM(new.y)-100)],
                  width=.6 if net in ('5V','GND') or net.startswith('SENSE') else .35)
