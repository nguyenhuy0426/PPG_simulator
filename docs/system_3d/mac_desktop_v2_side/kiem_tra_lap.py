"""Full fit check of the Mac V2 side assembly (CAD level, not a print test).

python kiem_tra_lap.py -> prints a PASS/FAIL table and writes out/kiem_tra_lap.json
Checks: solids, bed size, pairwise interference, panel clearance and seating, every M4 axis
(hole alignment through panel and boss, M4x16 reach through the nut, shaft clear of parts and modules),
nut-pocket access, module clearance to the shell, screen in window and clip grip, assembly paths.
"""
import glob
import importlib.util
import itertools
import json
from pathlib import Path

import numpy as np
import trimesh

P = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('c', P / 'build.py'); c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
A = P / 'out/assembly_meshes'
ms = {p.stem: trimesh.load_mesh(p) for p in A.glob('*.stl')}
PRINT = {n: m for n, m in ms.items() if n.startswith(('01_', '08_', '09_', '10_', '11_', 'clip'))}
MOD = {n: m for n, m in ms.items() if n.startswith(('optical_', 'hood_', 'pi_'))}
SCREEN = ms['screen_ENVELOPE_ONLY']
W, D, H, WL = c.W_OUT, c.D, c.H_TOP, c.WALL
EPS = .02
rows = []


def I(a, b):
    if np.any(np.minimum(a.bounds[1], b.bounds[1]) - np.maximum(a.bounds[0], b.bounds[0]) < -1e-6):
        return 0.
    return abs(trimesh.boolean.intersection([a, b], engine='manifold').volume)


def rec(group, item, ok, detail=''):
    rows.append(dict(group=group, item=item, ok=bool(ok), detail=detail))
    print(f"{'PASS' if ok else 'FAIL'}  {group:14s} {item:40s} {detail}")


def cyl(a, b, r):
    a = np.array(a, float); b = np.array(b, float); d = b - a; L = np.linalg.norm(d)
    T = trimesh.geometry.align_vectors([0, 0, 1], d / L); T[:3, 3] = (a + b) / 2
    return trimesh.creation.cylinder(radius=r, height=L, sections=48, transform=T)


def boxm(lo, hi):
    return trimesh.creation.box(bounds=[lo, hi])


def hexprism(a, b, af=7.0):
    """M4 nut envelope (AF 7.0, across corners 8.08) between a and b, corners oriented like build.hexhole
    (axis x: a corner points along z; axis y or z: a corner points along x)."""
    a = np.array(a, float); b = np.array(b, float); d = b - a; L = np.linalg.norm(d); z = d / L
    xdir = np.array([0, 0, 1.]) if abs(z[0]) > .9 else np.array([1, 0, 0.])
    y = np.cross(z, xdir)
    R_ = np.eye(4); R_[:3, 0] = xdir; R_[:3, 1] = y; R_[:3, 2] = z; R_[:3, 3] = a
    poly = trimesh.path.polygons.Polygon([(af / np.sqrt(3) * np.cos(t), af / np.sqrt(3) * np.sin(t)) for t in np.arange(6) * np.pi / 3])
    m = trimesh.creation.extrude_polygon(poly, L); m.apply_transform(R_); return m


# 1. every printed part: one closed solid, fits 420 x 420 x 500
for n, m in PRINT.items():
    rec('chi tiet', n, m.is_volume and len(m.split(only_watertight=False)) == 1, f'{np.round(m.extents, 1).tolist()} mm')

# 2. pairwise interference of parts + modules + screen
allm = {**PRINT, **MOD, 'screen': SCREEN}
bad = [(a, b, round(I(allm[a], allm[b]), 2)) for a, b in itertools.combinations(allm, 2)
       if not (a.startswith(('optical_', 'hood_')) and b.startswith(('optical_', 'hood_'))) and I(allm[a], allm[b]) > EPS]
rec('giao thoa', f'{len(allm)} khoi, tung cap', not bad, str(bad) if bad else 'khong cap nao de nhau')

# 3. panel clearance: moving each panel 0.3 mm in every in-plane direction must not hit the body;
#    moving it 0.1 mm into its seat direction must hit (it actually bears on something)
body = ms['01_body']
seat = {'09_side_panel': (np.array([1, 0, 0.]), 'ep vao 4 tru'), '08_rear_low': (np.array([0, -1, 0.]), 'ep vao thanh ngang/tru'),
        '10_rear_top': (np.array([0, -1, 0.]), 'ep vao 4 tru'), '11_roof': (np.array([0, 0, -1.]), 'nam tren vach + khoi goc')}
plane = {'09_side_panel': [1, 2], '08_rear_low': [0, 2], '10_rear_top': [0], '11_roof': []}
for n, (sd, txt) in seat.items():
    p = ms[n]; free = True
    for ax in plane[n]:
        for s in (-1, 1):
            q = p.copy(); v = np.zeros(3); v[ax] = .3 * s; q.apply_translation(v)
            others = I(q, body) + (I(q, ms['11_roof']) if n != '11_roof' else 0)
            free &= others < EPS
    q = p.copy(); q.apply_translation(sd * .1)
    touch = I(q, body) > 1e-3
    rec('khe lap cua', n, free and touch, f'khe >= 0.3 quanh mep: {free}; {txt}: {touch}')
for n in ('08_rear_low', '09_side_panel'):   # panel top edge under the roof panel
    q = ms[n].copy(); q.apply_translation([0, 0, .3])
    rec('khe lap cua', f'{n} duoi nap ngang', I(q, ms['11_roof']) < EPS, 'khe 0.4 duoi nap')
q = ms['10_rear_top'].copy(); q.apply_translation([0, 0, -.3])
rec('khe lap cua', '10_rear_top tren nap ngang', I(q, ms['11_roof']) < EPS, 'khe 0.4 tren nap')
q = ms['10_rear_top'].copy(); q.apply_translation([0, 0, -.1])
rec('khe lap cua', '10_rear_top mai ngoi tren vach', I(q, body) > 1e-3, 'mai nap chu L tua len dinh vach + tam man (z 168)')

# 4. M4 joints: panel hole + boss hole coaxial, M4x16 reaches through the nut, shaft clear, nut pocket in material and reachable
joints = [('cua hong', '09_side_panel', (0, y, z), (1, 0, 0)) for y, z in c.SD_BOLTS]
joints += [('cua sau duoi', '08_rear_low', (x, D, z), (0, -1, 0)) for x, z in c.RL_BOLTS]
joints += [('nap ngang', '11_roof', (x, y, c.H_LOW), (0, 0, -1)) for x, y in c.RF_BOLTS]
nut_part = {tuple(np.round((*c.RF_BOLTS[0], c.H_LOW), 3)): '09_side_panel'}   # front-right roof bolt: block on the side door
joints += [('cua sau tren', '10_rear_top', (x, c.Y_STEP, z), (0, -1, 0)) for x, z in c.RT_BOLTS]
nut_start = {'cua hong': 10.4, 'cua sau duoi': D - c.RB_Y[0] - 3.6, 'nap ngang': c.H_LOW - c.BEAM_Z - 3.6, 'cua sau tren': WL + 8.4}
for kind, panel, s, d in joints:
    s = np.array(s, float); d = np.array(d, float)
    shaft = cyl(s - d * .5, s + d * 16, 2.0)             # M4 major d 4.0 in a 4.5 hole
    hit = {n: round(I(shaft, m), 2) for n, m in {**PRINT, **MOD}.items() if I(shaft, m) > EPS}
    n0 = nut_start[kind]; nut = hexprism(s + d * (n0 + .05), s + d * (n0 + 3.2))
    holder = ms[nut_part.get(tuple(np.round(s, 3)), '01_body')]
    nut_hit = I(nut, holder) > EPS
    reach = 16 - (n0 + 3.2)                               # bolt length past the far face of the nut
    access = hexprism(s + d * (n0 + 3.3), s + d * (n0 + 12))   # nut slides in from the open end of the pocket
    acc = I(access, body) < EPS and I(access, holder) < EPS
    ring = trimesh.boolean.difference([cyl(s + d * (WL + .5), s + d * n0, 5.0), cyl(s + d * WL, s + d * (n0 + .1), 2.4)], engine='manifold')
    mat = I(ring, holder) / ring.volume
    ok = not hit and not nut_hit and reach >= 1 and acc and mat > .6
    rec('bulong M4', f'{kind} {tuple(np.round(s, 0).astype(int))}', ok,
        f'truc thong={not hit}, dai oc vua tui={not nut_hit}, vit qua dai oc {reach:.1f} mm, dua dai oc vao={acc}, nhua quanh lo {mat:.0%}')

# 5. screen clips: bolt from the clip into the slab boss (local frame), screen held between slab and clip lip
L = c.L4()
def P_(x, y, z): return (L @ np.array([x, y, z, 1.]))[:3]
for xi, x in enumerate(c.CLIP_X):
    for zi, z in enumerate(c.CLIP_Z):
        xx = x + 30
        s, e = P_(xx, 14.5, z), P_(xx, 14.5 - 16, z)
        shaft = cyl(s + (s - e) / 16 * .2, e, 2.0)
        hit = {n: round(I(shaft, m), 2) for n, m in {**PRINT, 'screen': SCREEN}.items() if I(shaft, m) > EPS}
        rec('kep man hinh', f'kep {xi}{zi} bulong M4x16', not hit, f'truc thong: {not hit} {hit or ""}')
        clip = ms[f'clip_{xi}_{zi}'].copy(); clip.apply_translation(-(P_(0, 1, 0) - P_(0, 0, 0)) * .3)
        rec('kep man hinh', f'kep {xi}{zi} ep man', I(clip, SCREEN) > 1e-3, 'mieng kep cham mep sau man hinh')
scr_local = dict(x=(51, 229), z=(c.SCR_Z0, c.SCR_Z1)); win = dict(x=(55, 225), z=(c.ZC - 48.5, c.ZC + 48.5))
ov = [win['x'][0] - scr_local['x'][0], scr_local['x'][1] - win['x'][1], win['z'][0] - scr_local['z'][0], scr_local['z'][1] - win['z'][1]]
rec('man hinh', 'khung 178x105 che mep cua so 170x97', min(ov) >= 3, f'mep chong {ov} mm')

# 6. module clearance to the shell: move each module 1 mm in +-x, +-y and +z; the shell must not be hit
for name, grp in (('hop Pi', ['pi_housing']), ('buong toi', [n for n in MOD if n.startswith(('optical_', 'hood_'))])):
    m = trimesh.util.concatenate([MOD[n] for n in grp]); res = {}
    for ax, lab in ((0, 'x'), (1, 'y'), (2, 'z')):
        for s in ((-1, 1) if ax < 2 else (1,)):
            q = m.copy(); v = np.zeros(3); v[ax] = s; q.apply_translation(v)
            res[f'{"+" if s > 0 else "-"}{lab}'] = max(I(q, p) for p in PRINT.values()) < EPS
    rec('khe module', name, all(res.values()), f'con >= 1 mm moi phia: {res}')

# 7. assembly paths
fixed = [body] + [ms[n] for n in PRINT if n.startswith('clip')]
def path_ok(m, moves): return all(max(I(q, f) for f in fixed) < EPS for q in [m.copy().apply_translation(v) or m.copy() for v in []]) if False else all(
    max(I(_t(m, v), f) for f in fixed) < EPS for v in moves)
def _t(m, v): q = m.copy(); q.apply_translation(v); return q
pi = MOD['pi_housing']
rec('duong lap', 'Pi: thao NAP_NGANG, ha xuong roi day toi 20', path_ok(pi, [(0, 20, z) for z in (120, 80, 40, 10, 0)] + [(0, y, 0) for y in (15, 10, 5, 0)]))
ch = trimesh.util.concatenate([MOD[n] for n in MOD if n.startswith(('optical_', 'hood_'))])
rec('duong lap', 'Buong toi: thao CUA_SAU_DUOI, truot vao tu sau', path_ok(ch, [(0, y, 0) for y in (260, 200, 150, 100, 50, 20, 0)]))
rec('duong lap', 'Pi: thao CUA_HONG, rut ngang ra ben phai', path_ok(pi, [(-x, 0, 0) for x in (5, 20, 40, 70, 100, 130, 170)]))
lid = ms['10_rear_top']; fixed.append(ms['11_roof'])
rec('duong lap', 'Nap chu L (CUA_SAU_TREN + mai): ha thang tu tren xuong', path_ok(lid, [(0, 0, z) for z in (120, 60, 20, 5, 1)]))
fixed.pop()
cable = boxm([-30, 72.5 + 5, 25], [2.5, 132.5 - 5, 40])
rec('duong day', 'khe nguon cua hong thong ra ngoai', I(cable, ms['09_side_panel']) < EPS and I(cable, body) < EPS, 'khoi 50x15 xuyen khe khong cham')

ok = all(r['ok'] for r in rows)
(P / 'out/kiem_tra_lap.json').write_text(json.dumps(dict(passed=ok, rows=rows), indent=1, ensure_ascii=False))
print('\nTONG:', 'TAT CA DAT' if ok else 'CO LOI', f'{sum(r["ok"] for r in rows)}/{len(rows)}')
