"""Which interpretable features separate real from generated v3 windows (the strict judge's likely cues).

Per domain and per generator: the AUC of each hand feature between real validation windows and generated windows
prompted with training people's conditions (|AUC-0.5| large = a leak), the same for real windows of other (training)
people as a null, and a gradient-boosting C2ST on all features (how much of the judge's AUC they explain).
Engineering diagnostic of normalised 30 s PPG shape; no waveform is written.

  python3 scripts/leak_features.py --out ml/runs/leak-features-v1.json
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'scripts'))

from build_gan_report import RUNS, Bank, draw  # noqa: E402

PER_DOMAIN = 128
SEED = 20261024
BANDS = ((.5, 1), (1, 1.5), (1.5, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8))


def beats(x, fs):
    """Pulse onsets (feet) of one window: minima between systolic peaks found by scipy.signal.find_peaks."""
    from scipy.signal import find_peaks
    peaks, _ = find_peaks(x, distance=int(.33*fs), prominence=.15)
    feet = [a+np.argmin(x[a:b]) for a, b in zip(peaks[:-1], peaks[1:])]
    return peaks, np.asarray(feet, int)


def window_features(x, fs):
    """name -> value for one min-max normalised window."""
    from scipy.stats import kurtosis, skew
    f = {}
    c = x-x.mean()
    freq = np.fft.rfftfreq(len(x), 1/fs)
    p = np.abs(np.fft.rfft(c))**2
    total = p[(freq >= .5) & (freq <= 8)].sum()+1e-12
    for lo, hi in BANDS:
        f[f'band_{lo:g}_{hi:g}'] = np.log10(p[(freq >= lo) & (freq < hi)].sum()/total+1e-12)
    band = p[(freq >= .5) & (freq <= 8)]+1e-12
    f['spectral_flatness'] = np.exp(np.log(band).mean())/band.mean()
    q = band/band.sum()
    f['spectral_entropy'] = -(q*np.log(q)).sum()
    k = np.argmax(np.where((freq >= .6) & (freq <= 3.5), p, 0))
    f['f0_hz'] = freq[k]
    f['f0_peak_share'] = p[max(k-2, 0):k+3].sum()/total
    h2 = np.argmin(np.abs(freq-2*freq[k]))
    f['h2_over_h1'] = np.log10(p[max(h2-2, 0):h2+3].sum()/(p[max(k-2, 0):k+3].sum()+1e-12)+1e-12)
    d1, d2 = np.diff(x), np.diff(x, 2)
    f['diff1_std'] = d1.std()
    f['diff2_std'] = d2.std()
    f['diff2_over_diff1'] = d2.std()/(d1.std()+1e-12)
    f['mean'], f['median'] = x.mean(), np.median(x)
    f['skew'], f['kurtosis'] = skew(x), kurtosis(x)
    f['upslope_share'] = (d1 > 0).mean()
    acf = np.fft.irfft(np.abs(np.fft.rfft(c, n=2*len(x)))**2)[:int(2*fs)+1]
    acf = acf/max(acf[0], 1e-12)
    lo = int(.3*fs)
    f['acf_peak'] = acf[lo:].max()
    f['acf_min'] = acf[:int(1.5*fs)].min()
    peaks, feet = beats(x, fs)
    f['n_peaks'] = len(peaks)
    if len(peaks) >= 4:
        ibi = np.diff(peaks)/fs
        f['ibi_cv'] = ibi.std()/ibi.mean()
        f['ibi_rmssd'] = np.sqrt(np.mean(np.diff(ibi)**2))
        amp = x[peaks]
        f['peak_amp_cv'] = amp.std()/(amp.mean()+1e-12)
    else:
        f['ibi_cv'] = f['ibi_rmssd'] = f['peak_amp_cv'] = np.nan
    if len(feet) >= 4:
        n = int(np.median(np.diff(feet)))
        segs = np.stack([np.interp(np.linspace(a, b, 64), np.arange(len(x)), x)
                         for a, b in zip(feet[:-1], feet[1:]) if b-a >= .3*fs])
        segs = (segs-segs.mean(1, keepdims=True))/(segs.std(1, keepdims=True)+1e-9)
        tmpl = segs.mean(0)
        corr = (segs*tmpl).mean(1)
        f['beat_template_corr'] = corr.mean()
        f['beat_template_corr_sd'] = corr.std()
        f['beat_consecutive_corr'] = (segs[1:]*segs[:-1]).mean(1).mean() if len(segs) > 1 else np.nan
        top = np.argmax(tmpl)
        f['beat_peak_pos'] = top/64
        f['beat_late_bump'] = tmpl[top+8:].max()-tmpl[top+8:].min() if top+8 < 64 else np.nan
        f['beat_len_s'] = n/fs
    else:
        for name in ('beat_template_corr', 'beat_template_corr_sd', 'beat_consecutive_corr', 'beat_peak_pos',
                     'beat_late_bump', 'beat_len_s'):
            f[name] = np.nan
    return f


def table(x, fs):
    rows = [window_features(w, fs) for w in x]
    names = list(rows[0])
    return names, np.array([[r[n] for n in names] for r in rows], float)


def auc(a, b):
    """AUC that b scores higher than a (NaNs dropped)."""
    from sklearn.metrics import roc_auc_score
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 10 or len(b) < 10:
        return None
    return float(roc_auc_score(np.r_[np.zeros(len(a)), np.ones(len(b))], np.r_[a, b]))


def c2st(a, b, groups_a, groups_b, seed):
    """5-fold gradient-boosting AUC on all features (real a vs b), folds split by person (a person's windows, or the
    windows prompted with that person's conditions, never on both sides of a fold: no identity memorisation)."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.model_selection import cross_val_predict, StratifiedGroupKFold
    from sklearn.metrics import roc_auc_score
    x, y = np.vstack([a, b]), np.r_[np.zeros(len(a)), np.ones(len(b))]
    groups = np.r_[[f'a:{g}' for g in groups_a], [f'b:{g}' for g in groups_b]]
    folds = min(5, len(set(groups_a)), len(set(groups_b)))
    if folds < 2:
        return None
    p = cross_val_predict(HistGradientBoostingClassifier(max_iter=200, random_state=seed), x, y, groups=groups,
                          cv=StratifiedGroupKFold(folds, shuffle=True, random_state=seed), method='predict_proba')[:, 1]
    return float(roc_auc_score(y, p))


def main(argv=None):
    from ml.kaggle_lsm.train_lsm import FS
    from ml.kaggle_multidomain import strict_judge as sj
    from ml.kaggle_multidomain.experiment_strict import app_sources, sensor_finished
    parser = argparse.ArgumentParser()
    parser.add_argument('--pack', type=Path, default=RUNS/'physio3-data-v1')
    parser.add_argument('--app', type=Path, default=ROOT/'assets/neural')
    parser.add_argument('--flowgan', type=Path, default=RUNS/'flowgan-round-result-v2')
    parser.add_argument('--out', type=Path, default=RUNS/'leak-features-v1.json')
    a = parser.parse_args(argv)
    bank = Bank(a.pack)
    gens = dict(app_sources(a.app, bank.bank, 'cpu'))
    gens['physioflow_sensor'] = sensor_finished(gens['physioflow_app'])
    width = len(bank.bank.domains)+5
    for ts in sorted(a.flowgan.rglob('G1_flowgan_seed123/generator_cpu.ts')):
        gens['G1_flowgan_seed123'] = sj.torchscript_generator(ts, 'cpu', width)
    del gens['lsm_app']
    rng = np.random.default_rng(SEED)
    out = dict(per_domain=PER_DOMAIN, domains={})
    for d in sj.DOMAINS:
        subject = bank.pack['subject']
        real_ids = bank.ids('validation', (d,), PER_DOMAIN, rng)
        other_ids = bank.ids('train', (d,), PER_DOMAIN, rng)
        prompts = bank.ids('train', (d,), PER_DOMAIN, rng)
        names, f_real = table(bank.pack['signal'][real_ids], FS)
        blocks = {'real_other_people': (table(bank.pack['signal'][other_ids], FS)[1], subject[other_ids])}
        for i, (n, g) in enumerate(gens.items()):
            blocks[n] = (table(draw(g, bank, prompts, SEED+i), FS)[1], subject[prompts])
        res = {}
        for n, (f_fake, groups) in blocks.items():
            per = {k: auc(f_real[:, j], f_fake[:, j]) for j, k in enumerate(names)}
            top = sorted((k for k in per if per[k] is not None), key=lambda k: -abs(per[k]-.5))[:8]
            med = {k: [float(np.nanmedian(f_real[:, names.index(k)])), float(np.nanmedian(f_fake[:, names.index(k)]))]
                   for k in top}
            score = c2st(np.nan_to_num(f_real), np.nan_to_num(f_fake), subject[real_ids], groups, SEED)
            res[n] = dict(c2st_features=score, feature_auc=per,
                          top=top, median_real_fake=med)
        out['domains'][d] = res
        print(d, {n: v['c2st_features'] and round(v['c2st_features'], 3) for n, v in res.items()}, flush=True)
    a.out.write_text(json.dumps(out, indent=1))
    print('wrote', a.out)


if __name__ == '__main__':
    main()
