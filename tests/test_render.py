"""Smoke tests: every screen and phase draws without errors (headless SDL)."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

from game import config as C, profile, storage  # noqa: E402
from game.app import App  # noqa: E402
from game.audio import Audio  # noqa: E402


class FakeClock:
    def tick(self, fps=0):
        """Pretend exactly 1/60 s passed so tests are deterministic; `fps` is ignored."""
        return 1000 // 60


@pytest.fixture(params=C.LAYOUTS)
def app(request, tmp_path, monkeypatch):
    """Every rendering test runs in all three layouts (desktop, phone landscape, phone portrait).

    Args:
        request: pytest request; request.param is the layout name.
        tmp_path: temporary folder for the save file.
        monkeypatch: used to point storage at the temporary save file.

    Yields:
        A headless App, closed again after the test.
    """
    monkeypatch.setattr(storage, "DESKTOP_FILE", str(tmp_path / "save.json"))
    a = App(layout=request.param)
    a.clock = FakeClock()
    # the headless SDL driver reports focus loss, which (correctly) auto-pauses the game
    pygame.event.set_blocked(getattr(pygame, "WINDOWFOCUSLOST", pygame.NOEVENT))
    yield a
    pygame.quit()
    C.apply_layout("desktop")


def frames(app, n):
    """Run `n` frames of `app`."""
    for _ in range(n):
        app.frame()


def test_title_screen(app):
    """The title screen draws and stays on the title.

    Args:
        app: the App fixture (runs once per layout).
    """
    frames(app, 10)
    assert app.state == "title"


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5, 6, 7])
def test_every_level_draws_with_vision(app, level):
    """Every level (including the Gauntlet) draws with AI Vision on.

    Args:
        app: the App fixture (runs once per layout).
        level: level number to draw.
    """
    app.start_run()
    app.world.start_level(level)
    app.renderer.vision = True
    frames(app, 200)


def test_effects_and_bubbles_draw(app):
    """All status effects, speech bubbles and particles draw together.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.start_run()
    w = app.world
    w.phase = "play"
    w.confuse_timer, w.freeze_timer, w.decoy_timer, w.shield = 2, 2, 2, True
    w.decoy_cell = w.player.cell
    w.danger = 1.0
    w.say("surprise", force=True)
    w.events.append(("surprise", w.player.cell))
    w.events.append(("confused", None))
    frames(app, 30)


def test_full_death_flow_and_game_over(app):
    """A real catch runs death, kill-cam and game over, saves the type, and SPACE restarts.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.start_run()
    w = app.world
    w.start_level(3)
    w.phase = "play"
    w.hunters[0].place(w.arena.step(w.player.cell, w.arena.moves(w.player.cell)[0]))
    seen = set()
    for _ in range(600):
        app.frame()
        if app.world:
            seen.add(app.world.phase)
        if app.state == "over":
            break
    assert app.state == "over"
    assert {"dead", "killcam"} <= seen
    assert app.summary["type"] in profile.TYPES
    assert app.save["types"] == [app.summary["type"]] and app.new_type
    frames(app, 60)                          # game-over card
    app.over_timer = 0
    app.on_key(pygame.K_SPACE)               # play again
    assert app.state == "play"


@pytest.mark.parametrize("type_id", list(profile.TYPES))
def test_game_over_card_for_every_type(app, type_id):
    """The game-over card draws for every player type.

    Args:
        app: the App fixture (runs once per layout).
        type_id: player type shown on the card.
    """
    app.start_run()
    w = app.world
    w._die(0)
    summary = w.summary()
    summary["type"] = type_id
    summary["favourite_turn"] = ("U", "L")
    app.renderer.draw_game_over(w, 1 / 60, summary, 999, True,
                                [{"accuracy": 0.4, "moves": 20}] * 15, False, True, 3)


def test_killcam_skip_with_space(app):
    """SPACE skips the kill-cam.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.start_run()
    w = app.world
    w.phase = "play"
    w._die(0)
    w.phase, w.phase_timer = "killcam", 1.0
    app.on_key(pygame.K_SPACE)
    assert w.phase == "over"


def test_pause_and_resume(app):
    """P pauses and resumes the game.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.start_run()
    app.on_key(pygame.K_p)
    app.frame()
    assert app.state == "paused"
    app.on_key(pygame.K_p)
    assert app.state == "play"


def test_audio_is_safe_without_device():
    """Sound calls never crash, even without an audio device or with unknown names."""
    a = Audio()
    a.play("orb")
    a.play("heartbeat", 0.9)
    a.play("does-not-exist")
    a.music("music_a")
    a.music("music_a")
    a.toggle()
    a.music("music_b")
    a.toggle()
    a.music(None)
    assert a.track is None
