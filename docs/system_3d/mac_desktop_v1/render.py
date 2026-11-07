"""Render actual exported CAD; colors and waveform marks are preview graphics."""
import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image,ImageColor,ImageDraw,ImageFont
import trimesh
import vtk

P=Path(__file__).resolve().parent;O=P/'out'
spec=importlib.util.spec_from_file_location('cad_renderer',P.parent/'cyberdock_v3/render.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


def render(opened=False):
    ren=vtk.vtkRenderer();ren.SetBackground(1,1,1)
    colors=json.loads((O/'manifest.json').read_text())['colors']
    for p in (O/'assembly_meshes').glob('*.stl'):
        name=p.stem
        if opened and name.startswith(('05_','06_')):continue
        m=trimesh.load_mesh(p)
        moving=name.startswith(('optical_','hood_','07_','08_')) or name=='pi_housing'
        if opened and moving:m.apply_translation([0,80,0])
        col=colors.get(name,'#313941' if name.startswith(('optical_','hood_')) else '#8798a8')
        if 'screen' in name:col='#172824'
        ren.AddActor(r.actor(m,col))
    if not opened:
        for z,col,phase in ((117,'#72957a',0),(84,'#8fb9a4',.2)):
            x=np.linspace(30,190,350);u=(x/35+phase)%1
            sig=13*np.exp(-((u-.24)/.08)**2)+4*np.exp(-((u-.48)/.11)**2)
            pts=vtk.vtkPoints()
            for xx,zz in zip(x,z+sig):pts.InsertNextPoint(xx,.42,zz)
            line=vtk.vtkPolyLine();line.GetPointIds().SetNumberOfIds(len(x))
            for i in range(len(x)):line.GetPointIds().SetId(i,i)
            cells=vtk.vtkCellArray();cells.InsertNextCell(line)
            poly=vtk.vtkPolyData();poly.SetPoints(pts);poly.SetLines(cells)
            mapper=vtk.vtkPolyDataMapper();mapper.SetInputData(poly)
            a=vtk.vtkActor();a.SetMapper(mapper);a.GetProperty().SetColor(np.array(ImageColor.getrgb(col))/255)
            a.GetProperty().SetLineWidth(3);ren.AddActor(a)
    camera=ren.GetActiveCamera();camera.SetPosition(430,480 if opened else -470,280)
    camera.SetFocalPoint(110,120 if opened else 65,80);camera.SetViewUp(0,0,1)
    camera.ParallelProjectionOn();ren.ResetCamera();camera.Zoom(1.10)
    win=vtk.vtkRenderWindow();win.SetOffScreenRendering(1);win.SetSize(1500,1100)
    win.SetMultiSamples(4);win.AddRenderer(ren);win.Render()
    capture=vtk.vtkWindowToImageFilter();capture.SetInput(win);capture.ReadFrontBufferOff();capture.Update()
    out=O/('rear_open.png' if opened else 'front.png')
    writer=vtk.vtkPNGWriter();writer.SetFileName(str(out));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
    win.Finalize();return out


if __name__=='__main__':
    a,b=render(),render(True)
    im=Image.new('RGB',(3000,1200),'white');im.paste(Image.open(a),(0,70));im.paste(Image.open(b),(1500,70))
    draw=ImageDraw.Draw(im);font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',32)
    draw.text((40,20),'Mac Desktop · 178 × 105 × 10 mm',fill='#33443b',font=font)
    draw.text((1540,20),'Cửa sau mở · buồng tối chồng trên Pi',fill='#33443b',font=font)
    draw.text((40,1150),'CAD tham khảo — chưa in thử / thử tải',fill='#555555',font=font)
    im.save(O/'preview.png')
