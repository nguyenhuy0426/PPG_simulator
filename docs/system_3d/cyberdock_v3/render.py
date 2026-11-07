"""Offscreen previews of the exported mesh assembly (no imagined geometry)."""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont
import trimesh
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

HERE=Path(__file__).resolve().parent
OUT=HERE/"out"


def actor(mesh,color):
    points=vtk.vtkPoints();points.SetData(numpy_to_vtk(mesh.vertices.astype(float),deep=True))
    faces=np.column_stack([np.full(len(mesh.faces),3),mesh.faces]).astype(np.int64)
    cells=vtk.vtkCellArray();cells.SetCells(len(faces),numpy_to_vtkIdTypeArray(faces.ravel(),deep=True))
    poly=vtk.vtkPolyData();poly.SetPoints(points);poly.SetPolys(cells)
    normals=vtk.vtkPolyDataNormals();normals.SetInputData(poly);normals.SetFeatureAngle(35)
    normals.ConsistencyOn();normals.SplittingOn();normals.Update()
    mapper=vtk.vtkPolyDataMapper();mapper.SetInputConnection(normals.GetOutputPort())
    result=vtk.vtkActor();result.SetMapper(mapper)
    result.GetProperty().SetColor(np.array(ImageColor.getrgb(color))/255)
    result.GetProperty().SetAmbient(.25);result.GetProperty().SetDiffuse(.75)
    return result


def render(opened=False,cutaway=False):
    ren=vtk.vtkRenderer();ren.SetBackground(1,1,1)
    tilt=trimesh.transformations.rotation_matrix(np.deg2rad(-3),[1,0,0],[0,75,85])
    for p in (OUT/"assembly_meshes").glob("*.stl"):
        name=p.stem
        if cutaway and name.startswith(("05_","06_","09_","10_","11_","12_","knob_","gear_","spacer_")):continue
        if opened and name.startswith(("05_","06_")):continue
        m=trimesh.load_mesh(p)
        if cutaway and "shell" in name:
            m=m.slice_plane([0,0,20],[0,0,-1])
        if "screen" in name:color="#152731"
        elif name.startswith(("07_","08_")):color="#399a88"
        elif name.startswith(("09_","10_","11_","12_","trim_","gear_","clip_","spacer_")):color="#8da4b5"
        elif name.startswith(("optical_","hood_")):color="#313941"
        elif name=="pi_housing":color="#8798a8"
        else:color="#bc493f"
        moving=name.startswith(("07_","08_","hood_","optical_")) or name=="pi_housing"
        if opened and moving and not cutaway:m.apply_translation([0,75,0])
        if not opened and not cutaway and not name.startswith(("09_","10_","11_","12_","gear_","knob_","spacer_")):
            m.apply_transform(tilt)
        ren.AddActor(actor(m,color))
    if not opened and not cutaway:
        # Waveforms are preview graphics only, not manufactured geometry or model validation.
        for z0,col,phase in ((82,"#f15a54",0),(46,"#53c2b8",.3)):
            x=np.linspace(33,197,350);u=(x/35+phase)%1
            signal=16*np.exp(-((u-.24)/.08)**2)+5*np.exp(-((u-.48)/.11)**2)
            vertices=np.column_stack([x,np.full(len(x),.42),z0+signal])
            vertices=trimesh.transform_points(vertices,tilt)
            pts=vtk.vtkPoints()
            for v in vertices:pts.InsertNextPoint(*v)
            line=vtk.vtkPolyLine();line.GetPointIds().SetNumberOfIds(len(vertices))
            for i in range(len(vertices)):line.GetPointIds().SetId(i,i)
            cells=vtk.vtkCellArray();cells.InsertNextCell(line)
            poly=vtk.vtkPolyData();poly.SetPoints(pts);poly.SetLines(cells)
            mapper=vtk.vtkPolyDataMapper();mapper.SetInputData(poly)
            a=vtk.vtkActor();a.SetMapper(mapper);a.GetProperty().SetColor(np.array(ImageColor.getrgb(col))/255)
            a.GetProperty().SetLineWidth(3);ren.AddActor(a)
    camera=ren.GetActiveCamera();camera.SetPosition(450,530 if opened else -480,290)
    camera.SetFocalPoint(110,110 if opened else 75,85);camera.SetViewUp(0,0,1)
    if cutaway:
        camera.SetPosition(430,480,490);camera.SetFocalPoint(115,130,30)
    camera.ParallelProjectionOn();ren.ResetCamera();camera.Zoom(1.12)
    win=vtk.vtkRenderWindow();win.SetOffScreenRendering(1);win.SetSize(1500,1100)
    win.SetMultiSamples(4);win.AddRenderer(ren);win.Render()
    capture=vtk.vtkWindowToImageFilter();capture.SetInput(win);capture.ReadFrontBufferOff();capture.Update()
    path=OUT/("internal_layout.png" if cutaway else "rear_open.png" if opened else "front.png")
    writer=vtk.vtkPNGWriter();writer.SetFileName(str(path));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
    win.Finalize()
    return path


if __name__=="__main__":
    a,b=render(),render(True)
    render(cutaway=True)
    image=Image.new("RGB",(3000,1200),"white")
    image.paste(Image.open(a),(0,70));image.paste(Image.open(b),(1500,70))
    draw=ImageDraw.Draw(image);font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",32)
    draw.text((50,20),"CAD V3 · Màn hình 178 × 105 mm",fill="#25343f",font=font)
    draw.text((1550,20),"Cửa sau mở · khay kéo ra 75 mm",fill="#25343f",font=font)
    draw.text((50,1150),"Phác thảo kỹ thuật — chưa xác nhận in, tải và màn hình dày 10 mm",fill="#555555",font=font)
    image.save(OUT/"preview.png")
