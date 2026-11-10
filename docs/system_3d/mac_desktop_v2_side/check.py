"""Interference + clearance check for the side-by-side layout (assembly meshes)."""
import itertools,sys
from pathlib import Path
import numpy as np,trimesh
O=Path(__file__).resolve().parent/'out/assembly_meshes'
ms={p.stem:trimesh.load_mesh(p) for p in O.glob('*.stl')}
def ov(a,b):
    if np.any(np.minimum(a.bounds[1],b.bounds[1])-np.maximum(a.bounds[0],b.bounds[0])<1e-5):return 0.
    return abs(trimesh.boolean.intersection([a,b],engine='manifold').volume)
bad=[]
for (na,a),(nb,b) in itertools.combinations(ms.items(),2):
    v=ov(a,b)
    if v>.02:bad.append((na,nb,round(v,2)))
print('interferences:',bad or 'none')
mods={n:m for n,m in ms.items() if n.startswith(('optical_','hood_')) or n=='pi_housing'}
for n,m in sorted(mods.items()):print(n,m.bounds.round(1).tolist())
chb=trimesh.util.concatenate([m for n,m in mods.items() if n!='pi_housing'])
pi=mods['pi_housing']
print('chamber group X',chb.bounds[:,0].round(1),'Y',chb.bounds[:,1].round(1),'Z',chb.bounds[:,2].round(1))
print('gap chamber body -> Pi in X:',round(pi.bounds[0,0]-mods['optical_body'].bounds[1,0],2))
sys.exit(1 if bad else 0)
