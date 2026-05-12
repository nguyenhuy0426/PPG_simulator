"""
sliders.py — Interactive on-screen sliders and buttons for Pygame.
Matches the neon green Android app UI (Figure 2).
"""

import pygame

class Button:
    """A generic Pygame button with text."""
    def __init__(self, rect, text, font, bg_color, text_color, hover_color, active_color):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.font = font
        self.bg_color = bg_color
        self.text_color = text_color
        self.hover_color = hover_color
        self.active_color = active_color
        self.is_active = False

    def draw(self, surface):
        color = self.active_color if self.is_active else self.bg_color
        pygame.draw.rect(surface, color, self.rect, border_radius=8)
        
        # Draw text
        text_color = (0,0,0) if self.is_active and color != self.bg_color else self.text_color
        rendered = self.font.render(self.text, True, text_color)
        rx = self.rect.x + (self.rect.width - rendered.get_width()) // 2
        ry = self.rect.y + (self.rect.height - rendered.get_height()) // 2
        surface.blit(rendered, (rx, ry))

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                return True
        return False

class AndroidSlider:
    def __init__(self, rect, min_val, max_val, initial_val, color_bg, color_fg, font):
        """
        A slider with a [-] button, a track, and a [+] button matching Android UI.
        """
        self.rect = pygame.Rect(rect)
        self.min_val = min_val
        self.max_val = max_val
        self.val = initial_val
        self.color_bg = color_bg
        self.color_fg = color_fg
        self.font = font
        self.is_dragging = False
        
        # Dimensions
        self.btn_w = self.rect.height
        
        self.btn_minus_rect = pygame.Rect(self.rect.x, self.rect.y, self.btn_w, self.rect.height)
        self.btn_plus_rect = pygame.Rect(self.rect.right - self.btn_w, self.rect.y, self.btn_w, self.rect.height)
        
        self.track_rect = pygame.Rect(
            self.rect.x + self.btn_w + 10, 
            self.rect.y + self.rect.height // 2 - 4, 
            self.rect.width - (self.btn_w * 2) - 20, 
            8
        )
        self.knob_radius = 12

    def handle_event(self, event):
        changed = False
        step = (self.max_val - self.min_val) * 0.05
        if step == 0:
            step = 1

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.btn_minus_rect.collidepoint(event.pos):
                self.val = max(self.min_val, self.val - step)
                return True
            elif self.btn_plus_rect.collidepoint(event.pos):
                self.val = min(self.max_val, self.val + step)
                return True
            elif self.track_rect.collidepoint(event.pos) or self._get_knob_rect().collidepoint(event.pos):
                self.is_dragging = True
                self._update_val_from_pos(event.pos[0])
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.is_dragging = False
        elif event.type == pygame.MOUSEMOTION:
            if self.is_dragging:
                self._update_val_from_pos(event.pos[0])
                return True
        return changed

    def _get_knob_rect(self):
        if self.max_val == self.min_val:
            normalized = 0
        else:
            normalized = (self.val - self.min_val) / (self.max_val - self.min_val)
        normalized = max(0.0, min(1.0, normalized))
        x = self.track_rect.x + int(normalized * self.track_rect.width)
        y = self.track_rect.y + self.track_rect.height // 2
        return pygame.Rect(x - self.knob_radius, y - self.knob_radius, self.knob_radius * 2, self.knob_radius * 2)

    def _update_val_from_pos(self, x):
        rel_x = x - self.track_rect.x
        normalized = rel_x / self.track_rect.width
        normalized = max(0.0, min(1.0, normalized))
        self.val = self.min_val + normalized * (self.max_val - self.min_val)

    def set_value(self, val):
        self.val = max(self.min_val, min(self.max_val, val))

    def get_value(self):
        return self.val

    def draw(self, surface):
        # Draw minus button
        pygame.draw.rect(surface, self.color_fg, self.btn_minus_rect)
        minus = self.font.render("-", True, (0,0,0))
        surface.blit(minus, (self.btn_minus_rect.centerx - minus.get_width()//2, self.btn_minus_rect.centery - minus.get_height()//2))

        # Draw plus button
        pygame.draw.rect(surface, self.color_fg, self.btn_plus_rect)
        plus = self.font.render("+", True, (0,0,0))
        surface.blit(plus, (self.btn_plus_rect.centerx - plus.get_width()//2, self.btn_plus_rect.centery - plus.get_height()//2))

        # Draw track bg
        pygame.draw.rect(surface, self.color_bg, self.track_rect, border_radius=4)
        
        # Draw filled portion
        if self.max_val > self.min_val:
            normalized = (self.val - self.min_val) / (self.max_val - self.min_val)
            filled_rect = pygame.Rect(self.track_rect.x, self.track_rect.y, int(normalized * self.track_rect.width), self.track_rect.height)
            pygame.draw.rect(surface, self.color_fg, filled_rect, border_radius=4)

        # Draw knob
        knob_rect = self._get_knob_rect()
        pygame.draw.circle(surface, self.color_fg, knob_rect.center, self.knob_radius)
