import time

import customtkinter as ctk
from core.signal_engine import SignalEngine
from models.respiration import RespirationConfig
from models.waveform import WAVEFORM_KINDS
from models.noise import NOISE_KINDS
from ui import theme as T
from ui import focus_is_inside
from ui.i18n import normalise_language, text
from ui.touch_slider import TouchSlider
from models import limits
from config import MAX30102_AC_MV, MAX30102_DC_MV, MAX30102_PEAK_MAX_MV, MAX30102_WRITE_HZ

TOAST_MS = 3000
DRAG_START_PX = 8
NO_DRAG = (ctk.CTkButton, ctk.CTkSlider, ctk.CTkEntry, ctk.CTkOptionMenu, ctk.CTkCheckBox, ctk.CTkScrollbar)


def enable_drag_scroll(body):
    """Swipe to scroll a CTkScrollableFrame on a touch panel (no wheel there).

    Bound on the form's labels and frames only: a drag that starts on a button, slider,
    entry, menu or checkbox stays that widget's own gesture."""
    canvas = body._parent_canvas
    state = {}

    def press(event):
        state.update(y=event.y_root, top=canvas.yview()[0], dragging=False)

    def motion(event):
        if "y" not in state:
            return
        dy = event.y_root - state["y"]
        if not state["dragging"] and abs(dy) < DRAG_START_PX:
            return
        state["dragging"] = True
        content = max(1, body.winfo_height())
        canvas.yview_moveto(max(0.0, state["top"] - dy / content))

    def bind(widget):
        if isinstance(widget, NO_DRAG):
            return
        widget.bind("<ButtonPress-1>", press, add="+")
        widget.bind("<B1-Motion>", motion, add="+")
        for child in widget.winfo_children():
            bind(child)

    bind(body)

# Amplitude entries the phone can change live (BLE delta merge); a checkbox
# the user has just clicked gets this hold-off before the engine truth wins.
LIVE_ENTRY_KEYS = ("ac_ir_mv", "ac_red_mv", "dc_ir_mv", "dc_red_mv", "spo2")
LIVE_LOCK_KEYS = ("lock_ac", "lock_dc")

# Display text of the Signal setup window. Technical abbreviations and units (AC, DC, IR, RED, SpO2, PI, HR, RSA,
# mV, ms, Hz) stay as they are in both languages, like the rest of the shell (ui/i18n.py).
COPY = {
    "en": dict(
        tab_amplitude="Amplitude & shape", tab_respiration="Respiration", tab_noise="Noise & calibration",
        idle="Changes apply only when you press Apply.", applied="Applied. Settings will be saved on exit.",
        toast="✓ Parameters set: {what}",
        auto="Auto", ac_red_hint="Auto = derive from SpO₂", offset="Output DC offset",
        offset_hint="0–2000 mV; DC + offset ≤ 3000", gain="AC gain", gain_hint="0.1–5.0 ×",
        notch="Local notch attenuation", notch_hint="0–1; 0.25 = 25% local reduction", spo2="SpO₂ target",
        spo2_hint="0–100 %, calibration dependent", above="AC above DC", below="AC below DC",
        lock_ac="Hold AC when DC changes", lock_dc="Hold DC when the AC/DC ratio changes",
        shape_note="Component centres at 60 bpm · SP < DN < DP · actual extrema may shift.\n"
                   "Notch 0 = no extra indentation; a natural valley may remain. Not a clinical normal range.",
        sp="Systolic peak", dn="Dicrotic notch", dp="Diastolic peak", time_hint="ms / 0–1000",
        apply_signal="Apply amplitude & shape",
        resp_rate="Respiration rate", resp_rate_hint="1–150 breaths/min", ie="Inhale : exhale",
        ie_hint="1:N, N = 1…5", variation="Variation", variation_hint="1–16 % of AC",
        apnea_duration="Apnea duration", apnea_duration_hint="1–60 s", apnea_cycle="Apnea cycle",
        apnea_cycle_hint="1–10 min; duration < cycle", baseline="Baseline modulation",
        amplitude_mod="Amplitude modulation", frequency_mod="Frequency modulation / RSA",
        apnea="Enable periodic apnea",
        resp_note="Apnea suppresses respiratory modulation. Cardiac pulses continue.\n"
                  "Variation changes the model waveform; it is not a measured respiratory value.",
        apply_respiration="Apply respiration",
        dynamics_note="Physiological dynamics / switch off for repeatable nominal AC and HR tests",
        hr_amplitude="HR changes pulse amplitude", spo2_coupling="SpO₂ changes notch shape",
        variability="Beat variability / arrhythmia", apply_dynamics="Apply dynamics",
        noise_note="Artefact injection  /  independent random streams for IR and RED",
        noise_amplitude="Amplitude", noise_amplitude_hint="mV; white/motion RMS, sine peak",
        noise_freq="Frequency", noise_freq_hint="Hz; model Nyquist limit < 50 Hz", seed="Random seed",
        seed_hint="Auto = random; + / − = one seed", noise_level="Proportional noise",
        noise_level_hint="0–1; only used by proportional kind", apply_noise="Apply noise",
        mains_note="50/60 Hz mains injection is rejected at the 100 Hz model rate; interpolation adds no bandwidth.",
        calibration_note="SpO₂ calibration  /  SpO₂ = A − B × R  /  coefficients belong to your optical assembly",
        coeff_a="Coefficient A", coeff_b="Coefficient B", coeff_b_hint="Must be > 0",
        apply_coefficients="Apply coefficients", not_number="{key}: enter a number",
        ie_integer="Inhale : exhale requires an integer from 1 to 5", seed_integer="Seed must be an integer",
        tab_max30102="MAX30102",
        max30102_note="Output for a MAX30102 sensor (e.g. ESP32 + MAX30102 reading HR). The sensor cancels steady "
                      "light, so only the RED LED is driven, switched on and off {rate} times a second; "
                      "its on-level follows the PPG. IR is off.",
        max30102_preset="Preset while on: RED DC {dc:g} mV · AC {ac:g} mV · on-level capped at {peak:g} mV",
        max30102_user="Heart rate, SpO₂, respiration and noise stay under your control (main screen and the "
                      "other tabs). DC/AC on the Amplitude tab are held at the preset and come back when the "
                      "mode is switched off.",
        max30102_limits="One RED channel carries no SpO₂ for the sensor: it measures the pulse rate only. "
                        "The OPT101 reading pauses while this output runs. Bench check, not a clinical "
                        "measurement.",
        max30102_enable="MAX30102 mode", apply_max30102="Apply MAX30102 mode",
        waveforms={}, noises={}),
    "vi": dict(
        tab_amplitude="Biên độ & hình dạng", tab_respiration="Hô hấp", tab_noise="Nhiễu & hiệu chuẩn",
        idle="Thay đổi chỉ có hiệu lực khi bấm Áp dụng.", applied="Đã áp dụng. Thiết lập sẽ được lưu khi thoát.",
        toast="✓ Đã thiết lập thông số: {what}",
        auto="Tự động", ac_red_hint="Tự động = suy ra từ SpO₂", offset="Độ lệch DC đầu ra",
        offset_hint="0–2000 mV; DC + độ lệch ≤ 3000", gain="Hệ số khuếch đại AC", gain_hint="0,1–5,0 ×",
        notch="Độ suy giảm notch cục bộ", notch_hint="0–1; 0,25 = giảm cục bộ 25%", spo2="SpO₂ mục tiêu",
        spo2_hint="0–100 %, phụ thuộc hiệu chuẩn", above="AC phía trên DC", below="AC phía dưới DC",
        lock_ac="Giữ AC khi DC thay đổi", lock_dc="Giữ DC khi tỉ số AC/DC thay đổi",
        shape_note="Tâm các thành phần tính ở 60 bpm · SP < DN < DP · đỉnh/đáy thực tế có thể lệch.\n"
                   "Notch 0 = không lõm thêm; khe tự nhiên vẫn có thể còn. Không phải khoảng bình thường lâm sàng.",
        sp="Đỉnh tâm thu", dn="Khuyết dicrotic (notch)", dp="Đỉnh tâm trương", time_hint="ms / 0–1000",
        apply_signal="Áp dụng biên độ & hình dạng",
        resp_rate="Nhịp thở", resp_rate_hint="1–150 nhịp/phút", ie="Hít vào : thở ra",
        ie_hint="1:N, N = 1…5", variation="Biến thiên", variation_hint="1–16 % của AC",
        apnea_duration="Thời gian ngưng thở", apnea_duration_hint="1–60 s", apnea_cycle="Chu kỳ ngưng thở",
        apnea_cycle_hint="1–10 phút; thời gian < chu kỳ", baseline="Điều biến đường nền",
        amplitude_mod="Điều biến biên độ", frequency_mod="Điều biến tần số / RSA",
        apnea="Bật ngưng thở định kỳ",
        resp_note="Ngưng thở tắt điều biến hô hấp; xung tim vẫn tiếp tục.\n"
                  "Biến thiên làm thay đổi dạng sóng mô hình, không phải giá trị hô hấp đo được.",
        apply_respiration="Áp dụng hô hấp",
        dynamics_note="Động học sinh lý / tắt để kiểm tra AC và HR danh định lặp lại được",
        hr_amplitude="HR thay đổi biên độ xung", spo2_coupling="SpO₂ thay đổi hình dạng notch",
        variability="Biến thiên nhịp / loạn nhịp", apply_dynamics="Áp dụng động học",
        noise_note="Chèn nhiễu  /  luồng ngẫu nhiên độc lập cho IR và RED",
        noise_amplitude="Biên độ", noise_amplitude_hint="mV; RMS với nhiễu trắng/chuyển động, đỉnh với sin",
        noise_freq="Tần số", noise_freq_hint="Hz; giới hạn Nyquist của mô hình < 50 Hz", seed="Seed ngẫu nhiên",
        seed_hint="Tự động = ngẫu nhiên; + / − = một seed", noise_level="Nhiễu tỉ lệ",
        noise_level_hint="0–1; chỉ dùng cho loại tỉ lệ", apply_noise="Áp dụng nhiễu",
        mains_note="Nhiễu điện lưới 50/60 Hz bị từ chối ở tốc độ mô hình 100 Hz; nội suy không thêm băng thông.",
        calibration_note="Hiệu chuẩn SpO₂  /  SpO₂ = A − B × R  /  hệ số thuộc về cụm quang học của bạn",
        coeff_a="Hệ số A", coeff_b="Hệ số B", coeff_b_hint="Phải > 0",
        apply_coefficients="Áp dụng hệ số", not_number="{key}: hãy nhập một số",
        ie_integer="Hít vào : thở ra cần số nguyên từ 1 đến 5", seed_integer="Seed phải là số nguyên",
        tab_max30102="MAX30102",
        max30102_note="Đầu ra cho cảm biến MAX30102 (ví dụ ESP32 + MAX30102 đo nhịp tim). Cảm biến tự trừ ánh "
                      "sáng ổn định, nên chỉ LED RED được phát, bật/tắt {rate} lần mỗi giây; "
                      "mức sáng lúc bật đi theo dạng sóng PPG. LED IR tắt.",
        max30102_preset="Thông số đặt sẵn khi bật: RED DC {dc:g} mV · AC {ac:g} mV · mức bật tối đa {peak:g} mV",
        max30102_user="Nhịp tim, SpO₂, nhịp thở và nhiễu vẫn do bạn điều khiển (màn hình chính và các tab "
                      "khác). DC/AC ở tab Biên độ được giữ theo thông số đặt sẵn và trở lại giá trị cũ khi tắt "
                      "chế độ này.",
        max30102_limits="Chỉ một kênh RED nên cảm biến không đo được SpO₂: chỉ đo nhịp tim. Việc đọc OPT101 "
                        "tạm dừng trong lúc phát chế độ này. Đây là kiểm tra trên bàn thử, không phải phép đo "
                        "lâm sàng.",
        max30102_enable="Chế độ MAX30102", apply_max30102="Áp dụng chế độ MAX30102",
        # Option-menu labels for the model identifiers (English shows the identifiers themselves).
        waveforms=dict(ppg="PPG", sine="Hình sin", triangle="Tam giác", square="Vuông"),
        noises=dict(none="Không", proportional="Tỉ lệ", white="Nhiễu trắng", sine="Hình sin",
                    powerline="Điện lưới", motion="Chuyển động")),
}


class AdvancedFrame(ctk.CTkFrame):
    def __init__(self, master, language="en", **kwargs):
        super().__init__(master, **kwargs)
        self.language = normalise_language(language)
        self.t = COPY[self.language]
        self.engine = SignalEngine.get_instance()
        self._user_hold = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        T.label(self, text(self.language, "settings"), 22, True, anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.tabs = ctk.CTkTabview(self, fg_color=T.PANEL, command=lambda: self._build_tab(self.tabs.get()))
        self.tabs.grid(row=1, column=0, sticky="nsew")
        self.entries, self.vars = {}, {}
        # Each tab is filled the first time it is shown: building all three at once made opening
        # the window the slowest UI operation. Every Apply reads only its own tab.
        self._unbuilt = {}
        t = self.t
        self.max30102_var = None
        for name, build in ((t["tab_amplitude"], self._amplitude), (t["tab_respiration"], self._respiration),
                            (t["tab_noise"], self._noise), (t["tab_max30102"], self._max30102)):
            tab = self.tabs.add(name)
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)
            self._unbuilt[name] = (tab, build)
        self._build_tab(self.tabs.get())
        self.idle_status = self.t["idle"]
        self.status = T.label(self, self.idle_status, 12, text_color=T.MUTED, anchor="w")
        self.status.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.toast = ctk.CTkLabel(self, text="", fg_color=T.OK_BG, text_color=T.OK, corner_radius=8,
                                  font=T.font(13, True), height=30, padx=14)
        self._toast_job = None
        self._applying = ""

    def _entry(self, body, row, column, key, title, hint=""):
        box = ctk.CTkFrame(body, fg_color="transparent")
        box.grid(row=row, column=column, sticky="ew", padx=12, pady=5)
        box.grid_columnconfigure(0, weight=1)
        T.label(box, title, 12, anchor="w").grid(row=0, column=0, sticky="w")
        span = self._slider_range(key)
        entry = TouchSlider(box, *span, optional=key in ("ac_red_mv", "noise_seed"),
                            command=lambda _value: self._mark_user_edit(key), auto_label=self.t["auto"])
        entry.grid(row=1, column=0, columnspan=2, sticky="ew")
        if hint: T.label(box, hint, 10, text_color=T.MUTED, anchor="w").grid(row=2, column=0, columnspan=2, sticky="w")
        self.entries[key] = entry

    @staticmethod
    def _slider_range(key):
        spans = {
            "ac_ir_mv": limits.AC_LEVEL_MV, "ac_red_mv": limits.AC_LEVEL_MV,
            "dc_ir_mv": limits.DC_LEVEL_MV, "dc_red_mv": limits.DC_LEVEL_MV,
            "output_dc_offset_mv": limits.OUTPUT_DC_OFFSET_MV,
            "amplification": limits.AMPLIFICATION, "dicrotic_notch": limits.DICROTIC_NOTCH_DEPTH,
            "spo2": limits.SPO2, "resp_rate": limits.RESP_RATE,
            "resp_variation_ir_pct": limits.RESP_VARIATION_PCT,
            "resp_variation_red_pct": limits.RESP_VARIATION_PCT,
            "apnea_duration_s": limits.APNEA_DURATION_S, "apnea_cycle_min": limits.APNEA_CYCLE_MIN,
            "noise_amplitude_mv": limits.NOISE_AMPLITUDE_MV, "noise_level": limits.NOISE_LEVEL,
        }
        if key.startswith(("sp_ms_", "dn_ms_", "dp_ms_")):
            span = limits.FEATURE_TIME_MS
        else:
            span = spans.get(key)
        if span:
            return span.minimum, span.maximum, span.step
        return {"resp_ie_ratio": (1,5,1), "noise_freq_hz": (0,49.99,0.01),
                "noise_seed": (0,9999,1), "spo2_coeff_a": (90,130,0.1),
                "spo2_coeff_b": (5,50,0.1)}[key]

    def _check(self, body, row, column, key, title, command=None):
        var = ctk.BooleanVar(value=False)
        self.vars[key] = var
        ctk.CTkCheckBox(body, text=title, variable=var, command=command).grid(row=row, column=column, sticky="w", padx=12, pady=10)

    def _note(self, body, row, text):
        T.label(body, text, 11, text_color=T.MUTED, anchor="w", justify="left").grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=12, pady=8)

    def _label(self, table, key):
        """Option-menu label of a model identifier (the identifier itself when untranslated)."""
        return self.t[table].get(key, key)

    def _key(self, table, label, keys):
        return next((k for k in keys if self._label(table, k) == label), label)

    def _amplitude(self, b):
        t = self.t
        for row, fields in enumerate((
            (("ac_ir_mv", "AC · IR", "0–1500 mV"), ("ac_red_mv", "AC · RED", t["ac_red_hint"])),
            (("dc_ir_mv", "DC · IR", "0–1500 mV"), ("dc_red_mv", "DC · RED", "0–1500 mV")),
            (("output_dc_offset_mv", t["offset"], t["offset_hint"]), ("amplification", t["gain"], t["gain_hint"])),
            (("dicrotic_notch", t["notch"], t["notch_hint"]), ("spo2", t["spo2"], t["spo2_hint"])),
        )):
            for col, (key, title, hint) in enumerate(fields): self._entry(b, row, col, key, title, hint)
        self.waveform_menu = ctk.CTkOptionMenu(b, values=[self._label("waveforms", k) for k in WAVEFORM_KINDS])
        self.waveform_menu.grid(row=4, column=0, sticky="ew", padx=12, pady=8)
        self.polarity_menu = ctk.CTkOptionMenu(b, values=[t["above"], t["below"]])
        self.polarity_menu.grid(row=4, column=1, sticky="ew", padx=12, pady=8)
        self._check(b, 5, 0, "lock_ac", t["lock_ac"], command=lambda: self._mark_user_edit("lock_ac"))
        self._check(b, 5, 1, "lock_dc", t["lock_dc"], command=lambda: self._mark_user_edit("lock_dc"))
        self._note(b, 6, t["shape_note"])
        for row, kind in ((7, "sp"), (8, "dn"), (9, "dp")):
            for col, ch in enumerate(("ir", "red")):
                self._entry(b, row, col, kind + "_ms_" + ch, t[kind] + " · " + ch.upper(), t["time_hint"])
        self._apply_button("apply_signal", self.on_apply_signal)

    def _respiration(self, b):
        t = self.t
        for row, fields in enumerate((
            (("resp_rate", t["resp_rate"], t["resp_rate_hint"]), ("resp_ie_ratio", t["ie"], t["ie_hint"])),
            (("resp_variation_ir_pct", t["variation"] + " · IR", t["variation_hint"]),
             ("resp_variation_red_pct", t["variation"] + " · RED", t["variation_hint"])),
            (("apnea_duration_s", t["apnea_duration"], t["apnea_duration_hint"]),
             ("apnea_cycle_min", t["apnea_cycle"], t["apnea_cycle_hint"])),
        )):
            for col, field in enumerate(fields): self._entry(b, row, col, *field)
        self._check(b, 3, 0, "resp_mod_baseline", t["baseline"])
        self._check(b, 3, 1, "resp_mod_amplitude", t["amplitude_mod"])
        self._check(b, 4, 0, "resp_mod_frequency", t["frequency_mod"])
        self._check(b, 4, 1, "apnea_enabled", t["apnea"])
        self._note(b, 5, t["resp_note"])
        self._apply_button("apply_respiration", self.on_apply_respiration)
        self._note(b, 7, t["dynamics_note"])
        self._check(b, 8, 0, "hr_amplitude_enabled", t["hr_amplitude"])
        self._check(b, 8, 1, "spo2_coupling_enabled", t["spo2_coupling"])
        self._check(b, 9, 0, "variability_enabled", t["variability"])
        self._apply_button("apply_dynamics", self.on_apply_dynamics)

    def on_apply_dynamics(self):
        self._apply(lambda: self.engine.update_modelling_options(
            self.vars["hr_amplitude_enabled"].get(), self.vars["spo2_coupling_enabled"].get(),
            self.vars["variability_enabled"].get()))

    def _noise(self, b):
        t = self.t
        self._note(b, 0, t["noise_note"])
        self.noise_menu = ctk.CTkOptionMenu(b, values=[self._label("noises", k) for k in NOISE_KINDS])
        self.noise_menu.grid(row=1, column=0, sticky="ew", padx=12, pady=8)
        self._entry(b, 1, 1, "noise_amplitude_mv", t["noise_amplitude"], t["noise_amplitude_hint"])
        self._entry(b, 2, 0, "noise_freq_hz", t["noise_freq"], t["noise_freq_hint"])
        self._entry(b, 2, 1, "noise_seed", t["seed"], t["seed_hint"])
        self._entry(b, 3, 0, "noise_level", t["noise_level"], t["noise_level_hint"])
        self._apply_button("apply_noise", self.on_apply_noise)
        self._note(b, 4, t["mains_note"])
        self._note(b, 5, t["calibration_note"])
        self._entry(b, 6, 0, "spo2_coeff_a", t["coeff_a"])
        self._entry(b, 6, 1, "spo2_coeff_b", t["coeff_b"], t["coeff_b_hint"])
        self._apply_button("apply_coefficients", self.on_apply_coefficients)

    def _max30102(self, b):
        t = self.t
        self._note(b, 0, t["max30102_note"].format(rate=MAX30102_WRITE_HZ))
        self._note(b, 1, t["max30102_preset"].format(dc=MAX30102_DC_MV, ac=MAX30102_AC_MV, peak=MAX30102_PEAK_MAX_MV))
        self.max30102_var = ctk.BooleanVar(value=self.engine.max30102_mode)
        ctk.CTkCheckBox(b, text=t["max30102_enable"], variable=self.max30102_var).grid(
            row=2, column=0, sticky="w", padx=12, pady=10)
        self._note(b, 3, t["max30102_user"])
        self._note(b, 4, t["max30102_limits"])
        self._apply_button("apply_max30102", self.on_apply_max30102)

    def on_apply_max30102(self):
        self._apply(lambda: self.engine.set_max30102_mode(self.max30102_var.get()))

    def _number(self, key, optional=False):
        text = self.entries[key].get().strip()
        if optional and not text: return None
        try: return float(text)
        except ValueError: raise ValueError(self.t["not_number"].format(key=key))

    def _apply_button(self, key, command):
        """Apply buttons sit in the tab's fixed footer, outside the scrolled form: on the
        1024x600 panel the form is 2-4x taller than its visible area."""
        what = self.t[key].removeprefix("Áp dụng ").removeprefix("Apply ")
        def press():
            self._applying = what   # the on_apply_* handler runs its own _apply()
            try:
                command()
            finally:
                self._applying = ""
        button = ctk.CTkButton(self._footer, text=self.t[key], height=38, command=press)
        button.pack(side="left", fill="x", expand=True, padx=12, pady=8)

    def _apply(self, callback):
        """Run an Apply; on success show the 'applied' status and a short toast over the form."""
        try:
            callback()
            self._user_hold.clear()
            self.status.configure(text=self.t["applied"], text_color=T.ACCENT)
            self._show_toast(self.t["toast"].format(what=self._applying).rstrip(": "))
        except (ValueError, TypeError) as exc:
            self.status.configure(text=str(exc), text_color=T.ERROR)

    def _show_toast(self, message):
        if self._toast_job is not None:
            self.after_cancel(self._toast_job)
        self.toast.configure(text=message)
        self.toast.place(relx=0.5, y=6, anchor="n")
        self.toast.lift()
        self._toast_job = self.after(TOAST_MS, self._hide_toast)

    def _hide_toast(self):
        self._toast_job = None
        self.toast.place_forget()

    def on_apply_signal(self):
        def apply():
            keys = ("dc_ir_mv", "dc_red_mv", "ac_ir_mv", "output_dc_offset_mv", "amplification", "dicrotic_notch", "spo2")
            values = {k: self._number(k) for k in keys}
            values["ac_red_mv"] = self._number("ac_red_mv", True)
            values["waveform"] = self._key("waveforms", self.waveform_menu.get(), WAVEFORM_KINDS)
            values["ac_polarity"] = 0 if self.polarity_menu.get() == self.t["above"] else 1
            values.update({k: self.vars[k].get() for k in ("lock_ac", "lock_dc")})
            for ch in ("ir", "red"):
                for kind in ("sp", "dn", "dp"):
                    key = kind + "_ms_" + ch
                    values[key] = self._number(key)
            self.engine.update_signal_settings(values)
        self._apply(apply)

    def on_apply_respiration(self):
        def apply():
            ratio = self._number("resp_ie_ratio")
            if not ratio.is_integer(): raise ValueError(self.t["ie_integer"])
            self.engine.update_respiration(RespirationConfig(
                rate_brpm=self._number("resp_rate"), inhale_exhale_ratio=int(ratio),
                variation_ir_pct=self._number("resp_variation_ir_pct"),
                variation_red_pct=self._number("resp_variation_red_pct"),
                baseline_enabled=self.vars["resp_mod_baseline"].get(),
                amplitude_enabled=self.vars["resp_mod_amplitude"].get(),
                frequency_enabled=self.vars["resp_mod_frequency"].get(),
                apnea_enabled=self.vars["apnea_enabled"].get(),
                apnea_duration_s=self._number("apnea_duration_s"), apnea_cycle_min=self._number("apnea_cycle_min")))
        self._apply(apply)

    def on_apply_noise(self):
        def apply():
            seed = self._number("noise_seed", True)
            if seed is not None and not seed.is_integer(): raise ValueError(self.t["seed_integer"])
            self.engine.update_noise_settings(self._key("noises", self.noise_menu.get(), NOISE_KINDS),
                self._number("noise_amplitude_mv"),
                self._number("noise_freq_hz"), None if seed is None else int(seed), self._number("noise_level"))
        self._apply(apply)

    def on_apply_coefficients(self):
        self._apply(lambda: self.engine.update_spo2_coefficients(self._number("spo2_coeff_a"), self._number("spo2_coeff_b")))

    def _display_value(self, p, key):
        """Entry text for one engine parameter, with the derived-AC rule.

        AC IR None is displayed as its nominal PI/100 x DC value (what the
        generator actually outputs); a derived AC RED stays blank, matching
        the "Blank = derive from SpO2" hint.
        """
        value = getattr(p, key)
        if key == "ac_ir_mv" and value is None:
            value = p.perfusion_index * p.dc_ir_mv / 100
        return "" if value is None else f"{value:g}"

    def _mark_user_edit(self, key):
        """Keep an unapplied touch edit until Apply or the form is reopened."""
        self._user_hold[key] = float("inf")

    def periodic_update(self):
        """Mirror engine truth into the phone-addressable widgets every tick.

        - The entry under keyboard focus is never touched (the user may be
          mid-edit); any other entry always shows the engine value.
        - Lock checkboxes revert to engine truth once their hold-off expires.
        """
        p = self.engine.ppg_params
        focused = self.winfo_toplevel().focus_get()
        for key in LIVE_ENTRY_KEYS:
            entry = self.entries.get(key)
            if entry is None or focus_is_inside(focused, entry) or self._user_hold.get(key, 0) > time.monotonic():
                continue
            target = self._display_value(p, key)
            if entry.get() != target:
                entry.delete(0, "end")
                entry.insert(0, target)
        now = time.monotonic()
        for key in LIVE_LOCK_KEYS:
            var = self.vars.get(key)
            if var is None or var.get() == bool(getattr(p, key)):
                continue
            if self._user_hold.get(key, 0.0) > now:
                continue
            var.set(bool(getattr(p, key)))

    def _build_tab(self, name):
        """Fill a tab on its first showing and load its fields from the engine."""
        if name not in self._unbuilt:
            return
        tab, build = self._unbuilt.pop(name)
        entries, variables, menus = set(self.entries), set(self.vars), set(self._menus())
        body = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
        body.grid(row=0, column=0, sticky="nsew")
        body.grid_columnconfigure((0, 1), weight=1, uniform="forms")
        self._footer = ctk.CTkFrame(tab, fg_color=T.PANEL)
        self._footer.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        build(body)
        enable_drag_scroll(body)
        # Only the new widgets: unapplied edits on tabs already built stay as they are.
        self._load(set(self.entries)-entries, set(self.vars)-variables, set(self._menus())-menus)

    def _menus(self):
        return [name for name in ("waveform_menu", "polarity_menu", "noise_menu") if hasattr(self, name)]

    def _load(self, entry_keys, var_keys, menus):
        p = self.engine.ppg_params
        for key in entry_keys:
            entry = self.entries[key]
            entry.delete(0, "end")
            entry.insert(0, self._display_value(p, key))
        for key in var_keys:
            self.vars[key].set(getattr(p, key))
        if "waveform_menu" in menus:
            self.waveform_menu.set(self._label("waveforms", p.waveform))
        if "polarity_menu" in menus:
            self.polarity_menu.set(self.t["above"] if p.ac_polarity == 0 else self.t["below"])
        if "noise_menu" in menus:
            self.noise_menu.set(self._label("noises", p.noise_kind))

    def on_show(self):
        self._user_hold.clear()
        self._load(set(self.entries), set(self.vars), set(self._menus()))
        if self.max30102_var is not None:
            self.max30102_var.set(self.engine.max30102_mode)
