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

for ch,socket,cable,base,div,shunt,sense,qref,led,cmdcap,loopcap,rbe,amp_p,minus_p,plus_p in [
 ('IR','J1','J2','R3','R1','R2','R4','Q1','J5','C1','C2','R5','1','2','3'),
 ('RED','J3',None,'R8','R6','R7','R9','Q2','J6','C3','C4','R10','7','6','5'),
]:
    for pin,net in enumerate([f'DAC_{ch}','GND','SCL','SDA','3V3','GND'],1):
        required={(socket,str(pin))}
        if cable: required.add((cable,str(pin)))
        check(f'{socket}'+(f'/{cable}' if cable else '')+f' pin {pin}: {net}',required<=nets[net])
    expected={
      'DAC':({(socket,'1'),(div,'1')} | ({(cable,'1')} if cable else set())),
      'CMD':{(div,'2'),(shunt,'1'),('U1',plus_p)},
      'AMP':{('U1',amp_p),(base,'1'),(loopcap,'1')},
      'BASE':{(base,'2'),(qref,'2')},
      'SENSE':{('U1',minus_p),(qref,'1'),(sense,'1'),(loopcap,'2')},
      'LED_K':{(qref,'3'),(led,'2')},
    }
    for prefix,pins in expected.items(): check(ch+' '+prefix+' exact net',nets[prefix+'_'+ch]==pins)
check('5V isolated from all module/cable pins',nets['5V']=={('J7','1'),('J5','1'),('J6','1'),('U1','8'),('C5','1'),('C7','1')})
check('3V3 only module/cable supply',nets['3V3']=={(j,'5') for j in ('J1','J2','J3')})
check('I2C SDA shared on pin4',nets['SDA']=={(j,'4') for j in ('J1','J2','J3')})
check('I2C SCL shared on pin3',nets['SCL']=={(j,'3') for j in ('J1','J2','J3')})
check('Ground exact pin set',nets['GND']==({(j,pin) for j in ('J1','J2','J3') for pin in ('2','6')} | {('U1','4'),('R2','2'),('R4','2'),('R7','2'),('R9','2'),('C5','2'),('C7','2'),('J7','2')}))
critical=['GND','3V3','5V','SCL','SDA','DAC_IR','DAC_RED']
for i,a in enumerate(critical):
    for other in critical[i+1:]:
        check(a+' and '+other+' have no shared pins',nets[a].isdisjoint(nets[other]))
check('Only one Pi cable header remains',all(('J4',str(pin)) not in pins for pins in nets.values() for pin in range(1,7)))
check('Four-wire cable maps to J2 pads 3..6',all(('J2',str(pin)) in nets[net] for pin,net in [(3,'SCL'),(4,'SDA'),(5,'3V3'),(6,'GND')]))
fps={fp.GetReference():fp for fp in board.GetFootprints()}
for ref,fp in fps.items():
    for pad in fp.Pads():
        if pad.GetNumber(): check(ref+'.'+pad.GetNumber()+' PCB/netlist match',(ref,pad.GetNumber()) in nets[pad.GetNetname().lstrip('/')])
check('J4 footprint removed', 'J4' not in fps)
for ref in ('J1','J2','J3'):
    pads={pad.GetNumber():pad for pad in fps[ref].Pads()}
    check(ref+' has six holes',len(pads)==6)
    for i in range(1,6):
        a=pads[str(i)].GetPosition(); b=pads[str(i+1)].GetPosition()
        check(ref+f' pitch {i}',abs(p.ToMM(b.y-a.y)-2.54)<1e-6 and a.x==b.x)
for ref in ('Q1','Q2'):
    pads={pad.GetNumber():pad for pad in fps[ref].Pads()}
    check(ref+' physical pin order 1=E,2=B,3=C',pads['1'].GetPosition().x<pads['2'].GetPosition().x<pads['3'].GetPosition().x)
for ref in ('C2','C4'): check(ref+' marked DNP',bool(fps[ref].GetAttributes() & p.FP_DNP))
check('Only eight fitted resistors',len([r for r in fps if r.startswith('R')])==8)
check('Removed optional filter/bleeder and duplicate bypass',all(ref not in fps for ref in ('C1','C3','C6','R5','R10')))
tracks=list(board.GetTracks())
check('Tracks at least 0.35mm',all(p.ToMM(t.GetWidth())>=.3499 for t in tracks))
check('5V and LED cathodes at least 0.6mm',all(p.ToMM(t.GetWidth())>=.5999 for t in tracks if t.GetNetname() in ('/5V','/LED_K_IR','/LED_K_RED')))
check('I2C buses stay in upper module region',all(max(p.ToMM(t.GetStart().y),p.ToMM(t.GetEnd().y))<125 for t in tracks if t.GetNetname() in ('/SDA','/SCL')))
check('Bottom GND plane present',any(z.GetLayer()==p.B_Cu and z.GetNetname()=='/GND' for z in board.Zones()))
for ref,value in [('R4','82R 1% 0.25W'),('R9','100R 1% 0.25W')]: check(ref+' sense value',fps[ref].GetValue()==value)
edges=[d for d in board.GetDrawings() if d.GetLayer()==p.Edge_Cuts]
xy=[pt for e in edges for pt in (e.GetStart(),e.GetEnd())]
check('70x55mm outline',len(edges)==4 and abs(p.ToMM(max(v.x for v in xy)-min(v.x for v in xy))-70)<1e-6 and abs(p.ToMM(max(v.y for v in xy)-min(v.y for v in xy))-55)<1e-6)
for i,(x,y) in enumerate([(104,104),(166,104),(104,151),(166,151)],1):
    fp=fps[f'H{i}']; pos=fp.GetPosition(); pad=list(fp.Pads())[0]
    check(f'H{i} matches model mounting',abs(p.ToMM(pos.x)-x)<1e-6 and abs(p.ToMM(pos.y)-y)<1e-6 and abs(p.ToMM(pad.GetDrillSize().x)-3.2)<1e-6)
for s in ['DATN: PPG-Simulator','Nguyen Nhat Huy - Pham Thanh Vy']:
    check('Back credit: '+s,any(isinstance(t,p.PCB_TEXT) and t.GetText()==s and t.GetLayer()==p.B_SilkS and t.IsMirrored() for t in board.GetDrawings()))
rear=[t for t in board.GetDrawings() if isinstance(t,p.PCB_TEXT) and t.GetLayer()==p.B_SilkS]
rear_text={t.GetText() for t in rear}
for s in ('J1 IR DAC','J2 PI','J3 RED DAC','J5 IR LED','J6 RED LED','J7 POWER','IR_OUT','RED_OUT','GND','SCL','SDA','3V3','A+','K-','5V','U1 LM358','AMP_I','SNS_I','CMD_I','AMP_R','SNS_R','CMD_R','E','B','C'):
    check('Rear marking: '+s,s in rear_text)
import re
for item in rear:
    check('Rear pin label has no numeric prefix: '+item.GetText(),not re.match(r'^[1-4](?:\s|R$|I$|N$|V$|G|K$|A$)',item.GetText()))
report={'kicad_version':p.Version(),'passed':len(checks),'checks':checks,'limits':'Digital connectivity and geometry only; no physical/electrical measurements.'}
(HERE/'reports/pin_contract.json').write_text(json.dumps(report,indent=2)+'\n')
print(f'Pin contract: {len(checks)} checks passed')
