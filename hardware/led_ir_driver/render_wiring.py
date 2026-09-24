#!/usr/bin/env python3
"""Export actual PCB connectivity using pcbnew; plot with matplotlib separately.

KiCad Python: render_wiring.py --export
Plot Python:  render_wiring.py
Both copper layers are shown from the top for easy pin-to-pin comparison.
"""
import json
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent

def export():
    import pcbnew as p
    b=p.LoadBoard(str(HERE/'led_ir_driver.kicad_pcb'))
    def xy(pos): return [p.ToMM(pos.x)-100,p.ToMM(pos.y)-100]
    data={'tracks':[],'footprints':[]}
    for t in b.GetTracks():
        data['tracks'].append({'net':t.GetNetname().lstrip('/'),'layer':b.GetLayerName(t.GetLayer()),'width':p.ToMM(t.GetWidth()),'a':xy(t.GetStart()),'b':xy(t.GetEnd())})
    for fp in sorted(b.GetFootprints(),key=lambda f:f.GetReference()):
        data['footprints'].append({'ref':fp.GetReference(),'value':fp.GetValue(),'ref_xy':xy(fp.Reference().GetPosition()),'pads':[{'number':pad.GetNumber(),'net':pad.GetNetname().lstrip('/'),'xy':xy(pad.GetPosition()),'diameter':p.ToMM(pad.GetDrillSize().x)} for pad in fp.Pads()]})
    (HERE/'reports/routing_geometry.json').write_text(json.dumps(data,indent=2)+'\n')
    doc=['# Tra chân PCB driver v1.3','',
         'Số chân dưới đây đọc trực tiếp từ PCB đã đi dây. Hai hình trong wiring_guide.png',
         'đều nhìn từ mặt linh kiện; mặt đồng B.Cu được nhìn xuyên board, không lật ảnh.',
         'Tên net giống nhau nghĩa là nối điện với nhau. Khác lớp chỉ nối tại pad xuyên lỗ.',
         'GND là vùng đồng mặt dưới, được ẩn trong hình để dễ nhìn đường tín hiệu.','',
         'Nét đứt xám nối hai pad R/C chỉ biểu diễn thân linh kiện, không phải đường đồng.','',
         '| Linh kiện | Giá trị | Chân → net |','|---|---|---|']
    for fp in data['footprints']:
        if fp['ref'].startswith('H'): continue
        pins=', '.join(pad['number']+' → '+pad['net'] for pad in sorted(fp['pads'],key=lambda d:int(d['number'])))
        doc.append('| '+fp['ref']+' | '+fp['value']+' | '+pins+' |')
    (HERE/'PIN_MAP.md').write_text('\n'.join(doc)+'\n')

def plot():
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle,Circle
    from matplotlib.lines import Line2D
    data=json.loads((HERE/'reports/routing_geometry.json').read_text())
    palette={'GND':'#667085','5V':'#d97706','3V3':'#a88700','SCL':'#7950b8','SDA':'#292d80','DAC_IR':'#008b8b','DAC_RED':'#804800','CMD':'#1762b5','DRIVE':'#288747','SENSE':'#c12b83','LED':'#cc3636'}
    def group(net):
        if net in ('SCL','SDA','DAC_IR','DAC_RED'): return net
        if net.startswith(('AMP_','BASE_')): return 'DRIVE'
        if net.startswith('LED_K'): return 'LED'
        return net.split('_')[0]
    fig,axes=plt.subplots(1,2,figsize=(19,8.5),layout='constrained')
    for ax,layer in zip(axes,['F.Cu','B.Cu']):
        ax.add_patch(Rectangle((0,0),70,55,facecolor='#f8fafb',edgecolor='#283340',lw=1.2))
        for t in data['tracks']:
            if t['layer']!=layer: continue
            a,c=t['a'],t['b']
            ax.plot([a[0],c[0]],[a[1],c[1]],color=palette[group(t['net'])],lw=1.4+1.5*t['width'],solid_capstyle='round',zorder=2)
        for fp in data['footprints']:
            pads=fp['pads']
            if fp['ref'].startswith('H'):
                ax.add_patch(Circle(pads[0]['xy'],1.6,fill=False,edgecolor='#89929a'))
                continue
            # Show the component connection across pads as a dashed body line;
            # this is not copper (resistor/capacitor/socket).
            if fp['ref'].startswith(('R','C')):
                a,c=pads[0]['xy'],pads[1]['xy']; ax.plot([a[0],c[0]],[a[1],c[1]],'--',color='#aeb8c2',lw=1,zorder=1)
            for pad in pads:
                x,y=pad['xy']; col=palette[group(pad['net'])]
                ax.add_patch(Circle((x,y),.68,facecolor='white',edgecolor=col,lw=1.1,zorder=4))
                ax.text(x,y,pad['number'],ha='center',va='center',fontsize=5.5,color='#111827',zorder=5)
            x,y=fp['ref_xy']; ax.text(x,y,fp['ref'],ha='center',va='center',fontsize=7,fontweight='bold',color='#263341',bbox=dict(facecolor='white',edgecolor='none',pad=.2),zorder=6)
        ax.set_title(('Mặt trên — F.Cu' if layer=='F.Cu' else 'Mặt dưới — B.Cu (nhìn xuyên từ trên)'),fontsize=13,pad=12)
        ax.set_xlim(-2,72); ax.set_ylim(58,-2); ax.set_aspect('equal'); ax.set_xlabel('mm'); ax.set_ylabel('mm'); ax.grid(alpha=.13)
    names={'GND':'GND (vùng đồng ẩn)','5V':'5 V / LED anode','3V3':'3,3 V DAC','SCL':'SCL — J2.3','SDA':'SDA — J2.4','DAC_IR':'OUT IR — J1/J2.1','DAC_RED':'OUT RED — J3.1','CMD':'Command / ngõ +','DRIVE':'OUT LM358 / base','SENSE':'Sense / hồi tiếp ngõ −','LED':'LED cathode'}
    fig.legend([Line2D([0],[0],color=c,lw=3) for c in palette.values()],[names[n] for n in palette],loc='outside lower center',ncol=5,frameon=False,fontsize=10)
    fig.suptitle('PPG driver v1.3 — bản đồ đường đồng và số chân thực trên PCB',fontsize=17)
    fig.savefig(HERE/'reports/wiring_guide.png',dpi=180)
    fig.savefig(HERE/'reports/wiring_guide.pdf')
    plt.close(fig)

if __name__=='__main__':
    export() if '--export' in sys.argv else plot()
