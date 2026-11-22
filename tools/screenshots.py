"""Drive the real app headlessly and save a screenshot of every screen.

Used for checking the UI and for the report / slides:
    python tools/screenshots.py      -> docs/screenshots/*.png
"""

import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame  # noqa: E402

from game.ai.astar import astar  # noqa: E402
from game import storage  # noqa: E402
from game.app import App  # noqa: E402

# never touch the player's real save file
storage.DESKTOP_FILE = os.path.join(os.environ.get("TMPDIR", "/tmp"), "predictable_screenshots.json")
if os.path.exists(storage.DESKTOP_FILE):
    os.remove(storage.DESKTOP_FILE)

LAYOUT = os.environ.get("PREDICTABLE_LAYOUT", "desktop")
OUT = os.path.join(ROOT, "docs", "screenshots", *([] if LAYOUT == "desktop" else [LAYOUT]))


class FakeClock:
    def tick(self, fps):
        return 1000 // 60


def bot_steer(app):
    """Head for the orb with A* so the run looks like real play."""
    w = app.world
    if not w.orb:
        return
    res = astar(w.player.cell, w.orb.cell, w.arena.neighbors)
    if len(res.path) >= 2:
        (c0, r0), (c1, r1) = res.path[0], res.path[1]
        w.steer({(1, 0): "R", (-1, 0): "L", (0, 1): "D", (0, -1): "U"}[(c1 - c0, r1 - r0)])


def run(app, frames, bot=True):
    for _ in range(frames):
        if bot and app.state == "play":
            bot_steer(app)
        app.frame()


def shot(app, name):
    os.makedirs(OUT, exist_ok=True)
    pygame.image.save(app.screen, os.path.join(OUT, name + ".png"))
    print("saved", name)


def play_until_death(app, level, bot=True, limit=60 * 60):
    w = app.world
    w.start_level(level)
    w.phase = "play"
    for _ in range(limit):
        if app.state != "play" or app.world.phase != "play":
            break
        if bot:
            bot_steer(app)
        app.frame()


def main():
    random.seed(1)
    app = App()
    app.clock = FakeClock()
    pygame.event.set_blocked(getattr(pygame, "WINDOWFOCUSLOST", pygame.NOEVENT))
    for _ in range(40):
        app.frame()
    shot(app, "01_title")

    app.start_run()
    run(app, 30)
    shot(app, "02_level_intro")
    run(app, 200)
    shot(app, "03_level1_play")

    for level in (3, 4, 5, 6):
        app.world.start_level(level)
        app.world.shield = level == 5
        run(app, 150)
        app.renderer.vision = level >= 4
        run(app, 80)
        shot(app, f"04_level{level}_play" + ("_vision" if app.renderer.vision else ""))

    # a taunt + confused hunters (fresh level, player standing still, hunter 5 cells away)
    w = app.world
    w.start_level(4)
    w.phase = "play"
    app.renderer.vision = False
    dist = w.arena.distances(w.player.cell)
    w.hunters[0].place(min(c for c, d in dist.items() if d == 5))
    w.chaos = 0.0
    w.confuse_timer = 2.0
    w.say("confused", force=True)
    w.events.append(("confused", None))
    run(app, 20, bot=False)
    shot(app, "05_taunt_confused")

    app.world.orbs_level = app.world.level.orbs
    run(app, 20)
    shot(app, "06_level_clear")

    app.state = "paused"
    app.frame()
    shot(app, "07_paused")
    app.state = "play"

    # die to the Mind Reader with no bot steering -> kill-cam
    play_until_death(app, 4, bot=True, limit=60 * 25)
    w = app.world
    if w.phase == "play":                  # make sure we get caught for the screenshot
        h = w.hunters[0]
        h.place(w.arena.step(w.player.cell, w.arena.moves(w.player.cell)[0]))
    for _ in range(600):
        app.frame()
        if app.world.phase == "killcam" and app.world.phase_timer < 1.0:
            break
    shot(app, "08_killcam")
    for _ in range(600):
        app.frame()
        if app.state == "over":
            break
    run(app, 60, bot=False)
    shot(app, "09_game_over")
    pygame.quit()


if __name__ == "__main__":
    main()
