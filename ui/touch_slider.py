"""Touch-only numeric control: slider, readout and fine-step buttons."""
import math
import customtkinter as ctk
from ui import theme as T


class TouchSlider(ctk.CTkFrame):
    def __init__(self, master, minimum, maximum, step=1, value=None,
                 optional=False, command=None, width=230, **kwargs):
        super().__init__(master, fg_color="transparent", width=width, **kwargs)
        self.minimum, self.maximum, self.step = minimum, maximum, step
        self.command, self.optional = command, optional
        self._value = minimum if value is None else value
        self._auto = optional and value is None
        self._disabled = False
        self.grid_columnconfigure(1, weight=1)
        # Same control language as the Classic setpoint cards: outlined −/+,
        # a bold readout and a 28 px touch strip that draws a 6 px track.
        u = T.ui
        button = dict(width=u(34), height=u(34), font=T.font(u(17)))
        self.minus = T.outline_button(self, "−", command=lambda: self._move(-1), **button)
        self.minus.grid(row=0, column=0)
        self.readout = T.label(self, "", u(16), True)
        self.readout.grid(row=0, column=1, sticky="ew")
        self.plus = T.outline_button(self, "+", command=lambda: self._move(1), **button)
        self.plus.grid(row=0, column=2)
        self.slider = ctk.CTkSlider(self, from_=minimum, to=maximum, height=u(28), border_width=u(11),
                                   button_length=u(2), corner_radius=u(3), button_corner_radius=u(4),
                                   progress_color=T.ACCENT, button_color=T.INK,
                                   button_hover_color=T.ACCENT, command=self._slide)
        self.slider.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(u(4), 0))
        if optional:
            self.auto_var = ctk.BooleanVar(value=self._auto)
            self.auto = ctk.CTkCheckBox(self, text="Auto", variable=self.auto_var, font=T.font(u(12)),
                                       command=self._toggle_auto, height=u(28))
            self.auto.grid(row=2, column=0, columnspan=3, sticky="w")
        self.set(value)

    def _slide(self, value):
        self._auto = False
        self.set(self.minimum + round((value-self.minimum)/self.step)*self.step)
        if self.command:
            self.command(float(self._value))

    def _move(self, direction):
        self._slide(self._value + direction*self.step)

    def _toggle_auto(self):
        self._auto = self.auto_var.get()
        self._refresh()
        if self.command:
            self.command(None if self._auto else self._value)

    def set(self, value):
        self._auto = self.optional and (value is None or value == "")
        if not self._auto:
            value = self.minimum if value is None else float(value)
            if not math.isfinite(value):
                raise ValueError("Slider value must be finite")
            # Preserve externally supplied precision; quantise touch changes only.
            self._value = min(self.maximum, max(self.minimum, value))
        if self.optional:
            self.auto_var.set(self._auto)
        self._refresh()

    def _refresh(self):
        self.readout.configure(text="Auto" if self._auto else f"{self._value:g}")
        self.slider.set(self._value)
        state = "disabled" if self._disabled or self._auto else "normal"
        for widget in (self.slider, self.minus, self.plus):
            widget.configure(state=state)

    def get(self):
        return "" if self._auto else f"{self._value:g}"

    # Existing form synchronisation uses the Entry protocol; no editable text exists.
    def delete(self, *_args):
        pass

    def insert(self, _index, value):
        self.set(value)

    def configure(self, **kwargs):
        if "state" in kwargs:
            self._disabled = kwargs.pop("state") == "disabled"
            self._refresh()
            if self.optional:
                self.auto.configure(state="disabled" if self._disabled else "normal")
        if kwargs:
            super().configure(**kwargs)
