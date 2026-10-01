#!/usr/bin/env python3
"""Build one electrically isolated, zero-gap, three-design V-score panel.

Run using KiCad 10's Python. Edit the three source projects, then regenerate;
the panel is a fabrication artifact, not a fourth electrical schematic.
"""
import hashlib
import json
import shutil
from pathlib import Path

import pcbnew as p

HERE = Path(__file__).resolve().parent
HARDWARE = HERE.parent
SOURCES = [
    ('OPT', HARDWARE/'opt101_receiver_kicad/opt101_receiver', 'opt101_receiver', 30),
    ('BPW', HARDWARE/'bpw34_receiver', 'bpw34_receiver', 30),
    ('TX', HARDWARE/'led_ir_driver', 'led_ir_driver', 50),
]
NAME = 'ppg_panel'
def v(x,y): return p.VECTOR2I(p.FromMM(x), p.FromMM(y))
def line(board, a, b, layer):
    s=p.PCB_SHAPE(board); s.SetShape(p.SHAPE_T_SEGMENT)
    s.SetStart(v(*a)); s.SetEnd(v(*b)); s.SetWidth(p.FromMM(.05)); s.SetLayer(layer); board.Add(s)

def main():
    board=p.BOARD(); board.GetDesignSettings().SetCopperLayerCount(2)
    board.GetDesignSettings().SetBoardThickness(p.FromMM(1.6))
    manifest={'panel_mm':[70,110,1.6], 'vcut_y_from_top_mm':[30,60], 'copper_to_vcut_min_mm':.6, 'sources':[]}
    libraries=[]; offset=0
    for prefix,folder,name,height in SOURCES:
        source=folder/(name+'.kicad_pcb'); src=p.LoadBoard(str(source))
        edges=[e for e in src.GetDrawings() if e.GetLayer()==p.Edge_Cuts]
        pts=[pt for e in edges for pt in (e.GetStart(),e.GetEnd())]
        x0=min(pt.x for pt in pts); y0=min(pt.y for pt in pts)
        assert max(pt.x for pt in pts)-x0==p.FromMM(70)
        assert max(pt.y for pt in pts)-y0==p.FromMM(height)
        delta=v(50,50+offset)-p.VECTOR2I(x0,y0)
        nets={0:board.FindNet(0)}
        for old in src.GetNetsByNetcode().values():
            if not old.GetNetCode(): continue
            new=p.NETINFO_ITEM(board,prefix+old.GetNetname()); board.Add(new)
            nets[old.GetNetCode()]=new
        for original in src.GetFootprints():
            fp=p.Cast_to_FOOTPRINT(original.Duplicate(False))
            oldref=fp.GetReference()
            # Unique logical references; original printed identifiers retained
            # as separate graphics so each separated board stays readable.
            field=fp.Reference()
            if field.IsVisible():
                text=p.PCB_TEXT(board); text.SetText(oldref); text.SetPosition(field.GetPosition())
                text.SetTextSize(field.GetTextSize()); text.SetTextThickness(field.GetTextThickness())
                text.SetTextAngle(field.GetTextAngle()); text.SetLayer(field.GetLayer()); text.SetMirrored(field.IsMirrored())
                text.Move(delta); board.Add(text)
            fp.SetReference(prefix+'_'+oldref); fp.Reference().SetVisible(False)
            fp.SetPath(p.KIID_PATH())
            for pad in fp.Pads(): pad.SetNet(nets[pad.GetNetCode()])
            lib=str(fp.GetFPID().GetLibNickname()); local=prefix+'_'+lib
            fp.SetFPID(p.LIB_ID(local,str(fp.GetFPID().GetLibItemName())))
            dest=HERE/(local+'.pretty')
            shutil.copytree(folder/(lib+'.pretty'), dest, dirs_exist_ok=True)
            if local not in libraries: libraries.append(local)
            models = list(fp.Models())
            fp.Models().clear()
            for model in models:
                rel=model.m_Filename.replace('${KIPRJMOD}/','')
                target=HERE/'3dmodels'/prefix/Path(rel).relative_to('3dmodels')
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(folder/rel,target)
                model.m_Filename='${KIPRJMOD}/'+str(target.relative_to(HERE))
                fp.Models().push_back(model)
            fp.Move(delta); board.Add(fp)
        for original in src.GetTracks():
            cast=p.Cast_to_PCB_VIA if isinstance(original,p.PCB_VIA) else p.Cast_to_PCB_TRACK
            t=cast(original.Duplicate()); t.SetNet(nets[t.GetNetCode()]); t.Move(delta); board.Add(t)
        for original in src.Zones():
            z=p.Cast_to_ZONE(original.Duplicate(False)); z.SetNet(nets[z.GetNetCode()]); z.Move(delta); board.Add(z)
        for original in src.GetDrawings():
            if original.GetLayer()==p.Edge_Cuts: continue
            cast=p.Cast_to_PCB_TEXT if isinstance(original,p.PCB_TEXT) else p.Cast_to_PCB_SHAPE
            item=cast(original.Duplicate()); item.Move(delta); board.Add(item)
        manifest['sources'].append({'prefix':prefix,'source':str(source.relative_to(HARDWARE)),
            'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'offset_mm':[0,offset],
            'size_mm':[70,height], 'footprints':len(list(src.GetFootprints())),
            'tracks_and_vias':len(list(src.GetTracks()))})
        offset+=height
    for a,b in [((50,50),(120,50)),((120,50),(120,160)),((120,160),(50,160)),((50,160),(50,50))]:
        line(board,a,b,p.Edge_Cuts)
    for y in (80,110):
        # Cmts.User contains score centre-lines ONLY. Do not mill these as slots.
        line(board,(50,y),(120,y),p.Cmts_User)
        z=p.ZONE(board); z.SetIsRuleArea(True); z.SetLayerSet(p.LSET.AllCuMask())
        z.SetDoNotAllowTracks(True); z.SetDoNotAllowVias(True); z.SetDoNotAllowPads(True); z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowFootprints(False)
        poly=z.Outline(); poly.NewOutline()
        for x,yy in ((49,y-.6),(121,y-.6),(121,y+.6),(49,y+.6)): poly.Append(v(x,yy).x,v(x,yy).y)
        board.Add(z)
    p.ZONE_FILLER(board).Fill(board.Zones())
    p.SaveBoard(str(HERE/(NAME+'.kicad_pcb')),board)
    project={'meta':{'filename':NAME+'.kicad_pro','version':1},
        'board':{'design_settings':{'rules':{'min_clearance':.2,'min_track_width':.2,
        'min_through_hole_diameter':.3,'min_hole_clearance':.25,'min_copper_edge_clearance':.6}}},
        'net_settings':{'classes':[{'name':'Default','clearance':.25,'track_width':.3,
        'via_diameter':.8,'via_drill':.4,'microvia_diameter':.3,'microvia_drill':.1,
        'diff_pair_width':.2,'diff_pair_gap':.25,'diff_pair_via_gap':.25}]}}
    (HERE/(NAME+'.kicad_pro')).write_text(json.dumps(project,indent=2)+'\n')
    table='(fp_lib_table (version 7)\n'
    for lib in libraries:
        table+=f'(lib (name "{lib}") (type "KiCad") (uri "${{KIPRJMOD}}/{lib}.pretty") (options "") (descr "Panel source footprint"))\n'
        for mod in (HERE/(lib+'.pretty')).glob('*.kicad_mod'):
            text=mod.read_text().replace('${KIPRJMOD}/3dmodels/','${KIPRJMOD}/3dmodels/'+lib.split('_')[0]+'/')
            mod.write_text(text)
    (HERE/'fp-lib-table').write_text(table+')\n')
    (HERE/'reports').mkdir(exist_ok=True)
    (HERE/'reports/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Panel generated: 70 x 110 mm, score lines at 30 and 60 mm; isolated nets.')

if __name__=='__main__': main()
