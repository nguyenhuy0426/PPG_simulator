"""Touch controls, finite sequence synthesis, shared DAC output and real A0 RX."""
from dataclasses import replace
import secrets
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from tkinter import filedialog

import customtkinter as ctk

from core.neural_preview import export_preview, gaussian_preview, reference_preview, sequence_reference_preview, Preview
from core.signal_engine import SignalEngine
from core.waveform_clip import WaveformClip
from hw.opt101_rx import OPT101Receiver, raw_to_millivolts
from ui import theme as T
from ui.touch_slider import TouchSlider
from ui.trace_view import TraceView

COPY = {
    'vi': dict(title='PPG · Gaussian và chuỗi GAN', generate='Sinh đoạn mới',
               hr='Nhịp tim Gaussian / bpm', dc='DC / mV', ac='AC IR / mV',
               fitted='Gaussian đã fit', lsm='LSM-GAN · thăm dò',
               with_notch='Có notch rõ', no_notch='Không có notch rõ',
               play='Phát LED · 30 s', stop='Dừng đầu ra', export='Xuất sóng CSV',
               real='Tham chiếu real', rx='OPT101 · A0',
               info='GAN sinh cả đoạn 30 s, không điều khiển HR/notch. A2 tắt; chưa đo SpO₂.',
               ready='Chưa phát · chọn nguồn, kéo slider rồi nhấn Phát LED.',
               busy='Đang sinh chuỗi trên CPU…',
               detail='Seed {seed} · 40 Hz · v2 thăm dò · Real = đoạn train 30 s; không gán nhãn bệnh lý.',
               reference='Real: nhịp train đã xử lý, đổi thời gian và lặp; không phải cặp IR/RED đo thật.',
               running='Đang phát {name} · {elapsed:.1f} / 30 s · A0: {rx}',
               waiting='A0: {status} · chưa có mẫu thật mới. A2 tắt.',
               saved='Đã lưu: {path}', stopped='Đầu ra đã dừng · DAC về 0 V.'),
    'en': dict(title='PPG · Gaussian and GAN sequences', generate='New sequence',
               hr='Gaussian heart rate / bpm', dc='DC / mV', ac='IR AC / mV',
               fitted='Fitted Gaussian', lsm='LSM-GAN · exploratory',
               with_notch='Visible notch', no_notch='No visible notch',
               play='Play LED · 30 s', stop='Stop output', export='Export waveform CSV',
               real='Real reference', rx='OPT101 · A0',
               info='GAN generates a whole 30 s strip; no HR/notch control. A2 off; no measured SpO₂.',
               ready='Idle · choose source, adjust sliders, then press Play LED.',
               busy='Generating sequence on CPU…',
               detail='Seed {seed} · 40 Hz · exploratory v2 · Real = 30 s train strip; no diagnosis labels.',
               reference='Real: processed train pulse, retimed and repeated; not a measured IR/RED pair.',
               running='Playing {name} · {elapsed:.1f} / 30 s · A0: {rx}',
               waiting='A0: {status} · no fresh physical samples. A2 disabled.',
               saved='Saved: {path}', stopped='Output stopped · DAC parked at 0 V.'),
}


class NeuralFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.language = getattr(master, 'language', 'en')
        self.engine, self.rx = SignalEngine.get_instance(), OPT101Receiver.get_instance()
        self.mode, self.profile, self.comparison = 'Gaussian (fitted)', 'With notch', 'real'
        self.previews = {}
        self._process = None
        self._stdout = self._stderr = None
        self._busy, self._was_playing, self._pending = False, False, None
        self._last_live_render = 0.0
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        self.title_label = T.label(self,'',20,True,anchor='w')
        self.title_label.grid(row=0,column=0,sticky='ew')
        toolbar = ctk.CTkFrame(self,fg_color='transparent')
        toolbar.grid(row=1,column=0,sticky='ew',pady=4)
        self.mode_menu = ctk.CTkOptionMenu(toolbar,values=[''],width=195,height=36,command=self.change_mode)
        self.mode_menu.pack(side='left',padx=(0,8))
        self.profile_menu = ctk.CTkOptionMenu(toolbar,values=[''],width=150,height=36,command=self.change_profile)
        self.profile_menu.pack(side='left',padx=(0,8))
        self.generate_btn = ctk.CTkButton(toolbar,text='',width=135,height=36,command=self.generate)
        self.generate_btn.pack(side='left',padx=(0,8))
        self.compare_menu = ctk.CTkOptionMenu(toolbar,values=[''],width=175,height=36,command=self.change_comparison)
        self.compare_menu.pack(side='right')
        controls = ctk.CTkFrame(self,fg_color='transparent')
        controls.grid(row=2,column=0,sticky='ew')
        controls.grid_columnconfigure((0,1,2),weight=1,uniform='touch')
        self.control_labels = {}
        for col,(key,lo,hi,step,value) in enumerate((('hr',40,180,1,75),('dc',0,1500,1,1500),('ac',0,1500,1,45))):
            box=ctk.CTkFrame(controls,fg_color='transparent')
            box.grid(row=0,column=col,sticky='ew',padx=6)
            box.grid_columnconfigure(0,weight=1)
            label=T.label(box,'',11,anchor='w')
            label.grid(row=0,column=0,sticky='ew')
            self.control_labels[key]=label
            control=TouchSlider(box,lo,hi,step,value=value,
                                command=lambda _value,k=key:self.adjust(k))
            control.grid(row=1,column=0,sticky='ew')
            setattr(self,key+'_slider',control)
        self.info=T.label(self,'',10,text_color=T.MUTED,anchor='w')
        self.info.grid(row=3,column=0,sticky='ew',pady=3)
        plots=ctk.CTkFrame(self,fg_color='transparent')
        plots.grid(row=4,column=0,sticky='nsew')
        plots.grid_columnconfigure((0,1),weight=1,uniform='plots')
        plots.grid_rowconfigure(1,weight=1)
        self.left_label=T.label(plots,'',13,True,anchor='w')
        self.right_label=T.label(plots,'',13,True,anchor='w')
        self.left_label.grid(row=0,column=0,sticky='ew',padx=4)
        self.right_label.grid(row=0,column=1,sticky='ew',padx=4)
        self.trace=TraceView(plots,height=150)
        self.trace.channels=((1,"IR TX",T.IR),)
        self.reference_trace=TraceView(plots,height=130)
        self.trace.grid(row=1,column=0,sticky='nsew',padx=3)
        self.reference_trace.grid(row=1,column=1,sticky='nsew',padx=3)
        bottom=ctk.CTkFrame(self,fg_color='transparent')
        bottom.grid(row=5,column=0,sticky='ew',pady=5)
        bottom.grid_columnconfigure(0,weight=1)
        self.seek=ctk.CTkSlider(bottom,from_=0,to=22,height=32,button_length=24,command=lambda _:self.render())
        self.seek.set(0)
        self.seek.grid(row=0,column=0,sticky='ew',padx=(0,10))
        self.play_btn=ctk.CTkButton(bottom,text='',height=38,width=145,command=self.toggle_output)
        self.play_btn.grid(row=0,column=1,padx=4)
        self.export_btn=ctk.CTkButton(bottom,text='',height=38,width=155,command=self.export)
        self.export_btn.grid(row=0,column=2,padx=4)
        self.status=T.label(self,'',11,anchor='w',justify='left',wraplength=920)
        self.status.grid(row=6,column=0,sticky='ew')
        self.set_language(self.language)
        self.generate()

    def set_language(self, language):
        self.language=language if language in COPY else 'en'
        t=COPY[self.language]
        self.title_label.configure(text=t['title'])
        for key,label in self.control_labels.items():
            label.configure(text=t[key])
        self.generate_btn.configure(text=t['generate'])
        self.export_btn.configure(text=t['export'])
        self.info.configure(text=t['info'])
        self.mode_menu.configure(values=[t['fitted'],t['lsm']])
        self.mode_menu.set(t['lsm' if self.mode=='LSM-GAN' else 'fitted'])
        self.profile_menu.configure(values=[t['with_notch'],t['no_notch']])
        self.profile_menu.set(t['with_notch' if self.profile=='With notch' else 'no_notch'])
        self.compare_menu.configure(values=[t['real'],t['rx']])
        self.compare_menu.set(t[self.comparison])
        self.status.configure(text=t['ready'])
        self.render()

    def change_mode(self,label):
        self._stop_owned_output()
        self.mode='LSM-GAN' if label==COPY[self.language]['lsm'] else 'Gaussian (fitted)'
        self.mode_menu.set(COPY[self.language]['lsm' if self.mode=='LSM-GAN' else 'fitted'])
        if self.mode=='LSM-GAN':
            try:
                self.previews['Real sequence']=sequence_reference_preview()
            except (OSError,ValueError,KeyError) as exc:
                self.status.configure(text=str(exc),text_color=T.ERROR)
        self.hr_slider.configure(state='disabled' if self.mode=='LSM-GAN' else 'normal')
        self.profile_menu.configure(state='disabled' if self.mode=='LSM-GAN' else 'normal')
        self.render()
        if self.mode not in self.previews:
            self.generate()

    def change_profile(self,label):
        self._stop_owned_output()
        self.profile='With notch' if label==COPY[self.language]['with_notch'] else 'No notch'
        self.generate()

    def change_comparison(self,label):
        self.comparison='rx' if label==COPY[self.language]['rx'] else 'real'
        self.compare_menu.set(COPY[self.language][self.comparison])
        self.render()

    def adjust(self,key):
        self._stop_owned_output()
        if self._pending is not None:
            self.after_cancel(self._pending)
        # Only debounce cheap Gaussian rendering. GAN inference never runs on slider events.
        self._pending=self.after(120,self._apply_adjustment)

    def _apply_adjustment(self):
        self._pending=None
        self.previews['Gaussian (fitted)']=gaussian_preview(float(self.hr_slider.get()),self.profile)
        self.previews['Real reference']=reference_preview(float(self.hr_slider.get()),self.profile)
        self.render()

    def generate(self):
        self._stop_owned_output()
        if self.mode!='LSM-GAN':
            self._apply_adjustment()
            return
        if self._busy:
            return
        self._busy=True
        self.status.configure(text=COPY[self.language]['busy'],text_color=T.MUTED)
        self.generate_btn.configure(state='disabled')
        self.play_btn.configure(state='disabled')
        self._stdout, self._stderr = tempfile.TemporaryFile(), tempfile.TemporaryFile()
        self._started = time.monotonic()
        try:
            self._process = subprocess.Popen(
                [sys.executable,'-m','core.sequence_worker',str(secrets.randbits(32))],
                cwd=Path(__file__).resolve().parents[2],stdout=self._stdout,stderr=self._stderr)
        except OSError as exc:
            self._finish_inference(str(exc))

    def _finish_inference(self,error=None):
        try:
            if error is None:
                self._stdout.seek(0)
                preview=Preview(**json.load(self._stdout))
                self.previews[preview.name]=preview
        except (ValueError,TypeError,KeyError) as exc:
            error=str(exc)
        finally:
            for stream in (self._stdout,self._stderr):
                if stream is not None:
                    stream.close()
            self._process=None
            self._busy=False
            self.generate_btn.configure(state='normal')
            self.render()
        if error:
            self.status.configure(text=error,text_color=T.ERROR)

    def shutdown(self):
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
            self._process.wait(timeout=2)
        for stream in (self._stdout,self._stderr):
            if stream is not None and not stream.closed:
                stream.close()
        self._process=None

    def clip(self):
        preview=self.previews.get(self.mode)
        if preview is None:
            raise ValueError('Generate a waveform first')
        return WaveformClip.from_preview(preview,float(self.dc_slider.get()),float(self.ac_slider.get()))

    def render(self):
        t=COPY[self.language]
        self.left_label.configure(text=t['lsm' if self.mode=='LSM-GAN' else 'fitted'])
        self.right_label.configure(text=t[self.comparison])
        preview=self.previews.get(self.mode)
        self.play_btn.configure(text=t['stop' if self.engine.is_waveform_playing else 'play'],
                                fg_color=T.ERROR if self.engine.is_waveform_playing else T.ACCENT,
                                state='normal' if preview is not None and not self._busy else 'disabled')
        self.export_btn.configure(state='normal' if preview is not None else 'disabled')
        if not self.engine.is_waveform_playing:
            start=self.seek.get()
            self.trace.update_samples([s for s in self.clip().samples if start<=s[0]<=start+8] if preview else [])
        self.reference_trace.channels=((1,'OPT101 A0',T.IR),) if self.comparison=='rx' else ((1,'IR reference',T.IR),)
        if self.comparison=='real':
            ref=self.previews.get('Real sequence' if self.mode=='LSM-GAN' else 'Real reference')
            start=self.seek.get()
            rows=WaveformClip.from_preview(ref,float(self.dc_slider.get()),float(self.ac_slider.get())).samples if ref else ()
            self.reference_trace.update_samples([s for s in rows if start<=s[0]<=start+8])
        else:
            self._render_rx()
        if preview and not self.engine.is_waveform_playing and not self._busy:
            self.status.configure(text=t['detail'].format(seed=preview.seed) if self.mode=='LSM-GAN' else t['reference'],text_color=T.MUTED)

    def _render_rx(self):
        samples=self.rx.get_samples(0,800)
        status=self.rx.channel_status(0)
        fresh=bool(samples) and not self.rx.is_stale(0)
        if fresh:
            origin=samples[0].timestamp
            self.reference_trace.update_samples([(s.timestamp-origin,raw_to_millivolts(s.raw)/1000,0) for s in samples])
        else:
            self.reference_trace.update_samples([],COPY[self.language]['waiting'].format(status=status))
        return status if fresh else status+' / stale'

    def _stop_owned_output(self):
        if self.engine.is_waveform_playing:
            self.engine.stop_simulation()

    def toggle_output(self):
        try:
            if self.engine.is_waveform_playing:
                self.engine.stop_simulation()
                self.status.configure(text=COPY[self.language]['stopped'])
            else:
                if self._pending is not None:
                    self.after_cancel(self._pending)
                    self._apply_adjustment()
                self.engine.start_waveform(self.clip())
                self.comparison='rx'
                self.compare_menu.set(COPY[self.language]['rx'])
                self._was_playing=True
            self.render()
        except (ValueError,RuntimeError) as exc:
            self.status.configure(text=str(exc),text_color=T.ERROR)

    def periodic_update(self):
        if self._process is not None:
            result=self._process.poll()
            if result is not None:
                self._stderr.seek(0)
                error=self._stderr.read().decode(errors='replace')[-1200:] if result else None
                self._finish_inference(error)
            elif time.monotonic()-self._started>120:
                self._process.kill()
                self._process.wait(timeout=2)
                self._finish_inference('GAN inference timed out after 120 s')
        playing=self.engine.is_waveform_playing
        if playing:
            # Redraw at 10 fps; acquisition and DAC timing remain independent.
            now=time.monotonic()
            if now-self._last_live_render<.1:
                return
            self._last_live_render=now
            self.trace.update_samples(self.engine.get_display_history())
            rx_status=self._render_rx() if self.comparison=='rx' else self.rx.channel_status(0)
            self.status.configure(text=COPY[self.language]['running'].format(
                name=self.engine._waveform_clip.name,elapsed=self.engine._clip_tick/100,rx=rx_status),text_color=T.ACCENT)
        elif self._was_playing:
            self.render()
            self.status.configure(text=COPY[self.language]['stopped'],text_color=T.MUTED)
        elif self.comparison=='rx' and self.winfo_ismapped():
            self._render_rx()
        self._was_playing=playing

    def on_hide(self):
        self._stop_owned_output()

    def export(self):
        preview=self.previews.get(self.mode)
        if preview is None:
            return
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.csv',
            initialfile=f'{self.mode}-{preview.seed or self.profile}.csv',filetypes=[('CSV','*.csv')])
        if path:
            try:
                clip=self.clip()
                dc,ac=float(self.dc_slider.get())/1000,float(self.ac_slider.get())/1000
                export_preview(replace(preview,samples=list(clip.samples)),path,dc_v=dc,ac_ir_v=ac,ac_red_v=ac*.48)
                self.status.configure(text=COPY[self.language]['saved'].format(path=path))
            except (OSError,ValueError) as exc:
                self.status.configure(text=str(exc),text_color=T.ERROR)
