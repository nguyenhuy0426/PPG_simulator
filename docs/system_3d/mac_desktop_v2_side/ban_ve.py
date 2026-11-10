"""Dimension sheet for Mac V2 side variant (Modern-Mac silhouette), numbers from build.py and the assembly meshes.

python ban_ve.py -> BAN_VE_KICH_THUOC.png
"""
import importlib.util
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon, Circle
import trimesh

P = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('c', P / 'build.py'); c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
bb = {p.stem: trimesh.load_mesh(p).bounds for p in (P / 'out/assembly_meshes').glob('*.stl')}
W, D, H, WL, YS, ZL, HL = c.W_OUT, c.D, c.H_TOP, c.WALL, c.Y_STEP, c.Z_LID, c.H_LOW
RED, ORA = '#c0392b', '#e67e22'


def rect(ax, x0, y0, x1, y1, **kw):
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, **kw))


def dim(ax, p0, p1, txt, off=(0, 0), fs=8):
    ax.annotate('', p0, p1, arrowprops=dict(arrowstyle='<->', color=RED, lw=.8))
    ax.text((p0[0] + p1[0]) / 2 + off[0], (p0[1] + p1[1]) / 2 + off[1], txt, color=RED, fontsize=fs,
            ha='center', va='center', bbox=dict(fc='white', ec='none', pad=.5))


def holes(ax, pts):
    for a, b in pts:
        ax.add_patch(Circle((a, b), 2.25, fc='white', ec='k'))


fig, axs = plt.subplots(2, 3, figsize=(22, 13))
# 1. plan
ax = axs[0, 0]; ax.set_title('1. MAT BANG (tu tren) - tuong phai o TRAI hinh, man hinh o duoi', fontsize=10)
rect(ax, 0, 0, W, D, fc='none', ec='k', lw=1.5); rect(ax, 0, -50, W, 0, fc='#eee', ec='k')
rect(ax, 0, 0, W, YS, fc='#d9cbb0', ec='k', alpha=.6); ax.text(W / 2, 22, 'PHAN MAN HINH cao 170', ha='center', fontsize=8)
for n, col in (('pi_housing', '#2f8f63'), ('optical_body', '#4a5a6b')):
    b = bb[n]; rect(ax, b[0][0], b[0][1], b[1][0], b[1][1], fc=col, alpha=.45, ec='k')
ax.text(105, 97, 'HOP Pi\n104 x 124', ha='center', fontsize=9); ax.text(222.5, 97, 'BUONG TOI\n103 x 154', ha='center', fontsize=9, color='w')
rect(ax, 0, c.SD_Y[0], WL, c.SD_Y[1], fc=ORA, ec=ORA); rect(ax, 0, D - WL, W, D, fc=ORA, ec=ORA)
for y in (50.2, 194.2): ax.plot([16.5, W - 16.5], [y, y], color='#888', ls='--', lw=1)   # roof-panel ribs
holes(ax, c.RF_BOLTS)
dim(ax, (0, D + 14), (W, D + 14), 'RONG 280'); dim(ax, (-14, 0), (-14, D), 'than 205', off=(0, 60)); dim(ax, (-30, -50), (-30, D), 'tong 255', off=(0, -20))
dim(ax, (W + 12, 0), (W + 12, YS), f'{YS:.0f}', off=(8, 0))
dim(ax, (2, 110), (52.9, 110), '50.9'); dim(ax, (157.1, 120), (171, 120), '13.9', off=(0, 6))
ax.text(-6, (c.SD_Y[0] + c.SD_Y[1]) / 2, 'cua hong', color=ORA, fontsize=7, ha='right')
ax.text(W / 2, 182, 'gan duoi NAP_NGANG (sau)', fontsize=7, ha='center', color='#666'); ax.text(W / 2, 60, 'gan duoi NAP_NGANG (truoc)', fontsize=7, ha='center', color='#666')
ax.set_xlim(-60, 320); ax.set_ylim(-60, 235); ax.set_aspect('equal'); ax.axis('off')

# 2. side profile
ax = axs[0, 1]; ax.set_title('2. MAT BEN (nhin tu tuong phai) - truoc o TRAI', fontsize=10)
T = math.tan(math.radians(10)); yb = -9 - 140 * T
ax.add_patch(Polygon([(-50, 0), (-50, 30), (yb, 30), (-9, H), (YS, H), (YS, HL), (D, HL), (D, 0)], fc='#f4efe4', ec='k', lw=1.5))
ax.add_patch(Polygon([(yb, 30), (-9, H), (-9 + 4 / math.cos(math.radians(10)), H), (yb + 4 / math.cos(math.radians(10)), 30)], fc='#d9cbb0', ec='k'))
b = bb['pi_housing']; rect(ax, b[0][1], b[0][2], b[1][1], b[1][2], fc='#2f8f63', alpha=.45, ec='k')
rect(ax, c.SD_Y[0], WL, c.SD_Y[1], ZL, fc='none', ec=ORA, lw=2); rect(ax, 72.5, 20, 132.5, 45, fc=RED, alpha=.6)
holes(ax, c.SD_BOLTS)
dim(ax, (-62, 0), (-62, H), 'CAO 170', off=(-12, 0)); dim(ax, (D + 12, 0), (D + 12, HL), f'than thap {HL:.0f}', off=(14, 0))
dim(ax, (-50, -10), (0, -10), 'de 50'); dim(ax, (0, -22), (D, -22), 'than 205'); dim(ax, (0, H + 8), (YS, H + 8), f'{YS:.0f}')
dim(ax, (170, b[1][2]), (170, ZL), f'{ZL - b[1][2]:.0f} tren Pi', off=(16, 0), fs=7)
dim(ax, (c.SD_Y[0], ZL + 8), (c.SD_Y[1], ZL + 8), f'cua hong {c.SD_Y[1] - c.SD_Y[0] - .8:.1f} x {ZL - WL - .8:.1f}', fs=7)
ax.text(102, 32, 'khe nguon 60x25\nday cach san 20', fontsize=6, ha='center', color='w')
ax.set_xlim(-90, 250); ax.set_ylim(-35, 190); ax.set_aspect('equal'); ax.axis('off')

# 3. rear view with the three rear panels
ax = axs[0, 2]; ax.set_title('3. MAT SAU - 3 tam (TREN dung, NGANG nam, DUOI dung)', fontsize=10)
rect(ax, 0, 0, W, H, fc='none', ec='#bbb', ls=':')
rect(ax, WL + .4, HL + .4, W - WL - .4, H - WL - .4, fc='#e8dcc4', ec=ORA, lw=1.5); ax.text(W / 2, 130, 'CUA_SAU_TREN = nap chu L (mat sau + mai man hinh)', ha='center', fontsize=8)
rect(ax, 0, ZL, W, HL, fc='#7a6f5c', ec='k'); ax.text(W / 2, HL + 3, 'NAP_NGANG 280 x 161.6 x 2 (nhin canh)', ha='center', fontsize=7, va='bottom')
rect(ax, WL + .4, WL + .4, W - WL - .4, ZL - .4, fc='#f4efe4', ec=ORA, lw=1.5); ax.text(W / 2, 50, 'CUA_SAU_DUOI 275.2 x 85.2 x 2', ha='center', fontsize=8)
rect(ax, 0, 0, WL, H, fc='#ccc'); rect(ax, W - WL, 0, W, H, fc='#ccc')
holes(ax, c.RT_BOLTS); holes(ax, c.RL_BOLTS)
for x, z in c.RT_BOLTS[:2] + c.RL_BOLTS:
    ax.text(x + 4, z + 3, f'({x:.0f},{z:.0f})', fontsize=6)
dim(ax, (-10, 0), (-10, HL), f'{HL:.0f}', off=(-8, 0)); dim(ax, (-10, HL), (-10, H), f'{H - HL:.0f}', off=(-8, 0))
ax.set_xlim(-30, 300); ax.set_ylim(-15, 185); ax.set_aspect('equal'); ax.axis('off')

# 4. side door
ax = axs[1, 0]; ax.set_title('4. CUA_HONG.stl (nhin tu ngoai, truoc o TRAI)', fontsize=10)
y0, y1, z0, z1 = c.SD_Y[0] + .4, c.SD_Y[1] - .4, WL + .4, ZL - .4
rect(ax, y0, z0, y1, z1, fc='#f4efe4', ec=ORA, lw=1.5); rect(ax, 72.5, 20, 132.5, 45, fc='white', ec=RED, lw=1.5)
for y in (60.5, 136.5):
    for z in (25, 37): rect(ax, y, z, y + 8, z + 3, fc='white', ec='k', lw=.6)
holes(ax, c.SD_BOLTS)
dim(ax, (y0, -6), (y1, -6), f'{y1 - y0:.1f}'); dim(ax, (y0 - 8, z0), (y0 - 8, z1), f'{z1 - z0:.1f}', off=(-8, 0))
dim(ax, (72.5, 52), (132.5, 52), 'khe nguon 60'); dim(ax, (140, 20), (140, 45), '25', off=(6, 0)); dim(ax, (102.5, 0), (102.5, 20), 'cach san 20', off=(18, 0), fs=7)
dim(ax, (y0, 76), (10, 76), f'{10 - y0:.1f}', fs=7); dim(ax, (14, 2), (14, 12), '10', fs=7, off=(5, 0))
rect(ax, 43.6, 76, 55, z1, fc='#d9cbb0', ec='k', lw=.6); ax.text(49, 70, 'khoi bat\nNAP_NGANG', fontsize=6, ha='center', va='top')
ax.text(122, 65, '4 lo M4 D4.5, bulong M4x16 + dai oc AF 7.4', ha='center', fontsize=8)
ax.text(96, 56, 'Pi rut ngang ra qua cua nay', ha='center', fontsize=8, color=RED)
ax.set_xlim(-12, 200); ax.set_ylim(-15, 95); ax.set_aspect('equal'); ax.axis('off')

# 5. roof panel
ax = axs[1, 1]; ax.set_title('5. NAP_NGANG.stl (nhin tu tren, truoc o duoi)', fontsize=10)
rect(ax, 0, YS + .4, W, D, fc='#e8dcc4', ec=ORA, lw=1.5); rect(ax, WL + .4, c.FB_Y[0] + .4, W - WL - .4, YS + .4, fc='#e8dcc4', ec=ORA, lw=1.5)
holes(ax, c.RF_BOLTS)
dim(ax, (0, D + 8), (W, D + 8), '280'); dim(ax, (-10, c.FB_Y[0] + .4), (-10, D), f'{D - c.FB_Y[0] - .4:.1f}', off=(-10, 0))
for x, y in c.RF_BOLTS: ax.text(x + 4, y + 3, f'({x:.0f},{y:.0f})', fontsize=6)
ax.text(W / 2, 120, 'day 2 mm, 2 gan 2.4 x 7 o mat duoi; 4 bulong M4x16\nxuong 3 khoi goc + 1 khoi tren CUA_HONG, dai oc AF 7.4 day vao tu duoi qua ranh luc giac', ha='center', fontsize=8)
ax.set_xlim(-30, 300); ax.set_ylim(30, 225); ax.set_aspect('equal'); ax.axis('off')

# 6. summary
ax = axs[1, 2]; ax.axis('off'); ax.set_title('6. TOM TAT', fontsize=10)
txt = ('Vo ngoai 280 x 255 x 170 (rong x sau x cao), than thap phia sau cao 90\n'
       'Phan man hinh: sau 47 tu mat Y=0, cao 170, tam man nghieng 10 do day 4\n'
       'Vach / san / mai / cac tam cua: day 2 mm, khe lap 0.4 mm quanh mep\n'
       'Hop Pi va buong toi dat len gio san 10 mm (san khoet dai 20 mm, khong tru)\n'
       '4 tam cua: mat ngoai kin (da 0.6), tui khoet 22 mm o mat trong; thong gio: vach trai, de truoc, san, 10 khe tren NAP_NGANG (tren Pi)\n'
       'Khoang trong tren Pi: 16 mm (mai trong o z 88), tren buong toi ~20 mm\n'
       'Khong con thanh ngang: 4 khoi goc + 1 khoi tren CUA_HONG (z 76-88), mai man hinh lien CUA_SAU_TREN\n\n'
       'Bulong M4 x 16, tong 15 con + 15 dai oc M4:\n'
       '  CUA_HONG 4, CUA_SAU_DUOI 3, NAP_NGANG 4, CUA_SAU_TREN 4\n'
       '  (+ 4 bulong M4x16 + 4 dai oc cho 4 kep man hinh)\n'
       'Lo D4.5, tui dai oc luc giac AF 7.4 sau 3.7 o dau trong cua tru\n\n'
       'Lap: Pi ha tu tren (thao NAP_NGANG) hoac rut ngang qua CUA_HONG 184x85;\n'
       '     buong toi truot vao tu sau (thao CUA_SAU_DUOI).\n'
       'Kiem tra CAD: khong chi tiet nao de nhau; 15 truc bulong thong,\n'
       'khong cham Pi/buong toi. CHUA in thu.')
ax.text(0, 1, txt, va='top', fontsize=10, family='monospace')
fig.suptitle('Mac Desktop V2 - kieu Modern Mac, kich thuoc tu CAD (mm)', fontsize=14)
fig.tight_layout(); fig.savefig(P / 'BAN_VE_KICH_THUOC.png', dpi=100); print('ok')
