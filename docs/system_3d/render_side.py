"""360 deg preview renders of the side-by-side variants (assembly meshes; cables are preview graphics).

python render_side.py <variant> -> <variant>/render360/*.png, sheet_*.png, quay_360.gif
"""
import importlib.util,json,sys
from pathlib import Path
import numpy as np,trimesh,vtk
from PIL import Image,ImageColor,ImageDraw,ImageFont
from scipy.interpolate import CubicSpline

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('r',ROOT/'cyberdock_v3/render.py');R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
FONT=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',26)
SMALL=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',20)
COL=dict(optical_body='#4a5a6b',optical_lid='#2b343d',hood='#20262b',pi_housing='#2f8f63',tray='#3aa08a',screen='#10161a')
SHELL=('01_','02_','03_','04_','08_','09_','10_','11_','trim_')


def load(v):
    base=ROOT/v;ms={p.stem:trimesh.load_mesh(p) for p in (base/'out/assembly_meshes').glob('*.stl')}
    cfg={}
    if v.startswith('mac'):
        spec=importlib.util.spec_from_file_location('cad',base/'build.py');cad=importlib.util.module_from_spec(spec);spec.loader.exec_module(cad)
        ms['screen']=trimesh.load_mesh(base/'out/assembly_meshes/screen_ENVELOPE_ONLY.stl') if (base/'out/assembly_meshes/screen_ENVELOPE_ONLY.stl').exists() else __import__('build').b.to_mesh(cad.L2W(cad.box(21,199,.5,10.5,cad.SCR_Z0,cad.SCR_Z1)))
        cfg=dict(L=cad.L4(),pi=cad.PI_C,ch=cad.CH_C,mac=True,D=cad.D)
    else:
        spec=importlib.util.spec_from_file_location('cad',base/'build.py');cad=importlib.util.module_from_spec(spec);spec.loader.exec_module(cad)
        ms['screen']=cad.b.to_mesh(cad.box(26,204,.5,20.5,12.5,117.5))
        cfg=dict(pi=cad.PI_C,ch=cad.CH_C,mac=False)
    return ms,cfg


def routes(v,ms,cfg):
    """Preview cables. Pi port window faces the right wall (-X). Screen plugs sit on the screen's right edge,
    the power lead leaves straight through the right-wall slot."""
    pi=ms['pi_housing'];fy=pi.bounds[1,1];xc=(pi.bounds[0,0]+pi.bounds[1,0])/2;zb=pi.bounds[0,2]
    zh=zb+54.;zu=zb+46.
    if cfg['mac']:
        L=cfg['L'];P=lambda x,y,z:tuple((L@np.array([x,y,z,1.]))[:3])
        s_usb=P(51,13,48);s_hdmi=P(51,13,72)
    else:
        s_usb=(48,24,48);s_hdmi=(48,24,72)
    hd=[s_hdmi,(s_hdmi[0]+14,s_hdmi[1]+4,s_hdmi[2]-6),(xc-8,fy-60,zh+20),(xc-8,fy+14,zh+10),(xc-2,fy+14,zh),(xc,fy-3,zh)]
    usb=[s_usb,(s_usb[0]+18,s_usb[1]+6,s_usb[2]),(xc-16,fy-60,zu+14),(xc-16,fy+12,zu+8),(xc-12,fy+12,zu),(xc-10,fy-3,zu)]
    fy0=pi.bounds[0,1];pw=[(xc,fy0+3,zb+30),(xc-4,fy0-10,zb+30),(xc-35,fy0-14,zb+29),(30,fy0-8,zb+29),(22,fy0+30,zb+28),(14,fy0+66,zb+28),(2,fy0+67,zb+28),(-60,fy0+67,zb+28)]
    return [('HDMI',hd,'#e8c020',1.6),('USB màn hình',usb,'#e8e8e8',1.6),('Nguồn USB-C',pw,'#e2552d',2.1)]


def tube(pts,r,color):
    p=np.array(pts,float);t=np.r_[0,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))]
    q=np.linspace(0,t[-1],120);line=CubicSpline(t,p,bc_type='natural')(q)
    vp=vtk.vtkPoints();[vp.InsertNextPoint(*x) for x in line]
    pl=vtk.vtkPolyLine();pl.GetPointIds().SetNumberOfIds(len(line));[pl.GetPointIds().SetId(i,i) for i in range(len(line))]
    ca=vtk.vtkCellArray();ca.InsertNextCell(pl);pd=vtk.vtkPolyData();pd.SetPoints(vp);pd.SetLines(ca)
    f=vtk.vtkTubeFilter();f.SetInputData(pd);f.SetRadius(r);f.SetNumberOfSides(12);f.CappingOn()
    m=vtk.vtkPolyDataMapper();m.SetInputConnection(f.GetOutputPort());a=vtk.vtkActor();a.SetMapper(m)
    a.GetProperty().SetColor(np.array(ImageColor.getrgb(color))/255);return a


def color(n,cfg_colors):
    if n.startswith('hood'):return COL['hood']
    if n in COL:return COL[n]
    if n=='screen':return COL['screen']
    if n.startswith('07_'):return COL['tray']
    return cfg_colors.get(n,'#d9cbb0')


def scene(v,ms,cfg,mode):
    ren=vtk.vtkRenderer();ren.SetBackground(1,1,1)
    cols={}
    try:cols=json.loads((ROOT/v/'out/manifest.json').read_text()).get('colors',{})
    except Exception:pass
    for n,m in ms.items():
        if n.startswith(('05_','06_')) and mode!='solid':continue
        if mode=='plan' and n.startswith(('01_','02_','03_','04_')):pass
        a=R.actor(m,color(n,cols))
        if mode!='solid' and (n.startswith(SHELL) or n.startswith(('09_','10_','spacer','gear','knob','clip_'))):
            a.GetProperty().SetOpacity(.16)
        ren.AddActor(a)
    if mode!='solid':
        for name,pts,col,r in routes(v,ms,cfg):ren.AddActor(tube(pts,r,col))
    return ren


def shot(ren,center,dist,az,el,size=(1000,760),ortho_top=False,scale=None):
    cam=ren.GetActiveCamera();a=np.radians(az);e=np.radians(el)
    pos=center+dist*np.array([np.sin(a)*np.cos(e),-np.cos(a)*np.cos(e),np.sin(e)])
    cam.SetPosition(*pos);cam.SetFocalPoint(*center);cam.SetViewUp(0,0,1) if not ortho_top else cam.SetViewUp(0,1,0)
    cam.SetViewAngle(24);ren.ResetCameraClippingRange()
    win=vtk.vtkRenderWindow();win.SetOffScreenRendering(1);win.SetSize(*size);win.SetMultiSamples(4);win.AddRenderer(ren);win.Render()
    cap=vtk.vtkWindowToImageFilter();cap.SetInput(win);cap.ReadFrontBufferOff();cap.Update()
    w=vtk.vtkPNGWriter();w.SetFileName('/tmp/_f.png');w.SetInputConnection(cap.GetOutputPort());w.Write();win.Finalize()
    return Image.open('/tmp/_f.png').convert('RGB')


NAMES={0:'Trước',45:'Trước-phải',90:'Bên phải',135:'Sau-phải',180:'Sau',225:'Sau-trái',270:'Bên trái',315:'Trước-trái'}


def main(v):
    ms,cfg=load(v);out=ROOT/v/'render360';out.mkdir(exist_ok=True)
    for p in out.glob('*'):p.unlink()
    allb=np.array([m.bounds for m in ms.values()]);c=(allb[:,0].min(0)+allb[:,1].max(0))/2
    diag=np.linalg.norm(allb[:,1].max(0)-allb[:,0].min(0));dist=diag*2.0
    res={}
    for mode in ('solid','ghost'):
        ren=scene(v,ms,cfg,mode);ims=[]
        for az in range(0,360,45):
            im=shot(ren,c,dist,az,22);d=ImageDraw.Draw(im);d.text((14,10),f'{NAMES[az]} ({az}°)',fill='#222',font=FONT)
            im.save(out/f'{mode}_{az:03d}.png');ims.append(im)
        top=shot(ren,c,dist,0,89.5,ortho_top=True);ImageDraw.Draw(top).text((14,10),'Nhìn từ trên xuống',fill='#222',font=FONT);top.save(out/f'{mode}_top.png')
        bot=shot(ren,c,dist,0,-89.5);ImageDraw.Draw(bot).text((14,10),'Nhìn từ dưới lên',fill='#222',font=FONT);bot.save(out/f'{mode}_bottom.png')
        ims+=[top,bot]
        sheet=Image.new('RGB',(5*1000,2*760+90),'white');d=ImageDraw.Draw(sheet)
        title={'solid':'vỏ nguyên (cửa sau đóng) — 8 hướng + trên + dưới','ghost':'vỏ trong mờ: buồng tối + hộp Pi nằm cạnh nhau, đường cáp (đồ họa minh hoạ)'}[mode]
        d.text((20,20),f'{v} — {title}',fill='#111',font=FONT)
        for i,im in enumerate(ims):sheet.paste(im,((i%5)*1000,90+(i//5)*760))
        sheet.save(out/f'sheet_{mode}.png');res[mode]=ims
    gif=[]
    ren=scene(v,ms,cfg,'ghost')
    for az in range(0,360,10):gif.append(shot(ren,c,dist,az,22,size=(640,480)).convert('P',palette=Image.ADAPTIVE))
    gif[0].save(out/'quay_360_vo_trong_mo.gif',save_all=True,append_images=gif[1:],duration=100,loop=0)
    print(v,'done',len(list(out.iterdir())),'files')


if __name__=='__main__':main(sys.argv[1])
