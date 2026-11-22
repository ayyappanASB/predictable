"""Resolution-independent drawing.

The whole game is laid out in *logical* pixels (e.g. 1000 x 620). On a Retina
Mac or a phone the real screen has 2-3x more pixels, so the renderer draws to
a surface that is SCALE times larger and every coordinate goes through this
module. Game code never needs to know the real resolution, and text and
shapes are rendered natively sharp instead of being stretched afterwards.
"""

import pygame

SCALE = 1.0


def set_scale(s: float):
    global SCALE
    SCALE = max(1.0, float(s))


def s(v):
    """Scale a single length."""
    return v * SCALE


def pt(p):
    return (p[0] * SCALE, p[1] * SCALE)


def px_rect(rect):
    """Logical rect -> pixel Rect, rounding the edges so neighbours never leave gaps."""
    x, y, w, h = rect
    x0, y0 = round(x * SCALE), round(y * SCALE)
    return pygame.Rect(x0, y0, round((x + w) * SCALE) - x0, round((y + h) * SCALE) - y0)


def _w(width):
    return 0 if width == 0 else max(1, round(width * SCALE))


def surface(size, flags=0):
    w, h = size
    return pygame.Surface((max(1, round(w * SCALE)), max(1, round(h * SCALE))), flags)


def circle(surf, color, center, radius, width=0):
    return pygame.draw.circle(surf, color, pt(center), radius * SCALE, _w(width))


def rect(surf, color, r, width=0, border_radius=0):
    return pygame.draw.rect(surf, color, px_rect(r), _w(width),
                            border_radius=round(border_radius * SCALE) if border_radius else 0)


def line(surf, color, start, end, width=1):
    return pygame.draw.line(surf, color, pt(start), pt(end), _w(width))


def lines(surf, color, closed, points, width=1):
    return pygame.draw.lines(surf, color, closed, [pt(p) for p in points], _w(width))


def polygon(surf, color, points, width=0):
    return pygame.draw.polygon(surf, color, [pt(p) for p in points], _w(width))


def arc(surf, color, r, start, stop, width=1):
    return pygame.draw.arc(surf, color, px_rect(r), start, stop, _w(width))


def blit(target, source, pos, special_flags=0):
    return target.blit(source, (round(pos[0] * SCALE), round(pos[1] * SCALE)),
                       special_flags=special_flags)


def logical_size(surf):
    return surf.get_width() / SCALE, surf.get_height() / SCALE
