"""Touch controls, finite sequence synthesis, shared DAC output and real A0 RX."""
from dataclasses import replace
import os
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
from core.apft_preview import DEFAULT_APFT_BUNDLE
from core.apft_range import DEFAULT_RANGE, HR_LIMITS, MIN_WIDTH
from core.psf_preview import DEFAULT_PSF_BUNDLE
from core.sequence_worker import HR_MODELS, timeout_s
from config import MAX30102_AC_MV, MAX30102_DC_MV
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
               hr='Nhịp tim yêu cầu / bpm', hr_min='HR tối thiểu / bpm', hr_max='HR tối đa / bpm',
               dc='DC / mV', ac='AC IR / mV',
               fitted='Gaussian đã fit', lsm='LSM-GAN · thăm dò', psf='PSF-GAN · thử nghiệm', apft='APFT-GAN · ~1 phút',
               with_notch='Có notch rõ', no_notch='Không có notch rõ',
               play='Phát LED · 30 s', source='Nguồn dạng sóng', seek='Vị trí', stop='Dừng đầu ra', export='Xuất CSV',
               real='Tham chiếu real', tx='Tín hiệu phát TX', rx='Tín hiệu thu RX · OPT101',
               info='PSF nhận HR yêu cầu; APFT nhận khoảng HR 60–100 bpm (đo lại từng đoạn); LSM không điều khiển HR. GAN không có điều khiển notch. A4 tắt; chưa đo SpO₂.',
               ready='Chưa phát · chọn nguồn, kéo slider rồi nhấn Phát LED.',
               busy='Đang sinh chuỗi trên CPU…', busy_timed='Đang sinh {name} trên CPU… {elapsed:.0f} s (~{typical} s mỗi lượt sinh, tối đa {limit} s)',
               detail='Seed {seed} · 40 Hz · v2 thăm dò · Real = đoạn train 30 s; không gán nhãn bệnh lý.',
               psf_detail='PSF · seed {seed} · HR yêu cầu {hr:.0f} bpm · 40 Hz · mô phỏng nghiên cứu; IR/RED chưa hiệu chuẩn.',
               apft_detail='APFT · seed {seed} · HR yêu cầu {hr:.0f} bpm (không bảo đảm) · 40 Hz · checkpoint {step} · mô phỏng nghiên cứu; IR/RED chưa hiệu chuẩn.',
               timeout='{name} quá {limit} s, đã dừng tiến trình sinh.',
               apft_range_detail='APFT · seed {seed} · HR đo {hr:.1f} bpm, trong khoảng {lo:g}–{hi:g} · {tries} lần sinh · 40 Hz · checkpoint {step} · mô phỏng nghiên cứu; IR/RED chưa hiệu chuẩn.',
               range_miss='APFT: đã sinh {n} đoạn, không đoạn nào có HR trong {lo:g}–{hi:g} bpm (HR đo được {measured}). Nới rộng khoảng hoặc nhấn Sinh đoạn mới.',
               reference='Real: nhịp train đã xử lý, đổi thời gian và lặp; không phải cặp IR/RED đo thật.',
               running='Đang phát {name} · {elapsed:.1f} / 30 s · A0: {rx}',
               max30102=' · Chế độ MAX30102: chỉ LED RED, DC {dc:.0f} / AC {ac:.0f} mV (bỏ qua thanh DC/AC); OPT101 tạm dừng',
               saved='Đã lưu: {path}', stopped='Đầu ra đã dừng · DAC về 0 V.',
               save_rec='Lưu vào Recordings', saved_rec='Đã lưu vào Recordings: {name} (chỉ trên Pi, chưa lên DB)',
               sending='Đang gửi {name} về điện thoại ({n} gói)…', sent='Đã chuyển xong CSV cho điện thoại.'),
    'en': dict(title='PPG · Gaussian and GAN sequences', generate='New sequence',
               hr='Requested heart rate / bpm', hr_min='HR min / bpm', hr_max='HR max / bpm',
               dc='DC / mV', ac='IR AC / mV',
               fitted='Fitted Gaussian', lsm='LSM-GAN · exploratory', psf='PSF-GAN · experimental', apft='APFT-GAN · ~1 min',
               with_notch='Visible notch', no_notch='No visible notch',
               play='Play LED · 30 s', source='Waveform source', seek='Position', stop='Stop output', export='Export CSV',
               real='Real reference', tx='TX output signal', rx='RX received signal · OPT101',
               info='PSF takes a requested HR; APFT takes an HR range of 60–100 bpm (each window measured); LSM has no HR control. GAN has no notch control. A4 off; no measured SpO₂.',
               ready='Idle · choose source, adjust sliders, then press Play LED.',
               busy='Generating sequence on CPU…', busy_timed='Generating {name} on CPU… {elapsed:.0f} s (~{typical} s per generation round, at most {limit} s)',
               detail='Seed {seed} · 40 Hz · exploratory v2 · Real = 30 s train strip; no diagnosis labels.',
               psf_detail='PSF · seed {seed} · requested HR {hr:.0f} bpm · 40 Hz · research simulation; IR/RED not calibrated.',
               apft_detail='APFT · seed {seed} · requested HR {hr:.0f} bpm (not guaranteed) · 40 Hz · checkpoint {step} · research simulation; IR/RED not calibrated.',
               timeout='{name} took longer than {limit} s; the generator process was stopped.',
               apft_range_detail='APFT · seed {seed} · measured HR {hr:.1f} bpm, inside {lo:g}–{hi:g} · {tries} generated · 40 Hz · checkpoint {step} · research simulation; IR/RED not calibrated.',
               range_miss='APFT: {n} windows generated, none with HR in {lo:g}–{hi:g} bpm (measured HR {measured}). Widen the range or press New sequence.',
               reference='Real: processed train pulse, retimed and repeated; not a measured IR/RED pair.',
               running='Playing {name} · {elapsed:.1f} / 30 s · A0: {rx}',
               max30102=' · MAX30102 mode: RED LED only, DC {dc:.0f} / AC {ac:.0f} mV (DC/AC sliders not used); OPT101 paused',
               saved='Saved: {path}', stopped='Output stopped · DAC parked at 0 V.',
               save_rec='Save to Recordings', saved_rec='Saved to Recordings: {name} (on the Pi only, not in the DB)',
               sending='Sending {name} to the phone ({n} parts)…', sent='CSV handed to the phone.'),
}
GAN_MODES = ('LSM-GAN', 'PSF-GAN', 'APFT-GAN')
DATASET_DIR = Path(__file__).resolve().parents[2] / 'dataset'   # the Recordings page lists this folder
TRANSFER_TTL_S = 120.0       # a CSV for the phone is offered this long when the phone never acknowledges it
MODE_KEYS = {'LSM-GAN': 'lsm', 'PSF-GAN': 'psf', 'APFT-GAN': 'apft'}
REFERENCE_BUNDLES = {'PSF-GAN': DEFAULT_PSF_BUNDLE, 'APFT-GAN': DEFAULT_APFT_BUNDLE}
RANGE_MODE = 'APFT-GAN'          # takes an HR min-max range; the worker keeps only a window measured inside it
TYPICAL_S = {'APFT-GAN': 60}     # Pi 4: ~10 s load + ~46 s per window (core/apft_fast.py)
# One torch/BLAS thread per worker: the GUI process needs the other cores (on the Pi 4, 4 threads made APFT slower).
WORKER_ENV = {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'}


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
        self._busy_mode = None
        self._last_live_render = 0.0
        u = T.ui
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.title_label, self.info, actions = K.page_header(self)

        source, self.source_title, tools = K.section(self, span=3)
        source.grid(row=1, column=0, sticky='ew', pady=(0, u(8)))
        self._source = source
        menu = dict(height=u(34), font=T.font(u(13)), dropdown_font=T.font(u(14)), icon_size=u(14), pad=u(10))
        self.mode_menu = SelectButton(tools, [''], command=self.change_mode, width=u(190), **menu)
        self.mode_menu.pack(side='left', padx=(0, u(6)))
        self.profile_menu = SelectButton(tools, [''], command=self.change_profile, width=u(150), **menu)
        self.profile_menu.pack(side='left', padx=(0, u(6)))
        self.generate_btn = K.secondary_button(tools, command=self.generate, width=126)
        self.generate_btn.pack(side='left')
        self.control_labels = {}
        self.hr_range=list(DEFAULT_RANGE)
        for key,lo,hi,step,value in (('hr',40,180,1,75),('hr_min',*HR_LIMITS,1,DEFAULT_RANGE[0]),
                                     ('hr_max',*HR_LIMITS,1,DEFAULT_RANGE[1]),('dc',0,1500,1,1500),('ac',0,1500,1,45)):
            label=T.label(source,'',u(12),text_color=T.MUTED,anchor='w')
            self.control_labels[key]=label
            control=TouchSlider(source,lo,hi,step,value=value,inline=True,
                                command=lambda _value,k=key:self.adjust(k))
            setattr(self,key+'_slider',control)
        self._layout_controls()

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

        self.save_rec_btn=K.secondary_button(actions,command=self.save_to_recordings,width=170,icon='recordings')
        self.save_rec_btn.pack(side='left',padx=(0,u(8)))
        self.export_btn=K.secondary_button(actions,command=self.export,width=120,icon='save')
        self.export_btn.pack(side='left',padx=(0,u(8)))
        self._transfer=None     # (id, parts, until): a CSV on its way to the phone as UI parts
        self.play_btn=K.primary_button(actions,command=self.toggle_output,width=150)
        self.play_btn.pack(side='left')
        self.status=T.label(self,'',u(12),text_color=T.MUTED,anchor='w',justify='left',wraplength=u(900),height=u(20))
        self.status.grid(row=4,column=0,sticky='ew',pady=(u(6),0))
        # Wrap at the page's real width; a fixed wraplength overflows narrower windows.
        self._status_wrap=None
        self.bind('<Configure>',self._fit_status,add='+')
        self.set_language(self.language)
        self.generate()

    def _control_keys(self):
        return ('hr_min','hr_max','dc','ac') if self.mode==RANGE_MODE else ('hr','dc','ac')

    def _layout_controls(self):
        """APFT: HR min and HR max replace the single requested HR (four columns); other modes: three columns."""
        u=T.ui
        keys=self._control_keys()
        for key in ('hr','hr_min','hr_max','dc','ac'):
            label,control=self.control_labels[key],getattr(self,key+'_slider')
            if key in keys:
                col=keys.index(key)
                label.grid(row=1,column=col,sticky='ew',padx=u(12))
                control.grid(row=2,column=col,sticky='ew',padx=u(12),pady=(0,u(10)))
            else:
                label.grid_remove()
                control.grid_remove()
        for col in range(4):
            self._source.grid_columnconfigure(col,weight=1 if col<len(keys) else 0,
                                              uniform='touch' if col<len(keys) else '')

    def _set_hr_controls(self,state):
        for key in ('hr','hr_min','hr_max'):
            getattr(self,key+'_slider').configure(state=state)

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
        self.save_rec_btn.configure(text=t['save_rec'])
        self.info.configure(text=self._info_text())
        self.mode_menu.configure(values=[t['fitted'],t['lsm'],t['psf'],t['apft']])
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
        self.profile_menu.configure(state='disabled' if self.mode in GAN_MODES else 'normal')

    def _load_reference(self):
        try:
            if self.mode=='LSM-GAN':
                self.previews['Real sequence']=sequence_reference_preview()
            elif self.mode in REFERENCE_BUNDLES:
                self.previews['Real sequence']=sequence_reference_preview(REFERENCE_BUNDLES[self.mode])
        except (OSError,ValueError,KeyError) as exc:
            self.status.configure(text=str(exc),text_color=T.ERROR)

    def change_mode(self,label):
        self._stop_owned_output()
        t=COPY[self.language]
        self.mode={t[key]:mode for mode,key in MODE_KEYS.items()}.get(label,'Gaussian (fitted)')
        self.mode_menu.set(self._mode_label())
        self.info.configure(text=self._info_text())
        self._load_reference()
        self._layout_controls()
        self._set_hr_controls('disabled' if self.mode=='LSM-GAN' else 'normal')
        self._sync_profile_menu()
        if self.mode in self.previews and not self._preview_matches(self.previews[self.mode]):
            self.previews.pop(self.mode)
        self.render()
        if self.mode not in self.previews:
            self.generate()

    def change_profile(self,label):
        self._stop_owned_output()
        self.profile='With notch' if label==COPY[self.language]['with_notch'] else 'No notch'
        self._sync_profile_menu()
        self.generate()

    def _preview_matches(self,preview):
        """A cached window still fits the controls: same requested HR (PSF) or same HR range (APFT)."""
        if self.mode==RANGE_MODE:
            return (preview.provenance or {}).get('hr_range')==[float(v) for v in self.hr_range]
        if self.mode in HR_MODELS:
            return preview.hr_target==float(self.hr_slider.get())
        return True

    def _adjust_range(self,key):
        """Keep HR min + MIN_WIDTH <= HR max by moving the other end."""
        lo,hi=float(self.hr_min_slider.get()),float(self.hr_max_slider.get())
        if hi-lo<MIN_WIDTH:
            if key=='hr_min':
                hi=min(HR_LIMITS[1],lo+MIN_WIDTH)
                lo=hi-MIN_WIDTH
            else:
                lo=max(HR_LIMITS[0],hi-MIN_WIDTH)
                hi=lo+MIN_WIDTH
            self.hr_min_slider.set(lo)
            self.hr_max_slider.set(hi)
        self.hr_range=[lo,hi]

    def adjust(self,key):
        self._stop_owned_output()
        if key in ('hr_min','hr_max'):
            self._adjust_range(key)
        if key in ('hr','hr_min','hr_max') and self.mode in HR_MODELS and self.mode in self.previews \
                and not self._preview_matches(self.previews[self.mode]):
            self.previews.pop(self.mode,None)
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
        self._busy_mode=self.mode
        if self.mode in HR_MODELS:
            self._set_hr_controls('disabled')
        self.status.configure(text=COPY[self.language]['busy'],text_color=T.MUTED)
        self.generate_btn.configure(state='disabled')
        self.play_btn.configure(state='disabled')
        self._stdout, self._stderr = tempfile.TemporaryFile(), tempfile.TemporaryFile()
        self._started = time.monotonic()
        command=[sys.executable,'-m','core.sequence_worker',str(secrets.randbits(32))]
        if self.mode==RANGE_MODE:
            lo,hi=self.hr_range
            command+=[self.mode,f'{(lo+hi)/2:g}','--hr-range',f'{lo:g}',f'{hi:g}']
        elif self.mode in HR_MODELS:
            command+=[self.mode,str(self.hr_slider.get())]
        try:
            self._process = subprocess.Popen(
                command,
                cwd=Path(__file__).resolve().parents[2],stdout=self._stdout,stderr=self._stderr,
                env={**os.environ,**WORKER_ENV})
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
            self._set_hr_controls('disabled' if self.mode=='LSM-GAN' else 'normal')
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

    def _range_miss_text(self):
        """The worker's exit-2 report (no window measured inside the range), in the page language."""
        try:
            self._stdout.seek(0)
            miss=json.loads(self._stdout.read().decode())
            lo,hi=miss['range']
            rates=[tr[3] for tr in miss['tries'] if tr[3] is not None]
            measured=f'{min(rates):.0f}–{max(rates):.0f} bpm' if rates else '–'
            return COPY[self.language]['range_miss'].format(n=len(miss['tries']),lo=lo,hi=hi,measured=measured)
        except (ValueError,KeyError,TypeError,IndexError):
            return None

    def _status_detail(self,preview):
        t=COPY[self.language]
        if self.mode=='PSF-GAN':
            return t['psf_detail'].format(seed=preview.seed,hr=preview.hr_target)
        info=preview.provenance or {}
        if self.mode=='APFT-GAN' and 'hr_range' in info:
            return t['apft_range_detail'].format(seed=preview.seed,hr=info['hr_measured_bpm'],lo=info['hr_range'][0],
                                                 hi=info['hr_range'][1],tries=len(info.get('tries',())),
                                                 step=info.get('checkpoint_step','?'))
        if self.mode=='APFT-GAN':
            return t['apft_detail'].format(seed=preview.seed,hr=preview.hr_target,
                                           step=(preview.provenance or {}).get('checkpoint_step','?'))
        if self.mode=='LSM-GAN':
            return t['detail'].format(seed=preview.seed)
        return t['reference']

    def _reference_rows(self):
        ref=self.previews.get('Real sequence' if self.mode in GAN_MODES else 'Real reference')
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
        self.save_rec_btn.configure(state='normal' if preview is not None else 'disabled')
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

    # ---- BLE protocol v3 (ui/remote.py) ----
    def remote_parts(self):
        from comm.ble_remote import preview_parts
        from ui.remote import color_kind
        playing=self.engine.is_waveform_playing
        state={'mode':self.mode,'prof':self.profile,'ml':self._mode_label(),'hr':float(self.hr_slider.get()),
               'lo':float(self.hr_min_slider.get()),'hi':float(self.hr_max_slider.get()),
               'dc':float(self.dc_slider.get()),'ac':float(self.ac_slider.get()),'seek':float(self.seek.get()),
               'busy':bool(self._busy),'play':bool(playing),
               'can':self.previews.get(self.mode) is not None and not self._busy}
        parts=[('nn',state),('nnst',{'s':self.status.cget('text'),'c':color_kind(self.status.cget('text_color'))}),
               ('nni',{'i':self.info.cget('text')})]
        if not playing:     # the TX card shows the generated window and its reference, not live output
            parts+=preview_parts([list(lane.points) for lane in self.trace.lanes])
        if self._transfer is not None:
            if time.monotonic()<self._transfer[2]:
                parts+=self._transfer[1]
            else:
                self._transfer=None
        return parts

    def remote_tx_rows(self):
        """While a window plays: (clip time, generated mV, real reference mV at that time), as the TX card draws
        them; [] otherwise (the idle card is the preview, sent as parts)."""
        from bisect import bisect_left
        if not self.engine.is_waveform_playing:
            return []
        preview=self.previews.get('Real sequence' if self.mode in GAN_MODES else 'Real reference')
        key=(id(preview),float(self.dc_slider.get()),float(self.ac_slider.get()))
        if getattr(self,'_ref_cache',(None,))[0]!=key:
            rows=self._reference_rows()
            self._ref_cache=(key,[r[0] for r in rows],[r[1]*1000 for r in rows])
        _key,times,values=self._ref_cache
        out=[]
        for t,ir,_red in self.engine.get_display_history()[-100:]:
            ref=None
            if times:
                ref=values[min(len(times)-1,bisect_left(times,t))]
            out.append((t,ir*1000,ref))
        return out

    def remote_apply(self,request):
        """Phone request: the same menus, sliders and buttons as on this page."""
        from comm.ble_remote import number
        t=COPY[self.language]
        mode=request.get('mode')
        if mode in ('Gaussian (fitted)',)+GAN_MODES and mode!=self.mode:
            self.change_mode(t[MODE_KEYS.get(mode,'fitted')])
        profile=request.get('prof')
        if profile in ('With notch','No notch') and profile!=self.profile and self.mode not in GAN_MODES:
            self.change_profile(t['with_notch' if profile=='With notch' else 'no_notch'])
        for key,name in (('hr','hr'),('lo','hr_min'),('hi','hr_max'),('dc','dc'),('ac','ac')):
            value=number(request.get(key))
            if value is None:
                continue
            if name.startswith('hr') and (self._busy or self.mode=='LSM-GAN'):
                continue            # disabled on the Pi too while a window is generated / for LSM
            getattr(self,name+'_slider').set(value)
            self.adjust(name)
        seek=number(request.get('seek'))
        if seek is not None:
            self.seek.set(max(0.0,min(22.0,seek)))
            self.render()
        if request.get('gen') is True and not self._busy:
            self.generate()
        if request.get('save') is True and not self._busy:
            self.save_to_recordings()
        ident=request.get('exp')
        if isinstance(ident,int) and not isinstance(ident,bool) and 0<ident<2**31:
            self.start_transfer(ident)
        if self._transfer is not None and request.get('exp_ok')==self._transfer[0]:
            self._transfer=None
            self.status.configure(text=COPY[self.language]['sent'],text_color=T.MUTED)
        if 'play' in request and bool(request['play'])!=bool(self.engine.is_waveform_playing):
            if self._busy:
                return
            self.toggle_output()

    def periodic_update(self):
        if self._process is not None:
            result=self._process.poll()
            if result is not None:
                self._stderr.seek(0)
                error=self._stderr.read().decode(errors='replace')[-1200:] if result else None
                if result==2 and self._busy_mode==RANGE_MODE:
                    error=self._range_miss_text() or error
                self._finish_inference(error)
            else:
                elapsed,limit=time.monotonic()-self._started,timeout_s(self._busy_mode)
                if elapsed>limit:
                    self._process.kill()
                    self._process.wait(timeout=2)
                    self._finish_inference(COPY[self.language]['timeout'].format(name=self._busy_mode,limit=limit))
                elif self._busy_mode in TYPICAL_S:
                    self.status.configure(text=COPY[self.language]['busy_timed'].format(
                        name=self._busy_mode,elapsed=elapsed,typical=TYPICAL_S[self._busy_mode],limit=limit),
                        text_color=T.MUTED)
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
            t=COPY[self.language]
            text=t['running'].format(name=self.engine._waveform_clip.name,elapsed=self.engine._clip_tick/100,rx=rx_status)
            if self.engine.max30102_mode:
                text+=t['max30102'].format(dc=MAX30102_DC_MV,ac=MAX30102_AC_MV)
            self.status.configure(text=text,text_color=T.ACCENT)
        elif self._was_playing:
            self.render()
            self.status.configure(text=COPY[self.language]['stopped'],text_color=T.MUTED)
        self._was_playing=playing

    def on_hide(self):
        self._stop_owned_output()

    def save_to_recordings(self):
        """The window as a recording (dataset/), listed and playable on the Recordings page; never uploaded by
        this: the database gets it only through Upload to DB."""
        from core.model_export import file_stem, recording_csv, save_recording
        preview=self.previews.get(self.mode)
        if preview is None:
            return None
        try:
            path=save_recording(DATASET_DIR,file_stem(self.mode,preview,self.profile),
                                recording_csv(self.clip(),preview,self.mode))
        except (OSError,ValueError) as exc:
            self.status.configure(text=str(exc),text_color=T.ERROR)
            return None
        self.status.configure(text=COPY[self.language]['saved_rec'].format(name=path.name),text_color=T.OK)
        return path

    def start_transfer(self,ident):
        """Phone Export CSV: the window's CSV (time_s, ir_v, red_v) as parts; the phone saves it where the user
        picks and acknowledges, or the parts stop after TRANSFER_TTL_S."""
        from core.model_export import file_stem, transfer_parts, waveform_csv
        preview=self.previews.get(self.mode)
        if preview is None:
            return False
        name=file_stem(self.mode,preview,self.profile)+'.csv'
        try:
            parts=transfer_parts(waveform_csv(self.clip()),ident,name)
        except ValueError as exc:
            self.status.configure(text=str(exc),text_color=T.ERROR)
            return False
        self._transfer=(ident,parts,time.monotonic()+TRANSFER_TTL_S)
        self.status.configure(text=COPY[self.language]['sending'].format(name=name,n=len(parts)),text_color=T.MUTED)
        return True

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
