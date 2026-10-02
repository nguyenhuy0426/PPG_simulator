#!/usr/bin/env python3
"""Rebuild with KiCad 10's Python (pcbnew) and kicad-cli; no third-party router.

Usage: python generate_design.py --kicad-share /path/share/kicad --cli /path/kicad-cli
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
NAME = 'opt101_receiver'
ROOT = str(uuid.uuid5(uuid.NAMESPACE_URL, 'ppg-opt101-receiver-v1'))
def uid(s): return str(uuid.uuid5(uuid.UUID(ROOT), s))
def q(s): return json.dumps(str(s))
def effects(size=1.27): return f'(effects (font (size {size} {size})))'

PINS = {
    'OPT101P': [('1','VS','power_in',-12.7,7.62,0),
               ('2','-IN','input',-12.7,2.54,0),
               ('3','-V','power_in',-12.7,-2.54,0),
               ('4','1M_FB','input',12.7,-7.62,180),
               ('5','OUT','output',12.7,-2.54,180),
               ('6','NC','no_connect',12.7,2.54,180),
               ('7','NC','no_connect',12.7,7.62,180),
               ('8','COMMON','passive',-12.7,-7.62,0)],
    'Grove_Analog': [('1','SIGNAL','passive',-10.16,7.62,0),
                     ('2','UNUSED','passive',-10.16,2.54,0),
                     ('3','3V3','passive',-10.16,-2.54,0),
                     ('4','GND','passive',-10.16,-7.62,0)],
    'R': [('1','~','passive',-5.08,0,0),('2','~','passive',5.08,0,180)],
    'C': [('1','~','passive',0,3.81,270),('2','~','passive',0,-3.81,90)],
    'PWR_FLAG': [('1','pwr','power_out',0,0,90)],
    'MountingHole': [],
    'ADS_Output': [('1','RED','passive',-10.16,2.54,0),
                   ('2','IR','passive',-10.16,-2.54,0)],
}

def lib_symbol(name):
    ref = {'OPT101P':'U','Grove_Analog':'J','C':'C','R':'R','PWR_FLAG':'#FLG','MountingHole':'H','ADS_Output':'J'}[name]
    hidepins = '(pin_numbers (hide yes))' if name in ('C','PWR_FLAG') else ''
    out = [f'(symbol "PPG:{name}" {hidepins} (pin_names (offset 0.5) {"(hide yes)" if name in ("C","PWR_FLAG") else ""}) (in_bom yes) (on_board yes)',
           f'(property "Reference" "{ref}" (at 0 13.97 0) {effects()})',
           f'(property "Value" "{name}" (at 0 11.43 0) {effects()})',
           f'(symbol "{name}_0_1"']
    if name in ('OPT101P','Grove_Analog','ADS_Output'):
        w = 7.62 if name == 'OPT101P' else 5.08
        out += [f'(rectangle (start {-w} 10.16) (end {w} -10.16) (stroke (width 0.254) (type default)) (fill (type background)))']
    elif name == 'R':
        out += ['(rectangle (start -3.81 -1.27) (end 3.81 1.27) (stroke (width 0.254) (type default)) (fill (type none)))']
    elif name == 'C':
        for y in (-0.762,0.762):
            out += [f'(polyline (pts (xy -2.54 {y}) (xy 2.54 {y})) (stroke (width 0.254) (type default)) (fill (type none)))']
    elif name == 'PWR_FLAG':
        out += ['(polyline (pts (xy 0 0) (xy 0 2.54) (xy 1.27 3.81) (xy 0 5.08) (xy -1.27 3.81) (xy 0 2.54)) (stroke (width 0.254) (type default)) (fill (type none)))']
    else:
        out += ['(circle (center 0 0) (radius 2.54) (stroke (width 0.254) (type default)) (fill (type none)))']
    out += [')',f'(symbol "{name}_1_1"']
    for num,label,kind,x,y,a in PINS[name]:
        length = 0 if name == 'PWR_FLAG' else (1.27 if name == 'R' else (3.048 if name == 'C' else 5.08))
        out += [f'(pin {kind} line (at {x} {y} {a}) (length {length}) (name {q(label)} {effects(1)}) (number "{num}" {effects(1)}))']
    return '\n'.join(out + ['))'])

def schematic():
    out = [f'(kicad_sch (version 20250114) (generator "eeschema") (uuid {ROOT}) (paper "A4")',
           '(title_block (title "PPG - Dual OPT101P receiver") (date "2026-10-02") (rev "1.5") (comment 1 "70 x 20 mm / DIP-8 sockets / Grove A0 IR, A2 RED"))',
           '(lib_symbols', *(lib_symbol(n) for n in PINS), ')']
    def text(s,x,y,size=1.27): out.append(f'(text {q(s)} (at {x} {y} 0) {effects(size)} (uuid {uid(s)}))')
    def wire(x1,y1,x2,y2):
        out.append(f'(wire (pts (xy {x1} {y1}) (xy {x2} {y2})) (stroke (width 0) (type default)) (uuid {uid(str((x1,y1,x2,y2)))}))')
    def label(s,x,y):
        out.append(f'(label {q(s)} (at {x} {y} 0) (effects (font (size 1 1)) (justify left bottom)) (uuid {uid(s+str((x,y)))}))')
    def nc(x,y): out.append(f'(no_connect (at {x} {y}) (uuid {uid("nc"+str((x,y)))}))')
    def place(kind,ref,value,x,y,fp=''):
        out.append(f'(symbol (lib_id "PPG:{kind}") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid {uid(ref)})')
        for prop,val,py,hide in [('Reference',ref,y-14,False),('Value',value,y-11,False),('Footprint',fp,y,True)]:
            if kind in ('C','R','PWR_FLAG','MountingHole'): py = y-7 if prop=='Reference' else y-5
            px=x
            if kind=='C' and prop in ('Reference','Value'):
                px=x+5.08; py=y+(-1.27 if prop=='Reference' else 1.27)
            out.append(f'(property "{prop}" {q(val)} (at {px} {py} 0) (effects (font (size 1.1 1.1)) {"(justify left)" if kind=="C" else ""} {"(hide yes)" if hide or ref.startswith("#") else ""}))')
        for num,*_ in PINS[kind]: out.append(f'(pin "{num}" (uuid {uid(ref+num)}))')
        out.append(f'(instances (project "{NAME}" (path "/{ROOT}" (reference "{ref}") (unit 1)))))')
    # Complete wired channels, including an explicit branch to the ADS header.
    for idx,ch in enumerate(('RED','IR'),1):
        y = 66.04 + (idx-1)*66.04
        place('OPT101P',f'U{idx}','OPT101P',101.6,y,'PPG:DIP8_Socket')
        place('Grove_Analog',f'J{idx}','A2 / RED' if ch=='RED' else 'A0 / IR',177.8,y,'PPG:Header_1x04_P2mm')
        place('C',f'C{idx}','100nF 50V X7R ceramic',48.26,y,'PPG:C0805_Hand')
        top=y-22.86; bottom=y+22.86
        wire(167.64,y+2.54,160.02,y+2.54); wire(160.02,y+2.54,160.02,top)
        wire(160.02,top,73.66,top); wire(73.66,top,48.26,top)
        wire(48.26,top,48.26,y-3.81)
        wire(73.66,top,73.66,y-7.62); wire(73.66,y-7.62,88.9,y-7.62)
        label(f'3V3_{ch}',73.66,top); place('PWR_FLAG',f'#FLG{idx}1','PWR_FLAG',73.66,top)
        wire(167.64,y+7.62,165.1,y+7.62); wire(165.1,y+7.62,165.1,bottom)
        wire(165.1,bottom,81.28,bottom); wire(81.28,bottom,48.26,bottom)
        wire(48.26,bottom,48.26,y+3.81)
        wire(88.9,y+2.54,81.28,y+2.54); wire(81.28,y+2.54,81.28,y+7.62)
        wire(88.9,y+7.62,81.28,y+7.62); wire(81.28,y+7.62,81.28,bottom)
        label(f'GND_{ch}',81.28,bottom); place('PWR_FLAG',f'#FLG{idx}3','PWR_FLAG',81.28,bottom)
        for x,yy in [(88.9,y-2.54),(114.3,y-2.54),(114.3,y-7.62),(167.64,y-2.54)]: nc(x,yy)
        wire(114.3,y+2.54,124.46,y+2.54)
        wire(114.3,y+7.62,124.46,y+7.62); wire(124.46,y+7.62,124.46,y+2.54)
        wire(124.46,y+2.54,129.54,y+2.54)
        place('R',f'R{idx}','1k 1%',134.62,y+2.54,'PPG:R0805_Hand')
        wire(139.7,y+2.54,147.32,y+2.54); wire(147.32,y+2.54,147.32,y-7.62)
        wire(147.32,y-7.62,167.64,y-7.62)
        label(f'RAW_{ch}',124.46,y+2.54); label(f'OUT_{ch}',147.32,y-7.62)
        bx=200.66 if idx==1 else 208.28; target=99.06 if idx==1 else 104.14
        wire(147.32,y+2.54,147.32,y+10.16); wire(147.32,y+10.16,bx,y+10.16)
        place('C',f'C{idx+2}','1uF X7R 16V',134.62,y+15.24,'PPG:C0805_Hand')
        wire(139.7,y+2.54,139.7,y+8.89); wire(139.7,y+8.89,134.62,y+8.89)
        wire(134.62,y+8.89,134.62,y+11.43)
        wire(134.62,y+19.05,134.62,bottom)
        wire(bx,y+10.16,bx,target); wire(bx,target,218.44,target)
        for xx,yy in [(73.66,top),(81.28,bottom),(81.28,y+7.62),(124.46,y+2.54),(139.7,y+2.54),(147.32,y+2.54),(134.62,bottom)]:
            out.append(f'(junction (at {xx} {yy}) (diameter 0) (color 0 0 0 0) (uuid {uid(ch+str((xx,yy)))}))')
        text(f'{ch}: U{idx}.4 -- U{idx}.5 = internal 1 Mohm feedback',119.38,y+30.48,1.1)
    place('ADS_Output','J3','ADS1115 outputs',228.6,101.6,'PPG:Header_1x02_P2.54mm')
    text('DUAL OPT101 RECEIVER: RED -> A2 / IR -> A0',139.7,15.24,1.7)
    text('3.3 V only. C1/C2: non-polar ceramic 100 nF, X7R, 50 V.',139.7,22.86,1.2)
    text('Separate supply/return cables meet at the HAT. J3 has signals only: ADS must share HAT GND.',139.7,29.21,1.1)
    text('Crossings without dots are NOT connected. Pins 2, 6, 7 of OPT101 remain open.',139.7,35.56,1.1)
    text('R1/R2 + C3/C4: 1k / 1uF output low-pass, nominal fc = 159 Hz.',139.7,165.1,1.1)
    out += [f'(sheet_instances (path "/" (page "1")))',')']
    (HERE/f'{NAME}.kicad_sch').write_text('\n'.join(out))
    (HERE/'PPG.kicad_sym').write_text('(kicad_symbol_lib (version 20250114) (generator "kicad_symbol_editor")\n'+ '\n'.join(lib_symbol(n).replace('"PPG:'+n+'"','"'+n+'"',1) for n in PINS)+')')
    (HERE/'sym-lib-table').write_text('(sym_lib_table (version 7) (lib (name "PPG") (type "KiCad") (uri "${KIPRJMOD}/PPG.kicad_sym") (options "") (descr "Project-local receiver symbols")))\n')

def pcb(share, cli):
    import pcbnew as p
    mm=p.FromMM
    vec=lambda x,y:p.VECTOR2I(mm(x),mm(y))
    b=p.BOARD(); b.GetDesignSettings().SetCopperLayerCount(2)
    b.GetDesignSettings().SetBoardThickness(mm(1.6))
    netfile=HERE/'reports'/f'{NAME}.net'
    subprocess.run([cli,'sch','export','netlist','--format','kicadxml','-o',str(netfile),str(HERE/f'{NAME}.kicad_sch')],check=True)
    xml=ET.parse(netfile)
    nets={}; pin_nets={}
    for net in xml.findall('.//nets/net'):
        n=p.NETINFO_ITEM(b,net.attrib['name']); b.Add(n); nets[net.attrib['name'].lstrip('/')]=n
        for node in net.findall('node'): pin_nets[node.attrib['ref'],node.attrib['pin']]=n
    library=HERE/'PPG.pretty'; library.mkdir(exist_ok=True)
    fps={
        'DIP8_Socket':'Package_DIP.pretty/DIP-8_W7.62mm_Socket.kicad_mod',
        'Header_1x04_P2mm':'Connector_PinHeader_2.00mm.pretty/PinHeader_1x04_P2.00mm_Vertical.kicad_mod',
        'Header_1x02_P2.54mm':'Connector_PinHeader_2.54mm.pretty/PinHeader_1x02_P2.54mm_Vertical.kicad_mod',
        'MountingHole_M3':'MountingHole.pretty/MountingHole_3.2mm_M3.kicad_mod',
        'R0805_Hand':'Resistor_SMD.pretty/R_0805_2012Metric_Pad1.20x1.40mm_HandSolder.kicad_mod',
        'C0805_Hand':'Capacitor_SMD.pretty/C_0805_2012Metric_Pad1.18x1.45mm_HandSolder.kicad_mod',
    }
    # Vendor footprints/models so opening this project needs no global libraries.
    import re
    for name,src in fps.items():
        text=(share/'footprints'/src).read_text()
        text=re.sub(r'^\(footprint "[^"]+"',f'(footprint "{name}"',text)
        for model in re.findall(r'\(model "([^\"]+)"',text):
            suffix=model.split('}/')[-1]
            source=share/'3dmodels'/suffix
            if source.exists():
                dest=HERE/'3dmodels'/suffix; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,dest)
                text=text.replace(model,'${KIPRJMOD}/3dmodels/'+suffix)
        (library/f'{name}.kicad_mod').write_text(text)
    (HERE/'fp-lib-table').write_text('(fp_lib_table (version 7) (lib (name "PPG") (type "KiCad") (uri "${KIPRJMOD}/PPG.pretty") (options "") (descr "Vendored KiCad 10 footprints")))\n')
    def add(ref,name,value,x,y):
        fp=p.FootprintLoad(str(library),name); fp.SetReference(ref); fp.SetValue(value)
        fp.SetFPID(p.LIB_ID('PPG',name)); fp.SetPosition(vec(x,y))
        fp.SetAttributes(fp.GetAttributes() & ~p.FP_EXCLUDE_FROM_BOM)
        path=p.KIID_PATH(); path.push_back(p.KIID(ROOT)); path.push_back(p.KIID(uid(ref))); fp.SetPath(path)
        fp.Reference().SetTextSize(vec(0.9,0.9)); fp.Reference().SetTextThickness(mm(0.13))
        for pad in fp.Pads():
            if (ref,pad.GetNumber()) in pin_nets: pad.SetNet(pin_nets[ref,pad.GetNumber()])
        b.Add(fp); return fp
    def line(a,c,layer,width=.15):
        s=p.PCB_SHAPE(); s.SetShape(p.SHAPE_T_SEGMENT); s.SetStart(vec(*a)); s.SetEnd(vec(*c)); s.SetLayer(layer); s.SetWidth(mm(width)); b.Add(s)
    for a,c in [((100,100),(170,100)),((170,100),(170,130)),((170,130),(100,130)),((100,130),(100,100))]: line(a,c,p.Edge_Cuts,.05)
    def silk(s,x,y,size=.9,layer=p.F_SilkS,mirrored=False,angle=0):
        t=p.PCB_TEXT(b); t.SetText(s); t.SetPosition(vec(x,y)); t.SetTextSize(vec(size,size)); t.SetTextThickness(mm(.13)); t.SetLayer(layer); t.SetMirrored(mirrored); t.SetTextAngle(p.EDA_ANGLE(angle,p.DEGREES_T)); b.Add(t); return t
    def route(net,points,layer=p.F_Cu,width=.35):
        for a,c in zip(points,points[1:]):
            if a == c:
                continue
            if a[0] != c[0] and a[1] != c[1]:
                raise ValueError(f'diagonal track is not allowed: {net} {a} -> {c}')
            t=p.PCB_TRACK(b); t.SetStart(vec(*a)); t.SetEnd(vec(*c)); t.SetWidth(mm(width)); t.SetLayer(layer); t.SetNet(nets[net]); b.Add(t)
    for idx,(ch,cx) in enumerate([('RED',115.75),('IR',154.25)],1):
        cy=115
        u=add(f'U{idx}','DIP8_Socket','OPT101P',cx-3.81,cy-3.81)
        u.Reference().SetPosition(vec(cx+5.5,cy-6))
        c=add(f'C{idx}','C0805_Hand','100nF 50V X7R ceramic',cx-2.56,cy-8)
        c.Value().SetVisible(False)
        jx=113 if ch=='RED' else 151
        j=add(f'J{idx}','Header_1x04_P2mm','A2 / RED' if ch=='RED' else 'A0 / IR',jx,125)
        j.SetOrientationDegrees(90)
        j.Reference().SetPosition(vec(jx-2.7,125))
        c.Reference().SetPosition(vec(cx-6.2,cy-8))
        # Output and feedback are short, local copper; no resistor fitted.
        # Pin 4--5 is a straight strap.  The Grove branch drops below the
        # socket using only horizontal/vertical segments.
        out_left=(cx-3.81,cy+3.81); out_right=(cx+3.81,cy+3.81)
        route(f'RAW_{ch}',[out_left,out_right])
        r=add(f'R{idx}','R0805_Hand','1k 1%',cx,122.0)
        co=add(f'C{idx+2}','C0805_Hand','1uF X7R 16V',cx+6,122.0)
        for fp in (r,co):
            fp.Value().SetVisible(False)
            fp.Reference().SetPosition(vec(p.ToMM(fp.GetPosition().x)+(0 if fp==r else 2),122.0 if fp==r else 120.4))
            if fp==r: fp.Reference().SetPosition(vec(cx-5.6,122.0))
        def pp(fp,num):
            pad=next(a for a in fp.Pads() if a.GetNumber()==str(num))
            return p.ToMM(pad.GetPosition().x),p.ToMM(pad.GetPosition().y)
        ri,ro=pp(r,1),pp(r,2); cp,cg=pp(co,1),pp(co,2)
        route(f'RAW_{ch}',[out_left,(out_left[0],122.0),ri])
        route(f'OUT_{ch}',[ro,cp])
        route(f'OUT_{ch}',[ro,(ro[0],123.5),(jx,123.5),(jx,125.0)])
        v=p.PCB_VIA(b); v.SetPosition(vec(cx+9,122)); v.SetWidth(mm(.8)); v.SetDrill(mm(.4)); v.SetLayerPair(p.F_Cu,p.B_Cu); v.SetNet(nets[f'GND_{ch}']); b.Add(v)
        route(f'GND_{ch}',[cg,(cx+9,122)],p.F_Cu,.35)
        route(f'3V3_{ch}',[(cx-3.81,cy-3.81),(cx-3.81,cy-8)])
        if ch=='RED':
            pwr=[(cx-3.81,cy-8),(cx-3.81,105.0),(108.5,105.0),(108.5,121.0),(117.0,121.0),(117.0,125.0)]
        else:
            pwr=[(cx-3.81,cy-8),(cx-3.81,105.0),(161.5,105.0),(161.5,121.0),(155.0,121.0),(155.0,125.0)]
        route(f'3V3_{ch}',pwr,p.B_Cu,.5)
        # Replace the bypass THT supply anchor with a via to B.Cu.
        v=p.PCB_VIA(b); v.SetPosition(vec(cx-3.81,cy-8)); v.SetWidth(mm(.8)); v.SetDrill(mm(.4)); v.SetLayerPair(p.F_Cu,p.B_Cu); v.SetNet(nets[f'3V3_{ch}']); b.Add(v)
        for pin,x in ((1,cx-3.81),(2,cx-1.31)):
            pad=next(a for a in c.Pads() if a.GetNumber()==str(pin))
            route(f'3V3_{ch}' if pin==1 else f'GND_{ch}',[(x,cy-8),(p.ToMM(pad.GetPosition().x),cy-8)],p.F_Cu,.5)
        # Explicit ground traces, plus a separate bottom plane for each channel.
        route(f'GND_{ch}',[(cx-1.31,cy-8),(cx+3.81,cy-8),(cx+3.81,cy-3.81)],p.F_Cu,.5)
        # Pin 3 connects directly to the ground plane (no long input-side trace).
        # Ground pins connect through the rear-layer filled plane.
        z=p.ZONE(b); z.SetLayer(p.B_Cu); z.SetNet(nets[f'GND_{ch}']); z.SetLocalClearance(mm(.3)); z.SetPadConnection(p.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(mm(.3)); z.SetThermalReliefSpokeWidth(mm(.4)); z.SetMinThickness(mm(.25))
        poly=z.Outline(); poly.NewOutline()
        left,right=(100.6,133) if idx==1 else (137,169.4)
        for xy in [(left,100.6),(right,100.6),(right,129.4),(left,129.4)]: poly.Append(int(mm(xy[0])),int(mm(xy[1])))
        b.Add(z)
        silk(f'{ch} / '+('A2' if ch=='RED' else 'A0'),cx,102.2,1.2)
        silk('4--5  1M INT',cx,104.1,.8)
        silk('S NC V G',jx+3,129.0,.8)
        # Optical package centre = nominal lane axis; die tolerance is not dimensioned by TI.
        line((cx-1,cy),(cx+1,cy),p.Dwgs_User,.1); line((cx,cy-1),(cx,cy+1),p.Dwgs_User,.1)
    j3=add('J3','Header_1x02_P2.54mm','ADS1115 outputs',126,125)
    j3.SetOrientationDegrees(90)
    j3.Reference().SetPosition(vec(127.27,128))
    silk('ADS: RED IR',127.27,122.6,.8)
    route('OUT_RED',[(113,125),(113,123.5),(126,123.5),(126,125)],p.F_Cu,.35)
    route('OUT_IR',[(151,125),(151,123.5),(128.54,123.5),(128.54,125)],p.F_Cu,.35)
    silk('PPG RX  v1.4',135,103,1)
    silk('3.3V ONLY',135,106,.85)
    silk('70 x 30',135,127.5,.85)
    silk('OPT101P\nPIN 1 UP',135,120.5,.8)
    # Project credit and complete rear-side pin identification.
    silk('DATN: PPG-Simulator',135,102.4,.95,p.B_SilkS,True)
    silk('Nguyen Nhat Huy - Pham Thanh Vy',135,105.0,.80,p.B_SilkS,True)
    silk('R=OUT_RED  I=OUT_IR',135,107.8,.8,p.B_SilkS,True)
    silk('V=3V3  GR/GI=GND',135,110.0,.8,p.B_SilkS,True)

    rear_headers={
        'J1':('J1 A2 RED',('R','NC','V','GR')),
        'J3':('J3 ADS',('R','I')),
        'J2':('J2 A0 IR',('I','NC','V','GI')),
    }
    byref={fp.GetReference():fp for fp in b.GetFootprints()}
    def pad_xy(ref,pin):
        pad=next(x for x in byref[ref].Pads() if x.GetNumber()==str(pin)); pos=pad.GetPosition(); return p.ToMM(pos.x),p.ToMM(pos.y)
    for ref,(title,labels) in rear_headers.items():
        xs=[]
        for pin,label in enumerate(labels,1):
            x,_=pad_xy(ref,pin); xs.append(x); silk(label,x,128.0,.8,p.B_SilkS,True,90)
        silk(title,sum(xs)/len(xs),123.3,.8,p.B_SilkS,True)

    for ref,channel,left_x,right_x in (('U1','RED',108.8,122.7),('U2','IR',147.3,161.2)):
        silk(f'{ref} {channel} OPT101',sum((pad_xy(ref,1)[0],pad_xy(ref,8)[0]))/2,109.5,.8,p.B_SilkS,True)
        for pin,label in ((1,'V'),(2,'NC'),(3,'G'),(4,'FB')):
            _,y=pad_xy(ref,pin); silk(label,left_x,y,.8,p.B_SilkS,True)
        for pin,label in ((8,'G'),(7,'NC'),(6,'NC'),(5,'OUT')):
            _,y=pad_xy(ref,pin); silk(label,right_x,y,.8,p.B_SilkS,True)
    # Keep the middle clear for the existing 3 mm optical partition.
    line((133.5,100.5),(133.5,129.5),p.Dwgs_User,.1); line((136.5,100.5),(136.5,129.5),p.Dwgs_User,.1)
    p.ZONE_FILLER(b).Fill(b.Zones())
    p.SaveBoard(str(HERE/f'{NAME}.kicad_pcb'),b)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--kicad-share',required=True,type=Path); ap.add_argument('--cli',required=True); a=ap.parse_args()
    (HERE/'reports').mkdir(exist_ok=True)
    # A local project with conservative fabrication rules; no DRC exclusions.
    project={'meta':{'filename':NAME+'.kicad_pro','version':1},'board':{'design_settings':{'rules':{'min_clearance':0.2,'min_track_width':0.25,'min_through_hole_diameter':0.3,'min_hole_clearance':0.25,'min_copper_edge_clearance':0.3}}},'net_settings':{'classes':[{'name':'Default','clearance':0.25,'track_width':0.35,'via_diameter':0.8,'via_drill':0.4,'microvia_diameter':0.3,'microvia_drill':0.1,'diff_pair_width':0.2,'diff_pair_gap':0.25,'diff_pair_via_gap':0.25}]}}
    (HERE/f'{NAME}.kicad_pro').write_text(json.dumps(project,indent=2)+'\n')
    schematic(); pcb(a.kicad_share,a.cli)
    from compact_layout import compact
    compact()

if __name__=='__main__': main()
