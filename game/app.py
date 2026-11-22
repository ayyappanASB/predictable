"""Application shell: window, input handling and the screen state machine.

States:  title -> play <-> paused -> over -> play ...

Input works the same way on every device:
  * keyboard (arrows / WASD, V, P, M, H, F, Space, Esc)
  * mouse or touch: swipe anywhere to steer, on-screen D-pad and buttons on phones
"""

import json
import os
import sys
import time
import urllib.parse
import webbrowser

import pygame

from . import config as C
from . import gfx, guide, profile, storage
from .ai.predictor import MarkovPredictor
from .audio import Audio
from .render import Renderer
from .world import World

KEY_DIRS = {
    pygame.K_UP: "U", pygame.K_w: "U",
    pygame.K_RIGHT: "R", pygame.K_d: "R",
    pygame.K_DOWN: "D", pygame.K_s: "D",
    pygame.K_LEFT: "L", pygame.K_a: "L",
}
START_KEYS = (pygame.K_SPACE, pygame.K_RETURN, pygame.K_KP_ENTER)
EVENT_SOUNDS = {"orb": "orb", "powerup": "powerup", "close_call": "close", "death": "death",
                "level": "level", "level_clear": "clear", "shield_break": "shield",
                "surprise": "surprise", "confused": "confused", "taunt": "taunt",
                "killcam": "killcam"}
SWIPE_DISTANCE = 26          # canvas pixels a finger must travel to count as a swipe
OVER_INPUT_DELAY = 0.8       # ignore taps right after dying (you were probably still swiping)
FINGER_FALLBACK = 0.15       # use raw finger events only if no emulated mouse event follows
SLOW_WORK = 0.014            # avg CPU time per frame above which we lighten the drawing
                             # (60 fps needs < 16.7 ms; measuring work, not frame interval,
                             # means a throttled background tab never triggers it)


def _url_flag(name: str) -> bool:
    """True if `name` appears in the page URL's query string (browser only), e.g. "debug_input"."""
    if sys.platform != "emscripten":
        return False
    try:
        import platform as web
        return name in str(web.window.location.search or "")
    except Exception:
        return False


def detect_layout() -> str:
    """Pick desktop / phone-landscape / phone-portrait.

    Browser: touch screens get a touch layout matching the screen orientation;
    `?layout=portrait` (or landscape/desktop) in the URL forces one.
    Desktop: the PREDICTABLE_LAYOUT environment variable can force one (testing).
    """
    if sys.platform == "emscripten":
        try:
            import platform as web            # pygbag's bridge to the browser
            win = web.window
            search = str(win.location.search or "")
            for name in C.LAYOUTS:
                if f"layout={name}" in search:
                    return name
            touch = False
            try:
                touch = int(win.navigator.maxTouchPoints or 0) > 0
            except Exception:
                pass
            try:
                touch = touch or bool(win.matchMedia("(pointer: coarse)").matches)
            except Exception:
                pass
            if touch:
                return "portrait" if int(win.innerHeight) > int(win.innerWidth) else "landscape"
        except Exception:
            pass
        return "desktop"
    forced = os.environ.get("PREDICTABLE_LAYOUT", "desktop")
    return forced if forced in C.LAYOUTS else "desktop"


def web_scale() -> float:
    """Browser: draw at the device's real pixel density (capped at 1.5x for speed).

    A `?scale=` value in the URL overrides it.

    Returns:
        Scale factor between 1.0 and 1.5 (up to 3.0 when forced).
    """
    try:
        import platform as web
        win = web.window
        search = str(win.location.search or "")
        if "scale=" in search:                       # e.g. ?scale=1 to force a resolution
            return max(1.0, min(3.0, float(search.split("scale=")[1].split("&")[0])))
        dpr = float(win.devicePixelRatio or 1)
        fit = min(float(win.innerWidth) / C.WIDTH, float(win.innerHeight) / C.HEIGHT)
        # WebAssembly drawing is slower than native, so the browser starts at 1.5x at most;
        # watch_performance() steps it down further on slow devices
        return max(1.0, min(1.5, round(dpr * fit * 4) / 4))
    except Exception:
        return 1.0


class App:
    TITLE = "PREDICTABLE - It learns how you move"

    def __init__(self, layout=None, scale=None):
        """Open the window, load sounds and the save file, and show the title screen.

        Args:
            layout: "desktop", "landscape" or "portrait"; None detects it from the device.
            scale: fixed drawing scale (used by tests and screenshots); None picks
                the best resolution for the display.
        """
        C.apply_layout(layout or detect_layout())
        pygame.init()
        self.web = sys.platform == "emscripten"
        self.window = self.gpu = self.texture = None
        self._open_display(scale)
        self.clock = pygame.time.Clock()
        self.renderer = Renderer(self.screen)
        self.audio = Audio()
        self.save = storage.load()
        # One predictor for the whole session: the hunter keeps learning you across runs.
        self.predictor = MarkovPredictor(order=C.PREDICT_ORDER)
        self.world = None
        self.state = "title"
        self.guide_page = None       # page of the "How to play" guide, None when it is closed
        self.guide_swipe = None      # pointer position where a swipe on the guide started
        self.support_opened = 0      # how many times the support form was opened (for tests)
        self.held = []               # keyboard directions held, most recent last
        self.pad = {}                # pointer id -> D-pad direction held
        self.swipes = {}             # pointer id -> last swipe anchor position
        self.finger_mode = False     # True if the browser only sends raw touch events
        self.touch_mouse_seen = False  # touches arrive as emulated mouse events: ignore fingers
        self.finger_pending = None
        self.frame_times = []
        self.summary = None
        self.new_best = False
        self.new_type = False
        self.over_timer = 0.0
        self.heartbeat_timer = 0.0
        self.running = True
        self.debug_input = _url_flag("debug_input") or os.environ.get("PREDICTABLE_DEBUG_INPUT") == "1"
        self.last_input = ""
        self.work_ms = 0.0

    # ------------------------------------------------------------ display
    def _open_display(self, scale):
        """Create the screen surface at the best resolution for this device.

        The game is laid out in logical pixels (C.WIDTH x C.HEIGHT); the screen
        surface is gfx.SCALE times larger so text and shapes are drawn at the
        display's real resolution (e.g. 2x on a Retina Mac) instead of being
        stretched and blurred.

        Args:
            scale: fixed scale to use, or None to choose automatically.
        """
        headless = os.environ.get("SDL_VIDEODRIVER") == "dummy"
        if scale is not None or headless:
            gfx.set_scale(scale or 1.0)
            size = (round(C.WIDTH * gfx.SCALE), round(C.HEIGHT * gfx.SCALE))
            self.screen = pygame.display.set_mode(size)
            return
        if self.web:
            gfx.set_scale(web_scale())
            size = (round(C.WIDTH * gfx.SCALE), round(C.HEIGHT * gfx.SCALE))
            self.screen = pygame.display.set_mode(size)
            pygame.display.set_caption(self.TITLE)
            return
        try:
            self._open_hidpi_window()
        except Exception:
            # fallback: classic window, stretched by SDL
            gfx.set_scale(1.0)
            self.window = self.gpu = self.texture = None
            self.screen = pygame.display.set_mode((C.WIDTH, C.HEIGHT), pygame.SCALED | pygame.RESIZABLE)
            pygame.display.set_caption(self.TITLE)

    def _open_hidpi_window(self):
        """Open a high-DPI desktop window drawn through a GPU texture (sharp on Retina).

        The window is sized to fit the desktop and snapped to the game's aspect
        ratio so every drawn pixel maps 1:1 to a screen pixel.
        """
        from pygame._sdl2 import video
        try:
            dw, dh = pygame.display.get_desktop_sizes()[0]
        except Exception:
            dw, dh = C.WIDTH, C.HEIGHT
        # open the window as large as comfortably fits the screen (in points)
        fit = max(0.6, min(2.0, dw * 0.92 / C.WIDTH, dh * 0.86 / C.HEIGHT))
        win_size = (round(C.WIDTH * fit), round(C.HEIGHT * fit))
        self.window = video.Window(self.TITLE, size=win_size, resizable=True, allow_high_dpi=True)
        # macOS may shrink the window to fit around the menu bar: use the size we really got,
        # snapped to the game's aspect ratio, so every drawn pixel maps 1:1 to the screen
        got_w, got_h = self.window.size
        fit = min(got_w / C.WIDTH, got_h / C.HEIGHT)
        self.window.size = (round(C.WIDTH * fit), round(C.HEIGHT * fit))
        self.gpu = video.Renderer(self.window, vsync=False)
        density = self.gpu.get_viewport().w / max(1, self.window.size[0])   # 2.0 on Retina
        gfx.set_scale(min(3.0, fit * density))
        size = (round(C.WIDTH * gfx.SCALE), round(C.HEIGHT * gfx.SCALE))
        self.screen = pygame.Surface(size)
        self.gpu.logical_size = size                      # keeps the aspect when resized
        self.texture = video.Texture(self.gpu, size, streaming=True)

    def rescale(self, new_scale):
        """Change the drawing resolution while running (used to keep slow devices smooth).

        Args:
            new_scale: the new drawing scale (logical -> real pixels).
        """
        gfx.set_scale(new_scale)
        size = (round(C.WIDTH * gfx.SCALE), round(C.HEIGHT * gfx.SCALE))
        if self.gpu is not None:
            from pygame._sdl2 import video
            self.screen = pygame.Surface(size)
            self.gpu.logical_size = size
            self.texture = video.Texture(self.gpu, size, streaming=True)
        else:
            self.screen = pygame.display.set_mode(size)
        self.renderer.set_screen(self.screen)

    def present(self):
        """Show the finished frame (flip the display, or upload the texture in high-DPI mode)."""
        if self.gpu is None:
            pygame.display.flip()
            return
        self.texture.update(self.screen)
        self.gpu.draw_color = (0, 0, 0, 255)
        self.gpu.clear()
        self.texture.draw()
        self.gpu.present()

    @staticmethod
    def to_logical(pos):
        """Convert a screen position `pos` in real pixels to logical game pixels."""
        return (pos[0] / gfx.SCALE, pos[1] / gfx.SCALE)

    # ------------------------------------------------------------ actions
    def start_run(self):
        """Start a new run with a fresh World that shares the long-term predictor."""
        self.world = World(predictor=self.predictor)
        self.renderer.effects.clear()
        self.renderer.trail.clear()
        self.release_all()
        self.heartbeat_timer = 0.0
        self.state = "play"
        self.audio.play("click")
        self.audio.music("music_a")

    def finish_run(self):
        """Store the run's summary, classify the player type, update the best score and save."""
        self.summary = self.world.summary()
        s = self.summary
        s["type"] = profile.classify(s)
        self.new_type = s["type"] not in self.save["types"]
        if self.new_type:
            self.save["types"].append(s["type"])
        self.save["runs"].append({"accuracy": round(s["accuracy"], 4), "moves": s["moves"],
                                  "score": s["score"], "level": s["level"]})
        self.new_best = s["score"] > self.save["best"]
        self.save["best"] = max(self.save["best"], s["score"])
        storage.save(self.save)
        self.release_all()
        self.state = "over"
        self.over_timer = OVER_INPUT_DELAY

    def to_title(self):
        """Stop the music and go back to the title screen."""
        self.audio.music(None)
        self.state = "title"
        self.world = None
        self.release_all()

    def pause(self):
        """Pause the game (only while playing)."""
        if self.state == "play":
            self.state = "paused"
            self.release_all()

    def release_all(self):
        """Forget every held key, D-pad button and swipe (e.g. after pausing)."""
        self.held.clear()
        self.pad.clear()
        self.swipes.clear()

    def do_action(self, action, pid):
        """Handle a tap on an on-screen button.

        Args:
            action: the button's action, e.g. "dir:U", "vision", "sound", "pause",
                "resume", "menu" or "again".
            pid: pointer id ("mouse" or a finger id), so held D-pad buttons are
                tracked per finger.
        """
        if action.startswith("dir:"):
            if self.state == "play":
                self.pad[pid] = action[4:]
                self.world.steer(action[4:])
        elif action == "vision":
            self.renderer.vision = not self.renderer.vision
        elif action == "sound":
            self.audio.toggle()
        elif action == "pause":
            self.pause()
        elif action == "resume":
            self.state = "play"
        elif action == "menu":
            self.to_title()
        elif action == "again":
            self.start_run()
        elif action == "guide":
            self.open_guide()
        elif action == "support":
            self.open_support()
        elif action == "guide_close":
            self.close_guide()
        elif action == "guide_next":
            self.turn_guide(+1)
        elif action == "guide_prev":
            self.turn_guide(-1)
        elif action.startswith("guide_page:"):
            self.guide_page = int(action.split(":")[1])
            self.audio.play("click")

    # ------------------------------------------------------------ guide
    def open_guide(self):
        """Open the "How to play" guide on its first page (pausing the game if it is running)."""
        if self.state == "play":
            self.pause()
        self.release_all()
        self.guide_page = 0
        self.guide_swipe = None
        self.audio.play("click")

    def support_context(self):
        """Game details attached to a support report so problems can be reproduced.

        Returns:
            JSON text with the layout, screen, level, score and resolution.
        """
        w = self.world
        ctx = {"layout": C.LAYOUT, "state": self.state, "scale": round(gfx.SCALE, 2),
               "runs": len(self.save["runs"]), "best": self.save["best"], "version": "web" if self.web else "desktop"}
        if w is not None:
            ctx.update(level=w.level_no, score=w.score)
        return json.dumps(ctx)

    def open_support(self):
        """Open the support / feedback form (pausing the game if it is running).

        In the browser it appears as a pop-up over the game; the desktop app opens
        the same form in the default web browser.
        """
        if self.state == "play":
            self.pause()
        self.release_all()
        self.support_opened += 1
        ctx = self.support_context()
        self.audio.play("click")
        try:
            if self.web:
                import platform as web                 # pygbag's bridge to the browser page
                web.window.openSupport(ctx)
            else:
                webbrowser.open(C.SUPPORT_URL + "?ctx=" + urllib.parse.quote(ctx))
        except Exception as exc:                        # never let a missing browser crash the game
            print("support form could not be opened:", exc)

    def close_guide(self):
        """Close the guide and return to the screen underneath (the game stays paused)."""
        self.guide_page = None
        self.guide_swipe = None
        self.renderer.guide_shown = None
        self.audio.play("click")

    def turn_guide(self, step):
        """Go to the next or previous guide page; "next" on the last page closes the guide.

        Args:
            step: +1 for the next page, -1 for the previous one.
        """
        if self.guide_page is None:
            return
        page = self.guide_page + step
        if page >= len(guide.PAGES):
            self.close_guide()
        elif page >= 0:
            self.guide_page = page
            self.audio.play("click")

    # ------------------------------------------------------------ pointers
    def pointer_down(self, pos, pid):
        """A mouse button or finger went down: press a button, start the game, skip the kill-cam or begin a swipe.

        Args:
            pos: (x, y) in logical pixels.
            pid: pointer id ("mouse" or a finger id).
        """
        action = self.renderer.button_at(pos)
        if self.guide_page is not None:          # guide open: only its buttons and swipes count
            if action:
                self.do_action(action, pid)
            else:
                self.guide_swipe = pos
            return
        if self.state == "over" and self.over_timer > 0:
            return
        if action:
            self.do_action(action, pid)
        elif self.state == "title":
            self.start_run()
        elif self.state == "over":
            self.start_run()
        elif self.state == "paused":
            if not C.TOUCH:
                self.state = "play"
        elif self.state == "play":
            if self.can_skip_killcam():
                self.world.skip_killcam()
            else:
                self.swipes[pid] = pos

    def pointer_move(self, pos, pid):
        """A pointer moved: turn the player when a swipe travels far enough.

        Args:
            pos: (x, y) in logical pixels.
            pid: pointer id ("mouse" or a finger id).
        """
        if self.guide_page is not None:          # swipe left/right to change guide pages
            if self.guide_swipe is not None and abs(pos[0] - self.guide_swipe[0]) >= 60:
                self.turn_guide(-1 if pos[0] > self.guide_swipe[0] else +1)
                self.guide_swipe = None
            return
        anchor = self.swipes.get(pid)
        if anchor is None or self.state != "play":
            return
        dx, dy = pos[0] - anchor[0], pos[1] - anchor[1]
        if max(abs(dx), abs(dy)) >= SWIPE_DISTANCE:
            if abs(dx) > abs(dy):
                self.world.steer("R" if dx > 0 else "L")
            else:
                self.world.steer("D" if dy > 0 else "U")
            self.swipes[pid] = pos     # keep swiping in one stroke to chain turns

    def pointer_up(self, pid):
        """A pointer was released: end its swipe and release its D-pad button.

        Args:
            pid: pointer id ("mouse" or a finger id).
        """
        self.guide_swipe = None
        self.swipes.pop(pid, None)
        self.pad.pop(pid, None)

    def finger_pos(self, event):
        """Convert a finger event's normalised 0..1 position to logical pixels.

        Args:
            event: a pygame FINGERDOWN / FINGERMOTION event.
        """
        return (event.x * C.WIDTH, event.y * C.HEIGHT)

    # -------------------------------------------------------------- input
    def handle(self, event):
        """Route one pygame event to the keyboard, mouse or touch handlers.

        Touches normally arrive as emulated mouse events; raw finger events are
        only used if no mouse event follows, so a tap is never counted twice.

        Args:
            event: the pygame event.
        """
        t = event.type
        if self.debug_input and t in (pygame.MOUSEBUTTONDOWN, getattr(pygame, "FINGERDOWN", -1)):
            info = dict(getattr(event, "__dict__", {}))
            info.pop("window", None)
            self.last_input = f"{pygame.event.event_name(t)} {info} surf={self.screen.get_size()}"
        touch_mouse = bool(getattr(event, "touch", False))
        if t == pygame.QUIT:
            self.running = False
        elif t == pygame.KEYDOWN:
            self.on_key(event.key)
        elif t == pygame.KEYUP:
            d = KEY_DIRS.get(event.key)
            if d in self.held:
                self.held.remove(d)
        # Browsers normally turn touches into (emulated) mouse events, which map
        # cleanly onto the canvas. Raw finger events are only used as a fallback.
        elif t == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if touch_mouse:
                self.touch_mouse_seen = True
            self.finger_pending = None
            if not (self.finger_mode and touch_mouse):
                self.pointer_down(self.to_logical(event.pos), "mouse")
        elif t == pygame.MOUSEMOTION:
            if not (self.finger_mode and touch_mouse):
                self.pointer_move(self.to_logical(event.pos), "mouse")
        elif t == pygame.MOUSEBUTTONUP and event.button == 1:
            if not (self.finger_mode and touch_mouse):
                self.pointer_up("mouse")
        elif t == getattr(pygame, "FINGERDOWN", -1):
            if self.touch_mouse_seen:
                pass                    # same touch already handled as a mouse event
            elif self.finger_mode:
                self.pointer_down(self.finger_pos(event), event.finger_id)
            else:
                self.finger_pending = (time.monotonic(), self.finger_pos(event), event.finger_id)
        elif t == getattr(pygame, "FINGERMOTION", -1) and self.finger_mode:
            self.pointer_move(self.finger_pos(event), event.finger_id)
        elif t == getattr(pygame, "FINGERUP", -1) and self.finger_mode:
            self.pointer_up(event.finger_id)
        elif t == getattr(pygame, "WINDOWFOCUSLOST", -1):
            self.pause()

    def check_finger_fallback(self):
        """If a finger tap was not followed by a mouse event in time, handle the finger instead."""
        if self.finger_pending and time.monotonic() - self.finger_pending[0] > FINGER_FALLBACK:
            _, pos, pid = self.finger_pending
            self.finger_pending = None
            self.finger_mode = True
            self.pointer_down(pos, pid)

    def on_key(self, key):
        """Handle a key press for the current screen (title, play, pause or game over).

        Args:
            key: the pygame key code.
        """
        if key == pygame.K_m:
            self.audio.toggle()
            return
        if self.guide_page is not None:          # guide open: keys browse it
            if key in (pygame.K_RIGHT, pygame.K_d) or key in START_KEYS:
                self.turn_guide(+1)
            elif key in (pygame.K_LEFT, pygame.K_a):
                self.turn_guide(-1)
            elif key in (pygame.K_ESCAPE, pygame.K_h, pygame.K_q):
                self.close_guide()
            return
        if key == pygame.K_h or key == pygame.K_SLASH:
            self.open_guide()
            return
        if key == pygame.K_f:
            self.open_support()
            return
        if key == pygame.K_v:
            self.renderer.vision = not self.renderer.vision
            return
        if self.state == "title":
            if key in START_KEYS:
                self.start_run()
            elif key in (pygame.K_ESCAPE, pygame.K_q) and not self.web:
                self.running = False
        elif self.state == "play":
            d = KEY_DIRS.get(key)
            if key in START_KEYS and self.can_skip_killcam():
                self.world.skip_killcam()
            elif d:
                if d in self.held:
                    self.held.remove(d)
                self.held.append(d)
                self.world.steer(d)
            elif key in (pygame.K_p, pygame.K_ESCAPE):
                self.pause()
        elif self.state == "paused":
            if key in (pygame.K_p, pygame.K_ESCAPE, pygame.K_SPACE):
                self.state = "play"
            elif key == pygame.K_q:
                self.to_title()
        elif self.state == "over" and self.over_timer <= 0:
            if key in START_KEYS:
                self.start_run()
            elif key in (pygame.K_ESCAPE, pygame.K_q):
                self.to_title()

    def can_skip_killcam(self):
        """True if the death animation or kill-cam is playing long enough to be skipped."""
        w = self.world
        return w is not None and (w.phase == "dead" or
                                  (w.phase == "killcam" and w.phase_timer < C.KILLCAM_TIME - 0.5))

    def held_direction(self):
        """The direction currently held (latest key, else D-pad button), or None."""
        if self.held:
            return self.held[-1]
        if self.pad:
            return list(self.pad.values())[-1]
        return None

    def on_world_events(self, events):
        """Play the sound for each world event and switch music between levels.

        Args:
            events: list of event tuples from World.pop_events().
        """
        for ev in events:
            sound = EVENT_SOUNDS.get(ev[0])
            if sound:
                self.audio.play(sound)
            if ev[0] == "level":
                self.audio.music("music_b" if ev[1] >= 4 else "music_a")
            elif ev[0] == "death":
                self.audio.music(None)

    def heartbeat(self, dt):
        """Thump faster and louder the closer the nearest hunter is.

        Args:
            dt: seconds since the last frame.
        """
        danger = self.world.danger if self.world.phase == "play" else 0.0
        if danger < 0.05:
            self.heartbeat_timer = 0.0
            return
        self.heartbeat_timer -= dt
        if self.heartbeat_timer <= 0:
            self.audio.play("heartbeat", 0.25 + 0.6 * danger)
            self.heartbeat_timer = 0.95 - 0.5 * danger

    def watch_performance(self, work):
        """Slow device (e.g. an older phone)? First lower the resolution step by step,
        then switch to cheaper effects.

        Only normal gameplay frames are measured, averaged over 120 frames.

        Args:
            work: CPU time in seconds that the last frame took to update and draw.
        """
        if self.renderer.low_quality or self.state != "play" or self.world.phase != "play":
            return                       # only judge normal gameplay, not short replays/banners
        self.frame_times.append(work)
        if len(self.frame_times) >= 120:
            avg = sum(self.frame_times) / len(self.frame_times)
            self.frame_times.clear()
            if avg > SLOW_WORK:
                if gfx.SCALE > 1.0:
                    self.rescale(max(1.0, gfx.SCALE - 0.5))
                else:
                    self.renderer.low_quality = True
                    self.renderer.effects.MAX_PARTICLES = 150

    # -------------------------------------------------------------- frame
    def frame(self):
        """Run one frame: read input, update the current screen, draw it and check performance."""
        raw_dt = self.clock.tick(C.FPS) / 1000.0
        work_start = time.perf_counter()
        dt = min(raw_dt, 0.05)
        for event in pygame.event.get():
            self.handle(event)
        self.check_finger_fallback()

        best = self.save["best"]
        muted = self.audio.muted
        self.renderer.pressed_dirs = set(self.pad.values())
        if self.state == "title":
            self.renderer.draw_title(dt, best, len(self.save["runs"]), len(self.save["types"]), muted)
        elif self.state == "play":
            d = self.held_direction()
            if d:
                self.world.steer(d)
            self.world.update(dt)
            events = self.world.pop_events()
            self.on_world_events(events)
            self.heartbeat(dt)
            self.renderer.on_events(events, self.world)
            self.renderer.draw_game(self.world, dt, best, muted)
            if self.world.phase == "over":
                self.finish_run()
        elif self.state == "paused":
            self.renderer.draw_paused_game(self.world, best, muted)
            self.renderer.draw_pause()
        elif self.state == "over":
            self.over_timer -= dt
            self.renderer.draw_game_over(self.world, dt, self.summary, best, self.new_best,
                                         self.save["runs"], muted, self.new_type,
                                         len(self.save["types"]))
        if self.guide_page is not None:
            self.renderer.draw_guide(self.guide_page, dt)
        if self.debug_input:
            fps = getattr(self.clock, "get_fps", lambda: 0.0)()
            info = (f"fps {fps:.0f}  work {self.work_ms:.1f}ms  scale {gfx.SCALE:.2f}  layout {C.LAYOUT}  "
                    f"low-q {self.renderer.low_quality}  {self.last_input}")
            for i in range(0, len(info), 60):
                self.renderer.blit_text(info[i:i + 60], 20, (255, 255, 0), (10, 10 + i // 3))
        self.present()
        # CPU time spent on this frame (independent of browser throttling)
        work = time.perf_counter() - work_start
        self.work_ms += (work * 1000 - self.work_ms) * 0.05
        self.watch_performance(work)

    def quit(self):
        """Shut down pygame."""
        pygame.quit()
