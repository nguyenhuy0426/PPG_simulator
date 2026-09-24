#!/usr/bin/env python3
"""Generate the wired schematic and explicitly routed KiCad 10 PCB.

Run with KiCad's pcbnew Python, then refill zones and run ERC/DRC/parity.
"""
import argparse
import csv
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
NAME='led_ir_driver'
ROOT=str(uuid.uuid5(uuid.NAMESPACE_URL,'ppg-led-ir-driver-v1'))
def uid(s): return str(uuid.uuid5(uuid.UUID(ROOT),s))
def q(s): return json.dumps(str(s))
def fx(size=1.0): return f'(effects (font (size {size} {size})))'

# Pin numbers are PCB pad numbers, including module header rather than DAC IC.
PINS={
 'Conn6':[(str(i+1),n,'passive',-12.7,12.7-i*5.08,0) for i,n in enumerate(['OUT','GND','SCL','SDA','3V3','GND'])],
 'Conn2':[('1','1','passive',-10.16,2.54,0),('2','2','passive',-10.16,-2.54,0)],
 'LM358P':[('1','OUT_A','output',15.24,10.16,180),('2','IN_A-','input',-15.24,5.08,0),('3','IN_A+','input',-15.24,10.16,0),('4','V-','power_in',-15.24,-10.16,0),('5','IN_B+','input',-15.24,-2.54,0),('6','IN_B-','input',-15.24,-7.62,0),('7','OUT_B','output',15.24,-2.54,180),('8','V+','power_in',15.24,-10.16,180)],
 'NPN':[('1','E','passive',0,-7.62,90),('2','B','input',-7.62,0,0),('3','C','passive',0,7.62,270)],
 'R':[('1','~','passive',0,5.08,270),('2','~','passive',0,-5.08,90)],
 'C':[('1','~','passive',0,5.08,270),('2','~','passive',0,-5.08,90)],
 'CP':[('1','+','passive',0,5.08,270),('2','-','passive',0,-5.08,90)],
 'Flag':[('1','pwr','power_out',0,0,90)],
 'Hole':[],
}
FPS={
 'Socket6':'Connector_PinSocket_2.54mm.pretty/PinSocket_1x06_P2.54mm_Vertical.kicad_mod',
 'Header6':'Connector_PinHeader_2.54mm.pretty/PinHeader_1x06_P2.54mm_Vertical.kicad_mod',
 'Header2':'Connector_PinHeader_2.54mm.pretty/PinHeader_1x02_P2.54mm_Vertical.kicad_mod',
 'DIP8':'Package_DIP.pretty/DIP-8_W7.62mm_Socket.kicad_mod',
 'NPN':'Package_TO_SOT_THT.pretty/TO-92_Inline_Wide.kicad_mod',
 'R':'Resistor_THT.pretty/R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal.kicad_mod',
 'C':'Capacitor_THT.pretty/C_Disc_D5.0mm_W2.5mm_P2.50mm.kicad_mod',
 'CP':'Capacitor_THT.pretty/CP_Radial_D5.0mm_P2.00mm.kicad_mod',
 'Hole':'MountingHole.pretty/MountingHole_3.2mm_M3.kicad_mod',
}
PARTS=[]
def part(ref,kind,value,nets,fp,xy,sch,angle=0,dnp=False):
    PARTS.append(dict(ref=ref,kind=kind,value=value,nets=nets,fp=fp,xy=xy,sch=sch,angle=angle,dnp=dnp))

for ch,s,x in [('IR','J1',7),('RED','J3',40)]:
    ns=[f'DAC_{ch}','GND','SCL','SDA','3V3','GND']
    part(s,'Conn6',f'MCP4725 {ch} '+('0x60' if ch=='IR' else '0x61'),ns,'Socket6',(x,10),(43.18 if ch=='IR' else 228.6,50.8))
# One cable input is sufficient because both DACs deliberately share the same
# Pi I2C bus, 3.3 V rail and ground. Pins 1/2 remain a 1:1 breakout of J1.
part('J2','Conn6','PI I2C INPUT / IR OUT',['DAC_IR','GND','SCL','SDA','3V3','GND'],'Header6',(29,10),(116.84,50.8))

part('U1','LM358P','LM358P / DIP8 socket',['AMP_IR','SENSE_IR','CMD_IR','GND','CMD_RED','SENSE_RED','AMP_RED','5V'],'DIP8',(31.19,30.19),(193.04,139.7))
for i,ch in enumerate(['IR','RED']):
    sx=38.1+i*190.5
    left=i==0
    part(f'Q{i+1}','NPN','2N4401 / E-B-C',[f'SENSE_{ch}',f'BASE_{ch}',f'LED_K_{ch}'],'NPN',(18 if left else 47,41),(sx+66.04,152.4))
    for ref,val,ns,xy,sc,ang,dnp in [
      (f'R{1+i*5}','10k 1%',[f'DAC_{ch}',f'CMD_{ch}'],(9 if left else 46,27),(sx,114.3),0,False),
      (f'R{2+i*5}','10k 1%',[f'CMD_{ch}','GND'],(16.62 if left else 53.62,31),(sx,147.32),180,False),
      (f'R{3+i*5}','1k',[f'AMP_{ch}',f'BASE_{ch}'],(23 if left else 46,29.5 if left else 35),(sx+33.02,114.3),270 if left else 0,False),
      (f'R{4+i*5}','82R 1% 0.25W' if left else '100R 1% 0.25W',[f'SENSE_{ch}','GND'],(12 if left else 48,46),(sx+66.04,187.96),0,False),
    ]: part(ref,'R',val,ns,'R',xy,sc,ang,dnp)
    part(f'C{2+i*2}','C','DNP loop comp',[f'AMP_{ch}',f'SENSE_{ch}'],'C',(27 if left else 43,38),(sx+99.06,187.96),270,True)
    part(f'J{5+i}','Conn2',f'{ch} LED A / K',['5V',f'LED_K_{ch}'],'Header2',(23 if left else 46,50),(sx+99.06,114.3),90)
part('J7','Conn2','5V INPUT / GND',['5V','GND'],'Header2',(34,50),(193.04,218.44),90)
part('C5','C','100nF X7R 50V',['5V','GND'],'C',(38.81,26),(132.08,226.06))
part('C7','CP','10uF 16V',['5V','GND'],'CP',(30,45),(292.1,226.06))
for i,xy in enumerate([(4,4),(66,4),(4,51),(66,51)],1):
    part(f'H{i}','Hole','M3 / 3.2mm',[],'Hole',xy,(30.48+i*22.86,264.16))

def symbol(kind):
    ref={'R':'R','C':'C','CP':'C','NPN':'Q','LM358P':'U','Flag':'#FLG','Hole':'H'}.get(kind,'J')
    out=[f'(symbol "TX:{kind}" (pin_names (offset 0.5)) (in_bom yes) (on_board yes)',f'(property "Reference" "{ref}" (at 0 18 0) {fx()})',f'(property "Value" "{kind}" (at 0 16 0) {fx()})',f'(symbol "{kind}_0_1"']
    if kind in ('Conn6','Conn2','LM358P'):
        w,h=(10.16,15.24) if kind!='Conn2' else (5.08,5.08)
        out.append(f'(rectangle (start {-w} {h}) (end {w} {-h}) (stroke (width 0.254) (type default)) (fill (type background)))')
    elif kind=='R':
        out.append('(rectangle (start -1.27 3.81) (end 1.27 -3.81) (stroke (width 0.254) (type default)) (fill (type none)))')
    elif kind in ('C','CP'):
        for yy in (-.762,.762): out.append(f'(polyline (pts (xy -2.54 {yy}) (xy 2.54 {yy})) (stroke (width 0.254) (type default)) (fill (type none)))')
        if kind=='CP': out.append(f'(text "+" (at -3.5 2.5 0) {fx()})')
    elif kind=='NPN':
        for points in ['-2.54 -3.81) (xy -2.54 3.81','-2.54 1.27) (xy 0 5.08','-2.54 -1.27) (xy 0 -5.08','-7.62 0) (xy -2.54 0','-1.8 -4.4) (xy 0 -5.08) (xy -.1 -3.1']:
            out.append(f'(polyline (pts (xy {points})) (stroke (width .254) (type default)) (fill (type none)))')
    else: out.append('(circle (center 0 0) (radius 1.27) (stroke (width .254) (type default)) (fill (type none)))')
    out+=[')',f'(symbol "{kind}_1_1"']
    for num,name,typ,x,y,ang in PINS[kind]:
        length=0 if kind=='Flag' else (1.27 if kind=='R' else (4.318 if kind in ('C','CP') else (2.54 if kind=='NPN' else 5.08)))
        out.append(f'(pin {typ} line (at {x} {y} {ang}) (length {length}) (name {q(name)} {fx()}) (number "{num}" {fx()}))')
    return '\n'.join(out+['))'])

def board(share,cli):
    import pcbnew as p
    mm=p.FromMM
    def vec(x,y): return p.VECTOR2I(mm(x),mm(y))
    b=p.BOARD(); b.GetDesignSettings().SetCopperLayerCount(2)
    b.GetDesignSettings().SetBoardThickness(mm(1.6))
    subprocess.run([cli,'sch','export','netlist','--format','kicadxml','-o',str(HERE/'reports'/f'{NAME}.net'),str(HERE/f'{NAME}.kicad_sch')],check=True)
    pin_nets={}
    for n in ET.parse(HERE/'reports'/f'{NAME}.net').findall('.//nets/net'):
        net=p.NETINFO_ITEM(b,n.attrib['name']); b.Add(net)
        for nd in n.findall('node'): pin_nets[nd.attrib['ref'],nd.attrib['pin']]=net
    lib=HERE/'TX.pretty'; lib.mkdir(exist_ok=True)
    for name,src in FPS.items():
        s=(share/'footprints'/src).read_text()
        s=re.sub(r'^\(footprint "[^"]+"',f'(footprint "{name}"',s)
        for model in re.findall(r'\(model "([^\"]+)"',s):
            suffix=model.split('}/')[-1]; source=share/'3dmodels'/suffix
            if source.exists():
                dest=HERE/'3dmodels'/suffix; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,dest)
                s=s.replace(model,'${KIPRJMOD}/3dmodels/'+suffix)
        (lib/f'{name}.kicad_mod').write_text(s)
    (HERE/'fp-lib-table').write_text('(fp_lib_table (version 7) (lib (name "TX") (type "KiCad") (uri "${KIPRJMOD}/TX.pretty") (options "") (descr "Driver local footprints")))')
    footprints={}
    for d in PARTS:
        fp=p.FootprintLoad(str(lib),d['fp']); fp.SetReference(d['ref']); fp.SetValue(d['value']); fp.SetFPID(p.LIB_ID('TX',d['fp']))
        x,y=d['xy']; fp.SetPosition(vec(100+x,100+y)); fp.SetOrientationDegrees(d['angle'])
        path=p.KIID_PATH(); path.push_back(p.KIID(ROOT)); path.push_back(p.KIID(uid(d['ref']))); fp.SetPath(path)
        fp.SetAttributes(fp.GetAttributes() & ~p.FP_EXCLUDE_FROM_BOM)
        if d['dnp']: fp.SetAttributes(fp.GetAttributes() | p.FP_DNP)
        for pad in fp.Pads():
            if (d['ref'],pad.GetNumber()) in pin_nets: pad.SetNet(pin_nets[d['ref'],pad.GetNumber()])
        fp.Value().SetVisible(False)
        fp.Reference().SetTextSize(vec(.8,.8)); fp.Reference().SetTextThickness(mm(.12)); fp.Reference().SetTextAngle(p.EDA_ANGLE(0,p.DEGREES_T))
        fp.Reference().SetPosition(vec(100+x+2,100+y-2.5))
        if d['kind']=='Hole': fp.Reference().SetVisible(False)
        b.Add(fp); footprints[d['ref']]=fp
    def line(a,c,layer):
        s=p.PCB_SHAPE(); s.SetShape(p.SHAPE_T_SEGMENT); s.SetStart(vec(100+a[0],100+a[1])); s.SetEnd(vec(100+c[0],100+c[1])); s.SetLayer(layer); s.SetWidth(mm(.05 if layer==p.Edge_Cuts else .15)); b.Add(s)
    for a,c in [((0,0),(70,0)),((70,0),(70,55)),((70,55),(0,55)),((0,55),(0,0))]: line(a,c,p.Edge_Cuts)
    def silk(s,x,y,size=1,back=False,angle=0):
        t=p.PCB_TEXT(b); t.SetText(s); t.SetPosition(vec(100+x,100+y)); t.SetTextSize(vec(size,size)); t.SetTextThickness(mm(.13)); t.SetLayer(p.B_SilkS if back else p.F_SilkS); t.SetMirrored(back); t.SetTextAngle(p.EDA_ANGLE(angle,p.DEGREES_T)); b.Add(t)
    silk('DATN: PPG-Simulator',35,2.8,1,True)
    silk('Nguyen Nhat Huy - Pham Thanh Vy',35,6,.8,True)
    silk('PPG TX  v1.3',35,2.5)
    for x,ch,addr in [(7,'IR','0x60'),(40,'RED','0x61')]:
        silk('MCP4725 '+ch+' '+addr,x+9,4.6,.85)
        for i,label in enumerate(['OUT','GND','SCL','SDA','3V3','GND']): silk(label,x+5.5,10+i*2.54,.8)
        # Module body projection is an assembly guide, not a measured outline.
        for a,c in [((x+1,6),(x+19,6)),((x+19,6),(x+19,23)),((x+19,23),(x+1,23))]: line(a,c,p.Dwgs_User)
    silk('IR A+ K-',24,53.5,.8); silk('RED A+ K-',47,53.5,.8); silk('5V GND',35,53.5,.8)
    silk('DAC: 3.3V ONLY',35,6.5,.9)
    silk('SAME Pi BUS',35,8,.8)
    for i,label in enumerate(['OUT','GND','SCL','SDA','3V3','GND']):
        silk(label,32,10+i*2.54,.8)
    # Bracket only pins 3..6: the four-wire I2C cable must not occupy 1..4.
    for x in (29,):
        for a,c in [((x-1.8,14),(x-2.3,14)),((x-2.3,14),(x-2.3,23.8)),((x-2.3,23.8),(x-1.8,23.8))]:
            line(a,c,p.F_SilkS)
    silk('J2 PI: SCL SDA 3V3 GND',35,54,.8,True)
    silk('C2 / C4: DNP',35,41.5,.8)
    silk('82R',15.8,48.2,.8); silk('100R',51.8,48.2,.8)
    for x in (18,47):
        for i,s in enumerate(('E','B','C')): silk(s,x+2.54*i,44,.8)

    def pad_local(ref,pin):
        pad=next(x for x in footprints[ref].Pads() if x.GetNumber()==str(pin)); pos=pad.GetPosition(); return p.ToMM(pos.x)-100,p.ToMM(pos.y)-100
    # Rear labels use signal names only; connector/component references remain.
    for ref,title,labels,label_x in (
        ('J1','J1 IR DAC',('IR_OUT','GND','SCL','SDA','3V3','GND'),12),
        ('J2','J2 PI',('IR_OUT','GND','SCL','SDA','3V3','GND'),34),
        ('J3','J3 RED DAC',('RED_OUT','GND','SCL','SDA','3V3','GND'),45),
    ):
        x0,_=pad_local(ref,1); silk(title,x0,7.8,.8,True)
        for pin,label in enumerate(labels,1):
            _,y=pad_local(ref,pin); silk(label,label_x,y,.8,True)
    for ref,title,labels in (
        ('J5','J5 IR LED',('A+','K-')),
        ('J6','J6 RED LED',('A+','K-')),
        ('J7','J7 POWER',('5V','GND')),
    ):
        coords=[pad_local(ref,pin) for pin in (1,2)]
        silk(title,sum(x for x,_ in coords)/2,48.2,.8,True)
        for (x,_),label in zip(coords,labels): silk(label,x,53.0,.8,True)
    silk('U1 LM358',35,27.2,.8,True)
    for pin,label in ((1,'AMP_I'),(2,'SNS_I'),(3,'CMD_I'),(4,'GND')):
        _,y=pad_local('U1',pin); silk(label,5.0,y,.8,True)
    for pin,label in ((8,'5V'),(7,'AMP_R'),(6,'SNS_R'),(5,'CMD_R')):
        _,y=pad_local('U1',pin); silk(label,65.0,y,.8,True)
    for ref,title in (('Q1','Q1 IR E-B-C'),('Q2','Q2 RED E-B-C')):
        coords=[pad_local(ref,pin) for pin in (1,2,3)]
        silk(title,sum(x for x,_ in coords)/3,39.2,.8,True)
        for (x,_),label in zip(coords,('E','B','C')): silk(label,x,43.7,.8,True)
    # Place refdes in nearby free silk area without crossing component outlines.
    def rect(bb,pad=.15):
        return (p.ToMM(bb.GetX())-pad,p.ToMM(bb.GetY())-pad,p.ToMM(bb.GetRight())+pad,p.ToMM(bb.GetBottom())+pad)
    def overlap(a,c): return a[0]<c[2] and a[2]>c[0] and a[1]<c[3] and a[3]>c[1]
    occupied=[rect(t.GetBoundingBox()) for t in b.GetDrawings() if t.GetLayer()==p.F_SilkS]
    for fp in b.GetFootprints():
        for item in list(fp.GraphicalItems())+list(fp.Pads()):
            if isinstance(item,p.PAD) or item.GetLayer() in (p.F_SilkS,p.F_CrtYd): occupied.append(rect(item.GetBoundingBox()))
    for fp in sorted(b.GetFootprints(),key=lambda f:f.GetReference()):
        if fp.GetReference().startswith('H'): continue
        t=fp.Reference(); pos=fp.GetPosition(); x,y=p.ToMM(pos.x),p.ToMM(pos.y)
        candidates=[(dx*dx+dy*dy,dx,dy) for dx in range(-9,11) for dy in range(-7,8)]
        for _,dx,dy in sorted(candidates):
            t.SetPosition(vec(x+dx,y+dy)); r=rect(t.GetBoundingBox())
            if r[0]>100.5 and r[2]<169.5 and r[1]>100.5 and r[3]<154.5 and not any(overlap(r,c) for c in occupied):
                occupied.append(r); break
        else: raise RuntimeError('No refdes position for '+fp.GetReference())
    from route_board import route_board
    route_board(b)
    p.ZONE_FILLER(b).Fill(b.Zones())
    p.SaveBoard(str(HERE/f'{NAME}.kicad_pcb'),b)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--share',required=True,type=Path); ap.add_argument('--cli',required=True); a=ap.parse_args()
    (HERE/'reports').mkdir(exist_ok=True)
    project={'meta':{'filename':NAME+'.kicad_pro','version':1},'board':{'design_settings':{'rules':{'min_clearance':.25,'min_track_width':.3,'min_through_hole_diameter':.3,'min_hole_clearance':.25,'min_copper_edge_clearance':.3}}},'net_settings':{'classes':[{'name':'Default','clearance':.25,'track_width':.35,'via_diameter':.8,'via_drill':.4,'microvia_diameter':.3,'microvia_drill':.1,'diff_pair_width':.2,'diff_pair_gap':.25,'diff_pair_via_gap':.25}]}}
    (HERE/f'{NAME}.kicad_pro').write_text(json.dumps(project,indent=2)+'\n')
    from schematic_connected import write_schematic
    write_schematic(HERE,NAME,ROOT,PARTS,uid,q,fx,symbol)
    board(a.share,a.cli)
    with (HERE/'BOM.csv').open('w') as f:
        w=csv.writer(f); w.writerow(['Reference','Value','Footprint','Fit'])
        for d in PARTS: w.writerow([d['ref'],d['value'],'TX:'+d['fp'],'DNP' if d['dnp'] else 'YES'])

if __name__=='__main__': main()
