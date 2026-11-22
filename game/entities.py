"""Game objects that live on the grid: the player, hunters, orbs and power-ups.

Positions are logical grid cells. Each mover also keeps its previous cell and a
step timer so the renderer can slide it smoothly between cells.
"""

from .config import DIRS, PLAYER_STEP


def direction_between(a, b):
    """Name of the direction that leads from cell `a` to the neighbouring cell `b`.

    Args:
        a: starting cell (col, row).
        b: neighbouring cell (col, row).

    Returns:
        "U", "R", "D" or "L", or None if the cells are not neighbours.
    """
    delta = (b[0] - a[0], b[1] - a[1])
    for name, vec in DIRS.items():
        if vec == delta:
            return name
    return None


class Mover:
    def __init__(self, cell, step_time: float):
        """Create something that moves one cell at a time.

        Args:
            cell: starting cell (col, row).
            step_time: seconds it takes to move one cell (smaller = faster).
        """
        self.cell = cell
        self.prev = cell
        self.step_time = step_time
        self.timer = 0.0
        self.facing = None

    def place(self, cell):
        """Teleport to `cell` (col, row) with no sliding animation."""
        self.cell = self.prev = cell
        self.timer = 0.0

    @property
    def progress(self) -> float:
        """0 -> just left `prev`, 1 -> arrived at `cell` (for smooth drawing)."""
        if self.prev == self.cell:
            return 1.0
        return max(0.0, min(1.0, self.timer / self.step_time))

    def visual_cell(self):
        """Fractional (col, row) position between prev and cell, eased with smoothstep."""
        t = self.progress
        t = t * t * (3 - 2 * t)  # smoothstep easing
        return (self.prev[0] + (self.cell[0] - self.prev[0]) * t,
                self.prev[1] + (self.cell[1] - self.prev[1]) * t)


class Player(Mover):
    QUEUE_STEPS = 4  # a buffered turn is remembered for this many steps

    def __init__(self, cell):
        """Create the player at `cell` (col, row), ready to move on the first input."""
        super().__init__(cell, PLAYER_STEP)
        self.queued = None
        self.queue_age = 0
        self.timer = self.step_time  # ready to move on the first input

    def place(self, cell):
        """Teleport to `cell` (col, row) and clear the facing direction and buffered turn."""
        super().place(cell)
        self.facing = None
        self.queued = None
        self.timer = self.step_time

    def queue(self, direction):
        """Buffer a turn so it happens at the next junction where it is possible.

        Args:
            direction: "U", "R", "D" or "L" from the keyboard, swipe or D-pad.
        """
        self.queued = direction
        self.queue_age = 0

    def update(self, dt, arena):
        """Advance the step timer and move one cell when it is time.

        The buffered turn is used if possible, otherwise the player keeps going
        straight; against a wall it waits.

        Args:
            dt: seconds since the last frame.
            arena: the Arena, for valid moves.

        Returns:
            (move, valid_moves) when a step happens, so the world can feed the move
            to the predictor; otherwise None.
        """
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
        """Create a hunter.

        Args:
            cell: spawn cell (col, row), usually a corner.
            step_time: seconds per cell; set by the level, lower is faster.
            brain: the Brain object that decides each move.
            color: RGB colour used to draw it.
        """
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
        """Teleport to `cell` (col, row) and forget the kill-cam forecast history."""
        super().place(cell)
        self.seen = {}

    def _remember_forecast(self, world):
        """Remember when each forecast cell was first predicted (for the kill-cam).

        Args:
            world: the World, for the predictor's move counter.
        """
        if not self.forecast:
            return                  # keep the last forecast while closing in
        now = world.predictor.total_observed
        snapshot = tuple(self.forecast)
        self.seen = {c: self.seen.get(c, (now, snapshot)) for c in self.forecast}

    def update(self, dt, world):
        """Advance the step timer and, when it is time, ask the brain for the next cell.

        While the hunters are confused the random-walk brain is used instead.

        Args:
            dt: seconds since the last frame.
            world: the World passed on to the brain.

        Returns:
            True if the hunter moved this frame.
        """
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
        """Create a collectable orb at `cell` (col, row); `age` drives its spawn animation."""
        self.cell = cell
        self.age = 0.0


class PowerUp:
    KINDS = ("freeze", "decoy", "shield")

    def __init__(self, cell, kind, lifetime):
        """Create a power-up.

        Args:
            cell: where it appears (col, row).
            kind: "freeze", "decoy" or "shield".
            lifetime: seconds before it disappears if not collected.
        """
        self.cell = cell
        self.kind = kind
        self.life = lifetime
        self.age = 0.0
