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
        """A clock that always reports `ms` milliseconds per frame."""
        self.ms = ms

    def tick(self, fps=0):
        """Return the fixed frame time; `fps` is ignored."""
        return self.ms


def make_app(layout, tmp_path, monkeypatch):
    """Create a headless App in the given layout with a temporary save file.

    Args:
        layout: "desktop", "landscape" or "portrait".
        tmp_path: temporary folder for the save file.
        monkeypatch: used to point storage at the temporary save file.
    """
    monkeypatch.setattr(storage, "DESKTOP_FILE", str(tmp_path / "save.json"))
    a = App(layout=layout)
    a.clock = FakeClock()
    pygame.event.set_blocked(getattr(pygame, "WINDOWFOCUSLOST", pygame.NOEVENT))
    return a


@pytest.fixture()
def phone(tmp_path, monkeypatch):
    """A portrait-layout App (a phone held upright), closed after the test.

    Args:
        tmp_path: temporary folder for the save file.
        monkeypatch: used to point storage at the temporary save file.
    """
    a = make_app("portrait", tmp_path, monkeypatch)
    yield a
    pygame.quit()
    C.apply_layout("desktop")


def button_center(app, action):
    """Logical centre of the on-screen button with `action` in `app` (fails if it is not drawn)."""
    for rect, act in app.renderer.buttons:
        if act == action:
            return rect.center
    raise AssertionError(f"no button {action!r}; have {[a for _, a in app.renderer.buttons]}")


def tap(app, pos, pid="mouse"):
    """Press and release a pointer on `app` at `pos` (logical pixels) with pointer id `pid`."""
    app.pointer_down(pos, pid)
    app.pointer_up(pid)


def start_playing(app):
    """Start a run on `app`, skip the level intro and draw one frame."""
    app.start_run()
    app.world.phase = "play"
    app.frame()


# ------------------------------------------------------------------ layout
@pytest.mark.parametrize("layout", C.LAYOUTS)
def test_layout_fits_on_screen(layout):
    """Arena and side cards fit on screen and never overlap.

    Args:
        layout: layout to check.
    """
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
    """The portrait layout really is portrait."""
    C.apply_layout("portrait")
    try:
        assert C.HEIGHT > C.WIDTH
    finally:
        C.apply_layout("desktop")


def test_detect_layout_env(monkeypatch):
    """PREDICTABLE_LAYOUT forces a layout; unknown values fall back to desktop.

    Args:
        monkeypatch: used to set the environment variable.
    """
    monkeypatch.setenv("PREDICTABLE_LAYOUT", "portrait")
    assert detect_layout() == "portrait"
    monkeypatch.setenv("PREDICTABLE_LAYOUT", "nonsense")
    assert detect_layout() == "desktop"


@pytest.mark.parametrize("layout", ["landscape", "portrait"])
def test_touch_controls_are_on_screen_and_do_not_overlap(layout, tmp_path, monkeypatch):
    """Touch buttons are on screen, outside the arena, finger-sized and never overlap.

    Args:
        layout: "landscape" or "portrait".
        tmp_path: temporary folder for the save file.
        monkeypatch: used to point storage at the temporary save file.
    """
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
    """Tapping the title starts the game, but the SOUND button only toggles sound.

    Args:
        phone: a portrait-layout App fixture.
    """
    phone.frame()
    tap(phone, button_center(phone, "sound"))
    assert phone.state == "title" and phone.audio.muted
    tap(phone, (C.WIDTH // 2, 300))
    assert phone.state == "play"


def test_dpad_steers_and_holds(phone):
    """Holding a D-pad button steers and keeps steering until released.

    Args:
        phone: a portrait-layout App fixture.
    """
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
    """Swipes in all four directions steer the player.

    Args:
        phone: a portrait-layout App fixture.
    """
    start_playing(phone)
    cx, cy = C.ARENA_X + 300, C.ARENA_Y + 250
    for (dx, dy), expected in (((1, 0), "R"), ((-1, 0), "L"), ((0, 1), "D"), ((0, -1), "U")):
        phone.pointer_down((cx, cy), 1)
        phone.pointer_move((cx + dx * (SWIPE_DISTANCE + 4), cy + dy * (SWIPE_DISTANCE + 4)), 1)
        assert phone.world.player.queued == expected
        phone.pointer_up(1)


def test_small_finger_jitter_is_not_a_swipe(phone):
    """A tiny finger movement is not treated as a swipe.

    Args:
        phone: a portrait-layout App fixture.
    """
    start_playing(phone)
    phone.world.player.queued = None
    phone.pointer_down((300, 400), 1)
    phone.pointer_move((300 + SWIPE_DISTANCE - 5, 400), 1)
    assert phone.world.player.queued is None


def test_one_stroke_can_chain_turns(phone):
    """One continuous stroke can make several turns.

    Args:
        phone: a portrait-layout App fixture.
    """
    start_playing(phone)
    phone.pointer_down((300, 400), 1)
    phone.pointer_move((340, 400), 1)
    assert phone.world.player.queued == "R"
    phone.pointer_move((340, 440), 1)
    assert phone.world.player.queued == "D"


def test_pause_resume_and_menu_buttons(phone):
    """AI VISION, PAUSE, RESUME and QUIT TO MENU buttons work; empty taps do not resume.

    Args:
        phone: a portrait-layout App fixture.
    """
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
    """PLAY AGAIN and MENU work on the game-over card, after the short input delay.

    Args:
        phone: a portrait-layout App fixture.
    """
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
    """Tapping the screen skips the kill-cam.

    Args:
        phone: a portrait-layout App fixture.
    """
    start_playing(phone)
    phone.world._die(0)
    tap(phone, (C.WIDTH // 2, C.ARENA_Y + 200))
    assert phone.world.phase == "over"


def test_raw_finger_events_fallback(phone, monkeypatch):
    """If the browser sends only finger events (no emulated mouse), they still work.

    Args:
        phone: a portrait-layout App fixture.
        monkeypatch: used to move the clock forward past the fallback delay.
    """
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
    """When both a finger and a mouse event arrive, the tap counts only once.

    Args:
        phone: a portrait-layout App fixture.
    """
    phone.frame()
    phone.handle(pygame.event.Event(pygame.FINGERDOWN, x=0.5, y=0.3, finger_id=3, touch_id=0,
                                    dx=0, dy=0))
    phone.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(360, 400), button=1, touch=True))
    assert phone.finger_pending is None and not phone.finger_mode
    assert phone.state == "play"               # exactly one start, no double tap


# -------------------------------------------------------------- performance
def slow_frames(app, n=120, work=0.03):
    """Report n frames that each took `work` seconds of drawing.

    Args:
        app: the App being measured.
        n: number of frames to report.
        work: CPU time per frame in seconds.
    """
    for _ in range(n):
        app.watch_performance(work)


def test_slow_device_switches_to_low_quality(phone):
    """A slow device at 1x resolution switches to low-quality effects and still draws.

    Args:
        phone: a portrait-layout App fixture.
    """
    start_playing(phone)
    slow_frames(phone)                          # 30 ms of work per frame
    assert phone.renderer.low_quality
    for _ in range(30):                         # still draws fine
        phone.frame()


def test_slow_device_lowers_resolution_first(tmp_path, monkeypatch):
    """A slow device first drops the resolution, then the effects.

    Args:
        tmp_path: temporary folder for the save file.
        monkeypatch: used to point storage at the temporary save file.
    """
    from game import gfx
    a = make_app("portrait", tmp_path, monkeypatch)
    try:
        a.rescale(1.5)
        start_playing(a)
        a.world.freeze_timer = 1e9                  # stay alive: performance is measured in play
        slow_frames(a)
        assert gfx.SCALE == 1.0 and not a.renderer.low_quality      # step 1: resolution
        assert a.screen.get_size() == (C.WIDTH, C.HEIGHT)
        for _ in range(20):
            a.frame()
        slow_frames(a)
        assert a.renderer.low_quality                               # step 2: effects
        a.world._die(0)
        for _ in range(300):                                        # everything still draws
            a.frame()
    finally:
        pygame.quit()
        C.apply_layout("desktop")


def test_fast_device_keeps_full_quality(phone):
    """A fast device keeps full quality.

    Args:
        phone: a portrait-layout App fixture.
    """
    start_playing(phone)
    for _ in range(130):
        phone.frame()
    assert not phone.renderer.low_quality


def test_real_phone_event_order_gives_exactly_one_tap(phone, monkeypatch):
    """SDL sends the emulated mouse click first and the finger event after it.
    The finger event must not be treated as a second tap (e.g. pause then resume).

    Args:
        phone: a portrait-layout App fixture.
        monkeypatch: used to move the clock forward past the fallback delay.
    """
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


# ------------------------------------------------------------ high resolution
@pytest.mark.parametrize("layout", C.LAYOUTS)
@pytest.mark.parametrize("scale", [1.5, 2.0, 2.65])
def test_high_resolution_rendering(layout, scale, tmp_path, monkeypatch):
    """Retina / phone densities: the screen is bigger, the layout is identical.

    Args:
        layout: layout to draw.
        scale: drawing scale (1.5, 2.0 or 2.65).
        tmp_path: temporary folder for the save file.
        monkeypatch: used to point storage at the temporary save file.
    """
    monkeypatch.setattr(storage, "DESKTOP_FILE", str(tmp_path / "save.json"))
    a = App(layout=layout, scale=scale)
    try:
        a.clock = FakeClock()
        assert a.screen.get_size() == (round(C.WIDTH * scale), round(C.HEIGHT * scale))
        for _ in range(5):
            a.frame()                            # title
        a.start_run()
        a.world.phase = "play"
        a.renderer.vision = True
        for _ in range(60):
            a.frame()
        a.world._die(0)
        for _ in range(400):
            a.frame()
            if a.state == "over":
                break
        assert a.state == "over"
        for _ in range(5):
            a.frame()
    finally:
        pygame.quit()
        C.apply_layout("desktop")


def test_clicks_map_to_logical_coordinates_at_2x(tmp_path, monkeypatch):
    """At 2x resolution a click in real pixels still hits the right button.

    Args:
        tmp_path: temporary folder for the save file.
        monkeypatch: used to point storage at the temporary save file.
    """
    monkeypatch.setattr(storage, "DESKTOP_FILE", str(tmp_path / "save.json"))
    a = App(layout="portrait", scale=2.0)
    try:
        a.clock = FakeClock()
        start_playing(a)
        lx, ly = button_center(a, "pause")                  # logical position of the button
        a.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(lx * 2, ly * 2), button=1))
        assert a.state == "paused"
    finally:
        pygame.quit()
        C.apply_layout("desktop")



def test_throttled_tab_does_not_lower_quality(tmp_path, monkeypatch):
    """A background tab at 25 fps but with light drawing work keeps full quality.

    Args:
        tmp_path: temporary folder for the save file.
        monkeypatch: used to point storage at the temporary save file.
    """
    from game import gfx
    a = make_app("desktop", tmp_path, monkeypatch)
    try:
        a.rescale(1.5)
        start_playing(a)
        a.world.freeze_timer = 1e9
        a.clock = FakeClock(ms=40)                 # slow frame *interval* only
        slow_frames(a, 240, work=0.006)            # but only 6 ms of real work
        assert gfx.SCALE == 1.5 and not a.renderer.low_quality
    finally:
        pygame.quit()
        C.apply_layout("desktop")
