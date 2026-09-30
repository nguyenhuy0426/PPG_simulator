"""Render measured audit results, with separate fit and validation evidence."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from core.neural_preview import NeuralPreview, gaussian_preview, reference_preview, export_preview
from ml.independent_ppg_eval import metrics


def main():
    out=Path('docs/morphology-audit')
    result=json.loads((out/'metrics.json').read_text())
    examples=np.load(out/'examples.npz')
    phase=np.linspace(0,1,256)
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,
                         'pdf.fonttype':42,'svg.fonttype':'none'})
    colors=['#009E73','#0072B2','#D55E00','#CC79A7']
    def save(fig,name):
        for extension in ('png','pdf'):
            fig.savefig(out/f'{name}.{extension}',dpi=220,bbox_inches='tight')
        plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(13,4.6),sharey=True,layout='constrained')
    matched={}
    profiles=json.loads(Path('assets/gaussian/profiles.json').read_text())['profiles']
    with np.load('ml/runs/kaggle-v1/ppg_run/prepared.npz') as data:
        for label,ax in zip(('With notch','No notch'),axes):
            real=examples['Real '+label]
            ax.plot(phase,real,color='black',lw=2.2,label='Real train exemplar')
            cond=data['condition'][profiles[label]['train_exemplar_index']].copy()
            cond[0]=.375
            matched[label]={}
            for i,(name,key) in enumerate((('Gaussian fitted',label),('TCN-FiLM','TCN-FiLM matched '+label),
                                          ('cWGAN-GP','cWGAN-GP matched '+label),('Gaussian original','Original'))):
                y=examples[key]
                row=metrics(y[None],cond[None],real[None])
                row.pop('development_score',None)
                row['waveform_rmse']=float(np.sqrt(np.mean((y-real)**2)))
                matched[label][name]=row
                ax.plot(phase,y,color=colors[i],ls=['--','-.',':',(0,(5,2))][i],lw=1.7,label=name)
            ax.set(xlabel='Pulse phase (cycle)',ylabel='Normalized amplitude (SP = 1)',
                   title=f'{label} · train #{profiles[label]["train_exemplar_index"]}',xlim=(0,1),ylim=(-.02,1.05))
            ax.legend(fontsize=9,loc='upper right')
    fig.suptitle('Same real target, HR 75 · neural seed 42\nGaussian was fitted to this train exemplar: fit evidence, not held-out accuracy',fontsize=12)
    save(fig,'matched-targets')
    (out/'matched-targets.json').write_text(json.dumps(matched,indent=2)+'\n')
    fig,axes=plt.subplots(1,3,figsize=(13,4.4),layout='constrained')
    groups=[['Gaussian (original)'],['Gaussian (fitted) class'],
            [f'cWGAN-GP seed {s}' for s in (42,43,44)],
            [f'TCN-FiLM seed {s}' for s in (42,43,44)]]
    labels=['Original','Fitted','cWGAN','TCN']
    for ax,key,title,scale in zip(axes,
        ('phase_acf_rmse','phase_log_psd_rmse','hf_absolute_error'),
        ('A · Autocorrelation error','B · Log-spectrum error','C · High-frequency power error'),(1,1,100)):
        vals=[np.array([result['results'][n][key]*scale for n in group]) for group in groups]
        ax.bar(labels,[v.mean() for v in vals],color=['#999999','#009E73','#D55E00','#0072B2'],alpha=.75)
        for i,v in enumerate(vals):
            ax.scatter(i+np.linspace(-.08,.08,len(v)),v,color='black',s=12,zorder=3)
        ax.set_title(title)
        ax.set_ylabel('Absolute difference (percentage points)' if scale==100 else 'RMSE (lower is better)')
        ax.set_ylim(bottom=0)
    fig.suptitle('Exploratory validation: 5,113 pulses / 7 subjects\nDots = inference seeds 42–44 for one checkpoint; not confidence intervals. No model wins all three.',fontsize=12)
    save(fig,'validation-criteria')
    fig,ax=plt.subplots(figsize=(10,5.5),layout='constrained')
    real=examples['Real With notch']
    ax.plot(phase*800,real,color='black',lw=2,label='Real train #16740 · time-scaled to HR 75')
    ax.plot(phase*800,examples['With notch'],color='#009E73',ls='--',lw=2,label='Gaussian fitted')
    d=result['examples']['Real With notch']
    for key,height,title,offset in [('sp_phase',1,'Systolic peak',(25,-5)),
                                   ('dn_phase',d['dn_height'],'Visible notch',(-80,-50)),
                                   ('dp_phase',d['dp_height'],'Diastolic peak',(35,30))]:
        x=d[key]*800
        ax.scatter([x],[height],color='black',s=30,zorder=5)
        ax.annotate(f'{title}\n{x:.0f} ms; {height:.3f}',xy=(x,height),xytext=offset,
                    textcoords='offset points',arrowprops=dict(arrowstyle='->'),fontsize=10)
    lo,hi=d['half_height_start']*800,d['half_height_end']*800
    ax.hlines(.5,lo,hi,color='#0072B2',lw=2)
    ax.annotate(f'FWHM {hi-lo:.0f} ms',((lo+hi)/2,.5),xytext=(0,12),textcoords='offset points',ha='center',color='#0072B2')
    ax.set(xlabel='Time (ms), illustrative HR 75',ylabel='Normalized amplitude (SP = 1)',
           xlim=(0,800),ylim=(-.08,1.18),title='A real reference example, not a universal physiological standard')
    ax.legend(loc='upper right',fontsize=9)
    save(fig,'landmarks')
    # Reproduce all five archived app modes, without post-filtering or inference
    # that calls an uneven LSM strip a disease. Same seed/order as original UI.
    previews=NeuralPreview().generate(42,75,'With notch','With notch')
    fig,axes=plt.subplots(5,1,figsize=(11,9),sharex=True,layout='constrained')
    for ax,name in zip(axes,('Gaussian (original)','Gaussian (fitted)','cWGAN-GP','LSM-GAN','TCN-FiLM')):
        a=np.array(previews[name].samples)
        mask=(a[:,0]>=19)&(a[:,0]<=23)
        ax.plot(a[mask,0],(a[mask,1]-1.5)/.045,color='#0072B2',lw=1.3)
        ax.set(title=name,ylabel='Amplitude',ylim=(-.03,1.06))
    axes[-1].set_xlabel('Time (s)')
    fig.suptitle('Original app settings: seed 42, HR request 75, With notch\nLSM: native 40 Hz, no HR/notch control. Neural and fitted presets originally targeted different pulses.',fontsize=12)
    save(fig,'five-modes')
    export_preview(gaussian_preview(75,'With notch'),out/'fitted.csv')
    export_preview(reference_preview(75,'With notch'),out/'real-reference.csv')
    print('Saved matched targets, all three criteria, landmarks, five modes, and trace CSVs.')


if __name__=='__main__':
    main()
