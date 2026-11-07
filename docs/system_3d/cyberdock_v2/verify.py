"""Check actual exported parts, assembly collisions, M4 alignment and service path."""
import importlib.util
import itertools
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

import cadquery as cq
import numpy as np
import trimesh
from scipy.spatial import cKDTree

HERE=Path(__file__).resolve().parent;OUT=HERE/"out"
spec=importlib.util.spec_from_file_location("qa_base",HERE.parent/"cyberdock_v1/verify.py")
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
intersection,material,EPS=v.intersection,v.material,v.EPS


def main():
    manifest=json.loads((OUT/"manifest.json").read_text());checks=[]
    meshes={p.stem:trimesh.load_mesh(p) for p in (OUT/"assembly_meshes").glob("*.stl")}
    for row in manifest["parts"]:
        name=row["name"];m=trimesh.load_mesh(OUT/"print"/row["print_file"])
        assert m.is_volume and len(m.split(only_watertight=False))==1,name
        assert np.all(m.bounds[0]>=-.001) and np.all(m.extents<=180.001),name
        s=cq.importers.importStep(str(OUT/"step"/(name+".step"))).val()
        assert s.isValid() and len(s.Solids())==1,name
        assert abs(s.Volume()-m.volume)<max(.1,s.Volume()*.005),name
        t=np.array(row["assembly_to_print"]);assert np.isclose(np.linalg.det(t[:3,:3]),1)
        m.apply_transform(np.linalg.inv(t))
        assert cKDTree(meshes[name].vertices).query(m.vertices)[0].max()<.001,name
        checks.append(name)
    for name,m in meshes.items():assert m.is_volume and len(m.split(only_watertight=False))==1,name
    for key in ("fixed_optical_body","pi_housing_m4"):
        m=trimesh.load_mesh(OUT/"print"/manifest[key]["print_file"])
        assert m.is_volume and np.all(m.extents<=180.001)
    package=OUT/manifest["single_assembly_file"]
    ns={"m":"http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    with zipfile.ZipFile(package) as z:
        assert z.testzip() is None;model=ET.fromstring(z.read("3D/3dmodel.model"))
    expected={n:m for n,m in meshes.items() if "ENVELOPE" not in n}
    assert model.attrib["unit"]=="millimeter"
    assert {o.attrib["name"] for o in model.findall("m:resources/m:object",ns)}==set(expected)
    imported=trimesh.load(package,force="scene");assert set(imported.geometry)==set(expected)
    for n,m in imported.geometry.items():
        assert m.is_volume and len(m.split(only_watertight=False))==1,n
        assert cKDTree(expected[n].vertices).query(m.vertices)[0].max()<.001,n
    bounds=np.array([np.min([m.bounds[0] for m in meshes.values()],axis=0),np.max([m.bounds[1] for m in meshes.values()],axis=0)])
    assert np.allclose(imported.bounds,bounds+manifest["assembly_3mf_translation_mm"],atol=.001)
    assert np.allclose(trimesh.load(OUT/"assembly.glb",force="scene").bounds,bounds*.001,atol=1e-6)
    compound=cq.importers.importStep(str(OUT/"enclosure_assembly.step")).val()
    assert compound.isValid() and len(compound.Solids())==len(checks)
    hits=[]
    for (na,a),(nb,b) in itertools.combinations(meshes.items(),2):
        volume=intersection(a,b)
        if volume>EPS:hits.append([na,nb,round(volume,4)])
    report={"native_CAD_solids":len(checks),"single_3mf_objects":len(expected),
            "step_stl_3mf_roundtrip":True,"intersections_over_tolerance":hits,"tolerance_mm3":EPS}
    def save(): (OUT/"verification.json").write_text(json.dumps(report,indent=2)+"\n")
    save()
    assert not hits,hits
    axes=[]
    def axis(label,direction,a,b,c1,c2):
        pos={"x":[a,c1,c2],"y":[c1,a,c2],"z":[c1,c2,a]}[direction]
        vec=np.array({"x":[1,0,0],"y":[0,1,0],"z":[0,0,1]}[direction])
        t=trimesh.geometry.align_vectors([0,0,1],vec);t[:3,3]=np.array(pos)+(b-a)/2*vec
        pin=trimesh.creation.cylinder(radius=2.2,height=b-a,sections=48,transform=t)
        for n,m in meshes.items(): assert intersection(pin,m)<EPS,("fastener",label,n)
        axes.append(label)
    for x in (16,214):
        for z in (9,121):axis(f"front {x},{z}","y",-5.1,15,x,z)
    for x in (19,211):
        for z in (9,99):axis(f"rear {x},{z}","y",230,247,x,z)
    for y in (40,232):axis(f"bottom seam {y}","z",-1,9.3,121,y)
    axis("roof width seam","z",119,132,121,21)
    for x in (35,195):
        axis(f"floor depth seam {x}","z",-1,9.3,x,131)
        axis(f"roof depth seam {x}","z",112,132,x,131)
    for x in (38,192):axis(f"tray retainer {x}","z",-2,14,x,230)
    for x in (90,140):axis(f"tray splice {x}","z",9,22,x,144)
    for x in (18.5,211.5):
        for z in (26.5,101.5):
            axis(f"screen {x},{z}","y",4,26,x,z)
            m=meshes["03_bezel_left" if x<115 else "03_bezel_right"]
            d=3.2 if x<115 else -3.2
            assert not material(m,[x+d,8,z]) and material(m,[x+d,10,z])
    for a,b in ((-35,13),(217,265)):axis(f"pivot {a}","x",a,b,70,65)
    for x in (110,120):axis(f"handle {x}","z",146,156,x,70)
    for x in (-11,241):
        for y in (144,156):axis(f"foot {x},{y}","z",-21,-11,x,y)
    for xs,ys in (((61,169),(40,131)),((69,161),(171,205))):
        for x in xs:
            for y in ys:axis(f"module {x},{y}","z",9,23,x,y)
    hardware=[]
    def clearance(label,direction,a,b,c1,c2,r):
        vec=np.array({"x":[1,0,0],"y":[0,1,0],"z":[0,0,1]}[direction])
        pos={"x":[a,c1,c2],"y":[c1,a,c2],"z":[c1,c2,a]}[direction]
        t=trimesh.geometry.align_vectors([0,0,1],vec);t[:3,3]=np.array(pos)+(b-a)/2*vec
        probe=trimesh.creation.cylinder(radius=r,height=b-a,sections=48,transform=t)
        for n,m in meshes.items():assert intersection(probe,m)<EPS,("hardware envelope",label,n)
        hardware.append(label)
    for x in (16,214):
        for z in (9,121):
            clearance(f"front washer {x},{z}","y",14.501,15.3,x,z,4.5)
            clearance(f"front socket head {x},{z}","y",15.3,19.3,x,z,3.5)
    for x in (19,211):
        for z in (9,99):
            clearance(f"door washer {x},{z}","y",245.501,246.3,x,z,4.5)
            clearance(f"door socket head {x},{z}","y",246.3,250.3,x,z,3.5)
    for x in (18.5,211.5):
        for z in (26.5,101.5):
            clearance(f"LCD washer {x},{z}","y",24.501,25.3,x,z,4.5)
            clearance(f"LCD socket head {x},{z}","y",25.3,29.3,x,z,3.5)
    for xs,ys in (((61,169),(40,131)),((69,161),(171,205))):
        for x in xs:
            for y in ys:
                clearance(f"module washer {x},{y}","z",9.7,10.499,x,y,4.5)
                clearance(f"module socket head {x},{y}","z",5.7,9.7,x,y,3.5)
    for x in (90,140):
        clearance(f"tray splice washer {x}","z",9.7,10.499,x,144,4.5)
        clearance(f"tray splice socket head {x}","z",5.7,9.7,x,144,3.5)
    for cy in (32.25,70.75):assert material(meshes["optical_body"],[22+19,34+cy,42])
    moving=[n for n in meshes if n.startswith(("07_","08_","hood_","optical_")) or n=="pi_housing"]
    fixed=[n for n in meshes if n not in moving and not n.startswith(("05_","06_"))]
    extraction=[]
    for d in (0,5,20,60,120,180,245):
        for n in moving:
            shifted=meshes[n].copy();shifted.apply_translation([0,d,0])
            for other in fixed:assert intersection(shifted,meshes[other])<EPS,("extraction",d,n,other)
        extraction.append(d)
    frame=[n for n in meshes if n.startswith(("09_","10_"))]
    body=[n for n in meshes if not n.startswith(("09_","10_","gear_","knob_","spacer_"))]
    tilts=[]
    # Deep retained Pi case limits tilt; verify the claimed operating range only.
    for angle in range(-6,7,3):
        t=trimesh.transformations.rotation_matrix(np.deg2rad(angle),[1,0,0],[0,70,65])
        for n in body:
            rotated=meshes[n].copy();rotated.apply_transform(t)
            assert rotated.bounds[0,2]>-20,("floor",angle,n)
            for other in frame:assert intersection(rotated,meshes[other])<EPS,("tilt",angle,n,other)
        tilts.append(angle)
    report.update(all_checks_passed=True,fastener_axes_checked=axes,fastener_standard="M4",
                  hardware_envelopes_checked=hardware,
                  clearance_probe_diameter_mm=4.4,rear_extraction_samples_mm=extraction,
                  tilt_samples_degrees=tilts,rod_bore_closure=True,
                  not_verified=["Screen thickness, active window, connector and cable envelopes",
                    "Slicer/supports/print tolerances", "Load, friction, creep and stability under touch",
                    "Thermal behavior, optical leakage/calibration and electrical board placement"])
    save();print(json.dumps(report,indent=2))


if __name__=="__main__":main()
