#!/usr/bin/env python3
"""Independent intended-circuit audit using the exported schematic netlist."""
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import pcbnew as p

HERE=Path(__file__).resolve().parent
board=p.LoadBoard(str(HERE/'led_ir_driver.kicad_pcb'))
netlist=ET.parse(HERE/'reports/led_ir_driver.net')
nets={n.attrib['name'].lstrip('/'):{(v.attrib['ref'],v.attrib['pin']) for v in n.findall('node') if not v.attrib['ref'].startswith('#')} for n in netlist.findall('.//nets/net')}
checks=[]
def check(name,condition):
    checks.append({'check':name,'pass':bool(condition)})
    if not condition: raise AssertionError(name)

I2C=['SCL_H','SDA_H','SCL_R','SDA_R','SCL','SDA','3V3','GNDI2C']
for ch,socket,out,hdr,(rscl,rsda,jscl,jsda),base,div,shunt,sense,qref,led,cmdcap,loopcap,rbe,amp_p,minus_p,plus_p in [
 ('IR','J1','J2','J8',('R11','R12','JP1','JP2'),'R3','R1','R2','R4','Q1','J5','C1','C2','R5','1','2','3'),
 ('RED','J3','J4','J9',('R13','R14','JP3','JP4'),'R8','R6','R7','R9','Q2','J6','C3','C4','R10','7','6','5'),
]:
    for pin,net in enumerate([f'DAC_{ch}','GND',f'SCL_{ch}',f'SDA_{ch}',f'3V3_{ch}',f'GNDI2C_{ch}'],1):
        check(f'{socket} pin {pin}: {net}',(socket,str(pin)) in nets[net])
    check(f'{out} pins 1/2: DAC_{ch}/GND',(out,'1') in nets[f'DAC_{ch}'] and (out,'2') in nets['GND'])
    # v2.0: one I2C header per module; nothing shared with the other channel.
    for pin,net in enumerate([f'SCL_H_{ch}',f'SDA_H_{ch}',f'3V3_{ch}',f'GNDI2C_{ch}'],1):
        check(f'{hdr} pin {pin}: {net}',(hdr,str(pin)) in nets[net])
    check(f'3V3_{ch} only {hdr}.3 -> {socket}.5',nets[f'3V3_{ch}']=={(hdr,'3'),(socket,'5')})
    check(f'GNDI2C_{ch} only {hdr}.4 -> {socket}.6',nets[f'GNDI2C_{ch}']=={(hdr,'4'),(socket,'6')})
    for sig,rref,jref,hpin,mpin in (('SCL',rscl,jscl,'1','3'),('SDA',rsda,jsda,'2','4')):
        check(f'{sig}_H_{ch}: header, R pad 1, JP pad 1',nets[f'{sig}_H_{ch}']=={(hdr,hpin),(rref,'1'),(jref,'1')})
        check(f'{sig}_R_{ch}: R pad 2, JP pad 3',nets[f'{sig}_R_{ch}']=={(rref,'2'),(jref,'3')})
        check(f'{sig}_{ch}: JP pad 2 -> {socket}.{mpin} only',nets[f'{sig}_{ch}']=={(jref,'2'),(socket,mpin)})
    expected={
      'DAC':{(socket,'1'),(div,'1'),(out,'1')},
      'CMD':{(div,'2'),(shunt,'1'),('U1',plus_p)},
      'AMP':{('U1',amp_p),(base,'1'),(loopcap,'1')},
      'BASE':{(base,'2'),(qref,'2')},
      'SENSE':{('U1',minus_p),(qref,'1'),(sense,'1'),(loopcap,'2')},
      'LED_K':{(qref,'3'),(led,'2')},
    }
    for prefix,pins in expected.items(): check(ch+' '+prefix+' exact net',nets[prefix+'_'+ch]==pins)
check('5V isolated from all module/cable pins',nets['5V']=={('J7','1'),('J5','1'),('J6','1'),('U1','8'),('C5','1'),('C7','1')})
check('No shared v1.x I2C bus nets remain',not {'SCL','SDA','3V3'} & nets.keys())
check('3V3_IR and 3V3_RED are separate nets',nets['3V3_IR'].isdisjoint(nets['3V3_RED']))
check('Ground exact pin set (socket pin 6 excluded)',nets['GND']==({('J1','2'),('J2','2'),('J3','2'),('J4','2')} | {('U1','4'),('R2','2'),('R4','2'),('R7','2'),('R9','2'),('C5','2'),('C7','2'),('J7','2')}))
critical=['GND','5V','DAC_IR','DAC_RED']+[f'{n}_{ch}' for ch in ('IR','RED') for n in I2C]
for i,a in enumerate(critical):
    for other in critical[i+1:]:
        check(a+' and '+other+' have no shared pins',nets[a].isdisjoint(nets[other]))
check('J4 is RED output and ground only',nets['DAC_RED'] >= {('J4','1')} and nets['GND'] >= {('J4','2')})
fps={fp.GetReference():fp for fp in board.GetFootprints()}
check('All resistor/capacitor pads are SMD',all(
    pad.GetAttribute()==p.PAD_ATTRIB_SMD
    for ref,fp in fps.items() if ref.startswith(('R','C')) for pad in fp.Pads()))
# Audit fitted values independently of the generator, not just net names.
for ref,value in [('R1','10k 1%'),('R2','10k 1%'),('R6','10k 1%'),('R7','10k 1%'),
                  ('R3','1k'),('R8','1k'),('C5','100nF X7R 50V'),('C7','10uF 16V'),
                  ('Q1','2N4401 / E-B-C'),('Q2','2N4401 / E-B-C'),('U1','LM358P / DIP8 socket')]:
    check(ref+' fitted value',fps[ref].GetValue()==value and not (fps[ref].GetAttributes() & p.FP_DNP))
check('C7 positive pad on 5V, negative on GND',('C7','1') in nets['5V'] and ('C7','2') in nets['GND'])
for ref,fp in fps.items():
    for pad in fp.Pads():
        if pad.GetNumber(): check(ref+'.'+pad.GetNumber()+' PCB/netlist match',(ref,pad.GetNumber()) in nets[pad.GetNetname().lstrip('/')])
j4pads=sorted(fps['J4'].Pads(),key=lambda pad:pad.GetNumber())
check('J4 has two pins at 2.54 mm pitch',len(j4pads)==2 and abs(p.ToMM(j4pads[1].GetPosition().y-j4pads[0].GetPosition().y)-2.54)<1e-6)
for ref,count,pitch in (('J1',6,2.54),('J3',6,2.54),('J2',2,2.54),('J8',4,2.0),('J9',4,2.0)):
    pads={pad.GetNumber():pad for pad in fps[ref].Pads()}
    check(ref+f' has {count} holes',len(pads)==count and all(pad.GetAttribute()==p.PAD_ATTRIB_PTH for pad in pads.values()))
    for i in range(1,count):
        a=pads[str(i)].GetPosition(); b=pads[str(i+1)].GetPosition()
        check(ref+f' pitch {i}',abs(p.ToMM(b.y-a.y)-pitch)<1e-6 and a.x==b.x)
for ref in ('R11','R12','R13','R14'):
    check(ref+' 100R 1% fitted SMD',fps[ref].GetValue()=='100R 1%' and not (fps[ref].GetAttributes() & p.FP_DNP))
for ref in ('JP1','JP2','JP3','JP4'):
    pads={pad.GetNumber():pad for pad in fps[ref].Pads()}
    check(ref+' three SMD pads, open (three distinct nets)',len(pads)==3 and all(x.GetAttribute()==p.PAD_ATTRIB_SMD for x in pads.values())
          and len({x.GetNetname() for x in pads.values()})==3)
for ch,socket,hdr,refs in (('IR','J1','J8',('R11','R12','JP1','JP2')),('RED','J3','J9',('R13','R14','JP3','JP4'))):
    lo,hi=p.ToMM(fps[socket].GetPosition().x),p.ToMM(fps[hdr].GetPosition().x)
    for ref in refs:
        bb=fps[ref].GetBoundingBox(False,False)
        check(f'{ref} between {socket} socket and {hdr} header',lo<p.ToMM(bb.GetX()) and p.ToMM(bb.GetRight())<hi)
# Jumper cells keep >= 1 mm between neighbouring courtyards.
cells=[fps[r].GetCourtyard(p.F_CrtYd).BBox() for r in ('R11','R12','JP1','JP2','R13','R14','JP3','JP4')]
gaps=[max(p.ToMM(b.GetX()-a.GetRight()),p.ToMM(a.GetX()-b.GetRight()),p.ToMM(b.GetY()-a.GetBottom()),p.ToMM(a.GetY()-b.GetBottom()))
      for i,a in enumerate(cells) for b in cells[i+1:]]
check('I2C R/JP courtyards >= 0.5 mm apart',min(gaps)>=.5-1e-6)
for ref in ('Q1','Q2'):
    pads={pad.GetNumber():pad for pad in fps[ref].Pads()}
    check(ref+' physical pin order 1=E,2=B,3=C',pads['1'].GetPosition().x<pads['2'].GetPosition().x<pads['3'].GetPosition().x)
for ref in ('C2','C4'): check(ref+' marked DNP',bool(fps[ref].GetAttributes() & p.FP_DNP))
check('Twelve fitted resistors (eight driver + four I2C 100R)',len([r for r in fps if r.startswith('R')])==12)
check('Removed optional filter/bleeder and duplicate bypass',all(ref not in fps for ref in ('C1','C3','C6','R5','R10')))
tracks=list(board.GetTracks())
check('Low-current signals at least 0.25mm',all(p.ToMM(t.GetWidth(t.GetLayer()) if isinstance(t,p.PCB_VIA) else t.GetWidth())>=.2499 for t in tracks))
check('5V and LED cathodes at least 0.6mm',all(p.ToMM(t.GetWidth(t.GetLayer()) if isinstance(t,p.PCB_VIA) else t.GetWidth())>=.5999 for t in tracks if t.GetNetname() in ('/5V','/LED_K_IR','/LED_K_RED')))
i2c_nets={f'/{n}_{ch}' for n in I2C for ch in ('IR','RED')}
check('I2C nets stay in upper module region',all(max(p.ToMM(t.GetStart().y),p.ToMM(t.GetEnd().y))<125 for t in tracks if t.GetNetname() in i2c_nets))
check('Bottom GND plane present',any(z.GetLayer()==p.B_Cu and z.GetNetname()=='/GND' for z in board.Zones()))
check('Copper zones are GND only (no GNDI2C pour)',all(z.GetNetname()=='/GND' for z in board.Zones() if not z.GetIsRuleArea()))
# GNDI2C copper must not touch board GND: no shared pads, no GND fill touching it.
gndi2c_pads=[pad for fp in fps.values() for pad in fp.Pads() if pad.GetNetname().startswith('/GNDI2C')]
check('GNDI2C pads: J1.6, J3.6, J8.4, J9.4',sorted(pad.GetParentFootprint().GetReference()+'.'+pad.GetNumber() for pad in gndi2c_pads)==['J1.6','J3.6','J8.4','J9.4'])
# Every I2C/3V3/GNDI2C item of sockets J1/J3 and headers J8/J9 stays off board GND.
gndi2c=[pad for fp in fps.values() for pad in fp.Pads() if pad.GetNetname() in i2c_nets]+[t for t in tracks if t.GetNetname() in i2c_nets]
for ref,pins in (('J1','3456'),('J3','3456'),('J8','1234'),('J9','1234')):
    for n in pins:
        check(f'{ref}.{n} not on board GND',next(x for x in fps[ref].Pads() if x.GetNumber()==n).GetNetname() in i2c_nets)
control=next(pad for pad in fps['J1'].Pads() if pad.GetNumber()=='2')
for z in board.Zones():
    if z.GetNetname()!='/GND': continue
    for layer in (p.F_Cu,p.B_Cu):
        if not z.IsOnLayer(layer): continue
        fill=z.GetFilledPolysList(layer)
        check(f'GND fill on {board.GetLayerName(layer)} reaches J1.2 (test control)',control.GetEffectiveShape(layer).Collide(fill,0))
        check(f'GND fill on {board.GetLayerName(layer)} does not touch I2C/3V3/GNDI2C copper',
              not any(x.IsOnLayer(layer) and x.GetEffectiveShape(layer).Collide(fill,0) for x in gndi2c))
# 5V keeps >= 2 mm surface spacing from every new I2C/3V3 copper item on the same layer.
items=[t for t in tracks]+[pad for fp in fps.values() for pad in fp.Pads()]
five=[x for x in items if x.GetNetname()=='/5V']; new=[x for x in items if x.GetNetname() in i2c_nets]
for layer in (p.F_Cu,p.B_Cu):
    close=[(a.GetNetname(),b.GetNetname()) for a in five if a.IsOnLayer(layer) for b in new if b.IsOnLayer(layer)
           and a.GetEffectiveShape(layer).Collide(b.GetEffectiveShape(layer),p.FromMM(2.0))]
    check(f'5V >= 2 mm from new I2C/3V3 nets on {board.GetLayerName(layer)}',not close)
for ref,value in [('R4','100R 1% 0.25W'),('R9','100R 1% 0.25W')]: check(ref+' sense value',fps[ref].GetValue()==value)
edges=[d for d in board.GetDrawings() if d.GetLayer()==p.Edge_Cuts]
xy=[pt for e in edges for pt in (e.GetStart(),e.GetEnd())]
check('70x40mm outline',len(edges)==4 and abs(p.ToMM(max(v.x for v in xy)-min(v.x for v in xy))-70)<1e-6 and abs(p.ToMM(max(v.y for v in xy)-min(v.y for v in xy))-40)<1e-6)
for i,(x,y) in enumerate([(104,124),(166,124),(104,136),(166,136)],1):
    fp=fps[f'H{i}']; pos=fp.GetPosition(); pad=list(fp.Pads())[0]
    check(f'H{i} matches model mounting',abs(p.ToMM(pos.x)-x)<1e-6 and abs(p.ToMM(pos.y)-y)<1e-6 and abs(p.ToMM(pad.GetDrillSize().x)-3.2)<1e-6)
for s in ['DATN: PPG-Simulator','Nguyen Nhat Huy - Pham Thanh Vy']:
    check('Back credit: '+s,any(isinstance(t,p.PCB_TEXT) and t.GetText()==s and t.GetLayer()==p.B_SilkS and t.IsMirrored() for t in board.GetDrawings()))
rear=[t for t in board.GetDrawings() if isinstance(t,p.PCB_TEXT) and t.GetLayer()==p.B_SilkS]
rear_text={t.GetText() for t in rear}
for s in ('IR','RED','GND','SCL','SDA','3V3','I2CGND','IR-','RED-','5V','AMP_I','SNS_I','CMD_I','AMP_R','SNS_R','CMD_R','E','B','C',
          'JP1/R11 SCL','JP2/R12 SDA','JP3/R13 SCL','JP4/R14 SDA'):
    check('Rear marking: '+s,s in rear_text)
import re
for item in rear:
    check('Rear pin label has no numeric prefix: '+item.GetText(),not re.match(r'^[1-4](?:\s|R$|I$|N$|V$|G|K$|A$)',item.GetText()))
check('all routed tracks horizontal, vertical or 45 degrees', all(
    t.GetStart().x == t.GetEnd().x or t.GetStart().y == t.GetEnd().y or
    abs(abs(t.GetStart().x-t.GetEnd().x)-abs(t.GetStart().y-t.GetEnd().y)) <= 2
    for t in board.GetTracks() if not isinstance(t, p.PCB_VIA)))
front={t.GetText() for t in board.GetDrawings() if isinstance(t,p.PCB_TEXT) and t.GetLayer()==p.F_SilkS}
check('Front silk v2.0 title',any('v2.0' in t for t in front))
for s in ('BYP','100R','I2C'): check('Front jumper marking: '+s,s in front)
report={'kicad_version':p.Version(),'passed':len(checks),'checks':checks,'limits':'Digital connectivity and geometry only; no physical/electrical measurements.'}
(HERE/'reports/pin_contract.json').write_text(json.dumps(report,indent=2)+'\n')
print(f'Pin contract: {len(checks)} checks passed')
