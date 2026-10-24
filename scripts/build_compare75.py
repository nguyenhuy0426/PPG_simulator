#!/usr/bin/env python3
"""Build docs/model-report/compare75.js: real windows near 75 bpm from every public dataset next to every generator.

Real windows: the processed v3 pack (0.5-8 Hz, 40 Hz, 30 s, min-max); per dataset two people whose window measures
within REAL_TOLERANCE of 75 bpm, closest first. Training domains look at validation people first (no generator saw
them) and fall back to training people only when validation has too few near 75 bpm; test people are never opened.
PTT is external (never trained on). OpenOximetry is not drawn: its PhysioNet credentialed-access DUA keeps its waveforms out of shared outputs.
Generators: conditioned models get 75 bpm and the dataset's default irregularity at one fixed seed (no seed search);
the unconditional LSM generators cannot be asked for a rate, so the first seed whose window measures 75 +- 3 bpm (or
the closest seed found) is shown and the search and the rate range it covered are reported. Research checkpoints are the seed-42 run of each round, not shipped in the app.
Engineering view of normalised waveform shape; not clinical validation.
"""
import argparse
import copy
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_model_report import git_commit, normalized, rounded  # noqa: E402

TARGET_BPM = 75.
VIEW_SECONDS = 10
GEN_SEED = 7                 # same seed as the earlier compare strip
LSM_SEARCH = range(200)      # unconditional generators: seeds searched for a window near 75 bpm
LSM_TOLERANCE = 3.
REAL_TOLERANCE = 5.
RUNS = ROOT/'ml/runs'
PACK = RUNS/'physio3-data-v1/physio3_data'
# key, label, pack domain, splits searched in order, generator condition domain, note
DATASETS = [
    ('bidmc', 'BIDMC', 'bidmc', ('validation', 'train'), 'bidmc', 'ICU, ngón tay (PhysioNet)'),
    ('perform_large', 'MIMIC PERform Large', 'perform_large', ('validation', 'train'), 'perform_large', 'ICU, MIMIC'),
    ('perform_af', 'MIMIC PERform AF', 'perform_af', ('validation', 'train'), 'perform_af', 'ICU, rung nhĩ'),
    ('perform_non_af', 'MIMIC PERform non-AF', 'perform_non_af', ('validation', 'train'), 'perform_non_af', 'ICU, nhịp xoang'),
    ('gxu_finger', 'GXU ngón tay', 'gxu_finger', ('validation', 'train'), 'gxu_finger', 'Mendeley, IR 940 nm'),
    ('wrist', 'Wrist PPG (vận động)', 'wrist', ('validation', 'train'), 'wrist', 'PhysioNet, cổ tay khi tập'),
    ('ptt_sit', 'PTT ngồi', 'ptt_sit', ('external',), 'gxu_finger', 'PhysioNet PTT, pleth_1; không có trong train'),
    ('ptt_walk', 'PTT đi bộ', 'ptt_walk', ('external',), 'wrist', 'PhysioNet PTT, pleth_1; không có trong train'),
    ('ptt_run', 'PTT chạy', 'ptt_run', ('external',), 'wrist', 'PhysioNet PTT, pleth_1; không có trong train'),
]
BLOCKED = [dict(key='openox', label='OpenOximetry', note=(
    'Không vẽ: OpenOximetry 1.1.1 là dữ liệu PhysioNet truy cập hạn chế (DUA), không được đưa dạng sóng vào '
    'báo cáo chia sẻ hay git. Bộ này chỉ dùng cho vòng 13 (nhánh red), không có trong benchmark GAN.'))]
# key, label, group, TorchScript under ml/runs (None = app or formula model), trained on
RESEARCH = [
    ('physiomix_s', 'PhysioMix-S', 'strict-train-physiomix-result-v1/strict_round/benchmark/'
     'L3_rel_beat_lr_crop_r1w_motion_dom_strict_seed42', '6 miền'),
    ('g1_flowgan', 'G1 flow-GAN', 'flowgan-round-result-v2/flowgan_round/benchmark/G1_flowgan_seed42', '6 miền'),
    ('g2_flowgan_lsm', 'G2 flow-GAN-LSM', 'flowgan-round-result-v2/flowgan_round/benchmark/'
     'G2_flowgan_lsm_bidmc_seed42', 'chỉ BIDMC'),
    ('beatgen', 'BeatGen', 'beat-round-result-v1/beat_round/benchmark/B1_beatgen_seed42', '6 miền'),
]
LSM_STRICT = 'strict-train-lsm-result-v1/strict_round/lsm/lsm_strict_seed42'
INTELLIVUE_FIT = ROOT/'assets/gaussian/intellivue_fit.json'


def view(values, fs):
    return rounded(normalized(list(values)[:int(VIEW_SECONDS*fs)]))


def real_windows(per_dataset=2):
    import numpy as np
    from core.neural_preview import estimate_rate_bpm
    with np.load(PACK/'windows.npz', allow_pickle=False) as data:
        signal, domain, split, subject = data['signal'], data['domain'], data['split'], data['subject']
    out = {}
    for key, _, name, parts, _, _ in DATASETS:
        picked, people = [], set()
        for part in parts:
            rows = np.flatnonzero((domain == name) & (split == part))
            rates = [estimate_rate_bpm(signal[r].astype(float).tolist(), 40) for r in rows]
            order = sorted((abs(rate-TARGET_BPM), i) for i, rate in enumerate(rates)
                           if rate is not None and abs(rate-TARGET_BPM) <= REAL_TOLERANCE)
            for _, i in order:
                if len(picked) == per_dataset or subject[rows[i]] in people:
                    continue
                people.add(subject[rows[i]])
                picked.append(dict(values=view(signal[rows[i]].astype(float), 40), fs=40, split=part,
                                   measured=round(rates[i], 1)))
        if not picked:
            raise ValueError(f'No {name} window within {REAL_TOLERANCE} bpm of {TARGET_BPM}')
        out[key] = dict(real=picked)
    return out


def conditioned_models():
    import torch
    from core.neural_preview import PhysioMixGenerator
    pm, pf = PhysioMixGenerator(), PhysioMixGenerator(slot='physioflow')
    models = [(key, label, 'app', g, '6 miền', f"{g.meta['variant']} seed {g.meta['seed']}")
              for key, label, g in (('physiomix', 'PhysioMix', pm), ('physioflow', 'PhysioFlow', pf))]
    for key, label, run, trained in RESEARCH:
        gen = copy.copy(pm)   # same (z, condition) contract and condition schema (checked against conditions.json)
        conditions = RUNS/run/'conditions.json'
        if conditions.exists():
            c = json.loads(conditions.read_text())
            if c['domains'] != pm.meta['domains'] or c['center'] != pm.meta['center'] or c['scale'] != pm.meta['scale']:
                raise ValueError(f'{run}: condition schema differs from the app PhysioMix')
        gen.model = torch.jit.load(str(RUNS/run/'generator_cpu.ts'), map_location='cpu').eval()
        gen.name = label
        models.append((key, label, 'research', gen, trained, run.split('/')[-1]))
    return models


def unconditional(key, label, group, sample, source):
    """First seed within LSM_TOLERANCE of the target; if none, the closest one (its measured rate is shown)."""
    from core.neural_preview import estimate_rate_bpm
    best, rates = None, []
    for seed in LSM_SEARCH:
        values = sample(seed)
        rate = estimate_rate_bpm(values, 40)
        if rate is None:
            continue
        rates.append(rate)
        if best is None or abs(rate-TARGET_BPM) < abs(best[1]-TARGET_BPM):
            best = (seed, rate, values)
        if abs(rate-TARGET_BPM) <= LSM_TOLERANCE:
            break
    if best is None:
        raise ValueError(f'{label}: no measurable window in {LSM_SEARCH}')
    seed, rate, values = best
    return dict(key=key, label=label, group=group, conditioned=False, trained='chỉ BIDMC', source=source,
                seed=seed, seeds_tried=len(rates), rate_range=[round(min(rates), 1), round(max(rates), 1)],
                wave=dict(values=view(values, 40), fs=40, measured=round(rate, 1)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'docs/model-report/compare75.js')
    a = parser.parse_args(argv)
    import torch
    torch.set_num_threads(1)
    from config import MODEL_SAMPLE_RATE_PPG
    from core.neural_preview import LSMSequenceGenerator, estimate_rate_bpm
    from models.ppg_model import PPGModel
    datasets = real_windows()
    models = []
    for key, label, group, gen, trained, source in conditioned_models():
        waves = {}
        for dkey, _, _, _, cond, _ in DATASETS:
            p = gen.generate(GEN_SEED, TARGET_BPM, cond)
            values = [s[1] for s in p.samples]
            waves[dkey] = dict(values=view(values, 40), fs=40, measured=p.provenance['measured_rate_bpm'] and
                               round(p.provenance['measured_rate_bpm'], 1))
        models.append(dict(key=key, label=label, group=group, conditioned=True, trained=trained, source=source,
                           seed=GEN_SEED, waves=waves))
    lsm = LSMSequenceGenerator()
    models.append(unconditional('lsm', 'LSM-GAN', 'app', lambda s: [x[1] for x in lsm.generate(s).samples],
                                'lsm_generator.ts (app)'))
    strict = torch.jit.load(str(RUNS/LSM_STRICT/'generator_cpu.ts'), map_location='cpu').eval()

    def strict_sample(seed):
        z = torch.randn(1, 1200, generator=torch.Generator().manual_seed(seed))
        with torch.inference_mode():
            return strict(z)[0, 0].clamp(0, 1).tolist()
    models.append(unconditional('lsm_strict', 'LSM-strict', 'research', strict_sample, LSM_STRICT.split('/')[-1]))
    # The app's formula model at its run defaults (HR 75, SpO2 99, RR 16, Normal): the IntelliVue-fitted Gaussian
    # pulse with respiration and beat-to-beat variability, IR channel, as played to the DAC (no v3 filter).
    random.seed(GEN_SEED)
    model = PPGModel()
    p = model.params
    if (p.heart_rate, p.spo2, p.resp_rate) != (TARGET_BPM, 99.0, 16.0):
        raise ValueError(f'PPGModel defaults are {p.heart_rate}/{p.spo2}/{p.resp_rate}, expected 75/99/16')
    dt = 1/MODEL_SAMPLE_RATE_PPG
    gauss = [model.generate_both_samples(dt)[0] for _ in range(int(VIEW_SECONDS*MODEL_SAMPLE_RATE_PPG))]
    models.append(dict(key='gaussian', label='Gaussian IntelliVue (app)', group='formula', conditioned=False,
                       trained='fit ảnh IntelliVue', source='models/ppg_model.py', seed=GEN_SEED,
                       wave=dict(values=view(gauss, MODEL_SAMPLE_RATE_PPG), fs=MODEL_SAMPLE_RATE_PPG,
                                 measured=round(estimate_rate_bpm(gauss, MODEL_SAMPLE_RATE_PPG), 1))))
    # The fitted target itself: the mean IntelliVue beat (one beat, repeated at 75 bpm; a shape reference only).
    fit = json.loads(INTELLIVUE_FIT.read_text())
    beat = fit['mean_beat']
    reference = [beat[int((i/100*TARGET_BPM/60) % 1*(len(beat)-1))] for i in range(VIEW_SECONDS*100)]
    intellivue = dict(label='IntelliVue (ảnh, nhịp TB lặp lại)', fs=100, values=view(reference, 100),
                      beats=fit['beats'], fit_rmse=fit['fit_rmse'], spread=fit['beat_to_beat_rms_sd'])
    report = dict(commit=git_commit(), target_bpm=TARGET_BPM, seconds=VIEW_SECONDS,
                  datasets=[dict(key=k, label=l, domain=d, condition=c, note=n, **datasets[k])
                            for k, l, d, _, c, n in DATASETS] + BLOCKED,
                  models=models, intellivue=intellivue)
    a.output.write_text('// Generated by scripts/build_compare75.py; do not edit by hand.\nwindow.COMPARE75 = '
                        + json.dumps(report, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + ';\n')
    print(f'Wrote {a.output} ({a.output.stat().st_size/1024:.0f} KiB)')
    for m in models:
        rates = [w['measured'] for w in m['waves'].values()] if 'waves' in m else [m['wave']['measured']]
        print(m['key'], rates, f"seed {m['seed']}" + (f" ({m['seeds_tried']} tried)" if 'seeds_tried' in m else ''))
    for k in datasets:
        print(k, [(r['split'], r['measured']) for r in datasets[k]['real']])


if __name__ == '__main__':
    main()
