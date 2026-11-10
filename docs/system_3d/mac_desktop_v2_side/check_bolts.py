"""M4 joint check: every bolt shaft (D4.4, M4x16 length) is clear of all parts and modules, and its nut pocket sits in material."""
import importlib.util
from pathlib import Path
import numpy as np,trimesh
P=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('c',P/'build.py');c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
ms={p.stem:trimesh.load_mesh(p) for p in (P/'out/assembly_meshes').glob('*.stl') if not p.stem.startswith('screen_')}
I=lambda a,b:abs(trimesh.boolean.intersection([a,b],engine='manifold').volume)
def pin(a,b,r):
    a=np.array(a,float);b=np.array(b,float);d=b-a;L=np.linalg.norm(d)
    T=trimesh.geometry.align_vectors([0,0,1],d/L);T[:3,3]=(a+b)/2
    return trimesh.creation.cylinder(radius=r,height=L,sections=48,transform=T)
def run(label,start,direction,panel,boss_from,boss_to,boss='01_body'):
    """start: outer face point; shaft = 16 mm along direction; panel must have a hole there; material ring between boss_from..boss_to."""
    d=np.array(direction,float);s=np.array(start,float)
    shaft=pin(s-d*.5,s+d*16,2.15)
    hit={n:round(I(shaft,m),3) for n,m in ms.items() if I(shaft,m)>.02}
    ring=trimesh.boolean.difference([pin(s+d*boss_from,s+d*boss_to,5.0),pin(s+d*(boss_from-1),s+d*(boss_to+1),2.4)],engine='manifold')
    mat=I(ring,ms[boss])/ring.volume
    ok=not hit and mat>.6
    print(f"{'OK ' if ok else 'BAD'} {label:28s} cham={hit or '-'} nhua quanh lo={mat:.0%}")
    return ok
W,D,WL=c.W_OUT,c.D,c.WALL;res=[]
for y,z in c.SD_BOLTS:res.append(run(f'cua hong y{y:.0f} z{z:.0f}',(0,y,z),(1,0,0),'09_side_panel',WL+.5,13.5))
for x,z in c.RL_BOLTS:res.append(run(f'cua sau duoi x{x:.0f} z{z:.0f}',(x,D,z),(0,-1,0),'08_rear_low',WL+.5,D-c.RB_Y[0]-.5))
for i,(x,y) in enumerate(c.RF_BOLTS):res.append(run(f'nap ngang x{x:.0f} y{y:.0f}',(x,y,c.H_LOW),(0,0,-1),'11_roof',WL+.5,c.H_LOW-c.BEAM_Z-.5,'09_side_panel' if i==0 else '01_body'))
for x,z in c.RT_BOLTS:res.append(run(f'cua sau tren x{x:.0f} z{z:.0f}',(x,c.Y_STEP,z),(0,-1,0),'10_rear_top',WL+.5,13.5))
print('ALL OK' if all(res) else 'FAILED',sum(res),'/',len(res))
