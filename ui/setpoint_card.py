"""Touch setpoint card: title, range or status badge, −/value/+ and a slider."""
import math

import customtkinter as ctk

from ui import theme as T


class SetpointCard(ctk.CTkFrame):
    def __init__(self, master, title, limit, unit, step, decimals=0, command=None, ui=round, **kwargs):
        super().__init__(master, fg_color=T.PANEL, border_width=T.hairline(), border_color=T.LINE,
                         corner_radius=ui(8), **kwargs)
        self.limit, self.step, self.decimals, self.command = limit, step, decimals, command
        self._value = limit.default
        self._enabled = True
        self._ui = ui
        pad = ui(10)
        self.grid_columnconfigure(1, weight=1)

        self.title_label = T.label(self, title, ui(13), True, anchor="w")
        self.title_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=(pad, ui(4)), pady=(ui(8), 0))
        self.range_label = T.label(self, f"{limit.minimum:g}–{limit.maximum:g}", ui(11), text_color=T.FAINT)
        self.range_label.grid(row=0, column=2, sticky="e", padx=(ui(4), pad), pady=(ui(8), 0))
        self.badge = T.label(self, "", ui(11), True, text_color=T.WARN_INK, fg_color=T.WARN_BG,
                             corner_radius=ui(4), height=ui(20))

        button = dict(width=ui(36), height=ui(36), font=T.font(ui(18)))
        self.minus = T.outline_button(self, "−", command=lambda: self._nudge(-1), **button)
        self.minus.grid(row=1, column=0, padx=(pad, 0), pady=(ui(6), 0))
        readout = ctk.CTkFrame(self, fg_color="transparent")
        readout.grid(row=1, column=1, pady=(ui(6), 0))
        self.value_label = T.label(readout, "", ui(25), True)
        self.value_label.pack(side="left")
        T.label(readout, unit, ui(11), text_color=T.MUTED).pack(side="left", padx=(ui(5), 0), pady=(ui(6), 0))
        self.plus = T.outline_button(self, "+", command=lambda: self._nudge(1), **button)
        self.plus.grid(row=1, column=2, padx=(0, pad), pady=(ui(6), 0))
        # A 28 px touch strip that draws a 6 px track: CTk insets the track by
        # the (transparent) border width while the knob keeps the full height.
        self.slider = ctk.CTkSlider(self, from_=limit.minimum, to=limit.maximum, height=ui(28),
                                    border_width=ui(11), button_length=ui(2), corner_radius=ui(3),
                                    button_corner_radius=ui(4), progress_color=T.ACCENT,
                                    button_color=T.INK, button_hover_color=T.ACCENT, command=self._slide)
        self.slider.grid(row=2, column=0, columnspan=3, sticky="ew", padx=pad - ui(4), pady=(ui(6), ui(8)))
        self._refresh()

    @property
    def value(self):
        return self._value

    def _emit(self, value):
        value = min(self.limit.maximum, max(self.limit.minimum, value))
        value = round(value, max(self.decimals, 3))
        if self.command:
            self.command(value)
        else:
            self.set(value)

    def _slide(self, value):
        self._emit(self.limit.minimum + round((value - self.limit.minimum) / self.step) * self.step)

    def _nudge(self, direction):
        # Snap to the step grid first so +/− never leave an odd remainder.
        base = round(self._value / self.step) * self.step
        if math.isclose(base, self._value, abs_tol=self.step * 1e-6):
            base += direction * self.step
        elif (base - self._value) * direction < 0:
            base += direction * self.step
        self._emit(base)

    def set(self, value):
        value = float(value)
        if not math.isfinite(value) or math.isclose(value, self._value, abs_tol=1e-9):
            return
        self._value = value
        self._refresh()

    def _refresh(self):
        self.value_label.configure(text=f"{self._value:.{self.decimals}f}")
        self.slider.set(self._value)

    def set_badge(self, text):
        """Show a short state (e.g. 'RED AC decoupled') instead of the range."""
        if text:
            self.badge.configure(text=f"  {text}  ")
            self.badge.grid(row=0, column=2, sticky="e", padx=(self._ui(4), self._ui(10)), pady=(self._ui(8), 0))
            self.range_label.grid_remove()
        else:
            self.badge.grid_remove()
            self.range_label.grid()

    def set_title(self, text):
        self.title_label.configure(text=text)

    def set_enabled(self, enabled):
        if enabled == self._enabled:
            return
        self._enabled = enabled
        state = "normal" if enabled else "disabled"
        for widget in (self.slider, self.minus, self.plus):
            widget.configure(state=state)
        self.value_label.configure(text_color=T.INK if enabled else T.FAINT)
