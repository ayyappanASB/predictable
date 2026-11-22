"""Core game rules, independent of drawing and input devices.

`World` is a pure simulation: it can run headless (tests, experiments, bots)
or be drawn by the renderer. It reports what happened each frame through
`self.events` so the renderer and audio can react (particles, sounds, speech).

Phases:  intro -> play -> (clear -> intro ...) | (dead -> killcam -> over)
"""

import math
import random
from collections import deque

from . import config as C
from . import taunts
from .ai.astar import manhattan
from .ai.brains import Wanderer, make_brain
from .ai.predictor import MarkovPredictor
from .entities import Player, Hunter, Orb, PowerUp
from .grid import generate_arena


class World:
    def __init__(self, seed=None, predictor=None):
        self.rng = random.Random(seed)
        self.predictor = predictor or MarkovPredictor(order=C.PREDICT_ORDER)
        self.predictor.new_run()
        self.events = []
        self.confused_brain = Wanderer(drift=0.0)

        self.score = 0
        self.orbs_total = 0
        self.combo = 0
        self.max_combo = 0
        self.combo_timer = 0.0
        self.time_alive = 0.0
        self.close_calls = 0
        self.surprises = 0
        self.chaos = 0.0
        self.shield = False
        self.slowmo = 0.0
        self.killcam = None
        self.level_no = 0
        self.player = Player((C.COLS // 2, C.ROWS // 2))
        self.start_level(1)

    # ---------------------------------------------------------------- levels
    def start_level(self, number: int):
        self.level_no = number
        self.level = C.level_config(number)
        self.arena = generate_arena(C.COLS, C.ROWS, self.rng)
        self.player.place(self.arena.center)
        self.predictor.history = []           # new layout -> new short-term context
        self.player_path = deque([self.player.cell], maxlen=16)

        corners = list(self.arena.corners)
        self.rng.shuffle(corners)
        self.hunters = []
        for i, brain_id in enumerate(self.level.brains):
            if brain_id == "mirror":
                colour = C.MIRROR_C
            else:
                colour = C.HUNTER if not any(h.color == C.HUNTER for h in self.hunters) else C.HUNTER_2
            self.hunters.append(Hunter(corners[i], self.level.hunter_step, make_brain(brain_id), colour))

        self.orbs_level = 0
        self.orb = None
        self.powerup = None
        self.spawn_orb()
        self.powerup_timer = self.rng.uniform(C.POWERUP_MIN_GAP, C.POWERUP_MAX_GAP)
        self.freeze_timer = 0.0
        self.decoy_timer = 0.0
        self.decoy_cell = None
        self.confuse_timer = 0.0
        self.close_cooldown = 0.0
        self.surprise_cooldown = 0.0
        self.taunt_cooldown = 0.0
        self.junction_streak = 0
        self.danger = 0.0
        self.phase = "intro"
        self.phase_timer = C.INTRO_TIME
        self.events.append(("level", number))

    # --------------------------------------------------------------- helpers
    @property
    def decoy_active(self) -> bool:
        return self.decoy_timer > 0 and self.decoy_cell is not None

    @property
    def frozen(self) -> bool:
        return self.freeze_timer > 0

    @property
    def confused(self) -> bool:
        return self.confuse_timer > 0

    def hunter_goal(self):
        return self.decoy_cell if self.decoy_active else self.player.cell

    def occupied(self):
        cells = {self.player.cell}
        cells.update(h.cell for h in self.hunters)
        if self.orb:
            cells.add(self.orb.cell)
        if self.powerup:
            cells.add(self.powerup.cell)
        return cells

    def _pick_cell(self, min_player: int, max_player: int, min_hunter: int):
        dist = self.arena.distances(self.player.cell)
        hunter_d = [self.arena.distances(h.cell) for h in self.hunters]
        taken = self.occupied()
        good, fallback = [], []
        for cell, d in dist.items():
            if cell in taken:
                continue
            fallback.append(cell)
            if min_player <= d <= max_player and all(hd.get(cell, 99) >= min_hunter for hd in hunter_d):
                good.append(cell)
        pool = good or fallback
        return self.rng.choice(pool) if pool else None

    def spawn_orb(self):
        cell = self._pick_cell(4, 12, 3)
        self.orb = Orb(cell) if cell else None

    def spawn_powerup(self):
        kinds = [k for k in PowerUp.KINDS if not (k == "shield" and self.shield)]
        cell = self._pick_cell(4, 10, 3)
        if cell:
            self.powerup = PowerUp(cell, self.rng.choice(kinds), C.POWERUP_LIFETIME)
            self.events.append(("powerup_spawn", cell))

    def farthest_corner(self):
        dist = self.arena.distances(self.player.cell)
        return max(self.arena.corners, key=lambda c: dist.get(c, -1))

    @staticmethod
    def visual_distance(a, b) -> float:
        (ax, ay), (bx, by) = a.visual_cell(), b.visual_cell()
        return math.hypot(ax - bx, ay - by)

    # --------------------------------------------------------------- taunts
    def speaker(self):
        """Index of the hunter that should talk: the smartest one, else the nearest."""
        if not self.hunters:
            return None
        for i, h in enumerate(self.hunters):
            if h.brain.id in ("mirror", "mindreader"):
                return i
        return min(range(len(self.hunters)),
                   key=lambda i: manhattan(self.hunters[i].cell, self.player.cell))

    def say(self, kind, force=False, hunter=None, text=None, **fmt):
        if not force and self.taunt_cooldown > 0:
            return
        idx = self.speaker() if hunter is None else hunter
        if idx is None:
            return
        self.taunt_cooldown = C.TAUNT_COOLDOWN
        self.events.append(("taunt", idx, text or taunts.line(kind, self.rng, **fmt)))

    # ---------------------------------------------------------------- input
    def steer(self, direction):
        if direction in C.DIRS:
            self.player.queue(direction)

    def skip_killcam(self):
        if self.phase in ("dead", "killcam"):
            self.phase = "over"
            self.events.append(("game_over", None))

    # --------------------------------------------------------------- update
    def update(self, dt: float):
        dt = min(dt, 0.05)                      # avoid huge jumps after a lag spike
        if self.slowmo > 0:
            self.slowmo -= dt
            dt *= 0.35

        if self.phase == "intro":
            self.phase_timer -= dt
            if self.phase_timer <= 0:
                self.phase = "play"
                self._opener()
            return
        if self.phase == "clear":
            self.phase_timer -= dt
            if self.phase_timer <= 0:
                self.start_level(self.level_no + 1)
            return
        if self.phase == "dead":
            self.phase_timer -= dt
            if self.phase_timer <= 0:
                self.phase = "killcam"
                self.phase_timer = C.KILLCAM_TIME
                self.events.append(("killcam", None))
            return
        if self.phase == "killcam":
            self.phase_timer -= dt
            if self.phase_timer <= 0:
                self.phase = "over"
                self.events.append(("game_over", None))
            return
        if self.phase != "play":
            return

        self._tick_timers(dt)
        step = self.player.update(dt, self.arena)
        if step:
            self._on_player_step(*step)

        if not self.frozen:
            for h in self.hunters:
                h.update(dt, self)

        if self._check_caught():
            return
        self._update_danger(dt)
        self._check_close_calls()
        if self.orbs_level >= self.level.orbs:
            self.score += C.LEVEL_BONUS * self.level_no
            self.phase = "clear"
            self.phase_timer = C.CLEAR_TIME
            self.events.append(("level_clear", self.level_no))

    def _opener(self):
        idx = self.speaker()
        if idx is not None:
            self.say("opener_" + self.hunters[idx].brain.id, force=True, hunter=idx)

    def _tick_timers(self, dt):
        self.time_alive += dt
        self.close_cooldown = max(0.0, self.close_cooldown - dt)
        self.surprise_cooldown = max(0.0, self.surprise_cooldown - dt)
        self.taunt_cooldown = max(0.0, self.taunt_cooldown - dt)
        self.chaos = max(0.0, self.chaos - C.CHAOS_DECAY * dt)
        if self.combo_timer > 0:
            self.combo_timer -= dt
            if self.combo_timer <= 0:
                self.combo = 0
        if self.freeze_timer > 0:
            self.freeze_timer = max(0.0, self.freeze_timer - dt)
        if self.confuse_timer > 0:
            self.confuse_timer = max(0.0, self.confuse_timer - dt)
        if self.decoy_timer > 0:
            self.decoy_timer = max(0.0, self.decoy_timer - dt)
            if self.decoy_timer == 0:
                self.decoy_cell = None
        if self.orb:
            self.orb.age += dt
        if self.powerup:
            self.powerup.age += dt
            if self.powerup.age >= self.powerup.life:
                self.powerup = None
                self.powerup_timer = self.rng.uniform(C.POWERUP_MIN_GAP, C.POWERUP_MAX_GAP)
        elif self.level_no >= 2:
            self.powerup_timer -= dt
            if self.powerup_timer <= 0:
                self.spawn_powerup()
                self.powerup_timer = self.rng.uniform(C.POWERUP_MIN_GAP, C.POWERUP_MAX_GAP)

    # ------------------------------------------------- player-move reactions
    def _on_player_step(self, move, valid):
        previous = self.predictor.history[-1] if self.predictor.history else None
        guess, confidence = self.predictor.observe(move, valid)
        self.player_path.append(self.player.cell)
        self._collect()

        # Only junctions (3+ exits) are real decisions; only a trained model counts.
        if len(valid) < 3 or self.predictor.total_observed <= C.MIN_TRAINING:
            return
        if guess == move:
            self.junction_streak += 1
            if self.junction_streak % 6 == 0:
                self.say("streak", n=self.junction_streak)
            elif move != previous and self.rng.random() < 0.35:
                self.say("called_it", move=taunts.DIR_WORDS[move])
        else:
            self.junction_streak = 0
            if confidence >= C.SURPRISE_MIN_CONFIDENCE and self.surprise_cooldown <= 0:
                self._surprise()

    def _surprise(self):
        self.surprise_cooldown = C.SURPRISE_COOLDOWN
        self.surprises += 1
        self.score += C.SURPRISE_POINTS
        self.events.append(("surprise", self.player.cell))
        if self.confused:
            return
        self.chaos = min(1.0, self.chaos + C.CHAOS_PER_SURPRISE)
        if self.chaos >= 1.0 - 1e-9:
            self.chaos = 0.0
            self.confuse_timer = C.CONFUSE_TIME
            self.events.append(("confused", None))
            self.say("confused", force=True)
        elif self.rng.random() < 0.4:
            self.say("surprise")

    def _collect(self):
        cell = self.player.cell
        if self.orb and self.orb.cell == cell:
            self.combo = min(C.MAX_COMBO, self.combo + 1) if self.combo_timer > 0 else 1
            self.max_combo = max(self.max_combo, self.combo)
            self.combo_timer = C.COMBO_WINDOW
            gained = C.ORB_POINTS * self.combo
            self.score += gained
            self.orbs_level += 1
            self.orbs_total += 1
            self.events.append(("orb", cell, gained, self.combo))
            self.orb = None
            if self.orbs_level < self.level.orbs:
                self.spawn_orb()
        if self.powerup and self.powerup.cell == cell:
            kind = self.powerup.kind
            if kind == "freeze":
                self.freeze_timer = C.FREEZE_TIME
                for h in self.hunters:
                    h.prev = h.cell
            elif kind == "decoy":
                self.decoy_timer = C.DECOY_TIME
                self.decoy_cell = cell
            elif kind == "shield":
                self.shield = True
            self.powerup = None
            self.events.append(("powerup", cell, kind))
            self.say(kind, force=True)

    # ------------------------------------------------------------- contact
    def _check_caught(self) -> bool:
        """Caught when the sprites actually touch (fair: what you see is what counts)."""
        for idx, h in enumerate(self.hunters):
            if self.visual_distance(h, self.player) > C.CATCH_DISTANCE:
                continue
            if self.shield:
                self.shield = False
                h.place(self.farthest_corner())
                h.close = False
                self.events.append(("shield_break", self.player.cell))
                self.say("shield", force=True, hunter=idx)
                continue
            self._die(idx)
            return True
        return False

    def _die(self, idx):
        h = self.hunters[idx]
        self.phase = "dead"
        self.phase_timer = C.DEATH_TIME
        self.slowmo = 0.0
        self.killcam = self._build_killcam(h)
        self.events.append(("death", self.player.cell, h.color))
        self.say("gotcha", force=True, hunter=idx, text=self.killcam["quote"])

    def _build_killcam(self, h):
        p = self.player
        seen = h.seen.get(p.cell) or h.seen.get(p.prev)
        forecast, moves_ago = [], 0
        if seen:
            moves_ago = self.predictor.total_observed - seen[0]
            forecast = list(seen[1])
        brain = h.brain.id
        if seen and moves_ago >= 2:
            caption = f"IT SAW THIS COMING {moves_ago} MOVES AGO"
            sub = "The Markov model predicted your path. A* planned the ambush."
        elif brain == "mirror":
            caption = "CAUGHT BY YOUR OWN HABITS"
            sub = "The Mirror moves the way you move - and you walked into yourself."
        elif brain == "mindreader":
            caption = "CUT OFF BY THE MIND READER"
            sub = "It forecast your next moves and got there first."
        elif brain == "astar":
            caption = "A* FOUND THE SHORTEST PATH"
            sub = f"Optimal route to you, {h.expanded} nodes searched."
        elif brain == "greedy":
            caption = "OUTSMARTED BY A ONE-STEP THINKER"
            sub = "Greedy search. It didn't even plan ahead."
        else:
            caption = "CAUGHT BY A RANDOM WALK"
            sub = "It wasn't even trying. Ouch."
        return {
            "path": list(self.player_path),
            "forecast": forecast,
            "catch": p.cell,
            "hunter": self.hunters.index(h),
            "color": h.color,
            "brain": brain,
            "caption": caption,
            "sub": sub,
            "moves_ago": moves_ago,
            "quote": taunts.death_line(self.predictor, self.rng),
        }

    def _update_danger(self, dt):
        nearest = min((self.visual_distance(h, self.player) for h in self.hunters), default=99)
        target = 0.0 if self.frozen else max(0.0, min(1.0, (4.0 - nearest) / 3.0))
        self.danger += (target - self.danger) * min(1.0, dt * 8)

    def _check_close_calls(self):
        for h in self.hunters:
            d = manhattan(h.cell, self.player.cell)
            if d <= 1:
                h.close = True
            elif d >= 3 and h.close:
                h.close = False
                if self.close_cooldown <= 0:
                    self.close_cooldown = C.CLOSE_CALL_COOLDOWN
                    self.close_calls += 1
                    self.score += C.CLOSE_CALL_POINTS
                    self.slowmo = 0.3
                    self.events.append(("close_call", self.player.cell))
                    self.say("close_call", hunter=self.hunters.index(h))

    # ------------------------------------------------------------ reporting
    def pop_events(self):
        events, self.events = self.events, []
        return events

    def summary(self) -> dict:
        p = self.predictor
        return {
            "score": self.score,
            "time": self.time_alive,
            "orbs": self.orbs_total,
            "level": self.level_no,
            "level_name": self.level.name,
            "accuracy": p.accuracy,
            "moves": p.run_total,
            "trained_on": p.total_observed,
            "straight": p.straight_ratio,
            "favourite_turn": p.favourite_turn(),
            "favourite_share": p.favourite_share(),
            "turns_total": p.turns_total,
            "max_combo": self.max_combo,
            "close_calls": self.close_calls,
            "surprises": self.surprises,
            "quote": self.killcam["quote"] if self.killcam else "",
        }
