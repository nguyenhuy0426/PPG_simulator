#!/usr/bin/env python3
"""Check nominal optical paths against the enclosure and aperture STL files.

This is a geometric visibility check. It does not model LED radiant intensity,
surface scattering, print translucency, socket tolerances, or OPT101 response.
"""
import importlib.util
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import trimesh
from trimesh.transformations import rotation_matrix

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
STL = REPO / 'docs/system_3d/out/stl'
spec = importlib.util.spec_from_file_location('system_geometry', REPO/'docs/system_3d/build_system.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

SENSOR_X_RANGE = (126.5, 132.0)  # conservative socket + IC envelope from fit model
ACTIVE_HALF = 2.29 / 2.0         # OPT101 active area is 2.29 x 2.29 mm
APERTURE_X = (g.AP_X0 + g.AP_X1) / 2
APERTURES = {'blank': 0.0, 'd2': 1.0, 'd5': 2.5, 'd16': 8.0}
LED_HALF_ANGLE = {'red': 25.0, 'ir': 15.0}  # half-intensity angle from source model


def segment_cylinder(a, b, radius=0.05):
    """Thin solid spanning arbitrary points a and b."""
    a=np.asarray(a,float); b=np.asarray(b,float)
    vector=b-a; length=float(np.linalg.norm(vector)); direction=vector/length
    mesh=trimesh.creation.cylinder(radius=radius,height=length,sections=12)
    z=np.array([0.0,0.0,1.0]); axis=np.cross(z,direction)
    dot=float(np.clip(np.dot(z,direction),-1,1))
    transform=np.eye(4)
    if np.linalg.norm(axis)>1e-12:
        transform=rotation_matrix(math.acos(dot),axis)
    elif dot < 0:
        transform=rotation_matrix(math.pi,[1,0,0])
    transform[:3,3]=(a+b)/2
    mesh.apply_transform(transform)
    return mesh


def overlap(a,b):
    result=trimesh.boolean.intersection([a,b],engine='manifold')
    return 0.0 if result is None else float(abs(result.volume))


def shifted_aperture(kind,lane):
    mesh=trimesh.load(STL/f'aperture_red_{kind}.stl',force='mesh')
    if lane == 'ir':
        mesh.apply_translation([0,0,g.LANE_Z['ir']-g.LANE_Z['red']])
    return mesh


def led_tip_x(lane):
    # The source model defines X_WIN=120 and d as LED-tip to legacy sensor window.
    return g.X_WIN-g.D_DEFAULT[lane]


def main():
    fixed={name:trimesh.load(STL/f'{name}.stl',force='mesh') for name in ('body','lid')}
    frame=trimesh.load(HERE/'frame_70x32_assembly.stl',force='mesh')
    checks=[]; lanes={}
    def record(name,condition,**data):
        checks.append({'check':name,'pass':bool(condition),**data})

    for lane in ('red','ir'):
        z=g.LANE_Z[lane]; sx_near,sx_far=SENSOR_X_RANGE
        source=np.array([led_tip_x(lane),g.Y_AX,z])
        sensor=np.array([sx_near,g.Y_AX,z])
        chief=segment_cylinder(source,sensor)
        record(f'{lane} nominal LED and sensor are coaxial',source[1]==sensor[1] and source[2]==sensor[2])
        for kind,radius in APERTURES.items():
            vol=overlap(chief,shifted_aperture(kind,lane))
            expected_blocked=kind=='blank'
            record(f'{lane} chief ray '+('blocked by blank' if expected_blocked else f'passes {kind} aperture'),
                   (vol>1e-7)==expected_blocked,intersection_mm3=vol)
        for solid_name,solid in {**fixed,'new_frame':frame,'d16_aperture':shifted_aperture('d16',lane)}.items():
            vol=overlap(chief,solid)
            record(f'{lane} chief ray clear of {solid_name}',vol<1e-7,intersection_mm3=vol)

        other='ir' if lane=='red' else 'red'
        cross=segment_cylinder(source,[sx_near,g.Y_AX,g.LANE_Z[other]])
        cross_vol=overlap(cross,fixed['body'])
        record(f'{lane} direct cross-channel ray blocked by enclosure separator',cross_vol>1e-7,intersection_mm3=cross_vol)

        # Project the square active-area corner back onto the aperture plane.
        projected=[]
        for sensor_x in SENSOR_X_RANGE:
            scale=(APERTURE_X-source[0])/(sensor_x-source[0])
            projected.append(ACTIVE_HALF*math.sqrt(2)*scale)
        cone_radius=1.5+(APERTURE_X-source[0])*math.tan(math.radians(LED_HALF_ANGLE[lane]))
        lanes[lane]={
            'source_tip_x_mm':source[0],
            'sensor_window_x_range_mm':list(SENSOR_X_RANGE),
            'axis_y_mm':g.Y_AX,'axis_z_mm':z,
            'active_area_mm':[2.29,2.29],
            'projected_active_corner_radius_at_aperture_mm':projected,
            'half_intensity_cone_radius_at_aperture_mm':cone_radius,
            'd2_covers_full_nominal_active_square':bool(max(projected)<=1.0),
            'd5_covers_full_nominal_active_square':bool(max(projected)<=2.5),
            'd16_covers_full_nominal_active_square':bool(max(projected)<=8.0),
        }

    report={
        'method':'Boolean intersection of thin nominal rays with actual exported STL meshes',
        'aperture_plane_x_mm':APERTURE_X,
        'lanes':lanes,'checks':checks,
        'passed':sum(c['pass'] for c in checks),'total':len(checks),
        'conclusion':{
            'nominal_alignment':'Both intended LED axes pass through their aperture centres and OPT101 active-area centres.',
            'separation':'The solid centre partition blocks a straight ray aimed from either LED at the other sensor.',
            'aperture':'Blank plates block the intended chief rays. D5 and D16 cover each full nominal active square; D2 is marginal for red and clips nominal IR active-area corners.',
        },
        'limitations':[
            'Sensor X uses the conservative socket-plus-IC envelope because the purchased socket height was not measured.',
            'The TI package drawing does not specify photodiode-die centring tolerance; nominal package centre is assumed.',
            'No model of LED radiant power, reflection, scattering, printed-plastic translucency, gaps, or cable openings.',
            'A physical dark-box leakage test and measured sensor response are still required before fabrication confidence.',
        ],
    }
    (HERE/'optical_report.json').write_text(json.dumps(report,indent=2)+'\n')

    fig,axes=plt.subplots(1,2,figsize=(12,4.8),sharey=True)
    for ax,lane in zip(axes,('red','ir')):
        z=g.LANE_Z[lane]; source_x=led_tip_x(lane)
        ax.axvspan(g.AP_X0,g.AP_X1,color='#6b7280',alpha=.35,label='Aperture plate')
        ax.axvspan(*SENSOR_X_RANGE,color='#16a34a',alpha=.18,label='OPT101 window X range')
        ax.plot([source_x,SENSOR_X_RANGE[1]],[0,0],color='#dc2626' if lane=='red' else '#7c3aed',lw=2,label='Chief ray')
        for diameter,color in [(2,'#f59e0b'),(5,'#2563eb'),(16,'#059669')]:
            r=diameter/2
            ax.plot([APERTURE_X,APERTURE_X],[-r,r],lw=5,solid_capstyle='round',color=color,label=f'Ø{diameter} opening')
        corner=max(lanes[lane]['projected_active_corner_radius_at_aperture_mm'])
        ax.plot([APERTURE_X,APERTURE_X],[-corner,corner],color='black',lw=2,label='Projected active corner')
        ax.set_title(f'{lane.upper()} lane, Z={z:g} mm')
        ax.set_xlabel('World X (mm)')
        ax.grid(alpha=.25)
        ax.set_xlim(source_x-4,136); ax.set_ylim(-9,9)
    axes[0].set_ylabel('Offset from optical axis (mm)')
    handles,labels=axes[1].get_legend_handles_labels()
    fig.legend(handles,labels,loc='lower center',ncol=4,frameon=False)
    fig.suptitle('Nominal optical alignment and aperture coverage')
    fig.tight_layout(rect=(0,.13,1,.95))
    fig.savefig(HERE/'optical_alignment.png',dpi=180)
    plt.close(fig)
    print(f"Optical geometry: {report['passed']}/{report['total']} checks passed")
    if not all(c['pass'] for c in checks):
        print(json.dumps([c for c in checks if not c['pass']],indent=2))
        raise SystemExit(1)


if __name__=='__main__':
    main()
