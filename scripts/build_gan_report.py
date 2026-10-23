#!/usr/bin/env python3
"""Build docs/model-report/gan-data.js: the strict-judge round and the PhysioFlow-GAN round, laid out like
Ding et al., "Log-Spectral Matching GAN ...", IEEE JBHI 27(3) 2023 (Table I-IV, Fig. 2, 3, 6-9).

Numbers come from the saved round outputs (judges.json, sets.json, DECISION_*.json, training_execution.json,
history.json); real windows from the v3 pack (ml/runs/physio3-data-v1); synthetic windows for Fig. 2, 3b and 9 are drawn
here on the CPU from the app models (assets/neural, checked against its manifest) and the rounds' checkpoints, prompted
with training people's labels as the judge rounds do. A round whose folder is missing is left out (the page says so).
The artifact share is a rule-based SQI (ml/kaggle_multidomain/artifact_sqi.py), not expert annotation.
Engineering evaluation of normalised 30 s PPG shape; not clinical validation.
"""
import argparse
from collections import defaultdict
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import warnings

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNS = ROOT/'ml/runs'
OUT = ROOT/'docs/model-report/gan-data.js'

INC = 'L3_rel_beat_lr_crop_r1w_motion_dom'
ARMS = {f'{INC}_strict': 'PhysioMix-S (critic nghiêm)',
        f'{INC}_strict_quiet': 'PhysioMix-SQ (critic nghiêm + nhiễu đo)',
        'lsm_author_v3': 'LSM-GAN tác giả (train lại, view v3)',
        'lsm_strict': 'LSM-GAN-S (critic nghiêm)',
        'G1_flowgan': 'PhysioFlow-GAN (6 miền)',
        'G2_flowgan_lsm_bidmc': 'PhysioFlow-GAN-LSM (BIDMC)'}
FIXED = {'physiomix_app': 'PhysioMix (app)', 'physioflow_app': 'PhysioFlow (app, 16 bước)',
         'physioflow_sensor': 'PhysioFlow + nhiễu cảm biến 0,03', 'lsm_app': 'LSM-GAN (app)',
         'real_other_people': 'Người thật khác (đối chứng null)'}
KIND_OF = {'physiomix_app': 'app', 'lsm_app': 'app', 'physioflow_app': 'reference', 'physioflow_sensor': 'reference',
           'real_other_people': 'null'}
DOMAIN_INFO = {
    'bidmc': ('BIDMC', 'ICU, ngón tay', 'Pimentel et al., BIDMC 1.0.0 (PhysioNet)'),
    'gxu_finger': ('GXU ngón tay', 'người khỏe, nghỉ và sau gắng sức', 'Li S. et al., Mendeley Data (2026)'),
    'perform_af': ('PERform AF', 'ICU, rung nhĩ', 'MIMIC PERform AF (Charlton et al., PhysioNet)'),
    'perform_large': ('PERform Large', 'ICU người lớn', 'MIMIC PERform Large (Charlton et al., PhysioNet)'),
    'perform_non_af': ('PERform không AF', 'ICU, nhịp xoang', 'MIMIC PERform AF (Charlton et al., PhysioNet)'),
    'wrist': ('Cổ tay vận động', 'đi bộ, chạy, đạp xe', 'Jarchi & Casson, Wrist PPG During Exercise (PhysioNet)'),
}
SPLITS = ('train', 'validation', 'test')
SLOTS = ('physiomix', 'lsm')
EMBED_PER_DOMAIN, EMBED_BIDMC = 50, 111     # Fig. 9: 6 x 50 = 300 windows per source; BIDMC validation has 111
EXAMPLES_PER_GROUP = 1
CURVE_POINTS = 60
SEED = 20261023


# ---------------------------------------------------------------- helpers
def git_commit():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def r(v, digits=4):
    return None if v is None or not np.isfinite(v) else round(float(v), digits)


def sd(values):
    return float(np.std(values, ddof=1)) if len(values) > 1 else 0.


def indist(auc):
    return 100*(1-abs(2*auc-1))


def split_source(name):
    """'G1_flowgan_seed42' -> ('G1_flowgan', 42); fixed sources -> (name, None)."""
    m = re.fullmatch(r'(.+)_seed(\d+)', name)
    return (m.group(1), int(m.group(2))) if m else (name, None)


def label_of(group):
    return ARMS.get(group) or FIXED.get(group) or group


def thin(rows, n=CURVE_POINTS):
    if len(rows) <= n:
        return rows
    keep = np.unique(np.linspace(0, len(rows)-1, n).round().astype(int))
    return [rows[i] for i in keep]


def find_round(root, marker):
    """The folder holding marker (DECISION_STRICT.json / DECISION_FLOWGAN.json) below root, or None."""
    if root is None or not Path(root).exists():
        return None
    hits = sorted(Path(root).rglob(marker))
    return hits[0].parent if hits else None


# ---------------------------------------------------------------- data (Table I, Fig. 3a)
def load_pack(folder):
    with np.load(Path(folder)/'windows.npz', allow_pickle=False) as data:
        return {k: data[k] for k in data.files}


def dataset_table(pack, domains):
    rows, total = [], {s: int(np.isin(pack['domain'], domains)[pack['split'] == s].sum()) for s in SPLITS}
    for d in domains:
        m = pack['domain'] == d
        row = dict(domain=d, name=DOMAIN_INFO[d][0], setting=DOMAIN_INFO[d][1], source=DOMAIN_INFO[d][2])
        for s in SPLITS:
            k = m & (pack['split'] == s)
            row[s] = dict(people=int(len(np.unique(pack['subject'][k]))), windows=int(k.sum()),
                          share=r(100*k.sum()/max(total[s], 1), 2))
        hr = pack['reference_hr_bpm'][m]
        hr = hr[np.isfinite(hr)]
        row['hr_median'] = r(np.median(hr), 1) if len(hr) else None
        rhythm = pack['rhythm_label'][m]
        row['af_share'] = r(100*(rhythm == 1).mean(), 1) if (rhythm >= 0).any() else None
        rows.append(row)
    return dict(rows=rows, total=total)


def quality_of(x):
    from ml.kaggle_multidomain import artifact_sqi
    fraction = artifact_sqi.artifact_fraction(x)
    return fraction, [artifact_sqi.quality_group(f) for f in fraction]


def quality_groups():
    from ml.kaggle_multidomain import artifact_sqi
    return list(artifact_sqi.GROUPS)


def quality_section(pack, domains):
    """Fig. 3a: windows per artifact group, per domain and split, and AF vs non-AF cohorts (PERform) per split."""
    groups = quality_groups()
    keep = np.isin(pack['domain'], domains)
    fraction, labels = quality_of(pack['signal'][keep])
    labels = np.asarray(labels)
    dom, split, rhythm = pack['domain'][keep], pack['split'][keep], pack['rhythm_label'][keep]
    count = lambda m: {g: int((labels[m] == g).sum()) for g in groups}
    per_domain = {d: {s: count((dom == d) & (split == s)) for s in SPLITS} for d in domains}
    cohort = {s: dict(af=count((rhythm == 1) & (split == s)), non_af=count((rhythm == 0) & (split == s)))
              for s in SPLITS}
    mean_fraction = {d: {s: r(100*fraction[(dom == d) & (split == s)].mean(), 2) for s in SPLITS} for d in domains}
    return dict(groups=groups, per_domain=per_domain, cohort=cohort, mean_fraction=mean_fraction)


def mask_spans(mask, fs):
    """Boolean samples -> [[start_s, end_s], ...]."""
    edges = np.flatnonzero(np.diff(np.r_[0, mask.astype(int), 0]))
    return [[r(a/fs, 3), r(b/fs, 3)] for a, b in zip(edges[::2], edges[1::2])]


def examples_section(pack, fs):
    """Fig. 2: real validation/test windows of the AF and non-AF cohorts, one per artifact group, SQI spans shaded."""
    from ml.kaggle_multidomain import artifact_sqi
    groups = quality_groups()
    held = np.isin(pack['split'], ['validation', 'test'])
    out = {}
    for cohort, value in (('af', 1), ('non_af', 0)):
        ids = np.flatnonzero(held & (pack['rhythm_label'] == value))
        x = pack['signal'][ids]
        fraction = artifact_sqi.artifact_fraction(x)
        labels = np.asarray([artifact_sqi.quality_group(f) for f in fraction])
        mask = artifact_sqi.artifact_mask(x)
        picks = []
        for g in groups:
            where = np.flatnonzero(labels == g)
            if not len(where):
                picks.append(dict(group=g, missing=True))
                continue
            i = where[np.argmin(np.abs(fraction[where]-np.median(fraction[where])))]
            picks.append(dict(group=g, fraction=r(100*fraction[i], 1), domain=str(pack['domain'][ids[i]]),
                              values=[r(v, 3) for v in x[i]], spans=mask_spans(mask[i], fs)))
        out[cohort] = picks
    return out


# ---------------------------------------------------------------- judges (Table II, IV, Fig. 6, 8)
def summarise(rows, kind):
    """Per source group (app / reference / null / arm over its seeds): mean AUC, SDs, indistinguishable %, balanced
    accuracy, per-domain AUC and the judge's inner-AUC curve."""
    by = defaultdict(list)
    for row in rows:
        if row['judge'] == kind:
            by[split_source(row['source'])[0]].append(row)
    out = {}
    for group, items in by.items():
        auc = [x['auc'] for x in items]
        seeds = defaultdict(list)
        for x in items:
            seeds[split_source(x['source'])[1]].append(x['auc'])
        seed_means = {s: float(np.mean(v)) for s, v in seeds.items() if s is not None}
        domains = defaultdict(list)
        for x in items:
            for d, v in x.get('per_domain', {}).items():
                domains[d].append(v['auc'])
        curve = defaultdict(list)
        for x in items:
            for point in x.get('history', []):
                curve[point['step']].append(point['inner_auc'])
        mean = float(np.mean(auc))
        out[group] = dict(label=label_of(group), kind=KIND_OF.get(group, 'arm'), n=len(items), auc=r(mean),
                          auc_sd=r(sd(auc)), seed_sd=r(sd(list(seed_means.values()))) if seed_means else None,
                          indistinguishable=r(indist(mean), 2),
                          balanced_accuracy=r(np.mean([x['balanced_accuracy'] for x in items]), 2),
                          seeds={str(s): r(v) for s, v in sorted(seed_means.items())},
                          per_domain={d: dict(auc=r(np.mean(v)), sd=r(sd(v)), n=len(v)) for d, v in domains.items()},
                          curve=[[s, r(np.mean(v))] for s, v in sorted(curve.items())])
    return out


def judge_round(folder, decision_file):
    if folder is None:
        return None
    out = dict(folder=str(folder.relative_to(ROOT)) if folder.is_relative_to(ROOT) else str(folder),
               decision=load(folder/decision_file), splits={})
    for split in ('validation', 'test'):
        for slot in SLOTS:
            path = folder/split/slot/'judges.json'
            if not path.exists():
                continue
            rows = load(path)
            kinds = sorted({x['judge'] for x in rows})
            sets = load(folder/split/slot/'sets.json')
            out['splits'].setdefault(split, {})[slot] = dict(
                sets=sets, judges_sha256=sha(path)[:16], kinds=kinds, **{k: summarise(rows, k) for k in kinds})
    summary = folder/'summary.json'
    out['wall_hours'] = r(load(summary)['wall_seconds']/3600, 2) if summary.exists() else None
    return out


# ---------------------------------------------------------------- training (Table III, Fig. 7)
def history_curve(path, family):
    rows = load(path)
    if family == 'lsm':
        return [dict(step=x['step'], selection=r(x['selection']), acf_mmd2=r(x['validation']['acf_mmd2']),
                     log_psd_mmd2=r(x['validation']['log_psd_mmd2'])) for x in thin(rows)]
    out = []
    for x in thin(rows):
        point = dict(step=x['step'], checkpoint=r(x['checkpoint_score']), S_real=r(x['S_real']), C=r(x['C']))
        point.update({f'Q_{pool}': r(v['Q']) for pool, v in x.get('pools', {}).items()})
        out.append(point)
    return out


HYPER_KEYS = ('critic', 'lr', 'g_lr', 'd_clip', 'r1_weight', 'schedule', 'quiet', 'sensor', 'distill', 'distill_every',
              'student_steps', 'flowgan_sensor', 'lsm_loss', 'train_domains')


def training_section(folders):
    """Each training round's runs: config, chosen step, scores, gates; and their validation curves."""
    runs, curves = [], defaultdict(dict)
    for folder in folders:
        if folder is None:
            continue
        for path in sorted(Path(folder).rglob('training_execution.json')):
            for row in load(path):
                family = row.get('family') or ('lsm' if row['arm'].startswith('lsm') else 'physiomix')
                run_dir = (path.parent/row['generator']).parent if family == 'lsm' else \
                    path.parent/'benchmark'/f"{row['arm']}_seed{row['seed']}"
                cfg = row.get('config', {})
                entry = dict(arm=row['arm'], label=label_of(row['arm']), family=family, seed=row['seed'],
                             best_step=row.get('best_step'), parameters=row.get('generator_parameters'),
                             hours=r(row.get('training_seconds', 0)/3600, 2), eligible=row.get('eligible'),
                             S_real=r(row.get('S_real_fresh')), C=r(row.get('C_fresh')),
                             derivative_auc=r(row.get('c2st_derivative_auc')),
                             selection=r(row.get('selection', row.get('checkpoint_score'))),
                             gates=row.get('gates'), config={k: cfg[k] for k in HYPER_KEYS if k in cfg})
                if cfg.get('flowgan') and (run_dir/'best.pt').exists():
                    entry['sensor_sigma'] = flowgan_sigma(run_dir)
                runs.append(entry)
                if (run_dir/'history.json').exists():
                    curves[row['arm']][str(row['seed'])] = history_curve(run_dir/'history.json', family)
    return dict(runs=runs, curves=curves)


def flowgan_sigma(run_dir):
    """Learned per-domain sensor level sigma_d = SENSOR_MAX sigmoid(raw_d) of a flow-GAN run's chosen checkpoint
    (domain order from the run's conditions.json)."""
    import torch
    from ml.kaggle_multidomain.flow_gan import SENSOR_MAX
    raw = torch.load(run_dir/'best.pt', map_location='cpu', weights_only=True)['generator']['sensor_raw'].float()
    domains = load(run_dir/'conditions.json')['domains']
    if len(domains) != len(raw):
        raise ValueError(f'{run_dir}: {len(raw)} sensor levels for {len(domains)} domains')
    return {d: r(SENSOR_MAX*float(torch.sigmoid(v)), 4) for d, v in zip(domains, raw)}


# ---------------------------------------------------------------- synthetic windows (Fig. 2b, 3b, 9)
class Bank:
    """The v3 pack without its external split, the training-only condition bank and the prompt sampler."""
    def __init__(self, pack_root):
        from ml.kaggle_multidomain import strict_judge as sj
        from ml.kaggle_multidomain.data_gxu import load_input
        from ml.kaggle_multidomain.experiment_v3 import PROTOCOL, conditions_for
        pack, _ = load_input(str(pack_root), PROTOCOL)
        self.pack = {k: v[pack['split'] != 'external'] for k, v in pack.items()}
        keep = np.flatnonzero(np.isin(self.pack['split'], ['train', 'validation']))
        self.bank = sj.ConditionsView(conditions_for({k: v[keep] for k, v in self.pack.items()}, 'v2'), keep)

    def ids(self, split, domains, per_domain, rng):
        """Equal windows per domain, people weighted equally (strict_judge.sample)."""
        from ml.kaggle_multidomain import strict_judge as sj
        rows = np.flatnonzero((self.pack['split'] == split) & np.isin(self.pack['domain'], domains))
        return sj.sample(self.pack, rows, per_domain, rng, replace=False, domains=domains)


def first(folders, pattern):
    hits = sorted(p for f in folders if f is not None and Path(f).exists() for p in Path(f).rglob(pattern))
    return hits[0] if hits else None


def generators(bank, app_root, train_dirs, flow_dir, strict_decision, flow_decision):
    """name -> generate(ids, conditions, seed) for the app models, the strict round's best arms (their checkpoints in
    the training rounds' folders) and the flow-GAN ship seeds (when their folders exist)."""
    from ml.kaggle_multidomain import strict_judge as sj
    from ml.kaggle_multidomain.experiment_strict import app_sources, checkpoint_generator, unconditional_generator
    out = dict(app_sources(app_root, bank.bank, 'cpu'))
    width = len(bank.bank.domains)+5
    if strict_decision is not None:
        pm = strict_decision['physiomix']
        arm = pm['winner'] or min(pm['arms'], key=lambda a: pm['arms'][a]['mean_auc'])
        seed = pm['arms'][arm]['ship_seed']
        hit = first(train_dirs, f'benchmark/{arm}_seed{seed}/best.pt')
        if hit:
            out[f'{arm}_seed{seed}'] = checkpoint_generator(hit.parent, arm, bank.bank, 'cpu')
        lsm = strict_decision['lsm']
        arm = lsm['winner'] or lsm['candidate']
        seed = lsm['arms'][arm]['ship_seed']
        hit = first(train_dirs, f'lsm/{arm}_seed{seed}/generator_cpu.ts')
        if hit:
            out[f'{arm}_seed{seed}'] = unconditional_generator(hit)
    if flow_dir is not None and flow_decision is not None:
        for slot in SLOTS:
            d = flow_decision[slot]
            path = flow_dir/'benchmark'/f"{d['arm']}_seed{d['ship_seed']}"/'generator_cpu.ts'
            if d.get('ship_seed') is not None and path.exists():
                out[f"{d['arm']}_seed{d['ship_seed']}"] = sj.torchscript_generator(path, 'cpu', width)
    return out


def draw(generate, bank, prompt_ids, seed):
    from ml.kaggle_multidomain import strict_judge as sj
    return sj.normalise(generate(prompt_ids, bank.bank, seed))


def features(x, kind, fs):
    """Fig. 9 input: 'amplitude' = the window values (as the paper's PaCMAP); 'spectral' = log power 0.5-8 Hz and
    the autocorrelation to 2 s (phase-free)."""
    if kind == 'amplitude':
        return x
    centred = x-x.mean(1, keepdims=True)
    freq = np.fft.rfftfreq(x.shape[1], 1/fs)
    power = np.abs(np.fft.rfft(centred, axis=1))**2
    band = (freq >= .5) & (freq <= 8)
    log_power = np.log10(power[:, band]+1e-8)
    spectrum = np.fft.rfft(centred, n=2*x.shape[1], axis=1)
    acf = np.fft.irfft(np.abs(spectrum)**2, axis=1)[:, :int(2*fs)+1]
    acf = acf/np.maximum(acf[:, :1], 1e-12)
    return np.hstack([log_power, acf])


def embed(blocks, kind, fs):
    """One joint 2-D t-SNE of every block (so the grey background is shared); per block its coordinates."""
    from sklearn.manifold import TSNE
    from sklearn.preprocessing import StandardScaler
    names = list(blocks)
    x = np.vstack([features(blocks[n], kind, fs) for n in names])
    x = StandardScaler().fit_transform(x)
    y = TSNE(n_components=2, perplexity=30, init='pca', learning_rate='auto', random_state=0).fit_transform(x)
    y = (y-y.min(0))/np.maximum(np.ptp(y, 0), 1e-9)
    out, start = {}, 0
    for n in names:
        out[n] = [[r(a, 3), r(b, 3)] for a, b in y[start:start+len(blocks[n])]]
        start += len(blocks[n])
    return out


def synthetic_section(bank, gens, fs, domains):
    """Fig. 9 (embeddings), Fig. 3b (artifact groups of generated vs real windows) and Fig. 2b (one window each)."""
    from ml.kaggle_multidomain import artifact_sqi
    rng = np.random.default_rng(SEED)
    groups = quality_groups()
    rows = {}
    # Row A: six domains, 50 validation people's windows each; fakes prompted with training people's labels.
    real_a = bank.ids('validation', domains, EMBED_PER_DOMAIN, rng)
    prompts_a = bank.ids('train', domains, EMBED_PER_DOMAIN, rng)
    conditional = [n for n in gens if n not in ('lsm_app',) and not split_source(n)[0].startswith('lsm')]
    block_a = {'real': bank.pack['signal'][real_a]}
    for i, n in enumerate(conditional):
        block_a[n] = draw(gens[n], bank, prompts_a, SEED+i)
    rows['six_domains'] = block_a
    # Row B: BIDMC, the LSM-GAN slot (unconditional LSM-GANs; conditional models prompted with BIDMC labels).
    real_b = bank.ids('validation', ('bidmc',), EMBED_BIDMC, rng)
    prompts_b = bank.ids('train', ('bidmc',), EMBED_BIDMC, rng)
    block_b = {'real': bank.pack['signal'][real_b]}
    for i, n in enumerate(gens):
        if n == 'physiomix_app':
            continue
        block_b[n] = draw(gens[n], bank, prompts_b, SEED+100+i)
    rows['bidmc'] = block_b
    out = dict(rows={}, artifacts={}, examples={})
    for row, block in rows.items():
        out['rows'][row] = dict(labels={n: ('Thật' if n == 'real' else label_of(split_source(n)[0])
                                            + (f' · seed {split_source(n)[1]}' if split_source(n)[1] else ''))
                                        for n in block},
                                counts={n: int(len(v)) for n, v in block.items()},
                                amplitude=embed(block, 'amplitude', fs), spectral=embed(block, 'spectral', fs))
        shares = {}
        for n, x in block.items():
            labels = [artifact_sqi.quality_group(f) for f in artifact_sqi.artifact_fraction(x)]
            shares[n] = {g: r(100*labels.count(g)/len(labels), 1) for g in groups}
        out['artifacts'][row] = shares
    mask_of = lambda x: artifact_sqi.artifact_mask(x[None])[0]
    for n, x in rows['six_domains'].items():
        if n != 'real':
            out['examples'][n] = dict(values=[r(v, 3) for v in x[0]], spans=mask_spans(mask_of(x[0]), fs),
                                      domain=str(bank.pack['domain'][prompts_a[0]]))
    for n, x in rows['bidmc'].items():
        if n != 'real' and n not in out['examples']:
            out['examples'][n] = dict(values=[r(v, 3) for v in x[0]], spans=mask_spans(mask_of(x[0]), fs),
                                      domain='bidmc')
    out['examples_real'] = dict(values=[r(v, 3) for v in rows['six_domains']['real'][0]],
                                spans=mask_spans(mask_of(rows['six_domains']['real'][0]), fs),
                                domain=str(bank.pack['domain'][real_a[0]]))
    out['prompts'] = dict(six_domains='train people, 50 per domain', bidmc='train people, BIDMC')
    return out


# ---------------------------------------------------------------- main
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--pack', type=Path, default=RUNS/'physio3-data-v1')
    parser.add_argument('--app', type=Path, default=ROOT/'assets/neural')
    parser.add_argument('--strict-round', type=Path, default=RUNS/'strict-judge-round-result-v1')
    parser.add_argument('--strict-train', type=Path, nargs='*',
                        default=[RUNS/'strict-train-physiomix-result-v1', RUNS/'strict-train-lsm-result-v1'])
    parser.add_argument('--flowgan', type=Path, default=RUNS/'flowgan-round-result-v2')
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--no-synthetic', action='store_true', help='Skip Fig. 2b/3b/9 (no model sampling)')
    a = parser.parse_args(argv)
    warnings.filterwarnings('ignore', category=RuntimeWarning)
    from ml.kaggle_lsm.train_lsm import FS
    from ml.kaggle_multidomain.strict_judge import DOMAINS
    pack_dir = next(p.parent for p in a.pack.rglob('windows.npz'))
    pack = load_pack(pack_dir)
    strict_dir = find_round(a.strict_round, 'DECISION_STRICT.json')
    flow_dir = find_round(a.flowgan, 'DECISION_FLOWGAN.json')
    strict = judge_round(strict_dir, 'DECISION_STRICT.json')
    flow = judge_round(flow_dir, 'DECISION_FLOWGAN.json')
    data = dict(generated=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), commit=git_commit(),
                pack=dict(folder=str(pack_dir.relative_to(ROOT)), windows_sha256=load(pack_dir/'manifest.json')
                          ['windows_sha256'], fs=FS, length=int(pack['signal'].shape[1])),
                domains={d: DOMAIN_INFO[d][0] for d in DOMAINS},
                table1=dataset_table(pack, DOMAINS), quality=quality_section(pack, DOMAINS),
                examples=examples_section(pack, FS), strict=strict, flowgan=flow,
                training=training_section([*a.strict_train, flow_dir]))
    if not a.no_synthetic:
        bank = Bank(pack_dir.parent)
        gens = generators(bank, a.app, a.strict_train, flow_dir,
                          strict['decision'] if strict else None, flow['decision'] if flow else None)
        data['synthetic'] = synthetic_section(bank, gens, FS, DOMAINS)
    a.out.write_text('// Generated by scripts/build_gan_report.py; do not edit.\nwindow.GAN_REPORT = '
                     + json.dumps(data, ensure_ascii=False, separators=(',', ':'))+';\n')
    print('wrote', a.out, f'{a.out.stat().st_size/1e6:.2f} MB', 'strict:', bool(strict), 'flowgan:', bool(flow))


if __name__ == '__main__':
    main()
