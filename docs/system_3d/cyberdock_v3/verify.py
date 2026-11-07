"""Validate stacked assembly and the six actual multi-component STL deliveries."""
from pathlib import Path
import itertools,json
import numpy as np,trimesh
P=Path(__file__).resolve().parent;O=P/'out';D=P/'GUI_IN_6_STL'
ms={p.stem:trimesh.load_mesh(p) for p in (O/'assembly_meshes').glob('*.stl')}
def overlap(a,b):
 if np.any(np.minimum(a.bounds[1],b.bounds[1])-np.maximum(a.bounds[0],b.bounds[0])<1e-5):return 0
 return abs(trimesh.boolean.intersection([a,b],engine='manifold').volume)
for n,m in ms.items():assert m.is_volume and len(m.split(only_watertight=False))==1,n
assert len(ms)==38
for (a,x),(b,y) in itertools.combinations(ms.items(),2):assert overlap(x,y)<.02,(a,b)
assert np.allclose(ms['screen_ENVELOPE_ONLY'].extents,[178,10,105])
assert np.isclose(ms['pi_housing'].bounds[1,2],ms['optical_body'].bounds[0,2])
assert np.isclose(ms['pi_housing'].bounds[0,2],19)
for x in (56,164):
 for y in (40,131):
  pin=trimesh.creation.cylinder(radius=2.2,height=15,sections=48);pin.apply_translation([x,y,88])
  for n in ('pi_housing','optical_body'):assert overlap(pin,ms[n])<.02,(x,y,n)
for x in (64,156):
 for y in (68,102):
  pin=trimesh.creation.cylinder(radius=2.2,height=15,sections=48);pin.apply_translation([x,y,16])
  for n in ('pi_housing','07_tray_left','08_tray_right'):assert overlap(pin,ms[n])<.02,(x,y,n)
moving=[n for n in ms if n.startswith(('optical_','hood_','07_','08_')) or n=='pi_housing']
fixed=[n for n in ms if n not in moving and not n.startswith(('05_','06_'))]
for d in (0,5,20,60,120,170):
 for n in moving:
  m=ms[n].copy();m.apply_translation([0,d,0])
  for other in fixed:assert overlap(m,ms[other])<.02,('pull',d,n,other)
rows=json.loads((D/'DANH_SACH_CHI_TIET.json').read_text());assert len(rows)==6
names=[n for r in rows for n in r['parts']];assert len(names)==len(set(names))==37
assert set(names)==set(ms)-{'screen_ENVELOPE_ONLY'}
for row in rows:
 m=trimesh.load_mesh(D/row['file']);parts=m.split(only_watertight=False)
 assert len(parts)==len(row['parts']) and all(p.is_volume for p in parts)
 assert np.all(m.bounds[0]>=-.001) and np.all(m.bounds[1]<=180.001)
 for p in parts:assert abs(p.bounds[0,2])<.001
 for a,b in itertools.combinations(parts,2):assert overlap(a,b)<.02
report=dict(passed=True,screen_mm=[178,105,10],layout='dark chamber stacked on existing Pi case',
 objects=37,STL_files=6,part_counts=[len(r['parts']) for r in rows],bed_mm=[180,180,180],
 assembly_collisions=False,M4_module_axes=True,extraction_samples_mm=[0,5,20,60,120,170],
 not_checked=['slicing supports/brim','physical load and PETG creep','actual cable/connector envelopes and optical calibration'])
(O/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
