"""Readable wired schematic: one Pi cable input, two DACs, two current sinks.

Drawing coordinates use a 2.54 mm grid. U1A, U1B and U1C are units of the
same physical LM358P; only one DIP8 footprint is assigned on the PCB.
"""
from collections import Counter

def write_schematic(here,name,root,parts,uid,q,fx,base_symbol):
    def mm(v): return round(v*2.54,5)
    shapes={k:base_symbol(k) for k in ('R','C','CP','NPN','Hole','Flag','Conn2','Conn6')}
    def pin(num,label,typ,x,y,angle,length=2):
        return f'(pin {typ} line (at {mm(x)} {mm(y)} {angle}) (length {mm(length)}) (name {q(label)} {fx()}) (number "{num}" {fx()}))'
    socket=['(symbol "TX:Socket6" (pin_names (offset .5)) (in_bom yes) (on_board yes)',f'(property "Reference" "J" (at 0 18 0) {fx()})',f'(property "Value" "MCP4725" (at 0 16 0) {fx()})','(symbol "Socket6_0_1" (rectangle (start -10.16 15.24) (end 10.16 -15.24) (stroke (width .254) (type default)) (fill (type background))))','(symbol "Socket6_1_1"']
    for i,n in enumerate(['OUT','GND','SCL','SDA','3V3','GND']): socket.append(pin(i+1,n,'passive',5,5-i*2,180,1))
    shapes['Socket6']='\n'.join(socket+['))'])
    op=['(symbol "TX:LM358P" (pin_names (offset .5)) (in_bom yes) (on_board yes)',f'(property "Reference" "U" (at 0 16 0) {fx()})',f'(property "Value" "LM358P" (at 0 13 0) {fx()})']
    for unit,plus,minus,outpin in [(1,3,2,1),(2,5,6,7)]:
        op.append(f'(symbol "LM358P_{unit}_1" (polyline (pts (xy -7.62 10.16) (xy 7.62 0) (xy -7.62 -10.16) (xy -7.62 10.16)) (stroke (width .254) (type default)) (fill (type background)))')
        op.extend([pin(plus,'+','input',-5,2,0),pin(minus,'-','input',-5,-2,0),pin(outpin,'OUT','output',5,0,180),')'])
    op+=['(symbol "LM358P_3_1" (rectangle (start -5.08 7.62) (end 5.08 -7.62) (stroke (width .254) (type default)) (fill (type background)))',pin(8,'V+','power_in',0,5,270),pin(4,'V-','power_in',0,-5,90),'))']
    shapes['LM358P']='\n'.join(op)
    out=[f'(kicad_sch (version 20250114) (generator "eeschema") (uuid {root}) (paper "A3")','(title_block (title "DATN: PPG-Simulator - LED / IR driver") (rev "1.3") (comment 1 "Nguyen Nhat Huy - Pham Thanh Vy"))','(lib_symbols',*shapes.values(),')']
    byref={d['ref']:d for d in parts}; segments=[]; placed=set(); anchors=set()
    def wire(*points): segments.extend(zip(points,points[1:]))
    def label(net,x,y):
        anchors.add((x,y))
        out.append(f'(label {q(net)} (at {mm(x)} {mm(y)} 0) (effects (font (size 1 1)) (justify left bottom)) (uuid {uid("label"+net+str((x,y)))}))')
    def text(s,x,y,size=1.27): out.append(f'(text {q(s)} (at {mm(x)} {mm(y)} 0) {fx(size)} (uuid {uid("text"+s)}))')
    def place(ref,x,y,angle=0,kind=None,unit=1):
        if ref.startswith('#'):
            d=dict(kind='Flag',value='PWR_FLAG',fp='',dnp=False)
            anchors.add((x,y))
        else: d=byref[ref]
        k=kind or d['kind']; key=ref if unit==1 else ref+str(unit)
        out.append(f'(symbol (lib_id "TX:{k}") (at {mm(x)} {mm(y)} {angle}) (unit {unit}) (in_bom yes) (on_board yes) (dnp {"yes" if d["dnp"] else "no"}) (uuid {uid(key)})')
        if k in ('R','C','CP','NPN','Hole'):
            px=x+(3 if angle==0 else 0); py=y+(-1 if angle==0 else -4)
            valy=py+1.8
        else:
            px=x; py=y-(8 if k in ('Socket6','Conn6') else (5.5 if k=='Conn2' else 7)); valy=py+1.8
        if k=='LM358P' and unit==3: px=x+6; py=y-1; valy=y+1
        for prop,val,xx,yy,hide in [('Reference',ref,px,py,False),('Value',d['value'],px,valy,False),('Footprint','TX:'+d['fp'] if d['fp'] else '',x,y,True)]:
            out.append(f'(property "{prop}" {q(val)} (at {mm(xx)} {mm(yy)} {angle}) (effects (font (size 1.1 1.1)) {"(justify left)" if (k in ("R","C","CP","NPN","Hole") and angle==0) or (k=="LM358P" and unit==3) else ""} {"(hide yes)" if hide or ref.startswith("#") else ""}))')
        out.append(f'(instances (project "{name}" (path "/{root}" (reference "{ref}") (unit {unit})))))')
        placed.add(ref)
    for offset,ch,jmod,jwire,jled,rtop,rbot,rbase,rsense,qref,comp,unit in [
      (0,'IR','J1','J2','J5','R1','R2','R3','R4','Q1','C2',1),
      (80,'RED','J3',None,'J6','R6','R7','R8','R9','Q2','C4',2),
    ]:
        def pt(x,y): return (x+offset,y)
        def w(*pts): wire(*(pt(x,y) for x,y in pts))
        def l(net,x,y): label(net,x+offset,y)
        def pl(ref,x,y,angle=0,kind=None,u=1): place(ref,x+offset,y,angle,kind,u)
        text(ch+': MCP4725 '+('0x60' if unit==1 else '0x61')+' -> LM358 -> 2N4401 -> LED',offset+40,6,1.4)
        pl(jmod,15,20,kind='Socket6')
        if jwire: pl(jwire,50,20)
        for i,net in enumerate([f'DAC_{ch}','GND','SCL','SDA','3V3','GND']):
            yy=15+2*i
            if jwire:
                w((20,yy),(22,yy),(45,yy)); l(net,31,yy)
            elif i == 0:
                w((20,yy),(22,yy)); l(net,22,yy)
        if jwire:
            w((24,17),(24,25))
        else:
            # J3.6 is the second module ground. A short labelled stub avoids
            # crossing the SCL/SDA/3V3 rows on the way back to the GND bus.
            w((20,25),(22,25)); l('GND',22,25)
        w((22,15),(22,13),(7,13),(7,47),(14,47))
        pl(rtop,16,47,90); w((18,47),(24,47),(32,47)); l('CMD_'+ch,25,47)
        pl(rbot,24,56); w((24,47),(24,54)); w((24,58),(24,70),(64,70))
        pl('U1',37,49,u=unit)
        w((42,49),(48,49)); l('AMP_'+ch,44,49)
        pl(rbase,50,49,90); w((52,49),(61,49)); l('BASE_'+ch,55,49)
        pl(qref,64,49)
        pl(jled,76,36); w((72,35),(68,35),(68,31)); l('5V',68,31)
        w((72,37),(64,37),(64,46)); l('LED_K_'+ch,64,42)
        w((64,52),(64,58),(64,62)); pl(rsense,64,64); w((64,66),(64,70))
        w((32,51),(30,51),(30,58),(64,58)); l('SENSE_'+ch,47,58)
        l('GND',40,70)
        text('I_LED approximately V_DAC / (2 x '+('82' if unit==1 else '100')+' ohm)',offset+43,74)
        # Only optional compensation uses labels, in a clearly separate area.
        pl(comp,40,81,90); w((31,81),(38,81)); w((42,81),(51,81))
        l('AMP_'+ch,31,81); l('SENSE_'+ch,51,81)
        text(comp+': DNP - DO NOT FIT until loop measured',offset+40,85,1.0)
    # Four separate horizontal nets. Keeping one row per signal avoids any
    # graphical crossing being interpreted as an electrical junction.
    for net,row in [('GND',17),('SCL',19),('SDA',21),('3V3',23)]:
        wire((45,row),(100,row))
        label(net,65,row)
    # Shared supply shown as actual rails, including both capacitor polarities.
    text('SHARED SUPPLY: U1A + U1B + U1C = ONE LM358 DIP-8',42,91,1.3)
    # J7 has left-facing pins at x=8, y=100/102; route supply around it.
    place('J7',12,101)
    wire((8,100),(5,100),(5,94),(32,94),(48,94),(64,94))
    wire((8,102),(5,102),(5,108),(32,108),(48,108),(64,108))
    place('C7',32,101); wire((32,94),(32,99)); wire((32,103),(32,108))
    place('C5',48,101); wire((48,94),(48,99)); wire((48,103),(48,108))
    place('U1',64,101,unit=3); wire((64,94),(64,96)); wire((64,106),(64,108))
    label('5V',21,94); label('GND',21,108)
    place('#FLG0',21,108); place('#FLG1',21,94); place('#FLG2',35,23)
    text('C5: ceramic, non-polar. C7: electrolytic, + to 5V.',39,112,1.0)
    for i in range(1,5): place(f'H{i}',70+i*10,97)
    text('MCP4725 VCC = 3.3 V ONLY; J2 is the only Pi cable input.',112,91,1.1)
    text('C2/C4 optional. Removed: R5/R10, C1/C3, C6.',112,94,1.1)
    text('J2 powers and controls both DAC modules over one shared Pi I2C bus.',94,101,1.1)
    text('OUT pins are DAC outputs: never connect them together.',94,104,1.1)
    text('Four shared nets above are NOT shorted to one another.',94,107,1.1)
    text('Crossings without dots = no connection.',94,110,1.1)
    assert {d['ref'] for d in parts}<=placed
    # Split T junctions into explicit wire endpoints; crossings without endpoints
    # remain crossings. Add junction dots wherever three wire ends meet.
    nodes={a for a,b in segments}|{b for a,b in segments}|anchors
    pieces=set()
    for a,b in segments:
        ax,ay=a; bx,by=b
        on=[v for v in nodes if min(ax,bx)<=v[0]<=max(ax,bx) and min(ay,by)<=v[1]<=max(ay,by) and abs((v[0]-ax)*(by-ay)-(v[1]-ay)*(bx-ax))<1e-7]
        on.sort(key=lambda v:(v[0]-ax)**2+(v[1]-ay)**2)
        for c,d in zip(on,on[1:]): pieces.add(tuple(sorted((c,d))))
    degree=Counter()
    for a,b in sorted(pieces):
        degree[a]+=1; degree[b]+=1
        out.append(f'(wire (pts (xy {mm(a[0])} {mm(a[1])}) (xy {mm(b[0])} {mm(b[1])})) (stroke (width 0) (type default)) (uuid {uid("wire"+str((a,b)))}))')
    for (x,y),n in degree.items():
        if n>=3: out.append(f'(junction (at {mm(x)} {mm(y)}) (diameter 0) (color 0 0 0 0) (uuid {uid("dot"+str((x,y)))}))')
    out+=['(sheet_instances (path "/" (page "1")))',')']
    (here/f'{name}.kicad_sch').write_text('\n'.join(out))
    lib='\n'.join(s.replace('"TX:'+k+'"','"'+k+'"',1) for k,s in shapes.items())
    (here/'TX.kicad_sym').write_text('(kicad_symbol_lib (version 20250114) (generator "kicad_symbol_editor")\n'+lib+')')
    (here/'sym-lib-table').write_text('(sym_lib_table (version 7) (lib (name "TX") (type "KiCad") (uri "${KIPRJMOD}/TX.kicad_sym") (options "") (descr "Driver local symbols")))')
