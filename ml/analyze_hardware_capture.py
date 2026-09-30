"""Describe measured A0 against commanded TX; never treat TX as a voltage measurement."""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.signal import detrend
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture',type=Path)
    path=parser.parse_args().capture
    summary=json.loads((path/'summary.json').read_text())
    rx=np.genfromtxt(path/'rx_a0.csv',delimiter=',',names=True,dtype=None,encoding='utf8')
    tx=np.genfromtxt(path/'tx_commanded.csv',delimiter=',',names=True)
    t=rx['monotonic_s']-summary['output_start_monotonic_s']
    mask=(t>2)&(t<28)
    measured=detrend(rx['raw'][mask].astype(float))
    lags=np.arange(-.25,.251,.01)
    correlations=[float(np.corrcoef(measured,detrend(np.interp(t[mask]-lag,tx['time_s'],tx['ir_v'])))[0,1]) for lag in lags]
    best=int(np.argmax(np.abs(correlations)))
    result=dict(interval_s=[2,28],detrended=True,lag_search_s=[-.25,.25],lag_step_s=.01,
                maximum_absolute_correlation=abs(correlations[best]),signed_correlation=correlations[best],
                lag_s=float(lags[best]),interpretation='Descriptive lag search, not statistical significance or proof of optical fidelity.')
    (path/'correlation.json').write_text(json.dumps(result,indent=2)+'\n')
    fig,axes=plt.subplots(3,1,figsize=(11,8),layout='constrained')
    axes[0].plot(tx['time_s'],tx['ir_v']*1000,label='IR commanded',color='#245e65')
    axes[0].plot(tx['time_s'],tx['red_v']*1000,label='RED commanded',color='#c36638')
    axes[0].set(ylabel='Command (mV)',title='LSM v2 seed 42 on Pi 4 — commanded TX is not measured voltage')
    axes[0].legend()
    axes[1].plot(t,rx['raw'],color='#245e65',lw=.7)
    axes[1].axvspan(0,30,color='#c36638',alpha=.1,label='Output interval')
    axes[1].set(xlabel='Seconds from start request',ylabel='Grove A0 raw ADC',title='Physical OPT101 A0 capture; A2 disabled')
    axes[1].legend()
    axes[2].plot(lags,correlations,color='#746285')
    axes[2].set(xlabel='TX lag (s)',ylabel='Pearson r',ylim=(-1,1),title=f'Interior 2–28 s, detrended; max |r| = {abs(correlations[best]):.4f}')
    for ax in axes:ax.grid(alpha=.2)
    fig.savefig(path/'capture.png',dpi=160)
    plt.close(fig)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
