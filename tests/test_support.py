"""Tests for the support / feedback button: where it is, what it opens, and that it never crashes."""

import json
import os
import urllib.parse

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

from game import config as C, storage  # noqa: E402
from game import app as appmod  # noqa: E402
from game.app import App  # noqa: E402


class FakeClock:
    def tick(self, fps=0):
        """Pretend 1/60 s passed so tests are deterministic; `fps` is ignored."""
        return 16


@pytest.fixture(params=C.LAYOUTS)
def app(request, tmp_path, monkeypatch):
    """A headless App in every layout whose "browser" only records the URLs it is asked to open.

    Args:
        request: pytest request; request.param is the layout name.
        tmp_path: temporary folder for the save file.
        monkeypatch: replaces the save file and webbrowser.open (no real browser opens).
    """
    monkeypatch.setattr(storage, "DESKTOP_FILE", str(tmp_path / "save.json"))
    opened = []
    monkeypatch.setattr(appmod.webbrowser, "open", lambda url: opened.append(url) or True)
    a = App(layout=request.param)
    a.clock = FakeClock()
    a.opened_urls = opened
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


def test_support_button_top_left_opens_the_form(app):
    """The headset button sits in the top-left corner and opens the support form with game details.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.frame()
    x, y = center_of(app, "support")
    assert x < C.WIDTH * 0.2 and y < C.HEIGHT * 0.15
    tap(app, (x, y))
    assert app.state == "title" and app.support_opened == 1
    url = app.opened_urls[-1]
    assert url.startswith(C.SUPPORT_URL + "?ctx=")
    ctx = json.loads(urllib.parse.unquote(url.split("?ctx=")[1]))
    assert ctx["layout"] == C.LAYOUT and ctx["state"] == "title"


def test_support_does_not_overlap_the_info_button(app):
    """Support (left) and How to play (right) buttons are separate, on-screen targets.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.frame()
    rects = {a: r for r, a in app.renderer.buttons}
    screen = pygame.Rect(0, 0, C.WIDTH, C.HEIGHT)
    assert screen.contains(rects["support"]) and screen.contains(rects["guide"])
    assert not rects["support"].colliderect(rects["guide"])


def test_f_key_mid_run_pauses_and_sends_level(app):
    """Pressing F while playing pauses the game and attaches the level and score.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.start_run()
    app.world.phase = "play"
    app.frame()
    app.on_key(pygame.K_f)
    assert app.state == "paused"
    ctx = json.loads(urllib.parse.unquote(app.opened_urls[-1].split("?ctx=")[1]))
    assert ctx["level"] == 1 and "score" in ctx


def test_pause_menu_has_support_button(app):
    """The pause menu offers SUPPORT next to HOW TO PLAY, and no buttons overlap.

    Args:
        app: the App fixture (runs once per layout).
    """
    app.start_run()
    app.world.phase = "play"
    app.frame()
    app.pause()
    app.frame()
    rects = [r for r, _ in app.renderer.buttons]
    for i, r in enumerate(rects):
        assert pygame.Rect(0, 0, C.WIDTH, C.HEIGHT).contains(r)
        for other in rects[i + 1:]:
            assert not r.colliderect(other)
    tap(app, center_of(app, "support"))
    assert app.support_opened == 1 and app.state == "paused"


def test_no_browser_never_crashes_the_game(app, monkeypatch):
    """If no browser can be opened the game keeps running.

    Args:
        app: the App fixture (runs once per layout).
        monkeypatch: makes webbrowser.open raise an error.
    """
    def broken(url):
        """Simulate a machine with no web browser; `url` is ignored."""
        raise RuntimeError("no browser")
    monkeypatch.setattr(appmod.webbrowser, "open", broken)
    app.open_support()
    for _ in range(5):
        app.frame()
    assert app.support_opened == 1


def test_web_build_calls_the_page_popup(app, monkeypatch):
    """In the browser the game asks the page to show the pop-up (window.openSupport).

    Args:
        app: the App fixture (runs once per layout).
        monkeypatch: provides a fake pygbag `platform` module.
    """
    import sys
    import types
    calls = []
    fake = types.SimpleNamespace(window=types.SimpleNamespace(openSupport=lambda ctx: calls.append(ctx)))
    monkeypatch.setitem(sys.modules, "platform", fake)
    app.web = True
    app.open_support()
    assert calls and json.loads(calls[0])["version"] == "web"
    assert app.opened_urls == []
