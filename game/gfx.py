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
    """Set how many real pixels one logical pixel uses (never below 1).

    Args:
        s: the scale factor, e.g. 2.6 on a Retina Mac or 1.5 in the browser.
    """
    global SCALE
    SCALE = max(1.0, float(s))


def s(v):
    """Scale a single length `v` from logical to real pixels."""
    return v * SCALE


def pt(p):
    """Scale a point `p` (x, y) from logical to real pixels."""
    return (p[0] * SCALE, p[1] * SCALE)


def px_rect(rect):
    """Logical rect -> pixel Rect, rounding the edges so neighbours never leave gaps.

    Args:
        rect: (x, y, w, h) in logical pixels.

    Returns:
        pygame.Rect in real pixels.
    """
    x, y, w, h = rect
    x0, y0 = round(x * SCALE), round(y * SCALE)
    return pygame.Rect(x0, y0, round((x + w) * SCALE) - x0, round((y + h) * SCALE) - y0)


def _w(width):
    """Scale a line width; 0 (filled shape) stays 0 and any other width is at least 1 pixel."""
    return 0 if width == 0 else max(1, round(width * SCALE))


def surface(size, flags=0):
    """Create a surface big enough for a logical size at the current scale.

    Args:
        size: (w, h) in logical pixels.
        flags: pygame surface flags, e.g. pygame.SRCALPHA for transparency.
    """
    w, h = size
    return pygame.Surface((max(1, round(w * SCALE)), max(1, round(h * SCALE))), flags)


def circle(surf, color, center, radius, width=0):
    """Draw a circle using logical coordinates.

    Args:
        surf: surface to draw on.
        color: RGB or RGBA colour.
        center: (x, y) centre in logical pixels.
        radius: radius in logical pixels.
        width: outline width; 0 fills the circle.
    """
    return pygame.draw.circle(surf, color, pt(center), radius * SCALE, _w(width))


def rect(surf, color, r, width=0, border_radius=0):
    """Draw a (rounded) rectangle using logical coordinates.

    Args:
        surf: surface to draw on.
        color: RGB or RGBA colour.
        r: (x, y, w, h) in logical pixels.
        width: outline width; 0 fills it.
        border_radius: corner radius in logical pixels.
    """
    return pygame.draw.rect(surf, color, px_rect(r), _w(width),
                            border_radius=round(border_radius * SCALE) if border_radius else 0)


def line(surf, color, start, end, width=1):
    """Draw a straight line using logical coordinates.

    Args:
        surf: surface to draw on.
        color: RGB or RGBA colour.
        start: (x, y) start point in logical pixels.
        end: (x, y) end point in logical pixels.
        width: line width in logical pixels.
    """
    return pygame.draw.line(surf, color, pt(start), pt(end), _w(width))


def lines(surf, color, closed, points, width=1):
    """Draw connected line segments using logical coordinates.

    Args:
        surf: surface to draw on.
        color: RGB or RGBA colour.
        closed: True to join the last point back to the first.
        points: list of (x, y) points in logical pixels.
        width: line width in logical pixels.
    """
    return pygame.draw.lines(surf, color, closed, [pt(p) for p in points], _w(width))


def polygon(surf, color, points, width=0):
    """Draw a polygon using logical coordinates.

    Args:
        surf: surface to draw on.
        color: RGB or RGBA colour.
        points: list of (x, y) corners in logical pixels.
        width: outline width; 0 fills it.
    """
    return pygame.draw.polygon(surf, color, [pt(p) for p in points], _w(width))


def arc(surf, color, r, start, stop, width=1):
    """Draw an arc of the ellipse inside a logical rect.

    Args:
        surf: surface to draw on.
        color: RGB or RGBA colour.
        r: bounding rect (x, y, w, h) in logical pixels.
        start: start angle in radians.
        stop: stop angle in radians.
        width: line width in logical pixels.
    """
    return pygame.draw.arc(surf, color, px_rect(r), start, stop, _w(width))


def blit(target, source, pos, special_flags=0):
    """Copy `source` onto `target` at a logical position.

    Args:
        target: surface to draw on.
        source: surface to copy (already rendered at real resolution).
        pos: (x, y) top-left in logical pixels.
        special_flags: pygame blend mode, e.g. BLEND_RGB_ADD for glows.
    """
    return target.blit(source, (round(pos[0] * SCALE), round(pos[1] * SCALE)),
                       special_flags=special_flags)


def logical_size(surf):
    """Size (w, h) of a real-resolution surface `surf` in logical pixels."""
    return surf.get_width() / SCALE, surf.get_height() / SCALE
