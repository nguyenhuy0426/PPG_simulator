#!/usr/bin/env python3
"""PhysioMix page in DRY RUN: conditioned inference, HR clamp, domain switch, DAC start/stop."""
import argparse
import os
from pathlib import Path
import sys
import time
os.environ['PPG_DRY_RUN'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import ImageGrab
from core.signal_engine import SignalEngine
from ui.ctk_app import CTkApp


def xwd_window(window_id):
    """Read one X window through xwd (ZPixmap, 24/32 bpp) without extra Python packages."""
    import struct
    import subprocess
    from PIL import Image
    data = subprocess.run(['xwd', '-silent', '-id', str(window_id)], capture_output=True, check=True).stdout
    header = struct.unpack('>25I', data[:100])
    size, width, height, bpp, line = header[0], header[4], header[5], header[11], header[12]
    colors = header[19]
    if bpp not in (24, 32):
        raise OSError(f'Unsupported xwd depth {bpp}')
    offset = size+12*colors
    order = 'BGRX' if header[7] == 0 else 'XRGB'
    return Image.frombuffer('RGBX', (width, height), data[offset:offset+line*height], 'raw', order, line, 1).convert('RGB')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('docs/ui/physiomix'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    engine = SignalEngine.get_instance()
    engine.begin()
    app = CTkApp(language='vi')
    app._save_language = lambda: None
    errors = []
    app.report_callback_exception = lambda *error: errors.append(error)

    def pump(seconds=.1):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            app.update()
            time.sleep(.01)
        assert not errors, errors

    def capture(name):
        pump()
        x, y = app.winfo_rootx(), app.winfo_rooty()
        try:
            image = ImageGrab.grab(xdisplay=os.environ.get('DISPLAY'),
                                   bbox=(x, y, x+app.winfo_width(), y+app.winfo_height()))
        except OSError:
            # XWayland refuses root-window reads; the app's own window can still be read.
            image = xwd_window(app.winfo_id())
        image.save(args.output/name)

    def wait(panel):
        deadline = time.monotonic()+60
        while panel._busy and time.monotonic() < deadline:
            pump(.1)
        assert not panel._busy and 'PhysioMix' in panel.previews, panel.status.cget('text')

    try:
        pump(1)
        app.attributes('-zoomed', False)
        app.geometry('1280x800+0+0')
        pump(1)
        app._show_frame('Neural')
        panel = app.frames['Neural']
        assert panel.pm_meta, 'PhysioMix bundle missing'
        copy = __import__('ui.frames.neural_frame', fromlist=['COPY']).COPY['vi']
        panel.hr_slider._slide(72)
        pump(.3)
        panel.mode_menu.invoke(copy['physiomix'])
        wait(panel)
        preview = panel.previews['PhysioMix']
        assert len(preview.samples) == 1200 and preview.native_fs == 40 and preview.hr_target == 72
        measured = preview.provenance['measured_rate_bpm']
        assert measured is not None and abs(measured-72) < 6, measured
        assert 'Real PhysioMix' in panel.previews
        capture('physiomix-bidmc-72-vi-1280.png')
        results = [('bidmc', 72, measured)]
        for domain, hr in (('gxu_finger', 62), ('perform_af', 95), ('perform_large', 120)):
            if domain not in panel.pm_meta['domains']:
                continue
            panel.hr_slider._slide(hr)
            pump(.3)
            panel.profile_menu.invoke(copy['domains'][domain])
            assert panel.profile_menu.get() == copy['domains'][domain]
            wait(panel)
            preview = panel.previews['PhysioMix']
            assert preview.provenance['domain'] == domain and preview.hr_target == hr
            results.append((domain, hr, preview.provenance['measured_rate_bpm']))
            capture(f'physiomix-{domain}-{hr}-vi-1280.png')
        lo, hi = panel.pm_meta['hr_support_bpm']
        panel.hr_slider._slide(45)
        pump(.3)
        panel.generate()
        wait(panel)
        assert panel.previews['PhysioMix'].hr_target == lo, 'HR outside support must clamp to the learned range'
        assert str(int(lo)) in panel.status.cget('text')
        panel.play_btn.invoke()
        pump(.3)
        assert engine.is_waveform_playing
        assert 0 < engine.dac_manager.last_ir < 4095
        capture('physiomix-playing-vi-1280.png')
        panel.play_btn.invoke()
        pump()
        assert not engine.is_running and engine.dac_manager.last_ir == 0
        print('PASS: PhysioMix conditioned inference', results, f'clamp to {lo:.0f}-{hi:.0f} bpm, DAC dry-run start/stop')
    finally:
        app.on_closing()
        engine.shutdown()


if __name__ == '__main__':
    main()
