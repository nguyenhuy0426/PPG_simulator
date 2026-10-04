#!/usr/bin/env python3
"""Touch UI and waveform lifecycle in DRY RUN; no I2C / LED writes."""
import argparse
import os
from pathlib import Path
import sys
import time
os.environ['PPG_DRY_RUN']='1'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import ImageGrab
import customtkinter as ctk
from config_store import config_from_ppg_params
from core.signal_engine import SignalEngine
from ui.ctk_app import CTkApp


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('docs/ui/touch-output'))
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    engine=SignalEngine.get_instance(); engine.begin()
    app=CTkApp(language='vi'); app._save_language=lambda:None
    errors=[]; app.report_callback_exception=lambda *error:errors.append(error)
    def pump(seconds=.1):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            app.update();time.sleep(.01)
        assert not errors,errors
    def capture(name):
        pump();x,y=app.winfo_rootx(),app.winfo_rooty()
        ImageGrab.grab(xdisplay=os.environ.get('DISPLAY'),bbox=(x,y,x+app.winfo_width(),y+app.winfo_height())).save(args.output/name)
    def no_entries(widget):
        assert not isinstance(widget,ctk.CTkEntry)
        for child in widget.winfo_children(): no_entries(child)
    try:
        pump(1);app.attributes('-zoomed',False);app.geometry('1024x600+0+0');pump(1)
        app._show_frame('Neural');panel=app.frames['Neural']
        params=config_from_ppg_params(engine.ppg_params)
        assert 'torch' not in sys.modules
        no_entries(panel)
        panel.hr_slider._slide(120);pump(.25)
        assert panel.previews['Gaussian (fitted)'].hr_target==120
        panel.dc_slider._slide(1200);panel.ac_slider._slide(100);pump(.25)
        for widget in (panel.play_btn,panel.export_btn,panel.status,panel.trace,panel.rx_panel):
            assert widget.winfo_rootx()+widget.winfo_width()<=app.winfo_rootx()+app.winfo_width()
            assert widget.winfo_rooty()+widget.winfo_height()<=app.winfo_rooty()+app.winfo_height()
        capture('gaussian-vi-1024.png')
        panel.play_btn.invoke();pump(.3)
        assert engine.is_waveform_playing
        assert 0<engine.dac_manager.last_ir<4095
        assert config_from_ppg_params(engine.ppg_params)==params
        app.select_pathology();pump()
        assert not engine.is_running and engine.dac_manager.last_ir==0
        no_entries(app.frames['Pathology'])
        app.open_signal_setup();pump()
        setup=app.signal_setup_panel;no_entries(setup)
        control=setup.entries['dc_ir_mv'];control._slide(1100)
        setup.periodic_update();assert control.get()=='1100'
        setup.entries['ac_red_mv'].auto_var.set(True);setup.entries['ac_red_mv']._toggle_auto()
        assert setup.entries['ac_red_mv'].get()==''
        capture('settings-sliders-1024.png')
        app.close_signal_setup()
        app.select_calibration();pump();no_entries(app.frames['Calibration'])
        capture('calibration-sliders-1024.png')
        app._show_frame('Neural');app.set_language('en')
        panel.change_mode('LSM-GAN · exploratory')
        deadline=time.monotonic()+30
        while panel._busy and time.monotonic()<deadline: pump(.1)
        if panel._busy:
            import faulthandler
            faulthandler.dump_traceback()
        assert not panel._busy and 'LSM-GAN' in panel.previews,panel.status.cget('text')
        assert len(panel.previews['LSM-GAN'].samples)==1200
        assert panel.previews['LSM-GAN'].hr_target is None
        capture('lsm-en-1024.png')
        panel.play_btn.invoke();pump(.3)
        assert engine.is_waveform_playing
        panel.play_btn.invoke();pump()
        assert not engine.is_running and engine.dac_manager.last_ir==0
        app.geometry('1280x800+0+0');app.set_language('vi');pump(1)
        capture('lsm-vi-1280.png')
        print('PASS: touch-only numerical controls, staged settings survive refresh, LSM native inference, shared DAC dry-run start/stop, page-leave stop, no Classic parameter mutation, vi/en, 1024x600 and 1280x800')
    finally:
        app.on_closing();engine.shutdown()

if __name__=='__main__':main()
