#!/usr/bin/env python3
"""Explicit 30 s bench output plus A0 capture. Parks both DACs in finally.
Run only when the user has authorized LED output and no other app owns I2C TX.
"""
import argparse
import csv
import json
from pathlib import Path
import statistics
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from config import DRY_RUN
from core.neural_preview import LSMSequenceGenerator, gaussian_preview
from core.waveform_clip import WaveformClip
from core.signal_engine import SignalEngine
from hw.opt101_rx import OPT101Receiver


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',choices=['gaussian','lsm'],default='lsm')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    if DRY_RUN:raise SystemExit('Hardware verifier refuses DRY RUN')
    t=time.monotonic()
    preview=LSMSequenceGenerator().generate(42) if args.source=='lsm' else gaussian_preview(75,'With notch')
    inference_s=time.monotonic()-t
    clip=WaveformClip.from_preview(preview)
    engine=SignalEngine();rx=OPT101Receiver(enabled_channels=(0,))
    received=[];tx=[];last_rx=-1.;last_tx=-1.
    def capture(seconds,phase):
        nonlocal last_rx,last_tx
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            for sample in rx.get_samples(0):
                if sample.timestamp>last_rx:
                    received.append((phase,*sample));last_rx=sample.timestamp
            if phase=='output':
                for row in engine.get_display_history():
                    if row[0]>last_tx:tx.append(row);last_tx=row[0]
            time.sleep(.02)
    try:
        engine.begin()
        if not engine.dac_manager.is_ready:raise RuntimeError('DAC unavailable')
        if not rx.begin():raise RuntimeError('ADC unavailable')
        rx.start();capture(2,'before')
        engine.start_waveform(clip);capture(31,'output')
        engine.stop_simulation();capture(2,'after')
        result=dict(source=args.source,seed=preview.seed,model_sha256=preview.model_sha256,
                    inference_seconds=inference_s,dry_run=False,rx_enabled=[0],rx_a2_status=rx.channel_status(2),
                    rx_a2_count=rx.sample_count(2),engine=engine.get_stats(),
                    dac_write_errors_ir=engine.dac_manager.error_count_ir,
                    dac_write_errors_red=engine.dac_manager.error_count_red,
                    dac_final_codes=[engine.dac_manager.last_ir,engine.dac_manager.last_red],
                    adc_errors=rx.error_count(0),adc_saturations=rx.saturation_count(0),
                    caveat='TX CSV is commanded voltage, not measured DAC/LED voltage. A0 readings do not prove optical isolation or SpO2 calibration.')
        for phase in ('before','output','after'):
            rows=[r for r in received if r[0]==phase];values=[r[2] for r in rows]
            result[phase]=dict(count=len(rows),raw_min=min(values) if values else None,
                               raw_max=max(values) if values else None,
                               raw_mean=statistics.mean(values) if values else None,
                               raw_std=statistics.pstdev(values) if values else None,
                               measured_sample_rate_hz=(len(rows)-1)/(rows[-1][1]-rows[0][1]) if len(rows)>1 else 0)
        with (args.output/'rx_a0.csv').open('w') as f:
            w=csv.writer(f);w.writerow(['phase','monotonic_s','raw','saturated']);w.writerows(received)
        with (args.output/'tx_commanded.csv').open('w') as f:
            w=csv.writer(f);w.writerow(['time_s','ir_v','red_v']);w.writerows(tx)
        (args.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    finally:
        rx.shutdown();engine.shutdown()

if __name__=='__main__':main()
