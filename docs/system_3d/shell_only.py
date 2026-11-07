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
}


def cyl(p0,p1,r=2.7):
    p0=np.asarray(p0,float);p1=np.asarray(p1,float);d=p1-p0;n=np.linalg.norm(d)
    t=trimesh.geometry.align_vectors([0,0,1],d/n);t[:3,3]=(p0+p1)/2
    return trimesh.creation.cylinder(radius=r,height=n,sections=32,transform=t)


def zc(x,y,a,b):return cyl([x,y,a],[x,y,b])
def yc(x,z,a,b):return cyl([x,a,z],[x,b,z])


def plugs(v):
    p=[];door=[];tray=[]
    if v in ('mac_desktop_v1','mac_desktop_v2','cyberdock_v3'):
        for z in (50,85,145):door.append(yc(116,z,146.5,150.5))
        for y in ((35,136) if v!='cyberdock_v3' else (45,120)):tray.append(zc(116,y,9,12))
    if v=='mac_desktop_v1':
        p+=[yc(116,18,-8,-1),yc(116,160,-10,-1)]
    if v=='mac_desktop_v2':
        sys.path.insert(0,str(ROOT/'mac_desktop_v2'))
        import build as cad
        L=cad.L4()
        def lp(z,a,b):return cyl((L@np.array([116,a,z,1.]))[:3],(L@np.array([116,b,z,1.]))[:3])
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
    if n.startswith(('01_','02_','03_','04_')):return 'shell'
    if n.startswith(('05_','06_')):return 'door'
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
    if kind_=='shell':R[:3,:3]=[[0,1,0],[0,0,1],[1,0,0]]
    elif kind_=='door':R[:3,:3]=[[1,0,0],[0,0,1],[0,-1,0]]
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
    groups={'shell':[],'door':[],'tray':[],'misc':[]}
    for n in sorted(ms):
        k=kind(n)
        if k:groups[k].append(n)
    x0,x1,z0,z1,y0,y1=cfg['slit']
    slit=trimesh.creation.box(extents=[x1-x0,y1-y0,z1-z0],transform=trimesh.transformations.translation_matrix([(x0+x1)/2,(y0+y1)/2,(z0+z1)/2]))
    report={'variant':v,'dropped':sorted(n for n in ms if kind(n) is None and not n.startswith('screen_')),'files':{}}
    result={}
    shell=merge(ms,groups['shell'])
    pl=plugs(v)
    ap=auto_plugs(shell);report['roof_floor_holes_plugged']=len(ap)
    allp=ap+pl['shell']
    if allp:shell=trimesh.boolean.union([shell,*allp],engine='manifold')
    cut_parts={'VO_LIEN_KHOI':shell}
    before=shell
    shell=trimesh.boolean.difference([shell,slit],engine='manifold')
    removed=before.volume-shell.volume
    assert removed>20,('USB-C slit removed almost nothing',v,removed)
    assert abs(trimesh.boolean.intersection([clean(shell),slit],engine='manifold').volume)<.5
    report['usb_c_slit']={'x_mm':[x0,x1],'z_mm':[z0,z1],'removed_mm3':round(removed)}
    result['VO_LIEN_KHOI']=('shell',shell)
    for k,fname in (('door','CUA_SAU'),('tray','KHAY_RUT')):
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
        pm=orient(k,clean(m))
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
     '- CUA_SAU.stl, KHAY_RUT.stl: hai nua cua/khay da gop thanh 1 chi tiet. PHU_KIEN_*.stl: kep man hinh va cac chi tiet nho/chan de (neu co), xep san tren ban 420 x 420.',
     f'- Khe cap nguon USB-C o mat truoc: rong {sl["x_mm"][1]-sl["x_mm"][0]:.0f} mm (X {sl["x_mm"][0]}..{sl["x_mm"][1]}), cao {sl["z_mm"][1]-sl["z_mm"][0]:.1f} mm (Z {sl["z_mm"][0]}..{sl["z_mm"][1]}), xuyen qua thanh truoc. Can phich/dau USB-C co dau boc khong qua 22 x 8 mm; cong USB-C cua Pi nam o X~66 mm (huong ve phia truoc), noi day ben trong sau khi mo cua sau.',
     '- Da bo: buong toi (than, nap, 4 chup day) va hop Pi 4. Khay rut, cua sau van giu de bat hop Pi/buong toi da in cua ban.',
     '- Hai nua trai/phai va truoc/sau duoc dich moi nua 0.13 mm vao nhau de han thanh khoi: kich thuoc ngoai nho hon 0.26 mm theo X (va Y cua than). Cac lo vit noi nua vo tren mai/day (va cua/khay/mat truoc neu co) da bit.',
     '- CHUA slice, CHUA in thu, CHUA kiem tra khe cap voi day that. Can kiem tra support (cac tai, ledge, mai ho phia truoc de Mac V2) trong slicer.']
    (out/'HUONG_DAN.txt').write_text(chr(10).join(txt)+chr(10))
    zp=out.parent/'VO_RIENG_420.zip';zp.unlink(missing_ok=True)
    with zipfile.ZipFile(zp,'w',zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out.iterdir()):zf.write(f,f.name)
    report['_asm_mesh']=result['_asm'][1]
    return report


if __name__=='__main__':
    for v in (sys.argv[1:] or VARIANTS):
        r=build(v);print(v);[print('  ',k,x) for k,x in r['files'].items()];print('  dropped',r['dropped'])
