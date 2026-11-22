"""All drawing lives here: arena, entities, HUD, side panel and menu screens.

The renderer only *reads* the World; it never changes game state.
"""

import math
import random

import pygame

from . import config as C
from . import gfx
from . import profile
from .effects import Effects

DIR_NAMES = {"U": "UP", "R": "RIGHT", "D": "DOWN", "L": "LEFT"}
POWER_COLORS = {"freeze": C.FREEZE_C, "decoy": C.DECOY_C, "shield": C.SHIELD_C}
POWER_NAMES = {"freeze": "FREEZE", "decoy": "DECOY", "shield": "SHIELD"}
BRAIN_NOTES = {
    "wanderer": "random walk + slight drift",
    "greedy": "looks only 1 step ahead",
    "mirror": "moves with YOUR habits",
}


def scale(color, k):
    """Darken or brighten an RGB colour.

    Args:
        color: RGB(A) colour; only the RGB part is used.
        k: brightness factor (0.5 = half as bright); results are clamped to 0..255.
    """
    return tuple(max(0, min(255, int(v * k))) for v in color[:3])


def mix(a, b, t):
    """Blend two RGB colours.

    Args:
        a: colour at t = 0.
        b: colour at t = 1.
        t: blend amount 0..1.
    """
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def accuracy_color(acc):
    """Low readability is good for the player (green), high is bad (red).

    Args:
        acc: the model's prediction accuracy 0..1.
    """
    if acc < 0.5:
        return mix(C.GOOD, C.WARN, acc / 0.5)
    return mix(C.WARN, C.HUNTER, min(1.0, (acc - 0.5) / 0.3))


def fmt_time(seconds):
    """Format a number of `seconds` as M:SS for the HUD."""
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


class Renderer:
    def __init__(self, screen):
        """Create the renderer and build its cached images.

        Args:
            screen: the pygame surface to draw on (real resolution = logical x gfx.SCALE).
        """
        self.screen = screen
        self.fonts = {}
        self.text_cache = {}
        self.glows = {}
        self.arena_ref = None
        self.arena_surf = None
        self.overlay = gfx.surface((C.ARENA_W, C.ARENA_H), pygame.SRCALPHA)
        self.vignette = self._make_vignette()
        self.effects = Effects()
        self.vision = False
        self.trail = []
        self.bubbles = {}          # hunter index -> [text, life, max_life]
        self.t = 0.0
        self.ox = self.oy = 0
        rng = random.Random(7)
        self.stars = [[rng.uniform(0, C.WIDTH), rng.uniform(0, C.HEIGHT),
                       rng.uniform(6, 22), rng.choice((C.PLAYER, C.HUNTER, C.ORB, C.DECOY_C))]
                      for _ in range(26)]
        self.backdrop = self._make_backdrop()
        self.static = None         # backdrop with the arena already drawn on it
        self.tints = {}            # cached translucent rectangles
        self.title_surfs = {}
        self.buttons = []          # (rect, action) of touch buttons drawn this frame
        self.pressed_dirs = set()  # D-pad directions currently held (for highlighting)
        self.low_quality = False   # set by the app on slow devices

    def set_screen(self, screen):
        """Switch to a new screen surface (resolution change): rebuild every cached image.

        Args:
            screen: the new pygame surface to draw on.
        """
        self.screen = screen
        self.fonts.clear()
        self.text_cache.clear()
        self.glows.clear()
        self.tints.clear()
        self.title_surfs.clear()
        self.overlay = gfx.surface((C.ARENA_W, C.ARENA_H), pygame.SRCALPHA)
        self.vignette = self._make_vignette()
        self.backdrop = self._make_backdrop()
        self.arena_ref = self.arena_surf = self.static = None

    # ================================================================ basics
    def font(self, size):
        """Default font at `size` logical pixels (cached, created at real resolution)."""
        f = self.fonts.get(size)
        if f is None:
            f = self.fonts[size] = pygame.font.Font(None, max(1, round(size * gfx.SCALE)))
        return f

    def text_surface(self, text, size, color, spacing=0):
        """Render text to a surface at real resolution (cached).

        Args:
            text: the string to render.
            size: font size in logical pixels.
            color: RGB colour.
            spacing: extra letter spacing in logical pixels (0 = normal).
        """
        key = (text, size, color, spacing)
        surf = self.text_cache.get(key)
        if surf is None:
            if len(self.text_cache) > 800:
                self.text_cache.clear()
            font = self.font(size)
            if spacing == 0:
                surf = font.render(text, True, color)
            else:
                spacing = round(spacing * gfx.SCALE)         # letter spacing in real pixels
                glyphs = [font.render(ch, True, color) for ch in text]
                w = sum(g.get_width() for g in glyphs) + spacing * max(0, len(glyphs) - 1)
                h = max((g.get_height() for g in glyphs), default=font.get_height())
                surf = pygame.Surface((max(1, w), h), pygame.SRCALPHA)
                x = 0
                for g in glyphs:
                    surf.blit(g, (x, 0))
                    x += g.get_width() + spacing
            self.text_cache[key] = surf
        return surf

    def text_size(self, text, size, color=(255, 255, 255), spacing=0):
        """Size of a text label in logical pixels.

        Args:
            text: the string to measure.
            size: font size in logical pixels.
            color: colour (only part of the cache key).
            spacing: extra letter spacing in logical pixels.
        """
        return gfx.logical_size(self.text_surface(text, size, color, spacing))

    def blit_text(self, text, size, color, pos, anchor="topleft", spacing=0, target=None):
        """Draw text; `pos`/`anchor` and the returned rect are in logical pixels.

        Args:
            text: the string to draw.
            size: font size in logical pixels.
            color: RGB colour.
            pos: (x, y) point the anchor is placed at.
            anchor: which point of the text sits at `pos`, e.g. "topleft" or "center".
            spacing: extra letter spacing in logical pixels.
            target: surface to draw on; None means the screen.

        Returns:
            The text's rect in logical pixels (for placing things next to it).
        """
        surf = self.text_surface(text, size, color, spacing)
        rect = surf.get_rect(**{anchor: (round(pos[0] * gfx.SCALE), round(pos[1] * gfx.SCALE))})
        (target or self.screen).blit(surf, rect)
        k = gfx.SCALE
        return pygame.Rect(round(rect.x / k), round(rect.y / k), round(rect.w / k), round(rect.h / k))

    def wrap(self, text, size, width, spacing=0):
        """Split `text` into lines that fit a width.

        Args:
            text: the text to wrap.
            size: font size in logical pixels.
            width: maximum line width in logical pixels.
            spacing: extra letter spacing in logical pixels.

        Returns:
            List of lines.
        """
        words, lines, line = text.split(), [], ""
        for w in words:
            trial = (line + " " + w).strip()
            if self.text_size(trial, size, spacing=spacing)[0] <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = w
        if line:
            lines.append(line)
        return lines

    def glow(self, radius, color, strength):
        """A soft radial light (built in real pixels and cached).

        Args:
            radius: glow radius in logical pixels.
            color: RGB colour at the centre.
            strength: brightness 0..1 (rounded to 0.1 so the cache stays small).
        """
        rp = max(2, round(radius * gfx.SCALE))
        strength = round(strength, 1)
        key = (rp, color, strength)
        surf = self.glows.get(key)
        if surf is None:
            if len(self.glows) > 300:
                self.glows.clear()
            surf = pygame.Surface((rp * 2, rp * 2))
            surf.fill((0, 0, 0))
            for r in range(rp, 0, -1):
                k = (1 - r / rp) ** 2 * strength
                pygame.draw.circle(surf, scale(color, k), (rp, rp), r)
            self.glows[key] = surf
        return surf

    def draw_glow(self, x, y, radius, color, strength=0.6, target=None):
        """Add a glow centred on (x, y) using additive blending.

        Args:
            x, y: centre in logical pixels.
            radius: glow radius in logical pixels.
            color: RGB colour.
            strength: brightness 0..1.
            target: surface to draw on; None means the screen.
        """
        surf = self.glow(radius, color, strength)
        r = surf.get_width() // 2
        (target or self.screen).blit(surf, (round(x * gfx.SCALE) - r, round(y * gfx.SCALE) - r),
                                     special_flags=pygame.BLEND_RGB_ADD)

    def card(self, rect, title=None, accent=None):
        """Draw a rounded panel like the side cards.

        Args:
            rect: (x, y, w, h) in logical pixels.
            title: optional small heading in the top-left corner.
            accent: optional colour for the short accent mark at the top.
        """
        gfx.rect(self.screen, C.CARD_BG, rect, border_radius=14)
        gfx.rect(self.screen, C.CARD_EDGE, rect, width=1, border_radius=14)
        if accent:
            gfx.rect(self.screen, accent, (rect[0] + 16, rect[1], 36, 3), border_radius=2)
        if title:
            self.blit_text(title, 17, C.MUTED, (rect[0] + 16, rect[1] + 14), spacing=2)

    def pill(self, x, y, text, color, target=None):
        """Draw a small rounded label such as "AI VISION" or "SHIELD".

        Args:
            x, y: top-left in logical pixels.
            text: the label text.
            color: colour of the text and border.
            target: surface to draw on; None means the screen.

        Returns:
            The pill's width in logical pixels (to place the next one).
        """
        surf = self.text_surface(text, 17, color, 1)
        tw, th = gfx.logical_size(surf)
        w, h = tw + 20, 24
        tgt = target or self.screen
        gfx.rect(tgt, scale(color, 0.18), (x, y, w, h), border_radius=12)
        gfx.rect(tgt, scale(color, 0.7), (x, y, w, h), width=1, border_radius=12)
        gfx.blit(tgt, surf, (x + 10, y + (h - th) / 2 + 1))
        return w

    def arrow(self, center, direction, size, color):
        """Draw an arrow (used for the mind-model bars and the D-pad).

        Args:
            center: (x, y) centre in logical pixels.
            direction: "U", "R", "D" or "L".
            size: half-length of the arrow in logical pixels.
            color: RGB colour.
        """
        x, y = center
        dx, dy = C.DIRS[direction]
        px, py = -dy, dx
        tip = (x + dx * size, y + dy * size)
        base = (x - dx * size * 0.2, y - dy * size * 0.2)
        left = (base[0] + px * size * 0.75, base[1] + py * size * 0.75)
        right = (base[0] - px * size * 0.75, base[1] - py * size * 0.75)
        gfx.polygon(self.screen, color, (tip, left, right))
        tail_end = (x - dx * size, y - dy * size)
        gfx.line(self.screen, color, base, tail_end, max(2, int(size * 0.45)))

    def power_icon(self, x, y, kind, color, target=None, r=8):
        """Draw the icon of a power-up.

        Args:
            x, y: centre in logical pixels.
            kind: "freeze", "decoy" or "shield".
            color: RGB colour.
            target: surface to draw on; None means the screen.
            r: icon radius in logical pixels.
        """
        tgt = target or self.screen
        if kind == "freeze":
            for k in range(3):
                a = math.pi * k / 3
                dx, dy = math.cos(a) * r, math.sin(a) * r
                gfx.line(tgt, color, (x - dx, y - dy), (x + dx, y + dy), 2)
        elif kind == "decoy":
            gfx.circle(tgt, color, (x - r * 0.35, y), r * 0.6, 2)
            gfx.circle(tgt, color, (x + r * 0.45, y), r * 0.6)
        else:
            pts = [(x - r * 0.8, y - r * 0.7), (x + r * 0.8, y - r * 0.7),
                   (x + r * 0.8, y + r * 0.1), (x, y + r), (x - r * 0.8, y + r * 0.1)]
            gfx.polygon(tgt, color, pts, 2)

    def tint(self, rect, rgba, radius=0):
        """Draw a translucent (optionally rounded) rectangle, cached so it costs one blit.

        Args:
            rect: (x, y, w, h) in logical pixels.
            rgba: colour with alpha (opacity) 0..255.
            radius: corner radius in logical pixels (0 = square).
        """
        x, y, w, h = rect
        rgba = (*rgba[:3], max(0, min(255, int(rgba[3]) // 8 * 8)))   # few cache entries
        key = (round(w), round(h), rgba, radius)
        surf = self.tints.get(key)
        if surf is None:
            if len(self.tints) > 120:
                self.tints.clear()
            surf = gfx.surface((w, h), pygame.SRCALPHA)
            if radius:
                gfx.rect(surf, rgba, (0, 0, w, h), border_radius=radius)
            else:
                surf.fill(rgba)
            self.tints[key] = surf
        gfx.blit(self.screen, surf, (x, y))

    # ============================================================== backdrop
    def _make_backdrop(self):
        """Build the dark background with its dot grid (drawn once, reused every frame)."""
        surf = gfx.surface((C.WIDTH, C.HEIGHT))
        surf.fill(C.BG)
        for x in range(0, C.WIDTH, 40):
            for y in range(0, C.HEIGHT, 40):
                gfx.circle(surf, (22, 29, 52), (x, y), 1)
        return surf

    def _make_vignette(self):
        """Red glow around the arena edge, shown when a hunter is close."""
        surf = gfx.surface((C.ARENA_W, C.ARENA_H), pygame.SRCALPHA)
        depth = 56
        for i in range(depth):
            a = int(170 * (1 - i / depth) ** 2)
            gfx.rect(surf, (255, 40, 90, a),
                             (i, i, C.ARENA_W - 2 * i, C.ARENA_H - 2 * i), width=1,
                             border_radius=max(0, 16 - i))
        return surf

    def draw_stars(self, dt, speed=1.0):
        """Draw the slowly rising background lights.

        Args:
            dt: seconds since the last frame.
            speed: drift speed multiplier (1 = normal).
        """
        for s in self.stars:
            s[1] -= s[2] * dt * speed
            if s[1] < -20:
                s[1] = C.HEIGHT + 20
                s[0] = random.uniform(0, C.WIDTH)
            if self.low_quality:
                gfx.circle(self.screen, scale(s[3], 0.35), (s[0], s[1]), 2)
            else:
                self.draw_glow(s[0], s[1], 10 + s[2] * 0.5, s[3], 0.25)

    # ================================================================= arena
    def _build_arena(self, arena):
        """Draw the arena floor, grid dots and neon walls into one cached surface.

        Args:
            arena: the Arena whose walls are drawn; neighbouring walls are joined.
        """
        surf = gfx.surface((C.ARENA_W, C.ARENA_H))
        surf.fill(C.BG)
        gfx.rect(surf, C.ARENA_BG, (0, 0, C.ARENA_W, C.ARENA_H), border_radius=16)
        for c in range(1, arena.cols):
            for r in range(1, arena.rows):
                gfx.circle(surf, C.GRID_DOT, (c * C.CELL, r * C.CELL), 2)
        cs, pad = C.CELL, 6
        pieces = []
        for (c, r) in arena.walls:
            x, y = c * cs, r * cs
            pieces.append(pygame.Rect(x + pad, y + pad, cs - 2 * pad, cs - 2 * pad))
            if (c + 1, r) in arena.walls:
                pieces.append(pygame.Rect(x + cs // 2, y + pad, cs, cs - 2 * pad))
            if (c, r + 1) in arena.walls:
                pieces.append(pygame.Rect(x + pad, y + cs // 2, cs - 2 * pad, cs))
            if {(c + 1, r), (c, r + 1), (c + 1, r + 1)} <= arena.walls:   # fill 2x2 blocks
                pieces.append(pygame.Rect(x + cs // 2, y + cs // 2, cs, cs))
        for rect in pieces:
            gfx.rect(surf, C.WALL_EDGE, rect.inflate(4, 4), border_radius=9)
        for rect in pieces:
            gfx.rect(surf, C.WALL, rect, border_radius=7)
        gfx.rect(surf, C.CARD_EDGE, (0, 0, C.ARENA_W, C.ARENA_H), width=2, border_radius=16)
        return surf

    def px(self, cell):
        """Screen position (logical pixels) of the centre of `cell`, including screen shake."""
        return (C.ARENA_X + self.ox + (cell[0] + 0.5) * C.CELL,
                C.ARENA_Y + self.oy + (cell[1] + 0.5) * C.CELL)

    def local(self, cell):
        """Position of the centre of `cell` inside the arena surface (logical pixels)."""
        return ((cell[0] + 0.5) * C.CELL, (cell[1] + 0.5) * C.CELL)

    # ============================================================ world events
    def on_events(self, events, world):
        """Turn this frame's world events into particles, floating text, flashes and bubbles.

        Args:
            events: list of event tuples from World.pop_events(), e.g. ("orb", cell, points, combo).
            world: the World being drawn.
        """
        fx = self.effects
        for ev in events:
            kind = ev[0]
            if kind == "level":
                self.trail.clear()
                self.bubbles.clear()
                fx.clear()
            elif kind == "orb":
                x, y = self.px(ev[1])
                fx.burst(x, y, C.ORB, 22, 200)
                fx.ring(x, y, C.ORB, 20, 160, 0.35)
                label = f"+{ev[2]}" + (f"  x{ev[3]}" if ev[3] > 1 else "")
                fx.text(x, y - 20, label, C.ORB, 0.9, 28)
            elif kind == "surprise":
                x, y = self.px(ev[1])
                fx.burst(x, y, C.CHAOS_C, 12, 150, 0.45, 3)
                fx.text(x, y - 46, f"+{C.SURPRISE_POINTS} SURPRISE!", C.CHAOS_C, 0.8, 24)
            elif kind == "confused":
                for h in world.hunters:
                    x, y = self.px(h.cell)
                    fx.ring(x, y, C.CHAOS_C, 30, 260, 0.6)
                fx.add_flash(C.CHAOS_C, 0.35)
                fx.add_shake(6)
            elif kind == "taunt":
                life = C.TAUNT_TIME if world.phase == "play" else C.DEATH_TIME + C.KILLCAM_TIME
                self.bubbles[ev[1]] = [ev[2], life, life]
            elif kind == "powerup":
                x, y = self.px(ev[1])
                col = POWER_COLORS[ev[2]]
                fx.ring(x, y, col, 32, 300, 0.5)
                fx.text(x, y - 22, POWER_NAMES[ev[2]] + "!", col, 1.1, 30)
                fx.add_flash(col, 0.25)
            elif kind == "close_call":
                x, y = self.px(ev[1])
                fx.text(x, y - 26, "CLOSE CALL! +50", C.WARN, 1.0, 28)
                fx.add_shake(6)
            elif kind == "shield_break":
                x, y = self.px(ev[1])
                fx.ring(x, y, C.SHIELD_C, 40, 360, 0.6)
                fx.text(x, y - 26, "SHIELD SAVED YOU", C.SHIELD_C, 1.2, 28)
                fx.add_shake(10)
                fx.add_flash(C.SHIELD_C, 0.4)
            elif kind == "death":
                x, y = self.px(ev[1])
                fx.burst(x, y, C.PLAYER, 60, 340, 1.0, 5)
                fx.burst(x, y, ev[2], 30, 260, 0.8, 4)
                fx.add_shake(16)
                fx.add_flash(C.HUNTER, 0.55)
            elif kind == "level_clear":
                x, y = self.px(world.player.cell)
                fx.ring(x, y, C.GOOD, 48, 420, 0.7)
                fx.add_flash(C.GOOD, 0.3)

    # ============================================================ game screen
    def draw_game(self, world, dt, best, muted, show_hud=True):
        """Draw one gameplay frame: arena, AI Vision, orbs, hunters, player, effects and HUD.

        Args:
            world: the World being drawn.
            dt: seconds since the last frame (animations).
            best: best score so far, shown in the HUD.
            muted: whether sound is off (for the SOUND button label).
            show_hud: False to draw only the arena (used under the game-over card).
        """
        self.t += dt
        self.buttons = []
        self.effects.update(dt)
        self.ox, self.oy = self.effects.shake_offset()
        if world.arena is not self.arena_ref:
            self.arena_ref = world.arena
            self.arena_surf = self._build_arena(world.arena)
            self.static = self.backdrop.copy()
            gfx.blit(self.static, self.arena_surf, (C.ARENA_X, C.ARENA_Y))

        scr = self.screen
        if self.ox == 0 and self.oy == 0:
            scr.blit(self.static, (0, 0))                  # one blit instead of two
        else:
            gfx.blit(scr, self.backdrop, (0, 0))
            gfx.blit(scr, self.arena_surf, (C.ARENA_X + self.ox, C.ARENA_Y + self.oy))

        vision = self.vision and world.phase in ("play", "intro")
        if vision or world.decoy_active:                   # the overlay only when needed
            self.overlay.fill((0, 0, 0, 0))
            if vision:
                self._draw_vision(world)
            if world.decoy_active:
                x, y = self.local(world.decoy_cell)
                a = int(110 + 70 * math.sin(self.t * 8))
                gfx.circle(self.overlay, (*C.DECOY_C, a), (x, y), 12)
                gfx.circle(self.overlay, (*C.DECOY_C, 200), (x, y), 17, 2)
            gfx.blit(scr, self.overlay, (C.ARENA_X + self.ox, C.ARENA_Y + self.oy))

        if world.orb:
            self._draw_orb(world.orb)
        if world.powerup:
            self._draw_powerup(world.powerup)
        alive = world.phase not in ("dead", "killcam", "over")
        if alive:
            self._draw_player(world)
        for i, h in enumerate(world.hunters):
            self._draw_hunter(h, world, i)

        if world.phase == "play" and world.danger > 0.02:
            pulse = 0.75 + 0.25 * math.sin(self.t * 8)
            self.vignette.set_alpha(int(255 * min(1.0, world.danger) * pulse))
            gfx.blit(scr, self.vignette, (C.ARENA_X + self.ox, C.ARENA_Y + self.oy))

        if world.phase in ("killcam", "over") and world.killcam:
            self._draw_killcam(world)
        self._draw_effects()
        if world.phase not in ("killcam", "over"):
            self._draw_bubbles(world, dt)
        self._draw_status_pills(world)
        self._draw_banner(world)

        if self.effects.flash > 0:
            self.tint((0, 0, C.WIDTH, C.HEIGHT), (*self.effects.flash_color, 90 * self.effects.flash))
        if show_hud:
            self._draw_hud(world, best, muted)
            self._draw_panel(world)

    def _draw_vision(self, world):
        """AI Vision overlay: each hunter's planned path, target and the Mind Reader's forecast.

        Args:
            world: the World being drawn.
        """
        ov = self.overlay
        for h in world.hunters:
            col = h.color
            if h.forecast:
                for i, cell in enumerate(h.forecast):
                    x, y = self.local(cell)
                    a = max(40, 210 - i * 22)
                    gfx.circle(ov, (*C.PLAYER, a), (x, y), max(5, 11 - i), 2)
            vc = h.visual_cell()
            pts = [self.local(vc)] + [self.local(c) for c in h.plan]
            if len(pts) >= 2:
                gfx.lines(ov, (*col, 110), False, pts, 3)
                for p in pts[1:]:
                    gfx.circle(ov, (*col, 170), p, 3)
            if h.target is not None:
                x, y = self.local(h.target)
                r = 14 + 2 * math.sin(self.t * 6)
                gfx.circle(ov, (*col, 220), (x, y), r, 2)
                gfx.line(ov, (*col, 220), (x - r - 5, y), (x - r + 5, y), 2)
                gfx.line(ov, (*col, 220), (x + r - 5, y), (x + r + 5, y), 2)
                gfx.line(ov, (*col, 220), (x, y - r - 5), (x, y - r + 5), 2)
                gfx.line(ov, (*col, 220), (x, y + r - 5), (x, y + r + 5), 2)

    def _draw_orb(self, orb):
        """Draw the orb with its pulsing glow and spawn animation.

        Args:
            orb: the Orb to draw.
        """
        x, y = self.px(orb.cell)
        grow = min(1.0, orb.age / 0.25)
        pulse = 0.5 + 0.5 * math.sin(self.t * 5)
        self.draw_glow(x, y, (26 + 6 * pulse) * grow, C.ORB, 0.6)
        if grow > 0.05:
            gfx.circle(self.screen, scale(C.ORB, 0.55), (x, y), (11 + 2 * pulse) * grow, 2)
            gfx.circle(self.screen, C.ORB, (x, y), 7 * grow)
            gfx.circle(self.screen, (245, 255, 225), (x - 2, y - 2), 2.5 * grow)

    def _draw_powerup(self, pu):
        """Draw a power-up, blinking when it is about to expire.

        Args:
            pu: the PowerUp to draw.
        """
        remaining = pu.life - pu.age
        if remaining < 2.0 and int(self.t * 8) % 2 == 0:
            return
        x, y = self.px(pu.cell)
        y += math.sin(self.t * 3) * 2
        col = POWER_COLORS[pu.kind]
        grow = min(1.0, pu.age / 0.3)
        self.draw_glow(x, y, 30 * grow, col, 0.55)
        gfx.circle(self.screen, scale(col, 0.15), (x, y), 14 * grow)
        gfx.circle(self.screen, col, (x, y), 14 * grow, 2)
        if grow >= 1.0:
            self.power_icon(x, y, pu.kind, col)

    def _draw_player(self, world):
        """Draw the player with its trail, shield ring and glow.

        Args:
            world: the World being drawn.
        """
        p = world.player
        x, y = self.px(p.visual_cell())
        self.trail.append((x - self.ox, y - self.oy))
        if len(self.trail) > 12:
            self.trail.pop(0)
        n = len(self.trail)
        for i, (tx, ty) in enumerate(self.trail[:-1]):
            k = (i + 1) / n
            if self.low_quality:
                gfx.circle(self.screen, scale(C.PLAYER, 0.5 * k), (tx + self.ox, ty + self.oy),
                                   2 + 6 * k)
            else:
                self.draw_glow(tx + self.ox, ty + self.oy, 6 + 10 * k, C.PLAYER, 0.3 * k)
        self.draw_glow(x, y, 38, C.PLAYER, 0.65)
        gfx.circle(self.screen, C.PLAYER, (x, y), 11)
        gfx.circle(self.screen, (225, 252, 255), (x, y), 5)
        if world.shield:
            for k in range(6):
                a0 = self.t * 2.5 + k * math.tau / 6
                gfx.arc(self.screen, C.SHIELD_C, (x - 18, y - 18, 36, 36), a0, a0 + 0.6, 2)

    def _draw_hunter(self, h, world, idx):
        """Draw one hunter in the style of its brain (Mirror twin, Mind Reader dots, confused "?").

        Args:
            h: the Hunter to draw.
            world: the World being drawn.
            idx: the hunter's index (for its speech bubble).
        """
        vx, vy = h.visual_cell()
        x, y = self.px((vx, vy))
        confused = world.confused and world.phase == "play"
        if confused:
            x += math.sin(self.t * 30 + idx) * 2
        col = C.FREEZE_C if world.frozen else h.color
        pulse = math.sin(self.t * 7 + idx)

        # eye looks at the player
        pvx, pvy = world.player.visual_cell()
        ex, ey = pvx - vx, pvy - vy
        norm = math.hypot(ex, ey) or 1.0
        ex, ey = ex / norm * 3.5, ey / norm * 3.5

        if h.brain.id == "mirror":
            # an "evil twin" of the player: same round body, inverted colours
            self.draw_glow(x, y, 42 + 4 * pulse, col, 0.5)
            gfx.circle(self.screen, (18, 22, 40), (x, y), 12)
            gfx.circle(self.screen, col, (x, y), 13, 3)
            gfx.circle(self.screen, C.HUNTER, (x + ex, y + ey), 4)
            for k in range(3):
                a = -self.t * 2 + k * math.tau / 3
                gfx.arc(self.screen, scale(col, 0.6), (x - 19, y - 19, 38, 38), a, a + 0.8, 1)
        else:
            self.draw_glow(x, y, 44 + 4 * pulse, col, 0.6)
            size = 12 + min(world.level_no, 6) * 0.7 + 1.5 * pulse
            spin = 0 if world.frozen else self.t * (9 if confused else 2.2)
            outer = [(x + math.cos(spin + k * math.pi / 2) * size,
                      y + math.sin(spin + k * math.pi / 2) * size) for k in range(4)]
            inner = [(x + math.cos(spin + k * math.pi / 2) * size * 0.5,
                      y + math.sin(spin + k * math.pi / 2) * size * 0.5) for k in range(4)]
            gfx.polygon(self.screen, col, outer)
            gfx.polygon(self.screen, scale(col, 0.25), inner)
            if h.brain.id in ("astar", "mindreader"):
                gfx.circle(self.screen, scale(col, 0.55), (x, y), size + 7, 1)
            if h.brain.id == "mindreader":       # orbiting "thoughts"
                for k in range(3):
                    a = self.t * 4 + k * math.tau / 3
                    gfx.circle(self.screen, (255, 235, 245),
                                       (x + math.cos(a) * (size + 7), y + math.sin(a) * (size + 7)), 2.5)
            gfx.circle(self.screen, (255, 255, 255), (x + ex, y + ey), 3)
        if world.frozen:
            gfx.circle(self.screen, (220, 240, 255), (x, y), 22, 1)
        if confused:
            bob = math.sin(self.t * 6 + idx) * 3
            self.blit_text("?", 34, C.WARN, (x + 24, y - 20 + bob), "center")

    def _draw_effects(self):
        """Draw particles and floating texts."""
        for p in self.effects.particles:
            k = p.life / p.max_life
            gfx.circle(self.screen, scale(p.color, 0.4 + 0.6 * k), (p.x + self.ox, p.y + self.oy),
                               max(1, p.size * k))
        for t in self.effects.texts:
            k = t.life / t.max_life
            col = scale(t.color, min(1.0, k * 1.6))
            half = self.text_size(t.text, t.size)[0] / 2
            x = max(C.ARENA_X + half + 6, min(C.ARENA_X + C.ARENA_W - half - 6, t.x))
            y = max(C.ARENA_Y + 52, t.y)                     # stay below the status pills
            self.blit_text(t.text, t.size, col, (x, y), "center")

    def _draw_bubbles(self, world, dt):
        """Speech bubbles above hunters (taunts).

        Args:
            world: the World being drawn.
            dt: seconds since the last frame (bubbles fade out).
        """
        for idx in list(self.bubbles):
            b = self.bubbles[idx]
            b[1] -= dt
            if b[1] <= 0 or idx >= len(world.hunters):
                del self.bubbles[idx]
                continue
            text, life, max_life = b
            h = world.hunters[idx]
            x, y = self.px(h.visual_cell())
            fade = max(0.0, min(1.0, (max_life - life) / 0.12, life / 0.3))
            surf = self.text_surface(text, 21, (12, 16, 30))
            tw, th = gfx.logical_size(surf)
            w, hgt = tw + 22, th + 14
            bx = max(C.ARENA_X + 6, min(C.ARENA_X + C.ARENA_W - w - 6, x - w / 2))
            above = y - 36 - hgt >= C.ARENA_Y + 4
            by = y - 36 - hgt if above else y + 34
            bubble = gfx.surface((w, hgt + 10), pygame.SRCALPHA)
            top = 0 if above else 10
            gfx.rect(bubble, (240, 244, 255), (0, top, w, hgt), border_radius=11)
            gfx.rect(bubble, h.color, (0, top, w, hgt), width=2, border_radius=11)
            tx = max(14, min(w - 14, x - bx))
            if above:
                tail = [(tx - 7, hgt - 1), (tx + 7, hgt - 1), (tx, hgt + 9)]
            else:
                tail = [(tx - 7, 11), (tx + 7, 11), (tx, 1)]
            gfx.polygon(bubble, (240, 244, 255), tail)
            gfx.blit(bubble, surf, (11, top + 8))
            bubble.set_alpha(int(255 * fade))
            gfx.blit(self.screen, bubble, (bx, by - (0 if above else 10)))

    def _draw_status_pills(self, world):
        """Pills in the arena corner showing active states (AI Vision, frozen, decoy, confused, shield).

        Args:
            world: the World being drawn.
        """
        if world.phase == "killcam":
            return
        x, y = C.ARENA_X + 12, C.ARENA_Y + 12
        if self.vision:
            x += self.pill(x, y, "AI VISION", C.PLAYER) + 8
        if world.confused:
            x += self.pill(x, y, f"CONFUSED {world.confuse_timer:.1f}s", C.CHAOS_C) + 8
        if world.frozen:
            x += self.pill(x, y, f"FREEZE {world.freeze_timer:.1f}s", C.FREEZE_C) + 8
        if world.decoy_active:
            x += self.pill(x, y, f"DECOY {world.decoy_timer:.1f}s", C.DECOY_C) + 8
        if world.shield:
            x += self.pill(x, y, "SHIELD", C.SHIELD_C) + 8

    def _draw_killcam(self, world):
        """Replay: the path the AI predicted vs the path you actually took.

        Args:
            world: the World being drawn.
        """
        kc = world.killcam
        if world.phase == "killcam":
            prog = 1.0 - world.phase_timer / C.KILLCAM_TIME
        else:
            prog = 1.0
        ax, ay = C.ARENA_X + self.ox, C.ARENA_Y + self.oy
        self.tint((ax, ay, C.ARENA_W, C.ARENA_H), (4, 6, 14, 175), 16)

        ov = self.overlay
        ov.fill((0, 0, 0, 0))
        fade = min(1.0, prog / 0.15)
        forecast = kc["forecast"]
        if forecast:
            pts = [self.local(c) for c in forecast]
            if len(pts) >= 2:
                gfx.lines(ov, (*kc["color"], int(150 * fade)), False, pts, 3)
            for p in pts:
                gfx.circle(ov, (*kc["color"], int(230 * fade)), p, 6, 2)
        path = [self.local(c) for c in kc["path"]]
        k = max(1, min(len(path), 1 + int((len(path) - 1) * min(1.0, prog / 0.6))))
        if k >= 2:
            gfx.lines(ov, (*C.PLAYER, 235), False, path[:k], 4)
        cx, cy = self.local(kc["catch"])
        r = 16 + 3 * math.sin(self.t * 8)
        gfx.circle(ov, (*C.HUNTER, 230), (cx, cy), r, 3)
        gfx.line(ov, (*C.HUNTER, 230), (cx - 8, cy - 8), (cx + 8, cy + 8), 3)
        gfx.line(ov, (*C.HUNTER, 230), (cx + 8, cy - 8), (cx - 8, cy + 8), 3)
        gfx.blit(self.screen, ov, (ax, ay))

        hx, hy = path[k - 1]
        self.draw_glow(ax + hx, ay + hy, 30, C.PLAYER, 0.7)
        gfx.circle(self.screen, C.PLAYER, (ax + hx, ay + hy), 8)
        if forecast and fade > 0.5:
            fx, fy = self.local(forecast[0])
            self.blit_text("AI PREDICTION", 16, kc["color"], (ax + fx, ay + fy - 18), "midbottom",
                           spacing=2)
        if len(path) >= 2:
            sx, sy = path[0]
            self.blit_text("YOUR PATH", 16, C.PLAYER, (ax + sx, ay + sy + 18), "midtop", spacing=2)
        # keep the catching hunter visible above the shade
        self._draw_hunter(world.hunters[kc["hunter"]], world, kc["hunter"])

        mid = C.ARENA_X + C.ARENA_W // 2
        if world.phase == "killcam":
            blink = int(self.t * 3) % 2 == 0
            gfx.circle(self.screen, C.HUNTER if blink else scale(C.HUNTER, 0.3),
                               (C.ARENA_X + 24, C.ARENA_Y + 24), 6)
            self.blit_text("KILL CAM", 17, C.TEXT, (C.ARENA_X + 36, C.ARENA_Y + 24), "midleft", spacing=3)
            self.blit_text("TAP to skip" if C.TOUCH else "SPACE / TAP to skip", 16, C.DIM, (mid, C.ARENA_Y + C.ARENA_H - 18),
                           "center", spacing=1)
            quote = kc.get("quote")
            if quote and prog > 0.35:
                surf = self.text_surface(f'"{quote}"', 22, (12, 16, 30))
                tw, th = gfx.logical_size(surf)
                qw, qh = tw + 28, th + 16
                qx, qy = mid - qw // 2, C.ARENA_Y + C.ARENA_H - 50 - qh
                gfx.rect(self.screen, (240, 244, 255), (qx, qy, qw, qh), border_radius=12)
                gfx.rect(self.screen, kc["color"], (qx, qy, qw, qh), width=2, border_radius=12)
                gfx.blit(self.screen, surf, (qx + 14, qy + 9))
        title_y = C.ARENA_Y + 58
        self.draw_glow(mid, title_y, 140, kc["color"], 0.15)
        cap_lines = self.wrap(kc["caption"], 38, C.ARENA_W - 60, 2)[:2]
        for i, line in enumerate(cap_lines):
            self.blit_text(line, 38, C.TEXT, (mid, title_y + i * 34), "center", spacing=2)
        self.blit_text(kc["sub"], 21, C.MUTED, (mid, title_y + 36 + 34 * (len(cap_lines) - 1)),
                       "center")

    def _draw_banner(self, world):
        """Big centred banner for the level intro and level clear phases.

        Args:
            world: the World being drawn.
        """
        cx = C.ARENA_X + C.ARENA_W // 2
        cy = C.ARENA_Y + C.ARENA_H // 2
        if world.phase == "intro":
            lvl = world.level
            k = min(1.0, (C.INTRO_TIME - world.phase_timer) / 0.25)
            band = pygame.Rect(C.ARENA_X, cy - 110, C.ARENA_W, 220)
            self.tint(band, (5, 8, 16, 215 * k))
            col = world.hunters[0].color
            self.blit_text(f"LEVEL {lvl.number}", 22, C.MUTED, (cx, cy - 78), "center", spacing=6)
            self.draw_glow(cx, cy - 26, 120, col, 0.18)
            self.blit_text(lvl.name, 76, col, (cx, cy - 28), "center", spacing=4)
            self.blit_text("HUNTER SKILL:  " + lvl.technique.upper(), 22, C.TEXT, (cx, cy + 24),
                           "center", spacing=2)
            hint = lvl.blurb if lvl.number > 1 else "Arrows / WASD (or swipe) to move."
            self.blit_text(hint, 24, C.MUTED, (cx, cy + 54), "center")
            frac = max(0.0, world.phase_timer / C.INTRO_TIME)
            gfx.rect(self.screen, C.CARD_EDGE, (cx - 120, cy + 84, 240, 4), border_radius=2)
            gfx.rect(self.screen, col, (cx - 120, cy + 84, int(240 * frac), 4), border_radius=2)
        elif world.phase == "clear":
            k = min(1.0, (C.CLEAR_TIME - world.phase_timer) / 0.2)
            self.tint((C.ARENA_X, cy - 80, C.ARENA_W, 150), (5, 8, 16, 200 * k))
            self.draw_glow(cx, cy - 20, 130, C.GOOD, 0.15)
            self.blit_text("LEVEL CLEAR", 76, C.GOOD, (cx, cy - 20), "center", spacing=4)
            self.blit_text(f"+{C.LEVEL_BONUS * world.level_no} BONUS", 28, C.TEXT, (cx, cy + 30),
                           "center", spacing=3)
        elif world.phase == "dead":
            self.blit_text("CAUGHT", 96, C.HUNTER, (cx, cy), "center", spacing=8)

    # ============================================================== controls
    def button(self, rect, action, label, active=False, color=None):
        """Draw a touch button and register it so taps on it trigger `action`.

        Args:
            rect: (x, y, w, h) in logical pixels.
            action: action name sent to the app when tapped, e.g. "pause".
            label: text on the button.
            active: True draws it highlighted (e.g. AI Vision on).
            color: accent colour; None uses the player cyan.
        """
        color = color or C.PLAYER
        r = pygame.Rect(rect)
        fill = scale(color, 0.22) if active else C.CARD_BG
        gfx.rect(self.screen, fill, r, border_radius=14)
        gfx.rect(self.screen, color if active else C.CARD_EDGE, r, width=2, border_radius=14)
        self.blit_text(label, 19, color if active else C.TEXT, r.center, "center", spacing=2)
        self.buttons.append((r, action))

    def button_at(self, pos):
        """The action of the button under `pos` (with some finger tolerance), else None.

        Args:
            pos: (x, y) in logical pixels.
        """
        for rect, action in reversed(self.buttons):
            if rect.inflate(12, 12).collidepoint(pos):
                return action
        return None

    def _draw_dpad(self, cx, cy, offset, r):
        """Draw the on-screen D-pad and register its four direction buttons.

        Args:
            cx, cy: centre in logical pixels.
            offset: distance from the centre to each button.
            r: radius of each button.
        """
        for d, (dx, dy) in C.DIRS.items():
            bx, by = cx + dx * offset, cy + dy * offset
            active = d in self.pressed_dirs
            gfx.circle(self.screen, scale(C.PLAYER, 0.25) if active else C.CARD_BG, (bx, by), r)
            gfx.circle(self.screen, C.PLAYER if active else C.CARD_EDGE, (bx, by), r, 2)
            self.arrow((bx, by), d, 15, C.PLAYER if active else C.TEXT)
            self.buttons.append((pygame.Rect(bx - r, by - r, 2 * r, 2 * r), "dir:" + d))
        gfx.circle(self.screen, C.CARD_EDGE, (cx, cy), 10, 2)

    def _draw_controls(self, world, muted):
        """Draw the keyboard hint (desktop) or the touch buttons and D-pad (phones).

        Args:
            world: the World being drawn.
            muted: whether sound is off (for the SOUND button label).
        """
        if not C.TOUCH:
            hint = "ARROWS / WASD  move     V  AI vision     P  pause     M  sound"
            self.blit_text(hint, 16, C.DIM, (C.WIDTH // 2, C.HEIGHT - 10), "center", spacing=1)
            return
        sound = "SOUND OFF" if muted else "SOUND ON"
        if C.PORTRAIT:
            top = C.CARD_MODEL[1] + C.CARD_MODEL[3] + 10
            cy = (top + C.HEIGHT) // 2
            self._draw_dpad(C.WIDTH // 2, cy, 86, 42)       # tap areas never overlap
            self.button((20, cy - 70, 170, 60), "vision", "AI VISION", self.vision)
            self.button((20, cy + 10, 170, 60), "sound", sound, not muted, C.GOOD)
            self.button((C.WIDTH - 190, cy - 70, 170, 60), "pause", "PAUSE")
            self.blit_text("or swipe", 17, C.DIM, (C.WIDTH - 105, cy + 30), "center", spacing=2)
            self.blit_text("anywhere", 17, C.DIM, (C.WIDTH - 105, cy + 50), "center", spacing=2)
        else:
            y = C.HEIGHT - 54
            self.button((20, y, 180, 44), "vision", "AI VISION", self.vision)
            self.button((212, y, 160, 44), "sound", sound, not muted, C.GOOD)
            self.button((C.WIDTH - 170, y, 150, 44), "pause", "PAUSE")
            self.blit_text("SWIPE ANYWHERE TO MOVE", 18, C.MUTED, ((372 + C.WIDTH - 170) // 2, y + 22),
                           "center", spacing=2)

    # =================================================================== HUD
    def _draw_bars(self, world, bx, by, bw):
        """Draw the orb progress bar and the CHAOS meter.

        Args:
            world: the World being drawn.
            bx, by: top-left of the bars in logical pixels.
            bw: width of the bars in logical pixels.
        """
        need = world.level.orbs
        got = min(world.orbs_level, need)
        self.blit_text(f"ORBS  {got} / {need}", 17, C.TEXT, (bx, by), spacing=2)
        if world.combo > 1:
            self.blit_text(f"x{world.combo} COMBO", 17, C.WARN, (bx + bw, by), "topright", spacing=1)
        gfx.rect(self.screen, C.CARD_EDGE, (bx, by + 20, bw, 8), border_radius=4)
        fill = int(bw * got / need)
        if fill > 0:
            gfx.rect(self.screen, C.ORB, (bx, by + 20, fill, 8), border_radius=4)

        # chaos meter: surprise the AI to fill it
        cbx, cbw, cy = bx + 74, bw - 74, by + 40
        if world.confused:
            col = scale(C.WARN, 0.7 + 0.3 * math.sin(self.t * 10))
            self.blit_text("CHAOS", 15, col, (bx, cy), "midleft", spacing=2)
            frac = world.confuse_timer / C.CONFUSE_TIME
        else:
            self.blit_text("CHAOS", 15, C.MUTED, (bx, cy), "midleft", spacing=2)
            col, frac = C.CHAOS_C, world.chaos
            if frac > 0.75:
                col = scale(C.CHAOS_C, 0.8 + 0.4 * (0.5 + 0.5 * math.sin(self.t * 10)))
        gfx.rect(self.screen, C.CARD_EDGE, (cbx, cy - 4, cbw, 8), border_radius=4)
        if frac > 0:
            gfx.rect(self.screen, col, (cbx, cy - 4, max(6, int(cbw * frac)), 8), border_radius=4)

    def _draw_hud(self, world, best, muted):
        """Draw the top bar: title, level, score, bars, time and best score.

        Args:
            world: the World being drawn.
            best: best score so far.
            muted: whether sound is off.
        """
        self.blit_text("PREDICTABLE", 34, C.TEXT, (C.ARENA_X, 16), spacing=3)
        self.blit_text(f"LEVEL {world.level_no}  ·  {world.level.name}", 18, C.MUTED,
                       (C.ARENA_X + 1, 50), spacing=1)
        if C.PORTRAIT:
            tx = C.WIDTH - 250
            self.blit_text(f"{world.score:,}", 58, C.TEXT, (C.ARENA_X, 84))
            self.blit_text("SCORE", 15, C.MUTED, (C.ARENA_X + 2, 128), spacing=3)
            self._draw_bars(world, C.WIDTH - 330, 82, 310)
        else:
            tx = C.ARENA_X + C.ARENA_W + 20
            sx = C.ARENA_X + C.ARENA_W // 2 - 20
            self.blit_text(f"{world.score:,}", 50, C.TEXT, (sx, 30), "center")
            self.blit_text("SCORE", 15, C.MUTED, (sx, 60), "center", spacing=3)
            self._draw_bars(world, C.ARENA_X + C.ARENA_W - 230, 12, 230)

        self.blit_text("TIME", 15, C.MUTED, (tx, 14), spacing=3)
        self.blit_text(fmt_time(world.time_alive), 36, C.TEXT, (tx, 32))
        self.blit_text("BEST", 15, C.MUTED, (tx + 120, 14), spacing=3)
        self.blit_text(f"{max(best, world.score):,}", 36, C.TEXT, (tx + 120, 32))
        if muted and not C.TOUCH:
            self.blit_text("MUTED", 14, C.DIM, (C.WIDTH - 20, 18), "topright", spacing=2)
        self._draw_controls(world, muted)

    def _draw_panel(self, world):
        # --- hunter brain -----------------------------------------------
        """Draw the side cards: hunter brain, mind model probabilities and read accuracy.

        Args:
            world: the World being drawn.
        """
        x, y, w, h = C.CARD_BRAIN
        lead = world.hunters[0].color
        self.card((x, y, w, h), "HUNTER BRAIN", lead)
        self.blit_text(world.level.name, 34, lead, (x + 16, y + 40), spacing=1)
        self.blit_text(world.level.technique, 21, C.TEXT, (x + 16, y + 72))
        for i, line in enumerate(self.wrap(world.level.blurb, 18, w - 32)[:2]):
            self.blit_text(line, 18, C.MUTED, (x + 16, y + 94 + i * 16))
        for i, hun in enumerate(world.hunters[:2]):
            ry = y + 134 + i * 17 - (8 if len(world.hunters) == 1 else 0)
            gfx.circle(self.screen, hun.color, (x + 22, ry + 6), 4)
            if world.confused:
                txt = "confused  ·  random moves"
            elif hun.brain.id in BRAIN_NOTES:
                txt = BRAIN_NOTES[hun.brain.id]
            else:
                txt = f"A* search: {hun.expanded} nodes"
            self.blit_text(txt, 17, C.MUTED, (x + 32, ry))

        # --- mind model --------------------------------------------------
        x, y, w, h = C.CARD_MODEL
        wide = w > 400
        self.card((x, y, w, h), "MIND MODEL", C.PLAYER)
        if wide:
            self.blit_text("P(your next move)", 18, C.MUTED, (x + w - 16, y + 14), "topright")
        else:
            self.blit_text("P(your next move)", 18, C.MUTED, (x + 16, y + 38))
        valid = world.arena.moves(world.player.cell)
        dist = world.predictor.distribution(valid)
        best_move = max(dist, key=dist.get) if dist else None
        cols = 2 if wide else 1
        colw = (w - 16) // cols
        bar_w = colw - 120
        for i, d in enumerate(C.DIR_ORDER):
            cx0 = x + (i % cols) * colw
            ry = y + (52 if wide else 70) + (i // cols) * 28
            p = dist.get(d, 0.0)
            active = d == best_move
            col = C.PLAYER if active else C.MUTED
            self.arrow((cx0 + 28, ry), d, 8, col if d in dist else C.DIM)
            gfx.rect(self.screen, C.CARD_EDGE, (cx0 + 48, ry - 5, bar_w, 10), border_radius=5)
            if p > 0:
                gfx.rect(self.screen, C.PLAYER if active else scale(C.PLAYER, 0.45),
                                 (cx0 + 48, ry - 5, max(6, int(bar_w * p)), 10), border_radius=5)
            label = f"{p * 100:.0f}%" if d in dist else "wall"
            self.blit_text(label, 18, col if d in dist else C.DIM, (cx0 + colw - 16, ry), "midright")
        trained = world.predictor.total_observed
        self.blit_text(f"Trained on {trained:,} of your moves", 17, C.MUTED, (x + 16, y + h - 24))

        # --- accuracy ----------------------------------------------------
        x, y, w, h = C.CARD_ACC
        self.card((x, y, w, h), "READ ACCURACY", C.WARN)
        pred = world.predictor
        if pred.run_total >= 10:
            acc = pred.accuracy
            self.blit_text(f"{acc * 100:.0f}%", 64, accuracy_color(acc), (x + 16, y + 40))
            line1, line2 = "of your moves", "predicted this run"
        else:
            self.blit_text("--", 64, C.DIM, (x + 16, y + 40))
            line1, line2 = "learning how", "you move..."
        self.blit_text(line1, 18, C.MUTED, (x + 140, y + 54))
        self.blit_text(line2, 18, C.MUTED, (x + 140, y + 72))
        self.blit_text(f"{pred.run_total} moves  ·  {world.surprises} surprises", 16, C.DIM,
                       (x + 16, y + h - 22))

    # ================================================================= title
    def _title_surface(self, size):
        """Build the glowing PREDICTABLE logo.

        Args:
            size: font size in logical pixels.

        Returns:
            (glow surface, text surface, padding in logical pixels).
        """
        text = self.text_surface("PREDICTABLE", size, C.TEXT, 6)
        w, h = text.get_size()
        pad_logical = 40
        pad = round(pad_logical * gfx.SCALE)
        surf = pygame.Surface((w + pad * 2, h + pad * 2))
        surf.fill((0, 0, 0))
        # glyph surfaces carry colour in their transparent pixels, so flatten the
        # tinted text onto black first; otherwise additive blending lights up the box
        tinted = pygame.Surface((w, h))
        tinted.fill((0, 0, 0))
        tinted.blit(self.text_surface("PREDICTABLE", size, scale(C.PLAYER, 0.8), 6), (0, 0))
        small = pygame.transform.smoothscale(tinted, (max(1, w // 6), max(1, h // 6)))
        blur = pygame.transform.smoothscale(small, (w, h))
        for _ in range(2):
            surf.blit(blur, (pad, pad), special_flags=pygame.BLEND_RGB_ADD)
        return surf, text, pad_logical

    def draw_title(self, dt, best, runs, types_found=0, muted=False):
        """Draw the title screen.

        Args:
            dt: seconds since the last frame (animations).
            best: best score, shown in the stats line.
            runs: number of runs played.
            types_found: how many of the 8 player types have been unlocked.
            muted: whether sound is off (for the SOUND button).
        """
        self.t += dt
        self.buttons = []
        scr = self.screen
        gfx.blit(scr, self.backdrop, (0, 0))
        self.draw_stars(dt)
        cx = C.WIDTH // 2
        portrait = C.PORTRAIT

        # little chase animation: the hunter follows the player across the top
        chase_y = 120 if portrait else 58
        span = C.WIDTH + 200
        px = (self.t * 170) % span - 100
        hx = px - 90 - 20 * math.sin(self.t * 2)
        y0 = chase_y + 6 * math.sin(self.t * 3)
        self.draw_glow(px, y0, 30, C.PLAYER, 0.6)
        gfx.circle(scr, C.PLAYER, (px, y0), 9)
        self.draw_glow(hx, chase_y, 34, C.HUNTER, 0.6)
        pts = [(hx + math.cos(self.t * 3 + k * math.pi / 2) * 12,
                chase_y + math.sin(self.t * 3 + k * math.pi / 2) * 12) for k in range(4)]
        gfx.polygon(scr, C.HUNTER, pts)

        size = 92 if portrait else 132
        if size not in self.title_surfs:
            self.title_surfs[size] = self._title_surface(size)
        glow, text, pad = self.title_surfs[size]
        ty = 200 if portrait else 92
        gx = cx - gfx.logical_size(glow)[0] / 2
        gfx.blit(scr, glow, (gx, ty - pad), special_flags=pygame.BLEND_RGB_ADD)
        gfx.blit(scr, text, (gx + pad, ty))
        tag_y = ty + gfx.logical_size(text)[1] + (34 if portrait else 22)
        self.blit_text("It learns how you move.", 32, C.MUTED, (cx, tag_y), "center")

        cards = (
            ("1", "COLLECT", "Grab the green orbs to", "clear each level.", C.ORB),
            ("2", "SURVIVE", "Six hunters, each with a", "smarter AI brain.", C.HUNTER),
            ("3", "SURPRISE IT", "Fool the AI's predictions", "to fill the CHAOS meter.", C.CHAOS_C),
        )
        if portrait:
            cw, ch = 600, 104
            positions = [(cx - cw // 2, 370 + i * (ch + 16)) for i in range(3)]
        else:
            cw, ch, gap = 286, 116, 21
            x0 = cx - (cw * 3 + gap * 2) // 2
            positions = [(x0 + i * (cw + gap), 252) for i in range(3)]
        for (x, y), (num, head, l1, l2, col) in zip(positions, cards):
            self.card((x, y, cw, ch), None, col)
            gfx.circle(scr, scale(col, 0.2), (x + 34, y + 38), 17)
            gfx.circle(scr, col, (x + 34, y + 38), 17, 2)
            self.blit_text(num, 26, col, (x + 34, y + 39), "center")
            self.blit_text(head, 24, C.TEXT, (x + 62, y + 30), spacing=3)
            if portrait:
                self.blit_text(f"{l1} {l2}", 19, C.MUTED, (x + 62, y + 66))
            else:
                self.blit_text(l1, 19, C.MUTED, (x + 20, y + 70))
                self.blit_text(l2, 19, C.MUTED, (x + 20, y + 89))

        items = (("freeze", "FREEZE", "stops hunters"), ("decoy", "DECOY", "fools them"),
                 ("shield", "SHIELD", "saves you once"))
        if portrait:
            rows = [(cx - 150, 760 + i * 40) for i in range(3)]
        else:
            rows = None
        x = cx - 330
        for i, (kind, name, desc) in enumerate(items):
            col = POWER_COLORS[kind]
            ix, iy = rows[i] if rows else (x, 404)
            gfx.circle(scr, scale(col, 0.15), (ix + 12, iy), 13)
            gfx.circle(scr, col, (ix + 12, iy), 13, 2)
            self.power_icon(ix + 12, iy, kind, col, r=7)
            r = self.blit_text(name, 19, col, (ix + 34, iy), "midleft", spacing=2)
            r2 = self.blit_text(desc, 19, C.MUTED, (r.right + 8, iy), "midleft")
            x = r2.right + 40

        prompt_y = 940 if portrait else 482
        prompt = "TAP TO START" if C.TOUCH else "PRESS SPACE OR TAP TO START"
        blink = 0.55 + 0.45 * math.sin(self.t * 4)
        self.draw_glow(cx, prompt_y, 150, C.PLAYER, round(0.12 * blink, 1) or 0.1)
        self.blit_text(prompt, 38 if portrait else 34, scale(C.TEXT, 0.6 + 0.4 * blink),
                       (cx, prompt_y), "center", spacing=3)

        stats = f"BEST  {best:,}     ·     RUNS  {runs}     ·     TYPES  {types_found} / {len(profile.TYPES)}"
        if portrait:
            self.blit_text(stats, 18, C.MUTED, (cx, 1040), "center", spacing=1)
            self.blit_text("Swipe or use the pad to move", 18, C.DIM, (cx, 1074), "center", spacing=1)
            self.button((cx - 90, 1110, 180, 56), "sound", "SOUND OFF" if muted else "SOUND ON",
                        not muted, C.GOOD)
        elif C.TOUCH:
            self.blit_text(stats + "     ·     SWIPE TO MOVE", 18, C.MUTED, (cx, 548), "center",
                           spacing=1)
        else:
            self.blit_text(stats + "     ·     V  AI VISION     ·     M  SOUND", 18, C.MUTED, (cx, 548),
                           "center", spacing=1)
        self.blit_text(f"{C.AUTHOR}  ·  {C.STUDENT_ID}  ·  AI Principles Mini Project 2026", 16, C.DIM,
                       (cx, C.HEIGHT - 24), "center", spacing=1)

    # ================================================================= pause
    def draw_pause(self):
        """Draw the pause overlay (with RESUME / QUIT buttons on touch screens)."""
        self.buttons = []
        self.tint((0, 0, C.WIDTH, C.HEIGHT), (4, 6, 12, 190))
        cx, cy = C.WIDTH // 2, C.HEIGHT // 2
        self.blit_text("PAUSED", 80, C.TEXT, (cx, cy - 40), "center", spacing=8)
        if C.TOUCH:
            self.button((cx - 130, cy + 20, 260, 64), "resume", "RESUME", True)
            self.button((cx - 130, cy + 100, 260, 64), "menu", "QUIT TO MENU", False, C.HUNTER)
        else:
            self.blit_text("P / ESC to resume     ·     Q to quit to menu", 22, C.MUTED,
                           (cx, cy + 16), "center", spacing=1)

    # ============================================================= game over
    def draw_game_over(self, world, dt, summary, best, new_best, history, muted,
                       new_type=False, types_found=0):
        """Draw the game-over card on top of the last frame.

        Args:
            world: the World being drawn.
            dt: seconds since the last frame.
            summary: the run's statistics from World.summary().
            best: best score so far.
            new_best: True if this run set a new best score.
            history: list of earlier run summaries (for the readability chart).
            muted: whether sound is off.
            new_type: True if this run unlocked a new player type.
            types_found: number of player types unlocked so far.
        """
        self.draw_game(world, dt, best, muted)
        self.buttons = []
        self.tint((0, 0, C.WIDTH, C.HEIGHT), (4, 6, 12, 215))

        scr = self.screen
        portrait = C.PORTRAIT
        if portrait:
            w, h = 680, 1180
            x, y = 20, 50
            lx, lw, ly = x + 40, w - 80, y
            rx, rw, ry = x + 40, w - 80, y + 490
        else:
            w, h = 900, 560
            x, y = (C.WIDTH - w) // 2, (C.HEIGHT - h) // 2
            lx, lw, ly = x + 34, 400, y
            rx, rw, ry = x + 486, 380, y
        gfx.rect(scr, C.CARD_BG, (x, y, w, h), border_radius=20)
        gfx.rect(scr, C.CARD_EDGE, (x, y, w, h), width=1, border_radius=20)
        if portrait:
            gfx.line(scr, C.CARD_EDGE, (x + 40, y + 476), (x + w - 40, y + 476))
        else:
            gfx.line(scr, C.CARD_EDGE, (x + 460, y + 28), (x + 460, y + h - 70))

        # ---------------- how readable you were ----------------
        lcx = lx + lw // 2
        self.blit_text(f"CAUGHT BY {summary['level_name']}", 19, C.HUNTER, (lcx, ly + 34),
                       "center", spacing=3)
        self.blit_text("THE AI READ", 21, C.MUTED, (lcx, ly + 66), "center", spacing=4)
        acc, moves = summary["accuracy"], summary["moves"]
        if moves >= 10:
            col = accuracy_color(acc)
            self.draw_glow(lcx, ly + 126, 100, col, 0.2)
            self.blit_text(f"{acc * 100:.0f}%", 112, col, (lcx, ly + 126), "center")
        else:
            self.blit_text("--", 112, C.DIM, (lcx, ly + 126), "center")
        self.blit_text("of your moves", 19, C.MUTED, (lcx, ly + 176), "center", spacing=2)

        quote = summary.get("quote") or ""
        if quote:
            lines = self.wrap(f'"{quote}"', 21, lw - 36)[:2]
            qh = 18 + 24 * len(lines)
            qy = ly + 202
            gfx.rect(scr, scale(C.HUNTER, 0.12), (lx, qy, lw, qh), border_radius=12)
            gfx.rect(scr, scale(C.HUNTER, 0.6), (lx, qy, lw, qh), width=1, border_radius=12)
            for i, line in enumerate(lines):
                self.blit_text(line, 21, C.TEXT, (lcx, qy + 21 + i * 24), "center")
            self.blit_text("- the hunter", 15, scale(C.HUNTER, 0.9), (lx + lw - 12, qy + qh + 4),
                           "topright", spacing=1)

        insights = []
        if moves >= 10:
            insights.append(f"You went straight {summary['straight'] * 100:.0f}% of the time.")
        fav = summary["favourite_turn"]
        if fav:
            insights.append(f"Favourite turn: {DIR_NAMES[fav[0]]} then {DIR_NAMES[fav[1]]}.")
        insights.append(f"You surprised the AI {summary['surprises']} times.")
        for i, line in enumerate(insights):
            self.blit_text(line, 19, C.MUTED, (lcx, ly + 300 + i * 22), "center")

        hx, hy, hw, hh = lx, ly + 412, lw, 50
        self.blit_text("READABILITY BY RUN", 14, C.MUTED, (hx, hy - 6), "bottomleft", spacing=2)
        self.blit_text("higher = it knows you better", 14, C.DIM, (hx + hw, hy - 6), "bottomright")
        runs = [r for r in history if r.get("moves", 0) >= 10][-12:]
        if runs:
            bw = min(30, (hw - 6 * (len(runs) - 1)) // len(runs))
            total_w = bw * len(runs) + 6 * (len(runs) - 1)
            bx = hx + (hw - total_w) // 2
            for i, r in enumerate(runs):
                a = r["accuracy"]
                bh = max(3, int(hh * a))
                col = accuracy_color(a) if i == len(runs) - 1 else scale(accuracy_color(a), 0.5)
                gfx.rect(scr, col, (bx + i * (bw + 6), hy + hh - bh, bw, bh), border_radius=4)
        gfx.line(scr, C.CARD_EDGE, (hx, hy + hh + 1), (hx + hw, hy + hh + 1))

        # ---------------- who you are ----------------
        rcx = rx + rw // 2
        type_id = summary.get("type", "strategist")
        name, tagline, tcol = profile.describe(type_id, summary)
        self.blit_text("YOUR PLAYER TYPE", 17, C.MUTED, (rcx, ry + 34), "center", spacing=3)
        name_lines = self.wrap(name, 44, rw, 1)[:2]
        ny = ry + 76 if len(name_lines) == 1 else ry + 62
        self.draw_glow(rcx, ny + 18, 120, tcol, 0.15)
        for i, line in enumerate(name_lines):
            self.blit_text(line, 44, tcol, (rcx, ny + i * 40), "center", spacing=1)
        tag_y = ny + 40 * (len(name_lines) - 1) + 46
        for i, line in enumerate(self.wrap(tagline, 21, rw)[:2]):
            self.blit_text(line, 21, C.TEXT, (rcx, tag_y + i * 22), "center")
        total = len(profile.TYPES)
        dx0 = rcx - (total * 18) // 2 + 9
        for i in range(total):
            filled = i < types_found
            gfx.circle(scr, tcol if filled else C.CARD_EDGE, (dx0 + i * 18, ry + 206), 5,
                               0 if filled else 1)
        self.blit_text(f"{types_found} / {total} TYPES FOUND", 14, C.MUTED, (rcx, ry + 224), "center",
                       spacing=2)
        if new_type:
            self.pill(rcx - 52, ry + 238, "NEW TYPE!", tcol)

        stats = (
            (f"{summary['score']:,}", "SCORE"), (fmt_time(summary["time"]), "TIME"),
            (str(summary["level"]), "LEVEL"), (str(summary["orbs"]), "ORBS"),
            (str(summary["surprises"]), "SURPRISES"), (str(summary["close_calls"]), "CLOSE CALLS"),
        )
        colw = rw // 3
        for i, (val, lab) in enumerate(stats):
            sx = rx + (i % 3) * colw + colw // 2
            sy = ry + 300 + (i // 3) * 62
            self.blit_text(val, 36, C.TEXT, (sx, sy), "center")
            self.blit_text(lab, 14, C.MUTED, (sx, sy + 24), "center", spacing=2)
        if new_best:
            self.pill(rcx - 54, ry + 430, "NEW BEST!", C.WARN)

        blink = 0.55 + 0.45 * math.sin(self.t * 4)
        prompt_col = scale(C.TEXT, 0.6 + 0.4 * blink)
        if C.TOUCH:
            by = y + h - 84 if portrait else y + h - 58
            self.button((x + w // 2 - 250, by, 300, 60 if portrait else 46), "again", "PLAY AGAIN",
                        True)
            self.button((x + w // 2 + 70, by, 180, 60 if portrait else 46), "menu", "MENU", False,
                        C.MUTED)
        else:
            self.blit_text("SPACE / TAP to play again     ·     ESC for menu", 22, prompt_col,
                           (x + w // 2, y + h - 30), "center", spacing=1)
