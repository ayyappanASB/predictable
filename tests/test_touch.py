"""Touch / mobile tests: layouts fit the screen, D-pad, swipes and on-screen buttons."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

from game import config as C, storage  # noqa: E402
from game.app import App, SWIPE_DISTANCE, detect_layout  # noqa: E402


class FakeClock:
    def __init__(self, ms=16):
        self.ms = ms

    def tick(self, fps=0):
        return self.ms


def make_app(layout, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DESKTOP_FILE", str(tmp_path / "save.json"))
    a = App(layout=layout)
    a.clock = FakeClock()
    pygame.event.set_blocked(getattr(pygame, "WINDOWFOCUSLOST", pygame.NOEVENT))
    return a


@pytest.fixture()
def phone(tmp_path, monkeypatch):
    a = make_app("portrait", tmp_path, monkeypatch)
    yield a
    pygame.quit()
    C.apply_layout("desktop")


def button_center(app, action):
    for rect, act in app.renderer.buttons:
        if act == action:
            return rect.center
    raise AssertionError(f"no button {action!r}; have {[a for _, a in app.renderer.buttons]}")


def tap(app, pos, pid="mouse"):
    app.pointer_down(pos, pid)
    app.pointer_up(pid)


def start_playing(app):
    app.start_run()
    app.world.phase = "play"
    app.frame()


# ------------------------------------------------------------------ layout
@pytest.mark.parametrize("layout", C.LAYOUTS)
def test_layout_fits_on_screen(layout):
    C.apply_layout(layout)
    try:
        assert C.ARENA_X >= 0 and C.ARENA_X + C.ARENA_W <= C.WIDTH
        assert C.ARENA_Y + C.ARENA_H <= C.HEIGHT
        for x, y, w, h in (C.CARD_BRAIN, C.CARD_MODEL, C.CARD_ACC):
            assert x >= 0 and y >= 0 and x + w <= C.WIDTH and y + h <= C.HEIGHT
            arena = pygame.Rect(C.ARENA_X, C.ARENA_Y, C.ARENA_W, C.ARENA_H)
            assert not arena.colliderect((x, y, w, h))
        assert C.TOUCH == (layout != "desktop") and C.PORTRAIT == (layout == "portrait")
    finally:
        C.apply_layout("desktop")


def test_portrait_is_taller_than_wide():
    C.apply_layout("portrait")
    try:
        assert C.HEIGHT > C.WIDTH
    finally:
        C.apply_layout("desktop")


def test_detect_layout_env(monkeypatch):
    monkeypatch.setenv("PREDICTABLE_LAYOUT", "portrait")
    assert detect_layout() == "portrait"
    monkeypatch.setenv("PREDICTABLE_LAYOUT", "nonsense")
    assert detect_layout() == "desktop"


@pytest.mark.parametrize("layout", ["landscape", "portrait"])
def test_touch_controls_are_on_screen_and_do_not_overlap(layout, tmp_path, monkeypatch):
    a = make_app(layout, tmp_path, monkeypatch)
    try:
        start_playing(a)
        rects = [r for r, _ in a.renderer.buttons]
        screen = pygame.Rect(0, 0, C.WIDTH, C.HEIGHT)
        arena = pygame.Rect(C.ARENA_X, C.ARENA_Y, C.ARENA_W, C.ARENA_H)
        assert {"vision", "sound", "pause"} <= {act for _, act in a.renderer.buttons}
        for i, r in enumerate(rects):
            assert screen.contains(r)
            assert not r.colliderect(arena)
            for other in rects[i + 1:]:
                assert not r.colliderect(other)
            assert min(r.width, r.height) >= 44          # comfortable finger size
    finally:
        pygame.quit()
        C.apply_layout("desktop")


# ----------------------------------------------------------------- controls
def test_title_tap_starts_and_sound_button_does_not(phone):
    phone.frame()
    tap(phone, button_center(phone, "sound"))
    assert phone.state == "title" and phone.audio.muted
    tap(phone, (C.WIDTH // 2, 300))
    assert phone.state == "play"


def test_dpad_steers_and_holds(phone):
    start_playing(phone)
    pos = button_center(phone, "dir:L")
    phone.pointer_down(pos, 7)
    assert phone.world.player.queued == "L"
    phone.frame()
    assert phone.renderer.pressed_dirs == {"L"}
    assert phone.held_direction() == "L"
    phone.pointer_up(7)
    assert phone.held_direction() is None


def test_swipe_steers_in_each_direction(phone):
    start_playing(phone)
    cx, cy = C.ARENA_X + 300, C.ARENA_Y + 250
    for (dx, dy), expected in (((1, 0), "R"), ((-1, 0), "L"), ((0, 1), "D"), ((0, -1), "U")):
        phone.pointer_down((cx, cy), 1)
        phone.pointer_move((cx + dx * (SWIPE_DISTANCE + 4), cy + dy * (SWIPE_DISTANCE + 4)), 1)
        assert phone.world.player.queued == expected
        phone.pointer_up(1)


def test_small_finger_jitter_is_not_a_swipe(phone):
    start_playing(phone)
    phone.world.player.queued = None
    phone.pointer_down((300, 400), 1)
    phone.pointer_move((300 + SWIPE_DISTANCE - 5, 400), 1)
    assert phone.world.player.queued is None


def test_one_stroke_can_chain_turns(phone):
    start_playing(phone)
    phone.pointer_down((300, 400), 1)
    phone.pointer_move((340, 400), 1)
    assert phone.world.player.queued == "R"
    phone.pointer_move((340, 440), 1)
    assert phone.world.player.queued == "D"


def test_pause_resume_and_menu_buttons(phone):
    start_playing(phone)
    tap(phone, button_center(phone, "vision"))
    assert phone.renderer.vision
    tap(phone, button_center(phone, "pause"))
    assert phone.state == "paused"
    phone.frame()
    tap(phone, (10, 10))                       # tapping empty space does not resume
    assert phone.state == "paused"
    tap(phone, button_center(phone, "resume"))
    assert phone.state == "play"
    phone.frame()
    tap(phone, button_center(phone, "pause"))
    phone.frame()
    tap(phone, button_center(phone, "menu"))
    assert phone.state == "title"


def test_game_over_buttons(phone):
    start_playing(phone)
    phone.world._die(0)
    phone.world.skip_killcam()
    phone.frame()                              # this frame notices the run ended
    phone.frame()                              # this one draws the results card
    assert phone.state == "over"
    tap(phone, button_center(phone, "again"))  # ignored during the short input delay
    assert phone.state == "over"
    phone.over_timer = 0
    phone.frame()
    tap(phone, button_center(phone, "again"))
    assert phone.state == "play"
    phone.world._die(0)
    phone.world.skip_killcam()
    phone.frame()
    phone.frame()
    phone.over_timer = 0
    phone.frame()
    tap(phone, button_center(phone, "menu"))
    assert phone.state == "title"


def test_tap_skips_killcam(phone):
    start_playing(phone)
    phone.world._die(0)
    tap(phone, (C.WIDTH // 2, C.ARENA_Y + 200))
    assert phone.world.phase == "over"


def test_raw_finger_events_fallback(phone, monkeypatch):
    """If the browser sends only finger events (no emulated mouse), they still work."""
    phone.frame()
    ev = pygame.event.Event(pygame.FINGERDOWN, x=0.5, y=0.3, finger_id=3, touch_id=0, dx=0, dy=0)
    phone.handle(ev)
    assert phone.state == "title"              # waits briefly for an emulated mouse event
    import game.app as appmod
    t0 = appmod.time.monotonic()
    monkeypatch.setattr(appmod.time, "monotonic", lambda: t0 + 1.0)
    phone.check_finger_fallback()
    assert phone.finger_mode and phone.state == "play"


def test_emulated_mouse_wins_over_finger(phone):
    phone.frame()
    phone.handle(pygame.event.Event(pygame.FINGERDOWN, x=0.5, y=0.3, finger_id=3, touch_id=0,
                                    dx=0, dy=0))
    phone.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(360, 400), button=1, touch=True))
    assert phone.finger_pending is None and not phone.finger_mode
    assert phone.state == "play"               # exactly one start, no double tap


# -------------------------------------------------------------- performance
def test_slow_device_switches_to_low_quality(phone):
    start_playing(phone)
    phone.clock = FakeClock(ms=40)             # 25 fps
    for _ in range(130):
        phone.frame()
    assert phone.renderer.low_quality
    for _ in range(30):                         # still draws fine
        phone.frame()


def test_fast_device_keeps_full_quality(phone):
    start_playing(phone)
    for _ in range(130):
        phone.frame()
    assert not phone.renderer.low_quality


def test_real_phone_event_order_gives_exactly_one_tap(phone, monkeypatch):
    """SDL sends the emulated mouse click first and the finger event after it.
    The finger event must not be treated as a second tap (e.g. pause then resume)."""
    start_playing(phone)
    pos = button_center(phone, "pause")
    phone.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1, touch=True))
    phone.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1, touch=True))
    phone.handle(pygame.event.Event(pygame.FINGERDOWN, x=pos[0] / C.WIDTH, y=pos[1] / C.HEIGHT,
                                    finger_id=1, touch_id=0, dx=0, dy=0))
    import game.app as appmod
    t0 = appmod.time.monotonic()
    monkeypatch.setattr(appmod.time, "monotonic", lambda: t0 + 1.0)
    phone.check_finger_fallback()
    assert phone.state == "paused" and not phone.finger_mode
