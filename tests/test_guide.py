"""Tests for the in-game "How to play" guide: opening, browsing, closing, in every layout."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

from game import config as C, guide, storage  # noqa: E402
from game.app import App  # noqa: E402


class FakeClock:
    def tick(self, fps=0):
        """Pretend 1/60 s passed so tests are deterministic; `fps` is ignored."""
        return 16


@pytest.fixture(params=C.LAYOUTS)
def app(request, tmp_path, monkeypatch):
    """A headless App in every layout (desktop, phone landscape, phone portrait).

    Args:
        request: pytest request; request.param is the layout name.
        tmp_path: temporary folder for the save file.
        monkeypatch: used to point storage at the temporary save file.
    """
    monkeypatch.setattr(storage, "DESKTOP_FILE", str(tmp_path / "save.json"))
    a = App(layout=request.param)
    a.clock = FakeClock()
    pygame.event.set_blocked(getattr(pygame, "WINDOWFOCUSLOST", pygame.NOEVENT))
    yield a
    pygame.quit()
    C.apply_layout("desktop")


def center_of(app, action):
    """Logical centre of the drawn button with `action` in `app` (fails if it is not drawn)."""
    for rect, act in app.renderer.buttons:
        if act == action:
            return rect.center
    raise AssertionError(f"no button {action!r}; have {[a for _, a in app.renderer.buttons]}")


def tap(app, pos):
    """Press and release the mouse on `app` at logical position `pos`."""
    app.pointer_down(pos, "mouse")
    app.pointer_up("mouse")


def test_info_button_on_title_opens_the_guide(app):
    """The info icon is drawn on the title screen, fully on screen, and opens page 1.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.frame()
    pos = center_of(app, "guide")
    assert 0 < pos[0] < C.WIDTH and 0 < pos[1] < C.HEIGHT
    tap(app, pos)
    assert app.guide_page == 0 and app.state == "title"


def test_browse_every_page_then_got_it_closes(app):
    """NEXT walks through every page in order; GOT IT on the last page closes the guide.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.open_guide()
    for page in range(len(guide.PAGES)):
        app.frame()
        assert app.guide_page == page
        if page > 0:
            assert any(a == "guide_prev" for _, a in app.renderer.buttons)
        tap(app, center_of(app, "guide_next"))
    assert app.guide_page is None and app.state == "title"


def test_back_close_and_page_dots(app):
    """BACK goes one page back, a page dot jumps straight to that page, X closes.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.open_guide()
    app.guide_page = 3
    app.frame()
    tap(app, center_of(app, "guide_prev"))
    assert app.guide_page == 2
    app.frame()
    tap(app, center_of(app, "guide_page:5"))
    assert app.guide_page == 5
    app.frame()
    tap(app, center_of(app, "guide_close"))
    assert app.guide_page is None


def test_taps_behind_the_guide_do_not_start_the_game(app):
    """While the guide is open, tapping empty space or pressing SPACE never starts a run.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.open_guide()
    app.frame()
    tap(app, (5, 5))
    assert app.state == "title" and app.guide_page == 0
    app.on_key(pygame.K_SPACE)                 # SPACE = next page inside the guide
    assert app.state == "title" and app.guide_page == 1


def test_keyboard_controls(app):
    """H opens it, right/left arrows browse, ESC closes.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.on_key(pygame.K_h)
    assert app.guide_page == 0
    app.on_key(pygame.K_RIGHT)
    app.on_key(pygame.K_RIGHT)
    app.on_key(pygame.K_LEFT)
    assert app.guide_page == 1
    app.on_key(pygame.K_ESCAPE)
    assert app.guide_page is None


def test_help_key_during_play_pauses_the_game(app):
    """Opening the guide mid-run pauses the game; closing it leaves the game paused.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.start_run()
    app.world.phase = "play"
    app.frame()
    app.on_key(pygame.K_h)
    assert app.state == "paused" and app.guide_page == 0
    before = app.world.time_alive
    for _ in range(30):
        app.frame()
    assert app.world.time_alive == before      # time does not run while reading
    app.on_key(pygame.K_ESCAPE)
    assert app.state == "paused" and app.guide_page is None


def test_pause_screen_has_a_how_to_play_button(app):
    """The pause screen offers HOW TO PLAY in every layout.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.start_run()
    app.world.phase = "play"
    app.frame()
    app.pause()
    app.frame()
    tap(app, center_of(app, "guide"))
    assert app.guide_page == 0 and app.state == "paused"


def test_swipe_changes_page(app):
    """Swiping left goes forward, swiping right goes back (like apps on a phone).

    Args:
        app: the App fixture (runs once per layout).
    """
    app.open_guide()
    app.frame()
    cx, cy = C.WIDTH // 2, C.HEIGHT // 2
    app.pointer_down((cx, cy), 1)
    app.pointer_move((cx - 80, cy), 1)
    app.pointer_up(1)
    assert app.guide_page == 1
    app.pointer_down((cx, cy), 1)
    app.pointer_move((cx + 80, cy), 1)
    app.pointer_up(1)
    assert app.guide_page == 0


def test_guide_buttons_fit_on_screen_and_do_not_overlap(app):
    """Every guide button is on screen and none overlap (fair finger targets).

    Args:
        app: the App fixture (runs once per layout).
    """
    app.open_guide()
    app.guide_page = 3
    app.frame()
    rects = [r for r, a in app.renderer.buttons if not a.startswith("guide_page:")]
    screen = pygame.Rect(0, 0, C.WIDTH, C.HEIGHT)
    for i, r in enumerate(rects):
        assert screen.contains(r)
        for other in rects[i + 1:]:
            assert not r.colliderect(other)


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_every_page_draws_at_every_resolution(app, scale):
    """Every guide page (and the over / paused screens underneath) draws without errors.

    Args:
        app: the App fixture (runs once per layout).
        scale: drawing resolution (1x and Retina-like 2x).
    """
    app.rescale(scale)
    app.open_guide()
    for page in range(len(guide.PAGES)):
        app.guide_page = page
        for _ in range(8):
            app.frame()
    app.close_guide()
    app.start_run()
    app.world._die(0)
    app.world.skip_killcam()
    app.frame()
    app.frame()
    app.on_key(pygame.K_h)                     # the guide also opens from the results card
    app.frame()
    assert app.state == "over" and app.guide_page == 0


def test_guide_text_matches_the_real_rules():
    """The numbers quoted in the guide come from the game's settings."""
    text = " ".join(p["body"] for p in guide.PAGES)
    assert f"+{C.SURPRISE_POINTS}" in text and f"{C.CONFUSE_TIME:g} seconds" in text
    assert len(guide.PAGES) == 7 and all(p["title"] and p["body"] for p in guide.PAGES)
