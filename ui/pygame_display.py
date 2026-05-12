"""
pygame_display.py — Fullscreen UI for PPG Simulator matching Android app layout.
Layout: Header bar | Left menu | Waveform area | Controls panel | Mode row
Auto-scales to any resolution (7", 11", 23.8" screens).
"""

import pygame
from config import (
    DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_FULLSCREEN, DISPLAY_FPS,
    WAVEFORM_DISPLAY_DURATION,
    COLOR_BG, COLOR_WAVEFORM_IR, COLOR_WAVEFORM_RED, COLOR_GRID,
    COLOR_HEADER_BG, COLOR_TEXT, COLOR_TEXT_VALUE,
    COLOR_TEXT_LABEL, COLOR_HIGHLIGHT, COLOR_SEPARATOR,
    COLOR_TIME_AXIS, COLOR_BUTTON_HOVER, COLOR_BUTTON_ACTIVE,
    COLOR_BUTTON_BG,
    compute_layout,
)
from comm.logger import log
from ui.sliders import AndroidSlider, Button
from models.ppg_model import CONDITION_NAMES


class PygameDisplay:
    """Manages the Pygame fullscreen display."""

    def __init__(self):
        self.screen = None
        self.clock = None
        self.running = False
        self._layout = None

        # Fonts
        self.font_header = None
        self.font_value = None
        self.font_footer = None
        self.font_label = None
        self.font_small = None

        # Waveform state
        self._waveform_surface = None
        self._sweep_x = 0
        self._prev_y_ir = 0
        self._prev_y_red = 0
        self._first_point = True
        self._last_draw_time = 0
        self._last_ir = 0.0
        self._last_red = 0.0
        self._sweep_min = 9999.0
        self._sweep_max = -9999.0
        self._disp_min = -0.2
        self._disp_max = 3.0
        self._peak_ir = 0.0
        self._peak_red = 0.0
        self._cycle_peak_ir = 0.0
        self._cycle_peak_red = 0.0
        self._last_beat_count = 0

        # Cached metrics
        self._cached_hr = -1
        self._cached_pi = -1
        self._cached_spo2 = -1
        self._cached_rr = -1
        self._cached_condition = ""

        # UI Components
        self.sliders = {}
        self.ui_buttons = {}
        self.cond_buttons = []
        self.ble_status = "DISCONNECTED"
        self.selected_cond_idx = 0

        # Dirty flags for selective redraw
        self._controls_dirty = True
        self._header_dirty = True

    def begin(self) -> bool:
        """Initialize Pygame and set up the display."""
        try:
            pygame.init()
        except pygame.error as e:
            log.error(f"[Display] Pygame init failed: {e}")
            return False

        if DISPLAY_WIDTH == 0 or DISPLAY_HEIGHT == 0:
            info = pygame.display.Info()
            screen_w = info.current_w
            screen_h = info.current_h
        else:
            screen_w = DISPLAY_WIDTH
            screen_h = DISPLAY_HEIGHT

        self._layout = compute_layout(screen_w, screen_h)
        L = self._layout

        if DISPLAY_FULLSCREEN:
            self.screen = pygame.display.set_mode((screen_w, screen_h), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode((screen_w, screen_h))

        pygame.display.set_caption("PPG Simulator")
        self.clock = pygame.time.Clock()

        # Load fonts
        try:
            self.font_header = pygame.font.SysFont("dejavusans", L["font_header"], bold=True)
            self.font_value  = pygame.font.SysFont("dejavusans", L["font_value"], bold=True)
            self.font_footer = pygame.font.SysFont("dejavusans", L["font_footer"])
            self.font_label  = pygame.font.SysFont("dejavusans", L["font_label"])
            self.font_small  = pygame.font.SysFont("dejavusans", L["font_small"])
        except Exception:
            self.font_header = pygame.font.Font(None, L["font_header"])
            self.font_value  = pygame.font.Font(None, L["font_value"])
            self.font_footer = pygame.font.Font(None, L["font_footer"])
            self.font_label  = pygame.font.Font(None, L["font_label"])
            self.font_small  = pygame.font.Font(None, L["font_small"])

        # Waveform surface
        self._waveform_surface = pygame.Surface((L["waveform_w"], L["waveform_h"]))
        self._waveform_surface.fill(COLOR_BG)
        self._prev_y_ir = L["waveform_h"] // 2
        self._prev_y_red = L["waveform_h"] // 2

        self._init_ui()

        # Initial full draw
        self.screen.fill(COLOR_BG)
        self._draw_all()
        pygame.display.flip()

        self.running = True
        log.info(f"[Display] Pygame initialized: {screen_w}x{screen_h} "
                 f"(header={L['header_h']}px, waveform={L['waveform_h']}px, "
                 f"controls={L['controls_h']}px, font_scale={L['font_scale']:.2f})")
        return True

    # ─────────────────────── UI INIT ───────────────────────
    def _init_ui(self):
        L = self._layout
        fs = L["font_scale"]

        # --- Header Buttons ---
        btn_h = max(28, int(32 * fs))
        btn_y = (L["header_h"] - btn_h) // 2
        scan_w = max(70, int(80 * fs))
        disc_w = max(100, int(110 * fs))
        self.ui_buttons['scan'] = Button(
            (L["screen_w"] - scan_w - disc_w - 30, btn_y, scan_w, btn_h),
            "SCAN", self.font_small, COLOR_HIGHLIGHT, (0,0,0),
            COLOR_BUTTON_HOVER, COLOR_HIGHLIGHT
        )
        self.ui_buttons['disconnect'] = Button(
            (L["screen_w"] - disc_w - 10, btn_y, disc_w, btn_h),
            "DISCONNECT", self.font_small, COLOR_BUTTON_BG, (255,100,100),
            COLOR_BUTTON_HOVER, COLOR_BUTTON_ACTIVE
        )

        # --- Sliders ---
        cx = L["waveform_x"]
        cy = L["controls_y"]
        cw = L["waveform_w"]
        ch = L["controls_h"]

        # Reserve bottom row for MODE buttons
        mode_row_h = max(40, int(45 * fs))
        slider_area_h = ch - mode_row_h - 20

        label_w = max(80, int(90 * fs))
        val_w = max(50, int(55 * fs))
        slider_h = max(24, int(28 * fs))
        gap = 10

        # Column 1: HR, SPO2, RR (left half)
        half_w = cw // 2
        s_w1 = half_w - label_w - val_w - gap * 4
        # Column 2: PI, NOISE (right half)
        s_w2 = half_w - label_w - val_w - gap * 4

        row_h = max(slider_h + 12, slider_area_h // 3)
        y_base = cy + 10

        col1_slider_x = cx + label_w + gap * 2
        col2_slider_x = cx + half_w + label_w + gap * 2

        tc = COLOR_BUTTON_BG
        kc = COLOR_HIGHLIGHT

        self.sliders['hr']    = AndroidSlider((col1_slider_x, y_base,            s_w1, slider_h), 20, 300, 75,   tc, kc, self.font_small)
        self.sliders['spo2']  = AndroidSlider((col1_slider_x, y_base + row_h,    s_w1, slider_h), 70, 100, 98,   tc, kc, self.font_small)
        self.sliders['rr']    = AndroidSlider((col1_slider_x, y_base + row_h*2,  s_w1, slider_h), 4,  60,  16,   tc, kc, self.font_small)
        self.sliders['pi']    = AndroidSlider((col2_slider_x, y_base,            s_w2, slider_h), 0.0, 20.0, 2.5, tc, kc, self.font_small)
        self.sliders['noise'] = AndroidSlider((col2_slider_x, y_base + row_h,    s_w2, slider_h), 0.0, 1.0, 0.0,  tc, kc, self.font_small)

        # Store label positions for drawing
        self._slider_labels = [
            (cx + gap, y_base,            "HEART\nRATE",   'hr',    lambda v: f"{int(v)}"),
            (cx + gap, y_base + row_h,    "SPO\u2082",    'spo2',  lambda v: f"{int(v)}"),
            (cx + gap, y_base + row_h*2,  "RESP.\nRATE",  'rr',    lambda v: f"{int(v)}"),
            (cx + half_w + gap, y_base,            "PERF.\nINDEX",  'pi',    lambda v: f"{v:.2f}"),
            (cx + half_w + gap, y_base + row_h,    "NOISE\nLEVEL",  'noise', lambda v: f"{v:.2f}"),
        ]

        # --- Condition Buttons ---
        self.cond_buttons = []
        mode_y = cy + ch - mode_row_h
        n = len(CONDITION_NAMES)
        total_gap = gap * (n + 1)
        avail = cw - label_w - total_gap
        btn_w = avail // n
        for i, name in enumerate(CONDITION_NAMES):
            bx = cx + label_w + gap + i * (btn_w + gap)
            abbrev = name[:12].upper()
            btn = Button(
                (bx, mode_y, btn_w, mode_row_h - 8), abbrev, self.font_small,
                COLOR_BUTTON_BG, COLOR_HIGHLIGHT, COLOR_BUTTON_HOVER, COLOR_HIGHLIGHT
            )
            self.cond_buttons.append(btn)
        if self.cond_buttons:
            self.cond_buttons[0].is_active = True

        self._mode_row_y = mode_y

    # ─────────────────────── DRAWING ───────────────────────
    def _draw_all(self):
        """Full redraw of all UI regions."""
        self._draw_header()
        self._draw_left_panel()
        self._draw_waveform_area()
        self._draw_controls_panel()

    def _draw_header(self):
        L = self._layout
        rect = pygame.Rect(0, 0, L["screen_w"], L["header_h"])
        pygame.draw.rect(self.screen, COLOR_HEADER_BG, rect)
        pygame.draw.line(self.screen, COLOR_SEPARATOR,
                         (0, L["header_h"] - 1), (L["screen_w"], L["header_h"] - 1), 2)

        # Status dot
        is_connected = "DISCONNECTED" not in self.ble_status
        dot_color = COLOR_HIGHLIGHT if is_connected else (255, 60, 60)
        dot_x = 20
        dot_cy = L["header_h"] // 2
        pygame.draw.circle(self.screen, dot_color, (dot_x, dot_cy), max(5, int(6 * L["font_scale"])))

        # Status text
        status_txt = self.font_small.render(self.ble_status, True, dot_color)
        self.screen.blit(status_txt, (dot_x + 18, dot_cy - status_txt.get_height() // 2))

        # "No Device" text
        dev_txt = self.font_small.render("No Device", True, COLOR_TEXT_LABEL)
        self.screen.blit(dev_txt, (dot_x + 22 + status_txt.get_width(), dot_cy - dev_txt.get_height() // 2))

        # Center title
        title = self.font_label.render("PPG SIMULATOR", True, COLOR_TEXT_LABEL)
        self.screen.blit(title, ((L["screen_w"] - title.get_width()) // 2,
                                  dot_cy - title.get_height() // 2))

        # Buttons
        self.ui_buttons['scan'].draw(self.screen)
        self.ui_buttons['disconnect'].draw(self.screen)
        self._header_dirty = False

    def _draw_left_panel(self):
        L = self._layout
        panel_x = 0
        panel_y = L["header_h"]
        panel_w = L["left_menu_w"]
        panel_h = L["screen_h"] - L["header_h"]

        pygame.draw.rect(self.screen, COLOR_BG, (panel_x, panel_y, panel_w, panel_h))
        pygame.draw.line(self.screen, COLOR_SEPARATOR,
                         (panel_w - 1, panel_y), (panel_w - 1, L["screen_h"]), 2)

        labels = ["HR", "SPO\u2082", "RR", "PI", "NOISE", "MODE"]
        btn_h = max(28, int(30 * L["font_scale"]))
        gap = max(6, int(8 * L["font_scale"]))
        bw = panel_w - 20
        y = panel_y + 10

        for text in labels:
            r = pygame.Rect(10, y, bw, btn_h)
            pygame.draw.rect(self.screen, COLOR_BUTTON_BG, r, border_radius=6)
            pygame.draw.rect(self.screen, COLOR_SEPARATOR, r, width=1, border_radius=6)
            t = self.font_small.render(text, True, COLOR_TEXT_LABEL)
            self.screen.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))
            y += btn_h + gap

    def _draw_waveform_area(self):
        L = self._layout
        # Border around waveform
        wf_rect = pygame.Rect(L["waveform_x"], L["waveform_y"], L["waveform_w"], L["waveform_h"])
        pygame.draw.rect(self.screen, COLOR_SEPARATOR, wf_rect, width=1)

        # Draw grid on surface
        self._draw_grid(self._waveform_surface, L["waveform_h"], L["waveform_w"])
        self.screen.blit(self._waveform_surface, (L["waveform_x"], L["waveform_y"]))
        self._draw_time_axis_overlay()

        # PPG label
        lbl = self.font_small.render("PPG", True, COLOR_TEXT_LABEL)
        self.screen.blit(lbl, (L["waveform_x"] + 8, L["waveform_y"] + 6))

        # Refresh rate label
        hz = self.font_small.render("50 Hz", True, COLOR_TEXT_LABEL)
        self.screen.blit(hz, (L["waveform_x"] + L["waveform_w"] - hz.get_width() - 8,
                               L["waveform_y"] + 6))

    def _draw_controls_panel(self):
        L = self._layout
        cx = L["waveform_x"]
        cy = L["controls_y"]
        cw = L["waveform_w"]
        ch = L["controls_h"]

        # Clear controls area (including left menu portion below waveform)
        pygame.draw.rect(self.screen, COLOR_BG, (cx, cy, cw, ch))
        pygame.draw.line(self.screen, COLOR_SEPARATOR, (0, cy), (L["screen_w"], cy), 2)

        # Draw slider labels and values
        for (lx, ly, text, key, fmt) in self._slider_labels:
            lines = text.split('\n')
            for j, line in enumerate(lines):
                t = self.font_small.render(line, True, COLOR_TEXT_LABEL)
                self.screen.blit(t, (lx, ly + j * (t.get_height() + 2)))

            slider = self.sliders[key]
            val_txt = self.font_value.render(fmt(slider.get_value()), True, COLOR_TEXT_VALUE)
            self.screen.blit(val_txt, (slider.rect.right + 15,
                                        ly + (slider.rect.height - val_txt.get_height()) // 2))

        # Draw sliders
        for s in self.sliders.values():
            s.draw(self.screen)

        # Mode label
        mode_lbl = self.font_small.render("MODE", True, COLOR_TEXT_LABEL)
        self.screen.blit(mode_lbl, (cx + 10, self._mode_row_y + 8))

        # Condition buttons
        for btn in self.cond_buttons:
            btn.draw(self.screen)

        self._controls_dirty = False

    # ─────────────────────── GRID / AXES ───────────────────────
    def _draw_grid(self, surface, height, width):
        mid_y = height // 2
        pygame.draw.line(surface, COLOR_GRID, (0, mid_y), (width, mid_y), 1)
        q1, q3 = height // 4, 3 * height // 4
        for x in range(0, width, 6):
            surface.set_at((x, q1), COLOR_GRID)
            surface.set_at((x, q3), COLOR_GRID)
        px_per_sec = width / WAVEFORM_DISPLAY_DURATION
        for i in range(1, int(WAVEFORM_DISPLAY_DURATION) + 1):
            gx = int(i * px_per_sec)
            if gx < width:
                for y in range(0, height, 4):
                    surface.set_at((gx, y), COLOR_GRID)

    def _draw_time_axis_overlay(self):
        L = self._layout
        w, h = L["waveform_w"], L["waveform_h"]
        ox, oy = L["waveform_x"], L["waveform_y"]
        px_per_sec = w / WAVEFORM_DISPLAY_DURATION
        try:
            tf = pygame.font.SysFont("dejavusans", max(10, L["font_small"] - 2))
        except Exception:
            tf = pygame.font.Font(None, max(10, L["font_small"] - 2))
        for i in range(int(WAVEFORM_DISPLAY_DURATION) + 1):
            gx = min(int(i * px_per_sec), w - 1)
            pygame.draw.line(self.screen, COLOR_TIME_AXIS,
                             (ox + gx, oy + h - 10), (ox + gx, oy + h - 1), 1)
            lbl = tf.render(f"{i}s", True, COLOR_TIME_AXIS)
            lx = max(2, min(w - lbl.get_width() - 2, gx - lbl.get_width() // 2))
            self.screen.blit(lbl, (ox + lx, oy + h - 10 - lbl.get_height()))

    # ─────────────────────── WAVEFORM ───────────────────────
    def draw_waveform_point(self, ac_ir: float, ac_red: float, current_beat_count: int = 0):
        import time as _time
        L = self._layout
        wh, ww = L["waveform_h"], L["waveform_w"]
        surface = self._waveform_surface

        now = _time.time()
        if self._last_draw_time == 0:
            self._last_draw_time = now
            self._last_ir = ac_ir
            self._last_red = ac_red
            return

        wall_dt = min(now - self._last_draw_time, 0.05)
        self._last_draw_time = now

        if current_beat_count != self._last_beat_count:
            if self._cycle_peak_ir > 0:
                self._peak_ir = self._cycle_peak_ir
                self._peak_red = self._cycle_peak_red
            self._cycle_peak_ir = 0.0
            self._cycle_peak_red = 0.0
            self._last_beat_count = current_beat_count

        px_per_sec = ww / WAVEFORM_DISPLAY_DURATION
        steps = max(1, round(wall_dt * px_per_sec))
        prev_ir, prev_red = self._last_ir, self._last_red

        for s in range(steps):
            t = (s + 1) / steps
            ir_val = prev_ir + (ac_ir - prev_ir) * t
            red_val = prev_red + (ac_red - prev_red) * t

            if ir_val < self._sweep_min: self._sweep_min = ir_val
            if ir_val > self._sweep_max: self._sweep_max = ir_val
            if abs(ir_val) > self._cycle_peak_ir: self._cycle_peak_ir = abs(ir_val)
            if abs(red_val) > self._cycle_peak_red: self._cycle_peak_red = abs(red_val)

            val_max, val_min = max(ir_val, red_val), min(ir_val, red_val)
            if val_max > self._disp_max: self._disp_max += (val_max - self._disp_max) * 0.05
            if val_min < self._disp_min: self._disp_min -= (self._disp_min - val_min) * 0.05

            y_ir = self._map_to_y(ir_val, self._disp_min, self._disp_max, wh)
            y_red = self._map_to_y(red_val, self._disp_min, self._disp_max, wh)

            # Erase ahead
            ex = (self._sweep_x + 2) % ww
            ew = 4
            if ex + ew <= ww:
                pygame.draw.rect(surface, COLOR_BG, (ex, 0, ew, wh))
            else:
                pygame.draw.rect(surface, COLOR_BG, (ex, 0, ww - ex, wh))
                pygame.draw.rect(surface, COLOR_BG, (0, 0, ew - (ww - ex), wh))

            cx = (self._sweep_x + 1) % ww
            pygame.draw.line(surface, COLOR_GRID, (cx, 0), (cx, wh - 1), 1)

            if self._first_point:
                surface.set_at((self._sweep_x % ww, y_ir), COLOR_WAVEFORM_IR)
                surface.set_at((self._sweep_x % ww, y_red), COLOR_WAVEFORM_RED)
                self._first_point = False
            else:
                px = (self._sweep_x - 1) % ww
                sx = self._sweep_x % ww
                pygame.draw.line(surface, COLOR_WAVEFORM_RED, (px, self._prev_y_red), (sx, y_red), 1)
                pygame.draw.line(surface, COLOR_WAVEFORM_IR, (px, self._prev_y_ir), (sx, y_ir), 2)

            self._prev_y_ir = y_ir
            self._prev_y_red = y_red
            self._sweep_x += 1

            if self._sweep_x >= ww:
                self._sweep_x = 0
                self._first_point = True
                margin = (self._sweep_max - self._sweep_min) * 0.12 + 5
                self._disp_min += ((self._sweep_min - margin) - self._disp_min) * 0.4
                self._disp_max += ((self._sweep_max + margin) - self._disp_max) * 0.4
                self._sweep_min = 9999.0
                self._sweep_max = -9999.0
                surface.fill(COLOR_BG)
                self._draw_grid(surface, wh, ww)

        self._last_ir = ac_ir
        self._last_red = ac_red

        # Blit waveform only into waveform region
        self.screen.blit(surface, (L["waveform_x"], L["waveform_y"]))
        self._draw_time_axis_overlay()
        # PPG label
        lbl = self.font_small.render("PPG", True, COLOR_TEXT_LABEL)
        self.screen.blit(lbl, (L["waveform_x"] + 8, L["waveform_y"] + 6))

    @staticmethod
    def _map_to_y(value, d_min, d_max, height):
        r_min, r_max = d_min, d_max
        if r_max - r_min < 0.1:
            r_max = r_min + 0.1
        padding = (r_max - r_min) * 0.1
        r_max += padding
        r_min -= padding
        normalized = max(0.0, min(1.0, (value - r_min) / (r_max - r_min)))
        return max(0, min(height - 1, int((height - 1) * (1.0 - normalized))))

    # ─────────────────────── PUBLIC API ───────────────────────
    def update_metrics(self, hr, pi, spo2, rr, condition_name):
        """Sync condition buttons when engine condition changes."""
        try:
            cond_idx = CONDITION_NAMES.index(condition_name)
            if self.selected_cond_idx != cond_idx:
                for btn in self.cond_buttons:
                    btn.is_active = False
                if cond_idx < len(self.cond_buttons):
                    self.cond_buttons[cond_idx].is_active = True
                self.selected_cond_idx = cond_idx
                self._controls_dirty = True
        except ValueError:
            pass

        if self._controls_dirty:
            self._draw_controls_panel()

    def update_sliders(self, p):
        """Update slider values from parameter object."""
        self.sliders['hr'].set_value(p.heart_rate)
        self.sliders['pi'].set_value(p.perfusion_index)
        self.sliders['spo2'].set_value(p.spo2)
        self.sliders['rr'].set_value(p.resp_rate)
        self.sliders['noise'].set_value(p.noise_level)
        self._draw_controls_panel()

    def handle_event(self, event):
        """Pass events to sliders/buttons. Returns True if any changed."""
        changed = False
        for s in self.sliders.values():
            if s.handle_event(event):
                changed = True

        for i, btn in enumerate(self.cond_buttons):
            if btn.handle_event(event):
                changed = True
                self.selected_cond_idx = i
                for b in self.cond_buttons:
                    b.is_active = False
                btn.is_active = True

        if changed:
            self._draw_controls_panel()
        return changed

    def clear_waveform(self):
        """Clear the waveform area and reset sweep state."""
        L = self._layout
        self._waveform_surface.fill(COLOR_BG)
        self._draw_grid(self._waveform_surface, L["waveform_h"], L["waveform_w"])
        self.screen.blit(self._waveform_surface, (L["waveform_x"], L["waveform_y"]))
        self._draw_time_axis_overlay()
        self._sweep_x = 0
        self._first_point = True
        self._prev_y_ir = L["waveform_h"] // 2
        self._prev_y_red = L["waveform_h"] // 2
        self._last_draw_time = 0
        self._last_ir = 0.0
        self._last_red = 0.0
        self._sweep_min = 9999.0
        self._sweep_max = -9999.0
        self._disp_min = -0.2
        self._disp_max = 3.0
        self._peak_ir = 0.0
        self._peak_red = 0.0
        self._cycle_peak_ir = 0.0
        self._cycle_peak_red = 0.0
        self._last_beat_count = 0

    def show_status(self, text):
        """Update header status text."""
        self.ble_status = text
        self._draw_header()

    def show_condition_select(self, condition_name, condition_index):
        """Compatibility stub."""
        pass

    def flip(self):
        pygame.display.flip()

    def tick(self, fps=None):
        self.clock.tick(fps or DISPLAY_FPS)

    def quit(self):
        pygame.quit()
