"""Checks exported CAD, fastener passages, rear servicing and six STL deliveries."""
import itertools
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import cadquery as cq
import numpy as np
import trimesh
from scipy.spatial import cKDTree

P=Path(__file__).resolve().parent;O=P/'out';D=P/'GUI_IN_6_STL'
EPS=.02  # mm³ allowance for float32 contact faces, not a mechanical fit allowance


def overlap(a,b):
    if np.any(np.minimum(a.bounds[1],b.bounds[1])-np.maximum(a.bounds[0],b.bounds[0])<1e-5):return 0.
    return abs(trimesh.boolean.intersection([a,b],engine='manifold').volume)


def assembly():
    manifest=json.loads((O/'manifest.json').read_text())
    ms={p.stem:trimesh.load_mesh(p) for p in (O/'assembly_meshes').glob('*.stl')}
    assert len(ms)==22
    assert not any(n.startswith('base_') for n in ms)
    assert np.isclose(min(m.bounds[0,2] for m in ms.values()),0)
    for n,m in ms.items():assert m.is_volume and len(m.split(only_watertight=False))==1,n
    assert np.allclose(ms['screen_ENVELOPE_ONLY'].bounds,[[21,.5,48],[199,10.5,153]])
    assert ms['pi_housing'].bounds[1,2]==ms['optical_body'].bounds[0,2]==89
    for x in (16,204):
        for y in (22,126):
            probe=trimesh.creation.box([1,1,1],transform=trimesh.transformations.translation_matrix([x,y,1.5]))
            assert sum(overlap(probe,m) for n,m in ms.items() if 'shell' in n)>.99,('obsolete base hole',x,y)
    for row in manifest['parts']:
        name=row['name'];m=trimesh.load_mesh(O/'print'/row['print_file'])
        assert m.is_volume and len(m.split(only_watertight=False))==1,name
        assert np.all(m.extents<=180.001),name
        shape=cq.importers.importStep(str(O/'step'/(name+'.step'))).val()
        assert shape.isValid() and len(shape.Solids())==1,name
        assert abs(shape.Volume()-m.volume)<max(.1,shape.Volume()*.005),name
        t=np.array(row['assembly_to_print']);assert np.isclose(np.linalg.det(t[:3,:3]),1)
        m.apply_transform(np.linalg.inv(t))
        assert cKDTree(ms[name].vertices).query(m.vertices)[0].max()<.001,name
    for (na,a),(nb,b) in itertools.combinations(ms.items(),2):
        assert overlap(a,b)<EPS,('assembly interference',na,nb)
    axes=[]
    def axis(label,direction,a,b,c1,c2):
        vec=np.array({'x':[1,0,0],'y':[0,1,0],'z':[0,0,1]}[direction])
        pos={'x':[a,c1,c2],'y':[c1,a,c2],'z':[c1,c2,a]}[direction]
        t=trimesh.geometry.align_vectors([0,0,1],vec);t[:3,3]=np.array(pos)+(b-a)/2*vec
        pin=trimesh.creation.cylinder(radius=2.2,height=b-a,sections=48,transform=t)
        for n,m in ms.items():assert overlap(pin,m)<EPS,('M4 shaft',label,n)
        axes.append(label)
    for x in (10,210):
        for z in (12,158):axis(f'front {x},{z}','y',-11,17,x,z)
    for x in (12,208):
        for z in (12,158):axis(f'door {x},{z}','y',135,152,x,z)
    for y in (18,132):axis(f'roof width seam {y}','z',160,171,116,y)
    axis('floor width seam','z',-1,9.3,116,14)
    for x in (16,204):
        axis(f'roof depth seam {x}','z',160,171,x,108)
        axis(f'floor depth seam {x}','z',-1,9.3,x,108)
    for z in (18,160):axis(f'bezel seam {z}','y',-11,7,116,z)
    for z in (50,85,145):axis(f'door seam {z}','y',140,152,116,z)
    for x in (13.5,206.5):
        for z in (62,137):axis(f'screen clip {x},{z}','y',1,15.5,x,z)
    for x in (33,187):axis(f'tray retainer {x}','z',-1,16,x,130)
    for y in (35,136):axis(f'tray splice {y}','z',8,20.3,116,y)
    for x in (56,164):
        for y in (40,131):axis(f'chamber to Pi {x},{y}','z',82,97,x,y)
    for x in (64,156):
        for y in (68,102):axis(f'Pi to tray {x},{y}','z',8,27,x,y)
    import build as cad
    hardware=[]
    def clearance(label,shape):
        probe=cad.b.to_mesh(shape)
        for n,m in ms.items():assert overlap(probe,m)<EPS,('hardware clearance',label,n)
        hardware.append(label)
    for x in (10,210):
        for z in (12,158):clearance(f'front captive nut {x},{z}',cad.hexhole('y',6.401,9.599,x,z,7))
    for x in (12,208):
        for z in (12,158):clearance(f'rear captive nut {x},{z}',cad.hexhole('y',136.401,139.599,x,z,7))
    for x in (13.5,206.5):
        for z in (62,137):
            clearance(f'LCD captive nut {x},{z}',cad.hexhole('y',2.401,5.599,x,z,7))
            clearance(f'LCD washer {x},{z}',cad.cyl('y',14.501,15.299,x,z,4.5))
            clearance(f'LCD socket head {x},{z}',cad.cyl('y',15.301,19.299,x,z,3.5))
    for x in (56,164):
        for y in (40,131):
            clearance(f'chamber bolt washer {x},{y}',cad.cyl('z',84.201,84.999,x,y,4.5))
            clearance(f'chamber socket head {x},{y}',cad.cyl('z',80.201,84.199,x,y,3.5))
    moving=[n for n in ms if n.startswith(('optical_','hood_','07_','08_')) or n=='pi_housing']
    fixed=[n for n in ms if n not in moving and not n.startswith(('05_','06_'))]
    for d in (0,5,20,60,120,175):
        for n in moving:
            m=ms[n].copy();m.apply_translation([0,d,0])
            for other in fixed:assert overlap(m,ms[other])<EPS,('extraction',d,n,other)
    expected=set(ms)-{'screen_ENVELOPE_ONLY'}
    with zipfile.ZipFile(O/manifest['single_assembly_file']) as z:
        assert z.testzip() is None;model=ET.fromstring(z.read('3D/3dmodel.model'))
    ns={'m':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
    assert model.attrib['unit']=='millimeter'
    assert {r.attrib['name'] for r in model.findall('m:resources/m:object',ns)}==expected
    imported=trimesh.load(O/manifest['single_assembly_file'],force='scene')
    assert set(imported.geometry)==expected
    for n,m in imported.geometry.items():
        assert m.is_volume and len(m.split(only_watertight=False))==1,n
        assert cKDTree(ms[n].vertices).query(m.vertices)[0].max()<.001,n
    print('Assembly, STEP, M4 axes, extraction and 3MF passed',flush=True)
    return ms,axes,hardware


def main():
    ms,axes,hardware=assembly()
    rows=json.loads((D/'DANH_SACH_CHI_TIET.json').read_text());assert len(rows)==6
    names=[n for r in rows for n in r['parts']]
    assert len(names)==len(set(names))==21
    assert set(names)==set(ms)-{'screen_ENVELOPE_ONLY'}
    for row in rows:
        m=trimesh.load_mesh(D/row['file']);parts=m.split(only_watertight=False)
        assert len(parts)==len(row['parts']) and all(p.is_volume for p in parts)
        assert np.all(m.bounds[0]>=-.001) and np.all(m.bounds[1]<=180.001)
        for name,part in zip(row['parts'],parts):
            assert abs(part.bounds[0,2])<.001
            assert np.allclose(sorted(part.extents),sorted(ms[name].extents),atol=.001),name
            assert abs(part.volume-ms[name].volume)<max(.01,abs(ms[name].volume)*.00002),name
        for a,b in itertools.combinations(parts,2):assert overlap(a,b)<EPS
    report=dict(passed=True,variant='Mac Desktop V1',screen_frame_mm=[178,105,10],
                layout='Optical chamber stacked on retained Pi case, no plinth',native_STEP_solids=14,
                printable_components=21,STL_files=6,part_counts=[len(r['parts']) for r in rows],
                bed_mm=[180,180,180],M4_axes=axes,hardware_envelopes=hardware,
                extraction_samples_mm=[0,5,20,60,120,175],
                not_verified=['Slicing/support/brim','Load, PETG creep, stability and cooling',
                              'Physical screen active window, cables/PCBs and optical validation'])
    (O/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
