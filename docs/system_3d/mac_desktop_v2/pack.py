"""Six Macintosh V2 non-overlapping 180 mm STL groups; preserve every closed component."""
import json,math,random
from pathlib import Path
import numpy as np,trimesh
from PIL import Image,ImageDraw
from scipy.signal import fftconvolve
from scipy.ndimage import binary_dilation
P=Path(__file__).resolve().parent;O=P/'out';DEST=P/'GUI_IN_6_STL';DEST.mkdir(exist_ok=True)
manifest=json.loads((O/'manifest.json').read_text());items={}
for r in manifest['parts']:
 items[r['name']]=trimesh.load_mesh(O/'print'/r['print_file'])
for p in (O/'assembly_meshes').glob('*.stl'):
 if p.stem.startswith(('optical_','hood_')) or p.stem=='pi_housing':
  m=trimesh.load_mesh(p)
  if p.stem=='optical_body':m=trimesh.load_mesh(O/'print/17_optical_body_fixed_LED.stl')
  elif p.stem=='pi_housing':m=trimesh.load_mesh(O/'print/18_pi_housing_m4.stl')
  else:
   if 'lid' in p.stem:
    t=trimesh.transformations.rotation_matrix(math.pi,[1,0,0]);m.apply_transform(t)
  items[p.stem]=m
assert len(items)==21,len(items)
for name in list(items):
 if name=='optical_lid':
  m=trimesh.load_mesh(O/'assembly_meshes'/(name+'.stl'));m.apply_transform(trimesh.geometry.align_vectors([1,0,0],[0,0,1]));items[name]=m
variants={}
for name,m in items.items():
 if name.startswith(('05_door','06_door')):
  m.apply_transform(trimesh.transformations.rotation_matrix(math.pi/2,[0,1,0]))
 if name.startswith(('trim_','gear_')):
  axis=int(np.argmin(m.extents));v=np.eye(3)[axis];m.apply_transform(trimesh.geometry.align_vectors(v,[0,0,1]))
 m.apply_translation(-m.bounds[0]); assert m.is_volume and max(m.extents)<=180.001,name
 vs=[]
 for k in range(4):
  x=m.copy();x.apply_transform(trimesh.transformations.rotation_matrix(k*math.pi/2,[0,0,1]));x.apply_translation(-x.bounds[0])
  w,h=np.ceil(x.extents[:2]).astype(int)+1
  im=Image.new('1',(w,h));d=ImageDraw.Draw(im)
  for face in x.triangles:d.polygon([tuple(v[:2]) for v in face],fill=1)
  mask=np.pad(np.array(im,dtype=bool),4);mask=binary_dilation(mask,iterations=1)
  vs.append((x,mask))
 variants[name]=vs
best=None
for attempt in range(80):
 beds=[np.zeros((180,180),bool) for _ in range(6)];placed=[]
 rng=random.Random(attempt)
 order=sorted(items,key=lambda n:-(variants[n][0][1].sum()*(1 if attempt==0 else rng.uniform(.75,1.3))))
 for name in order:
  options=[]
  for bi,occ in enumerate(beds):
   for ki,(mesh,mask) in enumerate(variants[name]):
    h,w=mask.shape
    if h>180 or w>180:continue
    conv=fftconvolve(occ.astype(float),mask[::-1,::-1].astype(float),mode='valid')
    yy,xx=np.where(conv<.1)
    if not len(xx):continue
    score=yy*180+xx;j=np.argmin(score)
    options.append((bi,int(score[j]),ki,int(xx[j]),int(yy[j])))
  if not options:
   print('FAILED',name,[v[1].shape for v in variants[name]],'placed',[(n,b) for n,b,*_ in placed],flush=True);break
  bi,_,ki,x,y=min(options);mesh,mask=variants[name][ki];h,w=mask.shape;beds[bi][y:y+h,x:x+w]|=mask
  placed.append((name,bi,ki,x,y))
 if len(placed)==21:best=placed;break
 print('attempt',attempt,'placed',len(placed),flush=True)
if best is None:raise RuntimeError('Cannot pack six beds without overlap; do not deliver')
# Keep six delivery files even if fewer beds suffice geometrically.
for bi in range(6):
 if not any(row[1]==bi for row in best):
  counts=[sum(row[1]==j for row in best) for j in range(6)];src=int(np.argmax(counts))
  assert counts[src]>1
  idx=next(i for i,row in enumerate(best) if row[1]==src)
  name,_,k,_,_=best[idx];best[idx]=(name,bi,k,0,0)
rows=[]
for bi in range(6):
 parts=[];names=[]
 for name,bidx,k,x,y in best:
  if bidx!=bi:continue
  mesh=variants[name][k][0].copy();mesh.apply_translation([x+4,y+4,0]);parts.append(mesh);names.append(name)
 assert parts
 combined=trimesh.util.concatenate(parts);assert combined.is_volume and np.all(combined.bounds[0]>=0) and np.all(combined.bounds[1]<=180.001)
 path=DEST/f'BAN_{bi+1:02d}.stl';combined.export(path)
 loaded=trimesh.load_mesh(path);assert len(loaded.split(only_watertight=False))==len(names),(bi,names)
 rows.append({'file':path.name,'parts':names,'bounds_mm':loaded.bounds.tolist()})
(DEST/'DANH_SACH_CHI_TIET.json').write_text(json.dumps(rows,indent=2))
print('SUCCESS',sum(len(r['parts']) for r in rows),[len(r['parts']) for r in rows])
