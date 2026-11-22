"""Application shell: window, input handling and the screen state machine.

States:  title -> play <-> paused -> over -> play ...

Input works the same way on every device:
  * keyboard (arrows / WASD, V, P, M, Space, Esc)
  * mouse or touch: swipe anywhere to steer, on-screen D-pad and buttons on phones
"""

import os
import sys
import time

import pygame

from . import config as C
from . import profile, storage
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
SLOW_FRAME = 1 / 38          # average frame time that switches on low-quality effects


def _url_flag(name: str) -> bool:
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


class App:
    def __init__(self, layout=None):
        C.apply_layout(layout or detect_layout())
        pygame.init()
        self.web = sys.platform == "emscripten"
        flags = 0 if self.web else (pygame.SCALED | pygame.RESIZABLE)
        self.screen = pygame.display.set_mode((C.WIDTH, C.HEIGHT), flags)
        pygame.display.set_caption("PREDICTABLE - It learns how you move")
        self.clock = pygame.time.Clock()
        self.renderer = Renderer(self.screen)
        self.audio = Audio()
        self.save = storage.load()
        # One predictor for the whole session: the hunter keeps learning you across runs.
        self.predictor = MarkovPredictor(order=C.PREDICT_ORDER)
        self.world = None
        self.state = "title"
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

    # ------------------------------------------------------------ actions
    def start_run(self):
        self.world = World(predictor=self.predictor)
        self.renderer.effects.clear()
        self.renderer.trail.clear()
        self.release_all()
        self.heartbeat_timer = 0.0
        self.state = "play"
        self.audio.play("click")
        self.audio.music("music_a")

    def finish_run(self):
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
        self.audio.music(None)
        self.state = "title"
        self.world = None
        self.release_all()

    def pause(self):
        if self.state == "play":
            self.state = "paused"
            self.release_all()

    def release_all(self):
        self.held.clear()
        self.pad.clear()
        self.swipes.clear()

    def do_action(self, action, pid):
        """Handle a tap on an on-screen button."""
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

    # ------------------------------------------------------------ pointers
    def pointer_down(self, pos, pid):
        action = self.renderer.button_at(pos)
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
        self.swipes.pop(pid, None)
        self.pad.pop(pid, None)

    def finger_pos(self, event):
        return (event.x * C.WIDTH, event.y * C.HEIGHT)

    # -------------------------------------------------------------- input
    def handle(self, event):
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
                self.pointer_down(event.pos, "mouse")
        elif t == pygame.MOUSEMOTION:
            if not (self.finger_mode and touch_mouse):
                self.pointer_move(event.pos, "mouse")
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
        if self.finger_pending and time.monotonic() - self.finger_pending[0] > FINGER_FALLBACK:
            _, pos, pid = self.finger_pending
            self.finger_pending = None
            self.finger_mode = True
            self.pointer_down(pos, pid)

    def on_key(self, key):
        if key == pygame.K_m:
            self.audio.toggle()
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
        w = self.world
        return w is not None and (w.phase == "dead" or
                                  (w.phase == "killcam" and w.phase_timer < C.KILLCAM_TIME - 0.5))

    def held_direction(self):
        if self.held:
            return self.held[-1]
        if self.pad:
            return list(self.pad.values())[-1]
        return None

    def on_world_events(self, events):
        for ev in events:
            sound = EVENT_SOUNDS.get(ev[0])
            if sound:
                self.audio.play(sound)
            if ev[0] == "level":
                self.audio.music("music_b" if ev[1] >= 4 else "music_a")
            elif ev[0] == "death":
                self.audio.music(None)

    def heartbeat(self, dt):
        """Thump faster and louder the closer the nearest hunter is."""
        danger = self.world.danger if self.world.phase == "play" else 0.0
        if danger < 0.05:
            self.heartbeat_timer = 0.0
            return
        self.heartbeat_timer -= dt
        if self.heartbeat_timer <= 0:
            self.audio.play("heartbeat", 0.25 + 0.6 * danger)
            self.heartbeat_timer = 0.95 - 0.5 * danger

    def watch_performance(self, raw_dt):
        """Slow device (e.g. an older phone)? Switch to cheaper effects, once."""
        if self.renderer.low_quality or self.state != "play":
            return
        self.frame_times.append(raw_dt)
        if len(self.frame_times) >= 120:
            avg = sum(self.frame_times) / len(self.frame_times)
            self.frame_times.clear()
            if avg > SLOW_FRAME:
                self.renderer.low_quality = True
                self.renderer.effects.MAX_PARTICLES = 150

    # -------------------------------------------------------------- frame
    def frame(self):
        raw_dt = self.clock.tick(C.FPS) / 1000.0
        dt = min(raw_dt, 0.05)
        for event in pygame.event.get():
            self.handle(event)
        self.check_finger_fallback()
        self.watch_performance(raw_dt)

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
            self.renderer.draw_game(self.world, 0.0, best, muted)
            self.renderer.draw_pause()
        elif self.state == "over":
            self.over_timer -= dt
            self.renderer.draw_game_over(self.world, dt, self.summary, best, self.new_best,
                                         self.save["runs"], muted, self.new_type,
                                         len(self.save["types"]))
        if self.debug_input and self.last_input:
            for i in range(0, len(self.last_input), 60):
                self.renderer.blit_text(self.last_input[i:i + 60], 20, (255, 255, 0), (10, 10 + i // 3))
        pygame.display.flip()

    def quit(self):
        pygame.quit()
