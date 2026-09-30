"""Frozen-model, exploratory BIDMC audit. Does not fit or select checkpoints.

Run: python -m ml.morphology_audit --output docs/morphology-audit
Pulse metrics are deliberately separate from the existing LSM strip audit.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from ml.fit_gaussian import PREPARED_SHA256, PHASE
from ml.independent_ppg_eval import landmarks, metrics
from models.waveform import PulseMorphology, PulseShaper, WAVE_PPG


def describe(y, hr=75):
    """Visible extrema; FWHM is the contiguous half-height lobe around SP.

    DN means a visible post-peak minimum plus >=3% rebound, not valve timing.
    Values refer to the processed, normalized pulse, not voltage calibration.
    """
    y = np.asarray(y, dtype=float)
    marks = landmarks(y)
    y = (y-y.min()) / np.ptp(y)
    sp = int(np.argmax(y))
    left = sp
    while left > 0 and y[left-1] >= .5:
        left -= 1
    right = sp
    while right < 255 and y[right+1] >= .5:
        right += 1
    lo = np.interp(.5, y[left-1:left+1], PHASE[left-1:left+1]) if left else 0.
    hi = np.interp(.5, y[right:right+2][::-1], PHASE[right:right+2][::-1]) if right < 255 else 1.
    result = dict(sp_phase=sp/255, sp_ms=sp/255*60000/hr,
                  half_height_start=float(lo), half_height_end=float(hi),
                  fwhm_phase=float(hi-lo), fwhm_ms=float((hi-lo)*60000/hr),
                  tail_80=float(np.interp(.8, PHASE, y)),
                  tail_90=float(np.interp(.9, PHASE, y)),
                  visible_notch=marks['notch'], dn_phase=None, dn_height=None,
                  dp_phase=None, dp_height=None, rebound=None)
    if marks['notch']:
        dn = int(round(marks['dn']*255))
        dp = int(round(marks['dp']*255))
        result.update(dn_phase=marks['dn'], dn_height=float(y[dn]),
                      dp_phase=marks['dp'], dp_height=float(y[dp]),
                      rebound=float(y[dp]-y[dn]))
    return result


def distribution(x, condition):
    rows = [describe(y, float(c[0]*200)) for y, c in zip(x, condition)]
    result = {'n': len(rows), 'visible_notch_fraction': float(np.mean([r['visible_notch'] for r in rows]))}
    for key in rows[0]:
        if key == 'visible_notch':
            continue
        values = [r[key] for r in rows if r[key] is not None]
        result[key] = dict(n=len(values), p10_p50_p90=np.percentile(values, [10,50,90]).tolist()) if values else None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('docs/morphology-audit'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    data_path = Path('ml/runs/kaggle-v1/ppg_run/prepared.npz')
    assert hashlib.sha256(data_path.read_bytes()).hexdigest() == PREPARED_SHA256
    with np.load(data_path, allow_pickle=False) as data:
        ids = np.flatnonzero(data['validation'])
        real, c, subjects = data['pulse'][ids], data['condition'][ids], data['subject'][ids]
        assert not set(subjects) & set(data['subject'][data['train'].astype(bool)])
    profiles = json.loads(Path('assets/gaussian/profiles.json').read_text())['profiles']
    def shape(m):
        shaper = PulseShaper(PulseMorphology(**m))
        return np.array([shaper.sample(WAVE_PPG, float(t)) for t in PHASE])
    curves = {name: shape(p['morphology']) for name, p in profiles.items()}
    curves['Original'] = shape({})
    outputs = {'Gaussian (original)': np.repeat(curves['Original'][None], len(ids), 0),
               'Gaussian (fitted) balanced': np.repeat(curves['Balanced'][None], len(ids), 0),
               'Gaussian (fitted) class': np.where((c[:,-1]>.5)[:,None], curves['With notch'], curves['No notch'])}
    hashes = {}
    for name, filename in [('cWGAN-GP','cwgan_generator.ts'), ('TCN-FiLM','tcn_generator.ts')]:
        path = Path('assets/neural') / filename
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        model = torch.jit.load(str(path), map_location='cpu').eval()
        for seed in (42, 43, 44):
            rng = torch.Generator().manual_seed(seed)
            z = torch.randn(len(ids), 32, generator=rng)
            with torch.inference_mode():
                generated = np.concatenate([model(z[i:i+64], torch.tensor(c[i:i+64])).numpy()
                                            for i in range(0,len(ids),64)])
            outputs[f'{name} seed {seed}'] = generated
    result = {}
    for name, y in outputs.items():
        row = metrics(y, c, real)
        row.pop('development_score', None)  # No post-hoc scalar ranking.
        row['waveform_rmse'] = float(np.sqrt(np.mean((y-real)**2)))
        row['hf_absolute_error'] = abs(row['above_5hz_power_fraction']-row['real_above_5hz_power_fraction'])
        row['by_subject'] = {}
        for s in np.unique(subjects):
            mask = subjects == s
            sub = metrics(y[mask], c[mask], real[mask])
            sub.pop('development_score', None)
            sub['waveform_rmse'] = float(np.sqrt(np.mean((y[mask]-real[mask])**2)))
            row['by_subject'][str(s)] = sub
        result[name] = row
        print(name, {k: round(row[k],6) for k in ('phase_acf_rmse','phase_log_psd_rmse','hf_absolute_error','waveform_rmse')}, flush=True)
    # Reproduce the screenshot settings, then condition on the SAME train real
    # exemplar as the fitted Gaussian. The old app used a different exemplar.
    manifest = json.loads(Path('assets/neural/manifest.json').read_text())
    examples = dict(curves)
    for label in ('No notch', 'With notch'):
        examples['Real '+label] = np.array(profiles[label]['reference_waveform'])
        for style, cond in [('screenshot', np.array(manifest['condition_presets'][label])),
                            ('matched', None)]:
            if cond is None:
                with np.load(data_path, allow_pickle=False) as data:
                    cond = data['condition'][profiles[label]['train_exemplar_index']].copy()
            cond[0] = .375
            for name, filename in [('cWGAN-GP','cwgan_generator.ts'), ('TCN-FiLM','tcn_generator.ts')]:
                model = torch.jit.load(str(Path('assets/neural')/filename), map_location='cpu').eval()
                z = torch.randn(1,32,generator=torch.Generator().manual_seed(42))
                with torch.inference_mode():
                    examples[f'{name} {style} {label}'] = model(z,torch.tensor(cond[None],dtype=torch.float32)).numpy()[0]
    summary = dict(samples=len(ids), subjects=len(np.unique(subjects)), seeds=[42,43,44],
                   prepared_sha256=PREPARED_SHA256, model_hashes=hashes, split='validation',
                   results=result, real_distribution=distribution(real,c),
                   examples={name: describe(y) for name,y in examples.items()},
                   limitations=['Exploratory: validation and test previously viewed; no new test claim.',
                       'Conditional neural models receive real automatic morphology conditions; fixed Gaussian does not.',
                       'BIDMC critical-care cohort; 12 Hz lowpass, baseline correction, 256-point phase resampling.',
                       'Quantiles are descriptive, beat-weighted; seven subjects, not clinical reference intervals.',
                       'Visible-notch detector is not manually validated valve-closure ground truth.',
                       'LSM generates 30 s at 40 Hz; its separate strip audit is not a pulse-metric ranking.',
                       'Three inference seeds for one checkpoint, not three independent training runs.'])
    (args.output/'metrics.json').write_text(json.dumps(summary,indent=2)+'\n')
    fields = ['model','phase_acf_rmse','phase_log_psd_rmse','above_5hz_power_fraction','hf_absolute_error','waveform_rmse']
    with (args.output/'comparison.csv').open('w',newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for name,row in result.items():
            writer.writerow(dict(model=name, **{key: row[key] for key in fields[1:]}))
    np.savez_compressed(args.output/'examples.npz', **examples)
    np.savez_compressed(args.output/'validation_summary.npz', phase=PHASE,
                        real_quantiles=np.percentile(real,[10,50,90],axis=0),
                        **{name:y.mean(0) for name,y in outputs.items()})


if __name__ == '__main__':
    main()
