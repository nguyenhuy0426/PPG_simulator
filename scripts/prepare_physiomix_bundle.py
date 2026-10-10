#!/usr/bin/env python3
"""Package a validation-selected PhysioMix generator for the Neural page (CPU, TorchScript).

The seed is chosen by validation score only. The Kaggle TorchScript export is checked against
the EMA checkpoint rebuilt from source, then re-traced with the local torch. Domain defaults,
the supported HR range and the reference strips come from TRAIN windows only.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CARRIER_BPM = (54., 198.)  # PhysioMix clamps its periodic prior to 0.9-3.3 Hz.


def load_pack(path):
    with np.load(Path(path)/'windows.npz', allow_pickle=False) as data:
        pack = {k: data[k] for k in ('signal', 'domain', 'split', 'record', 'start', 'subject')}
    manifest = json.loads((Path(path)/'manifest.json').read_text())
    return pack, manifest


def train_statistics(pack, domains, version='v1'):
    from ml.kaggle_multidomain.benchmark import morphology
    from ml.kaggle_multidomain.data_gxu import EDGE_EXCESS_MAX, edge_excess
    train = np.flatnonzero(pack['split'] == 'train')
    x = pack['signal'][train]
    m = morphology(x)
    ok = (edge_excess(x) <= EDGE_EXCESS_MAX) & (m[:, 0] >= 35) & (m[:, 0] <= 200)
    defaults, strips = {}, {}
    for domain in domains:
        rows = np.flatnonzero(ok & (pack['domain'][train] == domain))
        if len(rows) < 10:
            raise ValueError(f'Too few clean training windows for {domain}')
        rate, cv, std = (np.median(m[rows, k]) for k in (0, 1, 4))
        defaults[domain] = [float(cv), float(std)]
        best = rows[np.argmin(abs(m[rows, 0]-rate))]
        index = int(train[best])
        strips[domain] = dict(split='train', domain=domain, record=str(pack['record'][index]),
                              start_sample_40hz=int(pack['start'][index]), proxy_rate_bpm=float(m[best, 0]),
                              waveform=[round(float(v), 6) for v in pack['signal'][index]])
    rates = m[ok, 0]
    if version == 'v2':
        from ml.kaggle_multidomain.labels import robust_labels
        rates = robust_labels(x)[0]
        rates = rates[np.isfinite(rates)]
    lo = max(CARRIER_BPM[0], 5*np.floor(np.quantile(rates, .01)/5))
    hi = min(CARRIER_BPM[1], 5*np.ceil(np.quantile(rates, .99)/5))
    return defaults, strips, [float(lo), float(hi)]


def choose_run(run, arm):
    """v1 rounds: lowest validation score; v3 rounds: lowest fresh-seed S_arm among gate-eligible seeds."""
    if (run/'selection.json').exists():
        rows = [r for r in json.loads((run/'selection.json').read_text())['runs'] if r['arm'] == arm]
        return min(rows, key=lambda r: r['validation_score']), 'validation_score'
    rows = [r for r in json.loads((run/'training_execution.json').read_text())['runs']
            if r['arm'] == arm and r.get('eligible')]
    if not rows:
        raise ValueError(f'No gate-eligible {arm} runs in {run}')
    return min(rows, key=lambda r: r['S_arm']), 'S_arm'


def build_model(model_class, conditions, checkpoint):
    """Rebuild from source; v3 checkpoints record their own architecture flags."""
    import importlib
    cfg = checkpoint.get('config')
    if cfg is None:
        module, name = model_class.split(':')
        return getattr(importlib.import_module(module), name)(conditions['size'], conditions['center'], conditions['scale']), None
    from ml.kaggle_multidomain import physio
    cls = physio.PhysioMixH if cfg.get('osc') else physio.PhysioMix
    return cls(conditions['size'], conditions['center'], conditions['scale'], view='v3'), cfg


def prepare(run, arm, pack_dir, output, model_class, variant):
    import torch
    chosen, key = choose_run(run, arm)
    source = run/f"{arm}_seed{chosen['seed']}"
    conditions = json.loads((source/'conditions.json').read_text())
    checkpoint = torch.load(source/'best.pt', map_location='cpu', weights_only=True)
    model, cfg = build_model(model_class, conditions, checkpoint)
    model.load_state_dict(checkpoint['generator'])
    model.eval()
    exported = torch.jit.load(str(source/'generator_cpu.ts'), map_location='cpu').eval()
    rng = torch.Generator().manual_seed(1234)
    z = torch.randn(4, 1200, generator=rng)
    pack, pack_manifest = load_pack(pack_dir)
    domains = conditions['domains']
    version = conditions.get('version', 'v1')
    defaults, strips, support = train_statistics(pack, domains, version)
    if version == 'v2':
        defaults = conditions['domain_defaults']
    data_support = support
    if cfg and cfg.get('osc'):
        support = [40., 180.]  # rate is constructed; morphology outside data_support is extrapolated
    condition = torch.zeros(4, conditions['size'])
    for i, domain in enumerate(domains[:4]):
        condition[i, domains.index(domain)] = 1
        if version == 'v2':
            condition[i, len(domains):len(domains)+2] = 1
        raw = torch.tensor([75.+15*i, *defaults[domain]])
        condition[i, -3:] = (raw-torch.tensor(conditions['center']))/torch.tensor(conditions['scale'])
    with torch.no_grad():
        torch.testing.assert_close(exported(z, condition), model(z, condition), atol=1e-5, rtol=1e-4)
        traced = torch.jit.trace(model, (z[:2], condition[:2]))
        torch.testing.assert_close(traced(z, condition), model(z, condition), atol=1e-5, rtol=1e-4)
    output.mkdir(parents=True, exist_ok=True)
    target = output/'physiomix_generator.ts'
    traced.save(str(target))
    manifest_path = output/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['models']['physiomix_generator'] = dict(file=target.name,
                                                     sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    manifest['physiomix'] = dict(
        variant=variant, arm=arm, seed=chosen['seed'], best_step=chosen['best_step'],
        validation_score=chosen[key], selection=f'lowest {key} among seeds (validation only); no test data',
        condition_version=version, architecture=cfg, data_support_bpm=data_support,
        preprocessing=pack_manifest.get('base_manifest', {}).get('preprocessing') if version == 'v1'
        else 'v3 view: 0.5–8 Hz zero-phase Butterworth, per-window normalized 30 s at 40 Hz',
        domains=domains, center=conditions['center'], scale=conditions['scale'],
        features=conditions['features'], domain_defaults=defaults, domain_defaults_features=['PPG_ibi_cv', 'PPG_signal_std'],
        hr_support_bpm=support, hr_support_rule=('constructed beat sequence 40-180 bpm; data_support_bpm = train label 1-99%'
                                                 if cfg and cfg.get('osc') else
                                                 'train proxy-rate 1-99% quantiles within the 54-198 bpm carrier clamp'),
        checkpoint_sha256=hashlib.sha256((source/'best.pt').read_bytes()).hexdigest(),
        kaggle_export_sha256=hashlib.sha256((source/'generator_cpu.ts').read_bytes()).hexdigest(),
        traced_with_torch=torch.__version__, pack_sha256=pack_manifest['windows_sha256'],
        label_type=conditions['label_type'],
        note='Exploratory research generator. Normalized 30 s shape at 40 Hz; no calibrated AC/DC, SpO2 or paired IR/RED.')
    manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')
    (output/'physiomix_real_strips.json').write_text(json.dumps(dict(
        pack_sha256=pack_manifest['windows_sha256'], rule='train split; edge-clean; proxy rate nearest domain median',
        strips=strips), indent=1)+'\n')
    print(f"Packaged {arm} seed {chosen['seed']} ({key} {chosen[key]:.4f}); HR support {support}")
    return manifest['physiomix']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=ROOT/'ml/runs/physiomix-result-v1/physiomix/benchmark')
    parser.add_argument('--arm', default='physiomix_no_div')
    parser.add_argument('--pack', type=Path, default=ROOT/'ml/runs/physiomix-prepared-kaggle-v1/physio_data')
    parser.add_argument('--output', type=Path, default=ROOT/'assets/neural')
    parser.add_argument('--model-class', default='ml.kaggle_multidomain.physio:PhysioMix')
    parser.add_argument('--variant', default='physiomix_v1_no_div')
    a = parser.parse_args()
    prepare(a.run, a.arm, a.pack, a.output, a.model_class, a.variant)
