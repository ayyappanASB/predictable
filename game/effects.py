"""Visual feedback: particles, floating text, screen shake and flashes."""

import math
import random


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color", "size")

    def __init__(self, x, y, vx, vy, life, color, size):
        """Create one particle.

        Args:
            x, y: start position in logical pixels.
            vx, vy: velocity in pixels per second.
            life: seconds before it disappears.
            color: RGB colour.
            size: radius in pixels.
        """
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = self.max_life = life
        self.color, self.size = color, size


class FloatText:
    __slots__ = ("x", "y", "text", "color", "life", "max_life", "size")

    def __init__(self, x, y, text, color, life=1.0, size=26):
        """Create a text label that floats upwards and fades (e.g. "+100").

        Args:
            x, y: start position in logical pixels.
            text: the text to show.
            color: RGB colour.
            life: seconds before it disappears.
            size: font size in pixels.
        """
        self.x, self.y, self.text, self.color = x, y, text, color
        self.life = self.max_life = life
        self.size = size


class Effects:
    MAX_PARTICLES = 400

    def __init__(self):
        """Create an empty effects system (no particles, texts, shake or flash)."""
        self.rng = random.Random()
        self.particles = []
        self.texts = []
        self.shake = 0.0
        self.flash = 0.0
        self.flash_color = (255, 255, 255)

    def clear(self):
        """Remove every particle and text and stop shake and flash."""
        self.particles.clear()
        self.texts.clear()
        self.shake = self.flash = 0.0

    def burst(self, x, y, color, count=18, speed=180, life=0.6, size=4):
        """Explode particles in random directions from a point.

        Args:
            x, y: centre of the burst in logical pixels.
            color: RGB colour of the particles.
            count: number of particles.
            speed: maximum speed in pixels per second.
            life: maximum lifetime in seconds.
            size: maximum particle radius in pixels.
        """
        for _ in range(count):
            if len(self.particles) >= self.MAX_PARTICLES:
                break
            a = self.rng.uniform(0, math.tau)
            s = self.rng.uniform(0.3, 1.0) * speed
            self.particles.append(Particle(x, y, math.cos(a) * s, math.sin(a) * s,
                                           self.rng.uniform(0.6, 1.0) * life, color,
                                           self.rng.uniform(0.6, 1.0) * size))

    def ring(self, x, y, color, count=28, speed=240, life=0.5):
        """Send particles outwards in an even ring (used for shields and surprises).

        Args:
            x, y: centre of the ring in logical pixels.
            color: RGB colour of the particles.
            count: number of particles around the ring.
            speed: speed in pixels per second.
            life: lifetime in seconds.
        """
        for i in range(count):
            a = math.tau * i / count
            self.particles.append(Particle(x, y, math.cos(a) * speed, math.sin(a) * speed,
                                           life, color, 3))

    def text(self, x, y, text, color, life=1.0, size=26):
        """Add a floating text label.

        Args:
            x, y: start position in logical pixels.
            text: the text to show.
            color: RGB colour.
            life: seconds before it disappears.
            size: font size in pixels.
        """
        self.texts.append(FloatText(x, y, text, color, life, size))

    def add_shake(self, amount):
        """Shake the screen by up to `amount` pixels (keeps the stronger of old and new)."""
        self.shake = max(self.shake, amount)

    def add_flash(self, color, amount=0.6):
        """Flash the screen.

        Args:
            color: RGB colour of the flash.
            amount: starting strength 0..1.
        """
        self.flash_color = color
        self.flash = max(self.flash, amount)

    def update(self, dt):
        """Move and age all particles and texts, and fade shake and flash.

        Args:
            dt: seconds since the last frame.
        """
        for p in self.particles:
            p.life -= dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vx *= 0.92
            p.vy *= 0.92
        self.particles = [p for p in self.particles if p.life > 0]
        for t in self.texts:
            t.life -= dt
            t.y -= 38 * dt
        self.texts = [t for t in self.texts if t.life > 0]
        self.shake = max(0.0, self.shake - dt * 30)
        self.flash = max(0.0, self.flash - dt * 2.2)

    def shake_offset(self):
        """Random (dx, dy) pixel offset for this frame's screen shake, or (0, 0)."""
        if self.shake <= 0:
            return 0, 0
        s = self.shake
        return int(self.rng.uniform(-s, s)), int(self.rng.uniform(-s, s))
