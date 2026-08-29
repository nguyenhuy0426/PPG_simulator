#!/usr/bin/env python3
"""Render preview PNGs of the assembled PPG dark chamber model.

Uses out/model.json (new format: .parts[].subs[] instead of top-level vbase64).
"""
import json, os, base64
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D, art3d

OUT_DIR = os.path.join(os.path.dirname(__file__), 'out')

with open(os.path.join(OUT_DIR, 'model.json')) as f:
    model = json.load(f)
parts = model['parts']

COLOR_MAP = {
    'body': '#2a3a4a',
    'lid': '#3b4656',
    'led_carrier_red': '#9c2626',
    'led_carrier_ir': '#2a3fad',
    'led_red': '#cc2222',
    'led_ir': '#8a5cf0',
    'opt101_red': '#1d1d24',
    'opt101_ir': '#1d1d24',
    'base_tray': '#4a5566',
    'wire_cover_red': '#2c3540',
    'wire_cover_ir': '#2c3540',
}
APERTURE_COLORS = {'red': '#6a8090', 'ir': '#6a8090'}

def decode_part(p):
    """Decode the first sub of a part (or all subs merged). Returns V, F."""
    subs = p.get('subs', [])
    all_v, all_f = [], []
    voff = 0
    for s in subs:
        v = np.frombuffer(base64.b64decode(s['vbase64']), dtype=np.float32).reshape(-1, 3)
        f = np.frombuffer(base64.b64decode(s['fbase64']), dtype=np.uint32).reshape(-1, 3)
        all_v.append(v)
        all_f.append(f + voff)
        voff += len(v)
    if not all_v:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.uint32)
    return np.concatenate(all_v, axis=0), np.concatenate(all_f, axis=0)

def get_part_color(name):
    if name in COLOR_MAP:
        return COLOR_MAP[name]
    if name.startswith('aperture_'):
        return '#6a8090'
    return '#666666'

def plot_mesh(ax, vertices, faces, color, alpha=0.85):
    if len(faces) == 0 or len(vertices) == 0:
        return
    poly = art3d.Poly3DCollection(vertices[faces], alpha=alpha, facecolor=color,
                                   edgecolor='none', linewidth=0.0)
    ax.add_collection3d(poly)
    return poly

def get_all_vertices():
    all_v = []
    for p in parts:
        v, _ = decode_part(p)
        all_v.append(v)
    return np.concatenate(all_v, axis=0)

def render_view(angles, prefix, title, filter_names=None):
    n = len(angles)
    fig = plt.figure(figsize=(6 * n, 6))
    all_v = get_all_vertices()
    centroid = all_v.mean(axis=0)
    extent = np.ptp(all_v, axis=0).max() / 2 + 18

    for idx, (elev, azim, roll) in enumerate(angles):
        ax = fig.add_subplot(1, n, idx + 1, projection='3d')
        ax.set_proj_type('ortho')
        for p in parts:
            name = p['name']
            if filter_names and name not in filter_names:
                continue
            v, f = decode_part(p)
            v = v + np.array(p.get('explode', [0, 0, 0]), dtype=np.float32)
            plot_mesh(ax, v, f, get_part_color(name))

        ax.view_init(elev=elev, azim=azim, roll=roll)
        ax.set_xlabel('X (mm)')
        ax.set_ylabel('Y (mm)')
        ax.set_zlabel('Z (mm)')
        ax.set_xlim(centroid[0] - extent, centroid[0] + extent)
        ax.set_ylim(centroid[1] - extent, centroid[1] + extent)
        ax.set_zlim(centroid[2] - extent, centroid[2] + extent)
        ax.set_box_aspect([1, 1, 1])
        ax.grid(True, alpha=0.2)
        sub_titles = ['Góc trước-phải', 'Góc trước-trái', 'Góc trên']
        ax.set_title(sub_titles[idx] if idx < len(sub_titles) else f'Góc {idx+1}',
                     fontsize=13, fontweight='bold')

    fig.suptitle(title, fontsize=16, fontweight='bold', y=1.02)
    plt.tight_layout()
    path = os.path.join(OUT_DIR, f'{prefix}.png')
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#f0f0f0', edgecolor='none')
    plt.close()
    print(f'  → {path}  ({os.path.getsize(path)//1024} KB)')

print("Rendering preview images...")
# 1. Assembled view
render_view([(20, -45, 0), (20, 45, 0), (30, 0, 0)], 'preview_assembled',
            'PPG Dark Chamber — Mô hình lắp ráp')

# 2. Exploded view (apply explode offsets)
# Directly use explode from each part
angles_exp = [(15, -35, 0), (15, 35, 0), (25, 0, 0)]
n = len(angles_exp)
fig = plt.figure(figsize=(6 * n, 6))
all_v = get_all_vertices()
centroid = all_v.mean(axis=0)
extent = np.ptp(all_v, axis=0).max() / 2 + 50  # more space

for idx, (elev, azim, roll) in enumerate(angles_exp):
    ax = fig.add_subplot(1, n, idx + 1, projection='3d')
    ax.set_proj_type('ortho')
    for p in parts:
        name = p['name']
        v, f = decode_part(p)
        expl = np.array(p['explode'], dtype=np.float32) * 2.5
        v = v + expl
        plot_mesh(ax, v, f, get_part_color(name))

    ax.view_init(elev=elev, azim=azim, roll=roll)
    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    ax.set_zlabel('Z (mm)')
    ax.set_xlim(centroid[0] - extent, centroid[0] + extent)
    ax.set_ylim(centroid[1] - extent, centroid[1] + extent)
    ax.set_zlim(centroid[2] - extent, centroid[2] + extent)
    ax.set_box_aspect([1, 1, 1])
    ax.grid(True, alpha=0.2)
    sub_titles = ['Góc trước-phải', 'Góc trước-trái', 'Góc trên']
    ax.set_title(sub_titles[idx] if idx < len(sub_titles) else f'Góc {idx+1}',
                 fontsize=13, fontweight='bold')

fig.suptitle('PPG Dark Chamber — Dạng tháo rời (exploded)', fontsize=16, fontweight='bold', y=1.02)
plt.tight_layout()
path = os.path.join(OUT_DIR, 'preview_exploded.png')
plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#f0f0f0')
plt.close()
print(f'  → {path}  ({os.path.getsize(path)//1024} KB)')

# 3. Cross-section view
print("Rendering cross-section view...")
fig = plt.figure(figsize=(12, 8))
ax = fig.add_subplot(111, projection='3d')
ax.set_proj_type('ortho')

for p in parts:
    name = p['name']
    v, f = decode_part(p)
    if name == 'body':
        plot_mesh(ax, v, f, '#2a3a4a', alpha=0.08)
    elif name in ('led_red', 'led_ir', 'opt101_red', 'opt101_ir',
                  'aperture_red_open', 'aperture_ir_open',
                  'led_carrier_red', 'led_carrier_ir'):
        plot_mesh(ax, v, f, get_part_color(name), alpha=0.95)
    elif name == 'base_tray':
        plot_mesh(ax, v, f, get_part_color(name), alpha=0.3)

ax.view_init(elev=10, azim=0, roll=0)
ax.set_xlabel('X (mm) — trục quang', fontsize=11)
ax.set_ylabel('Y (mm)', fontsize=11)
ax.set_zlabel('Z (mm)', fontsize=11)
ax.set_title('Mặt cắt dọc — 2 buồng Đỏ (trên) / IR (dưới), LED + OPT101 + khẩu độ',
             fontsize=13, fontweight='bold')

all_v = get_all_vertices()
centroid = all_v.mean(axis=0)
extent = np.ptp(all_v, axis=0).max() / 2 + 25
ax.set_xlim(centroid[0] - extent, centroid[0] + extent)
ax.set_ylim(centroid[1] - extent, centroid[1] + extent)
ax.set_zlim(centroid[2] - extent, centroid[2] + extent)
ax.set_box_aspect([1.5, 1, 1])
ax.grid(True, alpha=0.2)

for label, x, y, z, clr in [
    ('LED Đỏ (~25mm)', -28, 16, 5, '#cc2222'),
    ('LED IR (~85mm)', -12, 48, 5, '#8a5cf0'),
    ('OPT101 #2 (Đỏ)', 28, 16, 5, '#1d1d24'),
    ('OPT101 #1 (IR)', 28, 48, 5, '#1d1d24'),
]:
    ax.text(x, y, z, label, color=clr, fontsize=9, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.8))

path = os.path.join(OUT_DIR, 'preview_cross_section.png')
plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#f0f0f0')
plt.close()
print(f'  → {path}  ({os.path.getsize(path)//1024} KB)')

print("Done — 3 preview images regenerated.")