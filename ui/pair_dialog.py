"""The "Connect a phone" window: the pairing QR (comm/pairing.py) and one line of instructions."""
import threading

import customtkinter as ctk

from comm.logger import log
from ui import theme as T
from ui.i18n import text

QR_PIXELS = 320          # screen pixels at most; 5 px per module for the usual version-9 code


def qr_image(data, pixels=QR_PIXELS):
    """A PIL image of the QR code, black on white with a quiet zone, at most `pixels` square.

    Every module gets the same whole number of pixels (uneven modules from a fractional resize defeat some
    phone decoders); _show() displays it 1:1, undoing CTk's widget scaling.
    """
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=1, border=4)  # L: a screen is not scratched
    qr.add_data(data)
    qr.make(fit=True)
    modules = qr.modules_count + 2 * qr.border
    qr.box_size = max(1, pixels // modules)
    return qr.make_image(fill_color="black", back_color="white").get_image().convert("RGB")


class PairDialog:
    """Built on demand; the QR text is assembled off the Tk thread (bluetoothctl may take a moment)."""

    def __init__(self, app, ble_name):
        self.app = app
        self.ble_name = ble_name
        self.window = None

    def show(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            return
        lang = self.app.language
        window = ctk.CTkToplevel(self.app)
        window.title(text(lang, "pair_title"))
        window.configure(fg_color=T.BG)
        window.transient(self.app)
        window.bind("<Escape>", lambda _e: window.destroy())
        self.window = window
        T.label(window, text(lang, "pair_title"), 16, True).pack(padx=20, pady=(16, 4))
        self.code = T.label(window, text(lang, "pair_wait"), 12, text_color=T.MUTED)
        self.code.pack(padx=20, pady=8)
        self.info = T.label(window, "", 11, text_color=T.MUTED, wraplength=420, justify="center")
        self.info.pack(padx=20, pady=(0, 6))
        T.label(window, text(lang, "pair_how"), 11, wraplength=420, justify="center").pack(padx=20, pady=(0, 6))
        ctk.CTkButton(window, text=text(lang, "pair_close"), width=110, command=window.destroy).pack(pady=(4, 16))
        self._fit()
        threading.Thread(target=self._build, daemon=True, name="pair-qr").start()

    def _fit(self):
        """Size the window to its content and centre it on the app.

        CTkToplevel keeps the size it was created with and scales the numbers given to geometry(), so the
        requested pixel size is converted back to CTk units first.
        """
        window = self.window
        window.update_idletasks()
        scale = window._get_window_scaling() if hasattr(window, "_get_window_scaling") else 1.0
        req_w, req_h = window.winfo_reqwidth(), window.winfo_reqheight()
        x = self.app.winfo_rootx() + max(0, (self.app.winfo_width() - req_w) // 2)
        y = self.app.winfo_rooty() + max(0, (self.app.winfo_height() - req_h) // 2)
        window.geometry(f"{round(req_w / scale)}x{round(req_h / scale)}+{x}+{y}")

    def _build(self):
        from comm import pairing
        try:
            uri = pairing.current_uri(self.ble_name)
            image = qr_image(uri)
            fields = pairing.parse_pairing_uri(uri)
            error = ""
        except Exception as exc:          # qrcode missing, unreadable CA file, ...
            log.exception("[Pair] QR failed")
            uri, image, fields, error = "", None, {}, str(exc)
        self.app.after(0, lambda: self._show(image, fields, error))

    def _show(self, image, fields, error):
        if self.window is None or not self.window.winfo_exists():
            return
        lang = self.app.language
        if image is None:
            self.code.configure(text=text(lang, "pair_error").format(error=error), text_color=T.ERROR)
            return
        scale = ctk.ScalingTracker.get_widget_scaling(self.code) or 1.0
        size = (image.width / scale, image.height / scale)      # CTk multiplies by the scaling again: 1 px per px
        self._image = ctk.CTkImage(light_image=image, dark_image=image, size=size)
        self.code.configure(image=self._image, text="")
        from comm.pairing import has_internet
        links = []
        if fields.get("a"):
            links.append(text(lang, "pair_ble").format(name=fields.get("n", ""), address=fields["a"]))
        if has_internet(fields):
            links.append(text(lang, "pair_net").format(device=fields["d"], host=fields["h"]))
        else:
            links.append(text(lang, "pair_no_net"))
        self.info.configure(text="\n".join(links))
        self._fit()
