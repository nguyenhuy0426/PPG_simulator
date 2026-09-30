import json,sys,time
from pathlib import Path
sys.path.insert(0,"/home/huy/final_project/PPG_simulator_raspi")
from core.signal_engine import SignalEngine
from hw.opt101_rx import OPT101Receiver
from ui.ctk_app import CTkApp
from ui.frames.neural_frame import COPY
engine=SignalEngine.get_instance();rx=OPT101Receiver.get_instance()
engine.begin();rx.begin();rx.start()
from main import start_ble
ble=start_ble(engine)
app=CTkApp(language="vi");app._show_frame("Neural")
page=app.frames["Neural"];started=time.monotonic();played=False

def finish():
    from config import FS_TIMER_HZ
    result=dict(dac_target_hz=FS_TIMER_HZ,engine=engine.get_stats(),dac_errors=[engine.dac_manager.error_count_ir,engine.dac_manager.error_count_red],a0_count=rx.sample_count(0),a2_count=rx.sample_count(2),a2_status=rx.channel_status(2),playing=engine.is_waveform_playing,seed=page.previews["LSM-GAN"].seed)
    Path("/home/huy/ppg-evidence/gui-bench.json").write_text(json.dumps(result,indent=2)+"\n")
    app.on_closing()

def poll():
    global played
    if "LSM-GAN" in page.previews and not played:
        played=True;page.toggle_output();app.after(31000,finish)
    elif not played:
        if time.monotonic()-started>120:raise RuntimeError("GUI inference timeout")
        app.after(200,poll)

app.after(500,lambda:page.change_mode(COPY["vi"]["lsm"]))
app.after(1000,poll)
app.after(150000,app.on_closing)
try:app.mainloop()
finally:
    if ble:ble.stop()
    rx.shutdown();engine.shutdown()
