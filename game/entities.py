"""Game objects that live on the grid: the player, hunters, orbs and power-ups.

Positions are logical grid cells. Each mover also keeps its previous cell and a
step timer so the renderer can slide it smoothly between cells.
"""

from .config import DIRS, PLAYER_STEP


def direction_between(a, b):
    delta = (b[0] - a[0], b[1] - a[1])
    for name, vec in DIRS.items():
        if vec == delta:
            return name
    return None


class Mover:
    def __init__(self, cell, step_time: float):
        self.cell = cell
        self.prev = cell
        self.step_time = step_time
        self.timer = 0.0
        self.facing = None

    def place(self, cell):
        self.cell = self.prev = cell
        self.timer = 0.0

    @property
    def progress(self) -> float:
        """0 -> just left `prev`, 1 -> arrived at `cell` (for smooth drawing)."""
        if self.prev == self.cell:
            return 1.0
        return max(0.0, min(1.0, self.timer / self.step_time))

    def visual_cell(self):
        """Fractional (col, row) position between prev and cell."""
        t = self.progress
        t = t * t * (3 - 2 * t)  # smoothstep easing
        return (self.prev[0] + (self.cell[0] - self.prev[0]) * t,
                self.prev[1] + (self.cell[1] - self.prev[1]) * t)


class Player(Mover):
    QUEUE_STEPS = 4  # a buffered turn is remembered for this many steps

    def __init__(self, cell):
        super().__init__(cell, PLAYER_STEP)
        self.queued = None
        self.queue_age = 0
        self.timer = self.step_time  # ready to move on the first input

    def place(self, cell):
        super().place(cell)
        self.facing = None
        self.queued = None
        self.timer = self.step_time

    def queue(self, direction):
        self.queued = direction
        self.queue_age = 0

    def update(self, dt, arena):
        """Advance the step timer. Returns (move, valid_moves) when a step happens."""
        self.timer += dt
        if self.timer < self.step_time:
            return None

        valid = arena.moves(self.cell)
        move = None
        if self.queued in valid:
            move = self.queued
            self.queued = None
        elif self.facing in valid:
            move = self.facing

        if move is None:                       # blocked or idle: wait at the cell
            self.prev = self.cell
            self.timer = self.step_time
            if self.queued is not None:
                self.queue_age += 1
                if self.queue_age > self.QUEUE_STEPS:
                    self.queued = None
            return None

        if self.queued is not None:            # turn not possible yet; keep it a little
            self.queue_age += 1
            if self.queue_age > self.QUEUE_STEPS:
                self.queued = None

        self.facing = move
        self.prev = self.cell
        self.cell = arena.step(self.cell, move)
        self.timer = min(self.timer - self.step_time, self.step_time * 0.5)
        return move, valid


class Hunter(Mover):
    def __init__(self, cell, step_time, brain, color):
        super().__init__(cell, step_time)
        self.brain = brain
        self.color = color
        self.plan = []          # cells the hunter intends to walk (AI Vision)
        self.target = None      # cell it is heading for
        self.forecast = []      # Mind Reader: predicted player cells
        self.expanded = 0       # nodes expanded in the last search
        self.close = False      # was adjacent to the player (close-call tracking)
        self.memory = []        # Mirror: its own recent moves (context for your model)
        # Kill-cam: forecast cell -> (player move count when first predicted, forecast)
        self.seen = {}

    def place(self, cell):
        super().place(cell)
        self.seen = {}

    def _remember_forecast(self, world):
        if not self.forecast:
            return                  # keep the last forecast while closing in
        now = world.predictor.total_observed
        snapshot = tuple(self.forecast)
        self.seen = {c: self.seen.get(c, (now, snapshot)) for c in self.forecast}

    def update(self, dt, world):
        self.timer += dt
        if self.timer < self.step_time:
            return False
        self.timer = min(self.timer - self.step_time, self.step_time * 0.5)
        if world.confused:
            self.forecast = []
            nxt = world.confused_brain.decide(self, world)
        else:
            nxt = self.brain.decide(self, world)
            self._remember_forecast(world)
        self.prev = self.cell
        if nxt is not None and world.arena.passable(nxt):
            self.facing = direction_between(self.cell, nxt) or self.facing
            self.cell = nxt
            return True
        return False


class Orb:
    def __init__(self, cell):
        self.cell = cell
        self.age = 0.0


class PowerUp:
    KINDS = ("freeze", "decoy", "shield")

    def __init__(self, cell, kind, lifetime):
        self.cell = cell
        self.kind = kind
        self.life = lifetime
        self.age = 0.0
