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
    # Fixed first validation strip / first seed: no selection for visual appeal.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,3,figsize=(14,7),layout='constrained')
    groups=[('Real validation',real,'#245e65'),('LSM v2',generated,'#c36638'),
            ('Gaussian 75 bpm',fixed,'#746285')]
    for i,(label,rows,color) in enumerate(groups):
        axes[0,0].plot(np.arange(1200)/40,rows[0]+i*1.2,color=color,label=label,lw=.8)
        f=features(rows)
        axes[0,1].plot(np.arange(1,201)/40,f[0].mean(0),color=color,label=label)
        axes[0,2].plot(np.arange(1,201)*.1,f[1].mean(0),color=color,label=label)
    axes[0,0].set(xlim=(0,12),xlabel='Time (s)',ylabel='Normalized amplitude + offset',title='Fixed examples (not paired)')
    axes[0,1].set(xlabel='Lag (s)',ylabel='Mean normalized ACF',title='Autocorrelation')
    axes[0,2].set(xlabel='Frequency (Hz)',ylabel='Mean log10 normalized power',title='Welch spectrum')
    axes[0,0].legend(fontsize=8)
    keys=['real_validation','lsm_v2','fixed_gaussian_75']
    for ax,key,title in [(axes[1,0],'ibi_cv_p10_p50_p90','Inter-peak interval CV'),
                         (axes[1,1],'peak_amplitude_cv_p10_p50_p90','Peak amplitude CV')]:
        for i,(label,_,color) in enumerate(groups):
            lo,mid,hi=result[keys[i]][key]
            ax.errorbar(i,mid,yerr=[[mid-lo],[hi-mid]],fmt='o',color=color,capsize=5)
        ax.set(xticks=range(3),xticklabels=['Real','LSM v2','Gaussian'],ylabel='CV (median; p10–p90)',title=title)
    axes[1,2].bar(['Real','LSM v2','Gaussian'],[100*result[k]['above_5hz_power_fraction_mean'] for k in keys],color=[g[2] for g in groups])
    axes[1,2].set(yscale='log',ylabel='Power above 5 Hz (%)',title='High-frequency energy')
    for ax in axes.flat:
        ax.grid(alpha=.2)
    fig.suptitle('Exploratory: test previously viewed | Real preprocessed 0.9–5 Hz | Gaussian HR distribution unmatched',fontsize=11)
    fig.savefig(args.output/'comparison.png',dpi=180)
    fig.savefig(args.output/'comparison.pdf')
    plt.close(fig)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
