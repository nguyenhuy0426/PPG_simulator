#!/usr/bin/env python3
"""Build the data file of the local model report (docs/model-report/data.js).

Every waveform and number shown is produced here from the packaged app models and the saved
evaluation results, so the page shows what the app actually runs. Open docs/model-report/index.html
in a browser (file:// works) or serve it with: python3 -m http.server --directory docs/model-report 8765
"""
import argparse
import datetime
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))

DOMAINS = ('gxu_finger', 'perform_large', 'bidmc', 'perform_af', 'perform_non_af', 'wrist')
HR_GRID = (40, 60, 80, 100, 120, 140, 160, 180)
VIEW_SECONDS = 10           # waveform strips shown in the page (the model makes 30 s)
CONTROL_SEEDS = 5
# Validation S_arm per round (lower is better) and what changed; docs/physiomix-v3/REPORT_VI.md and rules/.
ROUNDS = [
    dict(round='R3', name='physiomix_v2', change='Nhịp dựng sẵn + mạng tạo dáng (bản đầu)', S_arm=0.596, sd=0.026, shipped=True),
    dict(round='R4', name='L3', change='Learning rate thấp, nhịp sinh lý', S_arm=0.588, sd=0.029, shipped=False),
    dict(round='R5', name='crop', change='Sinh dài rồi cắt giữa (trượt cổng)', S_arm=0.527, sd=0.022, shipped=False),
    dict(round='R6', name='crop_r1', change='Sửa ngưỡng cắt gradient R1', S_arm=0.570, sd=0.023, shipped=True),
    dict(round='R7', name='crop_r1w', change='Giảm trọng số R1 còn 0,1', S_arm=0.510, sd=0.053, shipped=True),
]
# Wrist-targeted rounds (8, 9): S_arm only had to stay within the incumbent's pooled SD; their frozen rule and
# decision are in docs/physiomix-v3/rules/DECISION_ROUND{8,9}.json.
TARGETED_ROUNDS = {'R8': ('Bộ dao động chuyển động', 'DECISION_ROUND8.json'),
                   'R9': ('Dao động chuyển động + loss khớp phân bố theo miền', 'DECISION_ROUND9.json')}
APP_SOURCE = 'app'      # name of the shipped model's run in the realism file (passed with --app-source)


def git_commit():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def rounded(values, digits=3):
    return [round(float(v), digits) for v in values]


def normalized(values):
    lo, hi = min(values), max(values)
    return [(v-lo)/(hi-lo) if hi > lo else .5 for v in values]


def parameters_of(module):
    return int(sum(p.numel() for p in module.parameters()))


def latency_ms(call, repeats=20):
    call()
    start = time.perf_counter()
    for _ in range(repeats):
        call()
    return (time.perf_counter()-start)/repeats*1000


def physiomix_section(pm):
    import torch
    torch.set_num_threads(1)
    from core.neural_preview import estimate_rate_bpm
    meta = pm.meta
    n = int(VIEW_SECONDS*40)
    strips, control = {}, {}
    for domain in DOMAINS:
        strips[domain], control[domain] = {}, []
        for hr in HR_GRID:
            measured = []
            for seed in range(CONTROL_SEEDS):
                preview = pm.generate(1000+seed, hr, domain)
                measured.append(preview.provenance['measured_rate_bpm'])
                if seed == 0:
                    wave = [s[1] for s in preview.samples]
                    strips[domain][str(hr)] = dict(values=rounded(normalized(wave[:n])),
                                                   measured=preview.provenance['measured_rate_bpm'])
            ok = sorted(m for m in measured if m is not None)
            control[domain].append(dict(requested=hr, measured=ok[len(ok)//2] if ok else None,
                                        lo=ok[0] if ok else None, hi=ok[-1] if ok else None))
    z, c = torch.randn(1, 1200), torch.tensor([pm.condition('bidmc', 75.)])
    return dict(variant=meta['variant'], arm=meta['arm'], seed=meta['seed'], best_step=meta['best_step'],
                validation_score=round(meta['validation_score'], 3), domains=list(meta['domains']),
                hr_support=meta['hr_support_bpm'], data_support=meta.get('data_support_bpm'),
                architecture=meta['architecture'], parameters=parameters_of(pm.model),
                latency_ms=round(latency_ms(lambda: pm.model(z, c)), 1), strips=strips, control=control,
                sha256=pm.sha256)


def real_strips(pack_dir, per_domain=3):
    """A few processed TRAIN windows per dataset (people chosen at random, fixed seed)."""
    import numpy as np
    from core.neural_preview import estimate_rate_bpm
    with np.load(Path(pack_dir)/'windows.npz', allow_pickle=False) as data:
        signal, domain, split, subject = data['signal'], data['domain'], data['split'], data['subject']
    rng = np.random.default_rng(7)
    n = int(VIEW_SECONDS*40)
    out = {}
    for name in DOMAINS:
        rows = np.flatnonzero((domain == name) & (split == 'train'))
        people = rng.permutation(np.unique(subject[rows]))[:per_domain]
        out[name] = []
        for person in people:
            row = rng.choice(rows[subject[rows] == person])
            wave = signal[row].astype(float)
            out[name].append(dict(values=rounded(normalized(list(wave[:n]))), measured=estimate_rate_bpm(list(wave), 40)))
    return out


def dataset_counts(pack_dir):
    import numpy as np
    with np.load(Path(pack_dir)/'windows.npz', allow_pickle=False) as data:
        domain, split, subject = data['domain'], data['split'], data['subject']
    counts = {}
    for name in DOMAINS:
        counts[name] = {s: dict(windows=int(((domain == name) & (split == s)).sum()),
                                people=int(len(np.unique(subject[(domain == name) & (split == s)]))))
                        for s in ('train', 'validation', 'test')}
    return counts


def compare_sources(pm):
    """The four selectable app sources plus the Classic model, at 75 bpm, 10 s each."""
    from core.neural_preview import LSMSequenceGenerator, gaussian_preview, physiomix_reference_preview
    from config import MODEL_SAMPLE_RATE_PPG
    from models.ppg_model import PPGModel
    out = []
    real = physiomix_reference_preview('bidmc')
    out.append(dict(key='real', fs=40, values=rounded(normalized([s[1] for s in real.samples][:400]))))
    gauss = gaussian_preview(75, 'With notch')
    out.append(dict(key='gaussian', fs=100, values=rounded(normalized([s[1] for s in gauss.samples][:1000]))))
    try:
        lsm = LSMSequenceGenerator().generate(7)
        out.append(dict(key='lsm', fs=40, values=rounded(normalized([s[1] for s in lsm.samples][:400]))))
    except (RuntimeError, OSError, ValueError) as error:
        out.append(dict(key='lsm', fs=40, values=[], error=str(error)))
    physio = pm.generate(7, 75, 'bidmc')
    out.append(dict(key='physiomix', fs=40, values=rounded(normalized([s[1] for s in physio.samples][:400]))))
    model = PPGModel()
    model.set_heart_rate(75)
    dt = 1/MODEL_SAMPLE_RATE_PPG
    classic = [model.generate_both_samples(dt)[0] for _ in range(int(VIEW_SECONDS*MODEL_SAMPLE_RATE_PPG))]
    out.append(dict(key='classic', fs=MODEL_SAMPLE_RATE_PPG, values=rounded(normalized(classic))))
    return out


def lsm_section():
    try:
        import torch
        from core.neural_preview import LSMSequenceGenerator
        lsm = LSMSequenceGenerator()
        z = torch.randn(1, 1200)
        return dict(parameters=parameters_of(lsm.model), latency_ms=round(latency_ms(lambda: lsm.model(z)), 1))
    except (RuntimeError, OSError, ValueError, AttributeError) as error:
        return dict(error=str(error))


def realism_section(path, app):
    result = json.loads(Path(path).read_text())
    keep = ('real_other_people', app, 'round7', 'gaussian_shaper')
    rename = lambda k: APP_SOURCE if k == app else k
    realism = {d: {rename(k): {m: round(v[m], 3) for m in ('fidelity', 'coverage', 'indistinguishable')}
                   for k, v in entry.items() if k in keep}
               for d, entry in result['realism'].items()}
    for d, entry in result['realism'].items():
        realism[d]['people'] = entry['people']
    cond = result['condition_following']
    sources = [s for s in ('real_unseen', app, 'round7', 'gaussian_shaper') if s in cond]
    following = {rename(s): dict(accuracy={k: round(v, 3) for k, v in cond[s]['accuracy'].items()},
                         motion={k: round(v, 3) for k, v in cond[s]['motion_probability'].items()},
                         balanced=round(cond[s]['balanced_accuracy'], 3),
                         swap=round(cond[s]['swap_following'], 3) if 'swap_following' in cond[s] else None,
                         distinct=round(cond[s]['swap_distinct_answers_per_noise'], 2)
                         if 'swap_distinct_answers_per_noise' in cond[s] else None)
                 for s in sources}
    physiology = {rename(s): {k: dict(hr=v['hr_median'], cv=v['ibi_cv_median'], acf=v['periodicity_median'])
                              for k, v in cond['physiology'][s].items()}
                  for s in ('real_unseen', 'real_prompts', app, 'round7') if s in cond['physiology']}
    return dict(realism=realism, states=cond['states'], following=following, physiology=physiology)


def training_curves(run_dir, arm):
    curves = {}
    for path in sorted(Path(run_dir).glob(f'{arm}_seed*/history.json')):
        history = json.loads(path.read_text())
        curves[path.parent.name.rsplit('seed', 1)[1]] = [dict(step=h['step'], score=round(h['checkpoint_score'], 4),
                                                              S_real=round(h['S_real'], 4), C=round(h['C'], 4))
                                                         for h in history if 'checkpoint_score' in h]
    return curves


def rx_section():
    """Accuracy of the received pulse-rate estimator on the synthetic RX generator of its tests."""
    import itertools
    from core.rx_heart_rate import estimate_rx_rate
    from hw.opt101_rx import RXSample
    from test_rx_heart_rate import rx_stream
    regular = [dict(requested=b, measured=estimate_rx_rate(rx_stream(b, seed=b)).bpm) for b in (40, 60, 80, 100, 120, 140, 160, 180)]
    false = 0
    for k in range(100):
        r = random.Random(k)
        false += estimate_rx_rate([RXSample(i/100, round(1500+r.gauss(0, 20)), False) for i in range(800)]).bpm is not None
        r = random.Random(1000+k)
        walk = list(itertools.accumulate(r.gauss(0, 5) for _ in range(800)))
        false += estimate_rx_rate([RXSample(i/100, round(1500+v), False) for i, v in enumerate(walk)]).bpm is not None
    irregular = {}
    for sigma in (.1, .2, .3):
        rates = [estimate_rx_rate(rx_stream(95, sigma=sigma, seed=k)).bpm for k in range(30)]
        irregular[str(sigma)] = round(sum(r is not None for r in rates)/len(rates), 2)
    example = rx_stream(84, seconds=8)
    return dict(regular=[dict(r, measured=None if r['measured'] is None else round(r['measured'], 1)) for r in regular],
                noise_false_rate=round(false/200, 3), irregular_rated=irregular,
                example=dict(values=rounded(normalized([s.raw for s in example][::2])), fs=50,
                             measured=round(estimate_rx_rate(example).bpm, 1)))


def targeted_rounds(rules):
    out = []
    for name, (change, file) in TARGETED_ROUNDS.items():
        path = Path(rules)/file
        if not path.exists():
            continue
        d = json.loads(path.read_text())
        out.append(dict(round=name, change=change, S_arm=round(d['S_arm']['mean'], 3), sd=round(d['S_arm']['sd'], 3),
                        shipped=d['ship'], target=d.get('target'), wrist_Q=round(d['target_Q']['mean'], 3),
                        wrist_Q_sd=round(d['target_Q']['sd'], 3), incumbent_wrist_Q=round(d['incumbent_target_Q']['mean'], 3),
                        gap=round(d['target_gap'], 3), pooled_sd=round(d['target_pooled_sd'], 3)))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', type=Path, default=ROOT/'ml/runs/physio3-data-v1/physio3_data')
    parser.add_argument('--realism', type=Path, default=ROOT/'ml/runs/realism-v1/realism_round9.json')
    parser.add_argument('--app-source', default='round9', help='Run name of the shipped model in the realism file')
    parser.add_argument('--run', type=Path,
                        default=ROOT/'ml/runs/physiomix9-motion-dom-result-v1/physiomix9/benchmark')
    parser.add_argument('--rules', type=Path, default=ROOT/'docs/physiomix-v3/rules')
    parser.add_argument('--output', type=Path, default=ROOT/'docs/model-report/data.js')
    a = parser.parse_args(argv)
    from core.neural_preview import PhysioMixGenerator
    pm = PhysioMixGenerator()
    report = dict(generated=datetime.date.today().isoformat(), commit=git_commit(),
                  physiomix=physiomix_section(pm), lsm=lsm_section(), compare=compare_sources(pm),
                  real=real_strips(a.pack), datasets=dataset_counts(a.pack), rounds=ROUNDS,
                  targeted=targeted_rounds(a.rules), training=training_curves(a.run, pm.meta['arm']),
                  rx=rx_section(), **realism_section(a.realism, a.app_source))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text('// Generated by scripts/build_model_report.py; do not edit by hand.\nwindow.REPORT = '
                        + json.dumps(report, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + ';\n')
    print(f'Wrote {a.output} ({a.output.stat().st_size/1024:.0f} KiB)')


if __name__ == '__main__':
    main()
