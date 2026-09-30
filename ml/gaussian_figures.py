"""Plot train fit references and separately measured validation errors."""
import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from models.waveform import PulseMorphology, PulseShaper, WAVE_PPG


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,default=Path("ml/runs/gaussian-fit-final"))
    parser.add_argument("--output",type=Path,default=Path("docs/gaussian-fit"))
    args=parser.parse_args()
    profiles=json.loads((args.run/"profiles.json").read_text())["profiles"]
    report=json.loads((args.run/"metrics.json").read_text())
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"metrics.json").write_text(json.dumps(report,indent=2)+"\n")
    results=report["results"]
    fields=("waveform_rmse","phase_acf_rmse","phase_log_psd_rmse","above_5hz_power_fraction","real_above_5hz_power_fraction")
    with (args.output/"comparison.csv").open("w",newline="") as f:
        writer=csv.writer(f);writer.writerow(["model",*fields])
        for name,row in results.items():writer.writerow([name,*[row[k] for k in fields]])
    phase=np.linspace(0,1,256)
    original=PulseShaper()
    old=np.array([original.sample(WAVE_PPG,float(t)) for t in phase])
    plt.rcParams.update({"font.size":9,"axes.spines.top":False,"axes.spines.right":False,"pdf.fonttype":42})
    fig,axes=plt.subplots(2,3,figsize=(12,7.3))
    for ax,(name,row),letter in zip(axes[0],profiles.items(),"ABC"):
        shaper=PulseShaper(PulseMorphology(**row["morphology"]))
        y=np.array([shaper.sample(WAVE_PPG,float(t)) for t in phase])
        label="Train subject-balanced mean" if name=="Balanced" else f"Real train pulse {row['train_exemplar_index']}"
        ax.plot(phase,row["reference_waveform"],color="black",lw=2,label=label)
        ax.plot(phase,old,color="#E69F00",ls=":",lw=1.8,label="Original")
        ax.plot(phase,y,color="#0072B2",ls="--",lw=1.7,label="Fitted 3-Gaussian")
        ax.set(title=f"{letter}  Train fit: {name}",xlabel="Cycle phase",ylabel="Normalized amplitude",ylim=(-.03,1.06))
        ax.legend(fontsize=7,frameon=False)
    labels=["Original","Fitted\nbalanced","Fitted\nclass presets"]
    for ax,field,title,scale in zip(axes[1],fields[1:4],
            ("D  Validation ACF error","E  Validation log-spectrum error","F  Validation power above 5 Hz"),(1,1,100)):
        values=[v[field]*scale for v in results.values()]
        ax.bar(labels,values,color=["#E69F00","#0072B2","#009E73"],alpha=.65,width=.6)
        for i,row in enumerate(results.values()):
            points=[v[field]*scale for v in row["by_subject"].values()]
            ax.scatter(i+np.linspace(-.14,.14,len(points)),points,color="black",s=13,zorder=3)
        if scale==100:
            target=next(iter(results.values()))["real_above_5hz_power_fraction"]*100
            ax.axhline(target,color="black",ls="--",label=f"Real {target:.3f}%")
            ax.legend(frameon=False,fontsize=8)
        ax.set(title=title,ylabel="Power (%)" if scale==100 else "RMSE",ylim=(0,None))
    fig.suptitle(f"Three-Gaussian fit · unchanged formula · {report['samples']:,} validation pulses / {report['subjects']} subjects",fontsize=13)
    fig.text(.5,.015,"A–C show training references, not held-out examples. D–F: pooled metrics; dots are subjects, not confidence intervals.\n"
             "Parameters fitted on train only. Exploratory comparison; no external-test or optical-validation claim.",ha="center",fontsize=8)
    fig.tight_layout(rect=(0,.065,1,.96))
    fig.savefig(args.output/"comparison.png",dpi=300)
    fig.savefig(args.output/"comparison.pdf")
    plt.close(fig)
    # An unselected, full validation view: patient means and fixed balanced fit.
    with np.load(args.run/"samples.npz",allow_pickle=False) as data:
        real=data["reference"];fitted=data["Fitted balanced"][0]
    fig,ax=plt.subplots(figsize=(8,3.7))
    lo,hi=np.percentile(real,[10,90],axis=0)
    ax.fill_between(phase,lo,hi,color="gray",alpha=.2,label="Real validation 10–90% range")
    ax.plot(phase,real.mean(0),color="black",label="Real validation mean")
    ax.plot(phase,old,color="#E69F00",ls=":",label="Original")
    ax.plot(phase,fitted,color="#0072B2",ls="--",label="Fitted balanced")
    ax.set(xlabel="Cycle phase",ylabel="Normalized amplitude",title="Validation population: one preset cannot cover all morphology")
    ax.legend(fontsize=8,frameon=False)
    fig.tight_layout();fig.savefig(args.output/"validation.png",dpi=300);plt.close(fig)


if __name__=="__main__":
    main()
