"""Frozen-checkpoint sequence audit; no training and no test-set selection."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.signal import find_peaks
from core.neural_preview import LSMSequenceGenerator, gaussian_preview
from ml.kaggle_lsm.train_lsm import features, describe


def variability(rows):
    ibi_cv, amplitude_cv, peak_counts = [], [], []
    for row in rows:
        peaks,_=find_peaks(row,distance=10,prominence=.15)
        peak_counts.append(len(peaks))
        if len(peaks)>2:
            ibi=np.diff(peaks)/40
            ibi_cv.append(float(ibi.std()/ibi.mean()))
            amplitude_cv.append(float(row[peaks].std()/max(row[peaks].mean(),1e-9)))
    return dict(algorithm='find_peaks distance=10 at 40 Hz; prominence=.15; heuristic, not clinical HRV',
                valid_strips=len(ibi_cv), peak_count_median=float(np.median(peak_counts)),
                ibi_cv_p10_p50_p90=np.quantile(ibi_cv,[.1,.5,.9]).tolist(),
                peak_amplitude_cv_p10_p50_p90=np.quantile(amplitude_cv,[.1,.5,.9]).tolist())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=Path('ml/runs/lsm-kaggle-v2/lsm_comparison/windows.npz'))
    parser.add_argument('--output',type=Path,default=Path('docs/sequence-audit'))
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    data=np.load(args.data,allow_pickle=False)
    real=data['signal'][data['validation']]
    generator=LSMSequenceGenerator()
    seeds=list(range(1000,1064))
    generated=np.asarray([[(r[1]-1.5)/.045 for r in generator.generate(seed).samples] for seed in seeds])
    p=gaussian_preview(75,'With notch')
    fixed=np.interp(np.arange(1200)/40,np.asarray(p.samples)[:,0],(np.asarray(p.samples)[:,1]-1.5)/.045)[None]
    ref=features(real)
    result=dict(exploratory=True, no_retraining=True, no_checkpoint_selection=True,
                validation_strips=len(real),validation_subjects=len(set(data['subject'][data['validation']])),
                model_sha256=generator.sha256,windows_sha256=hashlib.sha256(args.data.read_bytes()).hexdigest(),seeds=seeds,
                caveats=['Test previously viewed; exploratory', 'Real reference is 0.9–5 Hz preprocessed BIDMC, not raw PPG',
                         'Fixed 75-bpm Gaussian is a control, not a distribution-matched competitor',
                         'Peak variability alone does not prove human physiology; 30 s is not long-term HRV'])
    for name,rows in [('real_validation',real),('lsm_v2',generated),('fixed_gaussian_75',fixed)]:
        f=features(rows)
        result[name]=dict(**describe(rows),**variability(rows),
                         mean_acf_rmse=float(np.sqrt(np.mean((f[0].mean(0)-ref[0].mean(0))**2))),
                         mean_log_psd_rmse=float(np.sqrt(np.mean((f[1].mean(0)-ref[1].mean(0))**2))))
    (args.output/'metrics.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
