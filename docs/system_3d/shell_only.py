"""Shell-only print sets for the 420 x 420 x 500 mm printer.

Drops the optical chamber (body, lid, hoods) and the Pi case, fuses the outer shell
(left/right/front/rear halves + front bezel/cap) into ONE solid, merges the rear door
and tray halves, and cuts a small horizontal USB-C power slit in the front.
Works on each variant's out/assembly_meshes (assembly coordinates, mm).
"""
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import trimesh

ROOT=Path(__file__).resolve().parent
BED=(420,420,500)
GAP=.13   # each half moves .13 mm towards the other: the .25 mm split gap becomes a .01 mm overlap
DROP=('optical_','hood_','screen_')
SLIT_W=22.
VARIANTS={  # slit: x0,x1,z0,z1,y0,y1 (assembly mm); plugs: (p0,p1) wall holes to close
 'cyberdock_v1':dict(slit=(56,78,20,29,-12,1.0)),
 'cyberdock_v2':dict(slit=(60,82,5.5,13.5,-12,26.0)),
 'cyberdock_v3':dict(slit=(56,78,20,29,-12,1.0)),
 'mac_desktop_v1':dict(slit=(56,78,20,29,-12,1.0)),
 'mac_desktop_v2':dict(slit=(56,78,14,22,-51,-45.5)),
 'cyberdock_v2_side':dict(slit=None),
 'mac_desktop_v2_side':dict(slit=None,monolithic=True),
}


def cyl(p0,p1,r=2.7):
    p0=np.asarray(p0,float);p1=np.asarray(p1,float);d=p1-p0;n=np.linalg.norm(d)
    t=trimesh.geometry.align_vectors([0,0,1],d/n);t[:3,3]=(p0+p1)/2
    return trimesh.creation.cylinder(radius=r,height=n,sections=32,transform=t)


def zc(x,y,a,b):return cyl([x,y,a],[x,y,b])
def yc(x,z,a,b):return cyl([x,a,z],[x,b,z])


def _load(v):
    spec=importlib.util.spec_from_file_location('cad_'+v,ROOT/v/'build.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def plugs(v):
    p=[];door=[];tray=[]
    if v in ('mac_desktop_v1','mac_desktop_v2','cyberdock_v3'):
        for z in (50,85,145):door.append(yc(116,z,146.5,150.5))
        for y in ((35,136) if v!='cyberdock_v3' else (45,120)):tray.append(zc(116,y,9,12))
    if v=='mac_desktop_v1':
        p+=[yc(116,18,-8,-1),yc(116,160,-10,-1)]
    if v in ('mac_desktop_v2','mac_desktop_v2_side'):
        cad=_load(v)
        L=cad.L4()
        sx=138 if v=='mac_desktop_v2_side' else 116
        def lp(z,a,b):return cyl((L@np.array([sx,a,z,1.]))[:3],(L@np.array([sx,b,z,1.]))[:3])
        for z in cad.TAB_Z:p.append(lp(z,-10,-1))
    return {'shell':p,'door':door,'tray':tray}


def auto_plugs(m,wall=3.):
    """Close every round Ø4.5 through-hole in the roof and floor (seam screws no longer needed)."""
    top=m.bounds[1,2];out=[]
    for z,a,b in ((top-wall/2,top-wall,top),(wall/2,0,wall)):
        s=m.section(plane_origin=[0,0,z],plane_normal=[0,0,1])
        for e in (s.discrete if s is not None else []):
            e=np.asarray(e);wx,wy=np.ptp(e[:,0]),np.ptp(e[:,1])
            if 4.2<=wx<=4.8 and 4.2<=wy<=4.8:out.append(zc(e[:,0].mean(),e[:,1].mean(),a,b))
    return out


def kind(n):
    if n.startswith(('optical_','hood_','screen_')) or n=='pi_housing':return None
    if n.startswith('02_screen'):return 'screenplate'
    if n.startswith(('01_','02_','03_','04_')):return 'shell'
    if n.startswith(('05_','06_','08_rear')):return 'door'
    if n.startswith('09_side'):return 'sidepanel'
    if n.startswith('10_rear'):return 'reartop'
    if n.startswith('11_roof'):return 'roof'
    if n.startswith(('07_','08_')):return 'tray'
    return 'misc'


def merge(ms,names,bezel_nudge=True):
    parts=[]
    for n in names:
        m=ms[n].copy();d=np.zeros(3)
        if 'left' in n:d[0]+=GAP
        if 'right' in n:d[0]-=GAP
        if 'shell' in n or 'tray' in n:
            if 'rear' in n:d[1]-=GAP
            elif 'front' in n:d[1]+=GAP
        if n.startswith(('03_','04_')):d[1]+=.2
        m.apply_translation(d);parts.append(m)
    u=trimesh.boolean.union(parts,engine='manifold')
    return u


def clean(m):
    """Drop zero-volume sliver shells left by boolean contact faces; keep real bodies."""
    keep=[c for c in m.split(only_watertight=False) if abs(c.volume)>1.0]
    return keep[0] if len(keep)==1 else trimesh.util.concatenate(keep)


def orient(kind_,m):
    R=np.eye(4)
    if kind_ in ('shell','sidepanel'):R[:3,:3]=[[0,1,0],[0,0,1],[1,0,0]]
    elif kind_ in ('door','reartop'):R[:3,:3]=[[1,0,0],[0,0,1],[0,-1,0]]
    elif kind_=='roof':R[:3,:3]=[[1,0,0],[0,-1,0],[0,0,-1]]   # top face down, stiffening ribs up
    pm=m.copy();pm.apply_transform(R);pm.apply_translation(-pm.bounds[0]);return pm


def shelf_pack(items,w=BED[0]-10,h=BED[1]-10,gap=6):
    """items: [(name,mesh)] -> list of plates, each [(name,mesh,x,y)]."""
    plates=[];items=sorted(items,key=lambda t:-t[1].extents[1])
    for name,m in items:
        e=m.extents
        placed=False
        for plate in plates:
            for row in plate['rows']:
                if row['x']+e[0]<=w and e[1]<=row['h']:
                    plate['items'].append((name,m,5+row['x'],5+row['y']));row['x']+=e[0]+gap;placed=True;break
            if placed:break
            if plate['next_y']+e[1]<=h and e[0]<=w:
                row={'x':e[0]+gap,'y':plate['next_y'],'h':e[1]};plate['rows'].append(row)
                plate['items'].append((name,m,5,5+plate['next_y']));plate['next_y']+=e[1]+gap;placed=True;break
        if not placed:
            plates.append({'rows':[{'x':e[0]+gap,'y':0,'h':e[1]}],'items':[(name,m,5,5)],'next_y':e[1]+gap})
    return [p['items'] for p in plates]


def build(v):
    cfg=VARIANTS[v];base=ROOT/v;ms={p.stem:trimesh.load_mesh(p) for p in (base/'out/assembly_meshes').glob('*.stl')}
    manifest=json.loads((base/'out/manifest.json').read_text())
    T={r['name']:np.array(r['assembly_to_print']) for r in manifest['parts']}
    out=base/'VO_RIENG_420';out.mkdir(exist_ok=True)
    for f in out.glob('*'):f.unlink()
    groups={'shell':[],'door':[],'tray':[],'sidepanel':[],'screenplate':[],'reartop':[],'roof':[],'misc':[]}
    for n in sorted(ms):
        k=kind(n)
        if k:groups[k].append(n)
    if cfg['slit'] is None:  # side-by-side variants: the power exit is a hole in the rear door (cut in CAD)
        slit=trimesh.creation.box(extents=[1,1,1],transform=trimesh.transformations.translation_matrix([-500,-500,-500]));x0=x1=z0=z1=0
    else:
        x0,x1,z0,z1,y0,y1=cfg['slit']
        slit=trimesh.creation.box(extents=[x1-x0,y1-y0,z1-z0],transform=trimesh.transformations.translation_matrix([(x0+x1)/2,(y0+y1)/2,(z0+z1)/2]))
    report={'variant':v,'dropped':sorted(n for n in ms if kind(n) is None and not n.startswith('screen_')),'files':{}}
    result={}
    shell=merge(ms,groups['shell'])
    pl=plugs(v)
    ap=[] if cfg.get('monolithic') else auto_plugs(shell);report['roof_floor_holes_plugged']=len(ap)
    allp=ap+([] if cfg.get('monolithic') else pl['shell'])
    if allp:shell=trimesh.boolean.union([shell,*allp],engine='manifold')
    cut_parts={'VO_LIEN_KHOI':shell}
    before=shell
    shell=trimesh.boolean.difference([shell,slit],engine='manifold')
    removed=before.volume-shell.volume
    assert removed>20 or cfg['slit'] is None,('USB-C slit removed almost nothing',v,removed)
    assert abs(trimesh.boolean.intersection([clean(shell),slit],engine='manifold').volume)<.5
    report['usb_c_slit']={'x_mm':[x0,x1],'z_mm':[z0,z1],'removed_mm3':round(removed)}
    result['VO_LIEN_KHOI']=('shell',shell)
    for k,fname in (('door','CUA_SAU_DUOI' if cfg.get('monolithic') else 'CUA_SAU'),('reartop','CUA_SAU_TREN'),('roof','NAP_NGANG'),('tray','KHAY_RUT'),('sidepanel','CUA_HONG'),('screenplate','TAM_MAN_HINH')):
        if not groups[k]:continue
        m=merge(ms,groups[k])
        if pl.get(k):m=trimesh.boolean.union([m,*pl[k]],engine='manifold')
        result[fname]=(k,m)
    small=[]
    for n in groups['misc']:
        m=ms[n].copy()
        if np.all(slit.bounds[0]<m.bounds[1]) and np.all(m.bounds[0]<slit.bounds[1]):
            m=trimesh.boolean.difference([m,slit],engine='manifold');report.setdefault('slit_also_cut',[]).append(n)
        pm=m.copy();pm.apply_transform(T[n]);pm.apply_translation(-pm.bounds[0]);small.append((n,pm))
    result['_asm']=('asm',clean(shell))
    for fname,(k,m) in result.items():
        if fname=='_asm':continue
        if k=='screenplate':
            pm=clean(m).copy();pm.apply_transform(T['02_screen_plate']);pm.apply_translation(-pm.bounds[0])
        else:pm=orient('upright' if (k=='shell' and cfg.get('monolithic')) else k,clean(m))   # monolithic body prints upright: least support (Bambu Studio slice)
        comps=len(pm.split(only_watertight=False))
        assert pm.is_volume and comps==1,(v,fname,comps)
        assert all(a<=b for a,b in zip(sorted(pm.extents),sorted(BED))),(fname,pm.extents)
        pm.export(out/(fname+'.stl'));report['files'][fname+'.stl']={'extents_mm':pm.extents.round(2).tolist(),'volume_cm3':round(pm.volume/1000,1)}
    for i,plate in enumerate(shelf_pack(small),1):
        meshes=[]
        for n,m,x,y in plate:
            mm=m.copy();mm.apply_translation([x,y,0]);meshes.append(mm)
        c=trimesh.util.concatenate(meshes);fn=f'PHU_KIEN_{i}.stl';c.export(out/fn)
        assert np.all(c.bounds[1]<=np.array(BED)+1e-6)
        report['files'][fn]={'parts':[n for n,*_ in plate],'extents_mm':c.extents.round(1).tolist()}
    (out/'bao_cao.json').write_text(json.dumps(report,indent=2))
    sl=report['usb_c_slit'];vol=report['files']['VO_LIEN_KHOI.stl']
    txt=[f'{v}: BO VO RIENG (khong co buong toi, khong co hop Pi) cho may in 420 x 420 x 500 mm','',
     'File gui in (STL, don vi mm, scale 100%, da xoay san theo huong in):']
    for fn,info in report['files'].items():txt.append(f'  {fn}: {info["extents_mm"]} mm'+(f' ({info["volume_cm3"]} cm3 khoi dac)' if 'volume_cm3' in info else ''))
    txt+=['',
     '- VO_LIEN_KHOI.stl: than vo + mat truoc (bezel/nap truoc) dung thanh MOT khoi, nam nghieng tren thanh ben (mat ben x_min xuong ban). Man hinh va kep nhom lap tu phia sau.',
     '- CUA_SAU.stl, KHAY_RUT.stl, CUA_HONG.stl (neu co): cua/khay/tam tuong phai da gop thanh 1 chi tiet; CUA_HONG la tam tuong phai thao duoc, khay truot vao tu ben phai. PHU_KIEN_*.stl: kep man hinh va cac chi tiet nho/chan de (neu co), xep san tren ban 420 x 420.',
     *(['- Lo cap nguon: o CUA_SAU (cua sau), ngay sau cua so cong cua hop Pi: rong 65 mm, cao 14-16 mm. Day nguon USB-C va day HDMI cua man hinh di theo duong nay, khong co khe o mat truoc. Hai kep giu man hinh nam o canh tren va canh duoi, hai ben man hinh de trong cho day cap.'] if cfg['slit'] is None else [f'- Khe cap nguon USB-C o mat truoc: rong {sl["x_mm"][1]-sl["x_mm"][0]:.0f} mm (X {sl["x_mm"][0]}..{sl["x_mm"][1]}), cao {sl["z_mm"][1]-sl["z_mm"][0]:.1f} mm (Z {sl["z_mm"][0]}..{sl["z_mm"][1]}), xuyen qua thanh truoc. Can phich/dau USB-C co dau boc khong qua 22 x 8 mm; cong USB-C cua Pi nam o X~66 mm (huong ve phia truoc), noi day ben trong sau khi mo cua sau.']),
     '- Da bo: buong toi (than, nap, 4 chup day) va hop Pi 4. Khay rut, cua sau van giu de bat hop Pi/buong toi da in cua ban.',
     '- Hai nua trai/phai va truoc/sau duoc dich moi nua 0.13 mm vao nhau de han thanh khoi: kich thuoc ngoai nho hon 0.26 mm theo X (va Y cua than). Cac lo vit noi nua vo tren mai/day (va cua/khay/mat truoc neu co) da bit.',
     '- CHUA slice, CHUA in thu, CHUA kiem tra khe cap voi day that. Can kiem tra support (cac tai, ledge, mai ho phia truoc de Mac V2) trong slicer.']
    if cfg.get('monolithic'):
        fl=report['files']
        txt=[f'{v}: VO NGUYEN KHOI (khong co buong toi, khong co hop Pi) cho may in 420 x 420 x 500 mm','',
         'File gui in (STL, mm, scale 100%, da xoay san theo huong in):']
        for fn,info in fl.items():txt.append(f'  {fn}: {info["extents_mm"]} mm')
        txt+=['',
         '- Hinh dang kieu Mac co dien: phan man hinh cao 170 o phia truoc (sau 47 tinh tu mat phang Y=0), than thap phia sau cao 90. Vach/san/mai day 2 mm, tam man hinh day 4 mm. San va day de truoc khoet thanh cac dai rong <= 20 mm (gan 4 mm, in nam nghieng khong can support cho lo), con gio 10 mm quanh day hop Pi va buong toi. Cac tam cua (CUA_HONG, CUA_SAU_TREN, NAP_NGANG, CUA_SAU_DUOI) KIN mat ngoai: da nhua 0.6 mm (3 lop, in up xuong ban nen mat ngoai phang min), phia trong khoet tui o luoi ~22 mm, gan 2 mm, sau 1.4 mm de bot nhua; tong day van 2 mm nen lap khong doi. Chi con ho: lo bulong, khe nguon va 4 khe day rut tren CUA_HONG, va 10 khe thoat nhiet 4 x 80 tren NAP_NGANG ngay tren hop Pi. Thong gio con lai: vach trai (8 khe la sach 105 x 3), khe de truoc va cac lo san duoi module - CHUA do nhiet do Pi khi dong kin.',
         '- VO_LIEN_KHOI.stl: san + vach trai + phan man hinh (tam man nghieng 10 do, hai vach ben, KHONG co mai) + de truoc + 4 khoi goc bat bulong. MOT khoi, cao 168. In DUNG (day up xuong ban). Thiet ke de in dung gan nhu khong can support: moi khoi/tru treo tren vach co gan cheo 45 do, tran de truoc la mai 2 doc 45 do, khe thong gio la sach nghieng 45 do. Bambu Studio (H2S, 0.20mm Standard, PETG, bat support tree(auto)): 315.5 g (support ~30 g), ~10.4 h.',
         '- San khoet lo, KHONG co tru chan de; hop Pi va buong toi tua len gio san 10 mm. Thu tu lap: thao NAP_NGANG, ha hop Pi xuong roi day ve phia truoc 20 mm - HOAC thao CUA_HONG va rut/day hop Pi ngang qua cua hong; thao CUA_SAU_DUOI, truot buong toi vao tu phia sau.',
         '- PHU_KIEN_1.stl: 4 kep giu man hinh (2 tren, 2 duoi), moi kep 1 bulong M4x16 vao tru tren tam man (dai oc M4 truot tu ben vao khe cua tru; dau vit vao lo mu sau 3 mm tren tam man).',
         '- CUA_HONG.stl: cua ben phai, 184.2 x 85.2 x 2 mm (phu het hong than thap va phan duoi cua phan man hinh), khe 0.4 mm quanh mep. Mat trong co 1 khoi 14 x 11.4 x 11.6 de bulong goc truoc-phai cua NAP_NGANG bat vao (dai oc dua tu duoi len) - thao CUA_HONG thi thao bulong nay truoc. In nam, mat ngoai up xuong ban. 4 bulong M4x16 vao 4 tru (dai oc trong tui luc giac AF 7.4 sau 3.7 o dau trong tru). Khe nguon 60 x 25 (y 72.5-132.5, z 20-45), 4 khe day rut (deu de ho). Mat ngoai kin, tui khoet o mat trong.',
         '- CUA SAU tach 3 tam (4 + 4 + 3 bulong M4x16), dai oc nam trong tui luc giac o dau trong cua tru/thanh ngang:',
         '    CUA_SAU_TREN.stl: nap chu L = mat sau + mai cua phan man hinh, 280 x 56 x 80. Ha thang tu tren xuong, mai ngoi len dinh vach (z 168). In mat sau up xuong ban, khong can support.',
         '    NAP_NGANG.stl: mai cua than thap (nam ngang), 280 x 161.6 x 2 + 2 gan cung 2.4 x 7 o mat duoi; 4 bulong xuong 3 khoi goc + 1 khoi tren CUA_HONG (dai oc dua vao tu duoi qua ranh luc giac trong gan cheo). In up mat tren xuong ban.',
         '    CUA_SAU_DUOI.stl: mat sau cua than thap (dung), 275.2 x 85.2 x 2; 3 bulong: 2 tren vao 2 khoi goc sau, 1 duoi-phai vao tru tren san (goc duoi-trai bo tru de buong toi truot vao).',
         '- Kiem tra CAD (kiem_tra_lap.py): 49/49 muc dat - khong chi tiet nao de nhau, khe 0.4 quanh moi cua, 19 truc bulong M4x16 thong va vit qua dai oc 2.4 mm, dai oc lot vao tui, Pi va buong toi con >= 1 mm moi phia, duong lap Pi (tu tren va ngang qua cua hong)/buong toi/nap chu L khong vuong.',
         '- Lo bulong M4 dai 4.5 mm, tui dai oc AF 7.4: CHUA in thu. In cac mau thu khop truoc (de_xuat_kich_thuoc/mau_thu_khop: lo vit/dai oc, ranh truot, chot LEGO) roi moi gui in vo.',
         '- Da slice bang Bambu Studio 2.9.1 (may H2S, cau hinh mac dinh + bat support): tong ~502 g PETG, ~16.3 h. CHUA in thu, CHUA kiem tra khe cap voi day that.']
    (out/'HUONG_DAN.txt').write_text(chr(10).join(txt)+chr(10))
    zp=out.parent/'VO_RIENG_420.zip';zp.unlink(missing_ok=True)
    with zipfile.ZipFile(zp,'w',zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out.iterdir()):zf.write(f,f.name)
    report['_asm_mesh']=result['_asm'][1]
    return report


if __name__=='__main__':
    for v in (sys.argv[1:] or VARIANTS):
        r=build(v);print(v);[print('  ',k,x) for k,x in r['files'].items()];print('  dropped',r['dropped'])
