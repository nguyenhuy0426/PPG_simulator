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
from hw.opt101_rx import OPT101Receiver
from ui import page_kit as K
from ui import theme as T
from ui.rx_monitor import RXPanel
from ui.select_button import SelectButton
from ui.touch_slider import TouchSlider
from ui.trace_view import Lane, LaneView

COPY = {
    'vi': dict(title='PPG · Gaussian và chuỗi GAN', generate='Sinh đoạn mới',
               hr='Nhịp tim Gaussian / bpm', dc='DC / mV', ac='AC IR / mV',
               fitted='Gaussian đã fit', lsm='LSM-GAN · thăm dò',
               with_notch='Có notch rõ', no_notch='Không có notch rõ',
               play='Phát LED · 30 s', source='Nguồn dạng sóng', seek='Vị trí', stop='Dừng đầu ra', export='Xuất CSV',
               real='Tham chiếu real', tx='Tín hiệu phát TX', rx='Tín hiệu thu RX · OPT101',
               info='GAN sinh cả đoạn 30 s, không điều khiển HR/notch. A2 tắt; chưa đo SpO₂.',
               ready='Chưa phát · chọn nguồn, kéo slider rồi nhấn Phát LED.',
               busy='Đang sinh chuỗi trên CPU…',
               detail='Seed {seed} · 40 Hz · v2 thăm dò · Real = đoạn train 30 s; không gán nhãn bệnh lý.',
               reference='Real: nhịp train đã xử lý, đổi thời gian và lặp; không phải cặp IR/RED đo thật.',
               running='Đang phát {name} · {elapsed:.1f} / 30 s · A0: {rx}',
               saved='Đã lưu: {path}', stopped='Đầu ra đã dừng · DAC về 0 V.'),
    'en': dict(title='PPG · Gaussian and GAN sequences', generate='New sequence',
               hr='Gaussian heart rate / bpm', dc='DC / mV', ac='IR AC / mV',
               fitted='Fitted Gaussian', lsm='LSM-GAN · exploratory',
               with_notch='Visible notch', no_notch='No visible notch',
               play='Play LED · 30 s', source='Waveform source', seek='Position', stop='Stop output', export='Export CSV',
               real='Real reference', tx='TX output signal', rx='RX received signal · OPT101',
               info='GAN generates a whole 30 s strip; no HR/notch control. A2 off; no measured SpO₂.',
               ready='Idle · choose source, adjust sliders, then press Play LED.',
               busy='Generating sequence on CPU…',
               detail='Seed {seed} · 40 Hz · exploratory v2 · Real = 30 s train strip; no diagnosis labels.',
               reference='Real: processed train pulse, retimed and repeated; not a measured IR/RED pair.',
               running='Playing {name} · {elapsed:.1f} / 30 s · A0: {rx}',
               saved='Saved: {path}', stopped='Output stopped · DAC parked at 0 V.'),
}
GAN_MODES = ('LSM-GAN',)
MODE_KEYS = {'LSM-GAN': 'lsm'}


class NeuralFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.language = getattr(master, 'language', 'en')
        self.engine, self.rx = SignalEngine.get_instance(), OPT101Receiver.get_instance()
        self.mode, self.profile = 'Gaussian (fitted)', 'With notch'
        self.previews = {}
        self._process = None
        self._stdout = self._stderr = None
        self._busy, self._was_playing, self._pending = False, False, None
        self._last_live_render = 0.0
        u = T.ui
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.title_label, self.info, actions = K.page_header(self)

        source, self.source_title, tools = K.section(self, span=3)
        source.grid(row=1, column=0, sticky='ew', pady=(0, u(8)))
        source.grid_columnconfigure((0, 1, 2), weight=1, uniform='touch')
        menu = dict(height=u(34), font=T.font(u(13)), dropdown_font=T.font(u(14)), icon_size=u(14), pad=u(10))
        self.mode_menu = SelectButton(tools, [''], command=self.change_mode, width=u(190), **menu)
        self.mode_menu.pack(side='left', padx=(0, u(6)))
        self.profile_menu = SelectButton(tools, [''], command=self.change_profile, width=u(150), **menu)
        self.profile_menu.pack(side='left', padx=(0, u(6)))
        self.generate_btn = K.secondary_button(tools, command=self.generate, width=126)
        self.generate_btn.pack(side='left')
        self.control_labels = {}
        for col,(key,lo,hi,step,value) in enumerate((('hr',40,180,1,75),('dc',0,1500,1,1500),('ac',0,1500,1,45))):
            label=T.label(source,'',u(12),text_color=T.MUTED,anchor='w')
            label.grid(row=1,column=col,sticky='ew',padx=u(12))
            self.control_labels[key]=label
            control=TouchSlider(source,lo,hi,step,value=value,inline=True,
                                command=lambda _value,k=key:self.adjust(k))
            control.grid(row=2,column=col,sticky='ew',padx=u(12),pady=(0,u(10)))
            setattr(self,key+'_slider',control)

        plots=ctk.CTkFrame(self,fg_color='transparent')
        plots.grid(row=3,column=0,sticky='nsew')
        plots.grid_columnconfigure((0,1),weight=1,uniform='plots')
        plots.grid_rowconfigure(0,weight=1)
        # TX on the left (generated lane over its reference lane), RX on the
        # right: the same split as the Classic and Calibration pages.
        tx, self.left_label, tx_tools = K.section(plots)
        tx.grid(row=0,column=0,sticky='nsew',padx=(0,u(4)))
        # Seek lives in the TX card header and Play/Export in the page header, as on the other pages:
        # a separate bottom bar left the 1024x600 panel no height for the plots.
        self.seek_label=T.label(tx_tools,'',u(12),text_color=T.MUTED)
        self.seek_label.pack(side='left',padx=(0,u(6)))
        self.seek=ctk.CTkSlider(tx_tools,from_=0,to=22,width=u(120),height=u(28),border_width=u(11),button_length=u(2),
                                corner_radius=u(3),button_corner_radius=u(4),progress_color=T.ACCENT,
                                button_color=T.INK,button_hover_color=T.ACCENT,command=lambda _:self.render())
        self.seek.set(0)
        self.seek.pack(side='left')
        holder=K.plot_holder(tx)
        # One view, two lanes (generated over real reference) on one time axis, like the RX panel:
        # two separate views each needed their own axis and minimum height.
        self.trace=LaneView(holder,height=120)
        self.trace.pack(fill='both',expand=True,padx=u(3),pady=u(3))
        rx, self.rx_title, _ = K.section(plots)
        rx.grid(row=0,column=1,sticky='nsew',padx=(u(4),0))
        self.rx_panel=RXPanel(K.plot_holder(rx),language=self.language,height=120)
        self.rx_panel.pack(fill='both',expand=True,padx=u(3),pady=u(3))

        self.export_btn=K.secondary_button(actions,command=self.export,width=120,icon='save')
        self.export_btn.pack(side='left',padx=(0,u(8)))
        self.play_btn=K.primary_button(actions,command=self.toggle_output,width=150)
        self.play_btn.pack(side='left')
        self.status=T.label(self,'',u(12),text_color=T.MUTED,anchor='w',justify='left',wraplength=u(900),height=u(20))
        self.status.grid(row=4,column=0,sticky='ew',pady=(u(6),0))
        # Wrap at the page's real width; a fixed wraplength overflows narrower windows.
        self._status_wrap=None
        self.bind('<Configure>',self._fit_status,add='+')
        self.set_language(self.language)
        self.generate()

    def _fit_status(self,_event=None):
        # CTkFrame delivers <Configure> from its inner canvas, so read the frame's own width.
        usable=self.winfo_width()-2*max(self.status.winfo_x(),0)
        scaling=self.status._get_widget_scaling()
        wrap=max(T.ui(200),round(usable/scaling)-T.ui(8))
        # The subtitle shares its row with Play/Export, so it wraps short of the buttons.
        info=max(T.ui(200),round((usable-self.play_btn.master.winfo_reqwidth())/scaling)-T.ui(16))
        if (wrap,info)!=self._status_wrap:
            self._status_wrap=(wrap,info)
            self.status.configure(wraplength=wrap)
            self.info.configure(wraplength=info)

    def set_language(self, language):
        self.language=language if language in COPY else 'en'
        t=COPY[self.language]
        self.title_label.configure(text=t['title'])
        self.source_title.configure(text=t['source'])
        self.seek_label.configure(text=t['seek'])
        for key,label in self.control_labels.items():
            label.configure(text=t[key])
        self.generate_btn.configure(text=t['generate'])
        self.export_btn.configure(text=t['export'])
        self.info.configure(text=self._info_text())
        self.mode_menu.configure(values=[t['fitted'],t['lsm']])
        self.mode_menu.set(self._mode_label())
        self._sync_profile_menu()
        self.left_label.configure(text=t['tx'])
        self.rx_title.configure(text=t['rx'])
        self.rx_panel.set_language(self.language)
        self.status.configure(text=t['ready'])
        self.render()

    def _mode_label(self):
        t=COPY[self.language]
        return t[MODE_KEYS.get(self.mode,'fitted')]

    def _info_text(self):
        return COPY[self.language]['info']

    def _sync_profile_menu(self):
        t=COPY[self.language]
        self.profile_menu.configure(values=[t['with_notch'],t['no_notch']])
        self.profile_menu.set(t['with_notch' if self.profile=='With notch' else 'no_notch'])
        self.profile_menu.configure(state='disabled' if self.mode=='LSM-GAN' else 'normal')

    def _load_reference(self):
        try:
            if self.mode=='LSM-GAN':
                self.previews['Real sequence']=sequence_reference_preview()
        except (OSError,ValueError,KeyError) as exc:
            self.status.configure(text=str(exc),text_color=T.ERROR)

    def change_mode(self,label):
        self._stop_owned_output()
        t=COPY[self.language]
        self.mode={t[key]:mode for mode,key in MODE_KEYS.items()}.get(label,'Gaussian (fitted)')
        self.mode_menu.set(self._mode_label())
        self.info.configure(text=self._info_text())
        self._load_reference()
        self.hr_slider.configure(state='disabled' if self.mode=='LSM-GAN' else 'normal')
        self._sync_profile_menu()
        self.render()
        if self.mode not in self.previews:
            self.generate()

    def change_profile(self,label):
        self._stop_owned_output()
        self.profile='With notch' if label==COPY[self.language]['with_notch'] else 'No notch'
        self._sync_profile_menu()
        self.generate()

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
        if self.mode not in GAN_MODES:
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
        command=[sys.executable,'-m','core.sequence_worker',str(secrets.randbits(32))]
        try:
            self._process = subprocess.Popen(
                command,
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

    def _status_detail(self,preview):
        t=COPY[self.language]
        if self.mode=='LSM-GAN':
            return t['detail'].format(seed=preview.seed)
        return t['reference']

    def _reference_rows(self):
        ref=self.previews.get('Real sequence' if self.mode=='LSM-GAN' else 'Real reference')
        return WaveformClip.from_preview(ref,float(self.dc_slider.get()),float(self.ac_slider.get())).samples if ref else ()

    def _draw_tx(self,generated,reference):
        """Rows (time_s, IR_V, ...): generated lane over its real reference lane, in mV."""
        t=COPY[self.language]
        lanes=[Lane(self._mode_label(),T.IR,'mV',[(r[0],r[1]*1000) for r in generated]),
               Lane(t['real'],T.PLOT_TEXT,'mV',[(r[0],r[1]*1000) for r in reference])]
        ends=[rows[-1][0] for rows in (generated,reference) if rows]
        self.trace.update_lanes(lanes,end_s=max([self.trace.window_s]+ends) if ends else None)

    def render(self):
        t=COPY[self.language]
        preview=self.previews.get(self.mode)
        K.set_running(self.play_btn,self.engine.is_waveform_playing,t['play'],t['stop'])
        self.play_btn.configure(state='normal' if preview is not None and not self._busy else 'disabled')
        self.export_btn.configure(state='normal' if preview is not None else 'disabled')
        if not self.engine.is_waveform_playing:
            start=self.seek.get()
            self._draw_tx([s for s in self.clip().samples if start<=s[0]<=start+8] if preview else [],
                          [s for s in self._reference_rows() if start<=s[0]<=start+8])
        if preview and not self.engine.is_waveform_playing and not self._busy:
            self.status.configure(text=self._status_detail(preview),text_color=T.MUTED)

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
        self.rx_panel.periodic_update()
        playing=self.engine.is_waveform_playing
        if playing:
            # Redraw at 10 fps; acquisition and DAC timing remain independent.
            now=time.monotonic()
            if now-self._last_live_render<.1:
                return
            self._last_live_render=now
            history=self.engine.get_display_history()
            # Clip playback stamps samples in clip time, so the reference lane shows the same seconds.
            end=history[-1][0] if history else 0
            self._draw_tx(history,[s for s in self._reference_rows() if end-self.trace.window_s<=s[0]<=end])
            rx_status=self.rx.channel_status(0)
            if self.rx.is_simulated: rx_status='dry-run'
            elif rx_status in ('ok','saturated') and self.rx.is_stale(0): rx_status+=' / stale'
            self.status.configure(text=COPY[self.language]['running'].format(
                name=self.engine._waveform_clip.name,elapsed=self.engine._clip_tick/100,rx=rx_status),text_color=T.ACCENT)
        elif self._was_playing:
            self.render()
            self.status.configure(text=COPY[self.language]['stopped'],text_color=T.MUTED)
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
