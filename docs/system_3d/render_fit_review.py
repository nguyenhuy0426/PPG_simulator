#!/usr/bin/env python3
"""Measured mechanical review from exported STL sections and the plate manifest."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Rectangle
import numpy as np
import trimesh

OUT = Path(__file__).resolve().parent / 'out'
INK, ACCENT, ROD = '#293847', '#b05f26', '#287d88'


def section(ax, mesh, axis, value, axes, offset=(0, 0), color=INK, width=1.2):
    normal, origin = np.zeros(3), np.zeros(3)
    normal[axis], origin[axis] = 1, value
    segments = trimesh.intersections.mesh_plane(mesh, normal, origin)
    projected = segments[:, :, axes] + np.array(offset)
    ax.add_collection(LineCollection(projected, colors=color, linewidths=width))


def dimension(ax, a, b, label, text_offset=(0, 0)):
    ax.annotate('', xy=a, xytext=b,
                arrowprops=dict(arrowstyle='<->', color=INK, lw=.8))
    mid = (np.array(a) + np.array(b))/2 + text_offset
    ax.text(*mid, label, ha='center', va='center', fontsize=9,
            bbox=dict(facecolor='white', edgecolor='none', pad=1))


def main():
    meshes = {p.stem: trimesh.load(p) for p in (OUT/'stl').glob('*.stl')}
    fig, axes = plt.subplots(2, 2, figsize=(16, 10), gridspec_kw={'height_ratios': [1, 1.1]})
    fig.patch.set_facecolor('#f4f6f7')
    for ax in axes.flat:
        ax.set_facecolor('white')
        ax.set_aspect('equal')
        ax.axis('off')
    ax = axes[0, 0]
    ax.set_title('01   Khẩu độ phẳng — không có tai lồi', loc='left', color=INK, weight='bold')
    for i, (kind, label) in enumerate([('blank', 'Bịt'), ('d2', 'Ø2'), ('d5', 'Ø5'), ('d16', 'Ø16')]):
        section(ax, meshes[f'aperture_red_{kind}'], 0, 114.2, [2, 1],
                (19.25 + 17.45 + i*44, -1.9))
        ax.text(17.45+i*44, -5, label, ha='center', color=INK)
    dimension(ax, (0, 69), (34.9, 69), '34.9 mm')
    ax.text(83, -17, 'Cao 62.9 mm · dày 1.6 mm · mỗi loại in 2 tấm', ha='center', color=INK)
    ax.set_xlim(-5, 176); ax.set_ylim(-22, 78)

    ax = axes[0, 1]
    ax.set_title('02   Mép khẩu độ vào rãnh âm của nắp', loc='left', color=INK, weight='bold')
    section(ax, meshes['lid'], 2, -19.25, [0, 1], color=INK, width=2)
    section(ax, meshes['aperture_red_blank'], 2, -19.25, [0, 1], color=ACCENT, width=2)
    # Background fills within the actual sectional outlines.
    ax.add_patch(Rectangle((109,65.1),10,1.9,color='#dae0e5',alpha=.5,zorder=0))
    ax.add_patch(Rectangle((113.4,62),1.6,2.8,color='#d99862',alpha=.35,zorder=0))
    dimension(ax, (113.1,63.1), (115.3,63.1), 'Rãnh 2.2 mm', (0,-.35))
    dimension(ax, (116.3,64.8), (116.3,65.1), '0.3 mm', (.8,0))
    dimension(ax, (111.0,65.1), (111.0,67), '1.9 mm', (-.7,0))
    ax.text(114.2,62.25,'Tấm khẩu độ',ha='center',color=ACCENT,fontsize=10)
    ax.text(114.2,67.65,'Mặt ngoài nắp phẳng',ha='center',color=INK)
    ax.text(114.2,61.25,'Ăn vào nắp 0.8 mm; khe mỗi mặt 0.3 mm',ha='center',color=INK,fontsize=10)
    ax.set_xlim(108.5,119.5); ax.set_ylim(60.8,68.6)

    ax = axes[1, 0]
    ax.set_title('03   Mặt cắt làn Đỏ — d = 25 mm', loc='left', color=INK, weight='bold')
    for name, color, width in [('body','#96a1ab',1), ('lid','#96a1ab',1),
                               ('frame','#667280',1.2), ('slide_shaft_red',INK,1.7),
                               ('led_carrier_red',ACCENT,1.5), ('push_rod_red',ROD,2),
                               ('rod_knob_red',ROD,1.4), ('aperture_red_d5',ACCENT,1.4)]:
        section(ax, meshes[name], 2, -19.25, [0,1], color=color, width=width)
    dimension(ax, (-43,-10), (87,-10), 'Trục tròn Ø5 × 130 mm')
    ax.annotate('Ray D Ø8', (40,14), (30,2), color=INK,
                arrowprops=dict(arrowstyle='-',color=INK), fontsize=10)
    ax.annotate('Trục đẩy Ø5', (20,26.5), (-15,44), color=ROD,
                arrowprops=dict(arrowstyle='-',color=ROD), fontsize=10)
    ax.annotate('Carrier LED', (85,39), (61,51), color=ACCENT,
                arrowprops=dict(arrowstyle='-',color=ACCENT), fontsize=10)
    ax.annotate('Rãnh âm', (114.2,65), (113,77), color=INK,
                arrowprops=dict(arrowstyle='-',color=INK), fontsize=10)
    ax.text(47,-24,'Lắp riêng trục đẩy và ray dẫn hướng · hai làn dùng cùng mẫu',ha='center',color=INK,fontsize=10)
    ax.set_xlim(-51,158); ax.set_ylim(-28,85)

    ax = axes[1, 1]
    ax.set_title('04   Hai bàn in — đủ 23 chi tiết', loc='left', color=INK, weight='bold')
    manifest = json.loads((OUT/'print_bambu'/'manifest.json').read_text())
    for n, plate in enumerate(manifest['plates']):
        xoff = n*278
        ax.add_patch(Rectangle((xoff,0),256,256,fill=False,edgecolor='#82909e',lw=1))
        for item in plate['instances']:
            lo,hi=np.array(item['bounds_mm'])
            prefix=item['instance'][:2]
            color=ROD if prefix=='12' else ('#d99862' if prefix in ['08','09','10','11'] else '#d4dce2')
            ax.add_patch(Rectangle((xoff+lo[0],lo[1]),hi[0]-lo[0],hi[1]-lo[1],
                                  facecolor=color,edgecolor=INK,lw=.7))
            if min(hi[:2]-lo[:2])>10:
                ax.text(xoff+(lo[0]+hi[0])/2,(lo[1]+hi[1])/2,prefix,ha='center',va='center',fontsize=8)
        ax.text(xoff+128,-22,f"Bàn {n+1} · {len(plate['instances'])} chi tiết",ha='center',color=INK,fontsize=10)
    ax.text(267,-48,'Mã số khớp tên STL · đơn vị mm · scale 100%',ha='center',color=INK,fontsize=10)
    ax.set_xlim(-10,544);ax.set_ylim(-55,270)
    fig.suptitle('PPG SIMULATOR  /  ĐỐI CHIẾU CƠ KHÍ V4',x=.05,ha='left',weight='bold',fontsize=20,color=INK)
    fig.text(.05,.018,'Hình lấy từ STL đã xuất. Khe hở CAD danh nghĩa; chưa đo co ngót, lực trượt hoặc rò sáng trên bản in.',color='#55616e',fontsize=10)
    fig.subplots_adjust(top=.90,bottom=.07,left=.045,right=.965,hspace=.23,wspace=.16)
    fig.savefig(OUT/'fit_review.png',dpi=160,facecolor=fig.get_facecolor())
    plt.close(fig)
    print(OUT/'fit_review.png')


if __name__ == '__main__':
    main()
