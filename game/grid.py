"""The arena: a grid of free cells and walls, plus procedural level generation."""

import random
from collections import deque

from .config import DIRS, DIR_ORDER

Cell = tuple  # (col, row)


class Arena:
    def __init__(self, cols: int, rows: int, walls=()):
        """Create an arena.

        Args:
            cols: width of the grid in cells.
            rows: height of the grid in cells.
            walls: iterable of (col, row) cells that are blocked.
        """
        self.cols = cols
        self.rows = rows
        self.walls = set(walls)

    # ------------------------------------------------------------------ queries
    def in_bounds(self, cell) -> bool:
        """True if `cell` (col, row) lies inside the grid."""
        c, r = cell
        return 0 <= c < self.cols and 0 <= r < self.rows

    def passable(self, cell) -> bool:
        """True if `cell` (col, row) is inside the grid and not a wall."""
        return self.in_bounds(cell) and cell not in self.walls

    def step(self, cell, direction: str):
        """Cell reached by moving one step from `cell` in `direction`.

        Args:
            cell: starting cell (col, row).
            direction: "U", "R", "D" or "L".

        Returns:
            The neighbouring cell (it may be a wall or off the grid; check passable()).
        """
        dc, dr = DIRS[direction]
        return (cell[0] + dc, cell[1] + dr)

    def moves(self, cell) -> list:
        """Directions that lead from `cell` (col, row) to a free neighbouring cell."""
        return [d for d in DIR_ORDER if self.passable(self.step(cell, d))]

    def neighbors(self, cell) -> list:
        """Free neighbouring cells of `cell` (col, row); used by the search algorithms."""
        return [self.step(cell, d) for d in self.moves(cell)]

    def free_cells(self) -> list:
        """Every cell that is not a wall, row by row."""
        return [(c, r) for r in range(self.rows) for c in range(self.cols)
                if (c, r) not in self.walls]

    def distances(self, start) -> dict:
        """Breadth-first search distance from `start` to every reachable cell.

        Args:
            start: cell (col, row) to measure from.

        Returns:
            Dict cell -> number of steps on the shortest path from `start`.
        """
        dist = {start: 0}
        queue = deque([start])
        while queue:
            cur = queue.popleft()
            for nxt in self.neighbors(cur):
                if nxt not in dist:
                    dist[nxt] = dist[cur] + 1
                    queue.append(nxt)
        return dist

    def is_connected(self) -> bool:
        """True if every free cell can be reached from every other (BFS check)."""
        free = self.free_cells()
        return bool(free) and len(self.distances(free[0])) == len(free)

    def has_dead_ends(self) -> bool:
        """True if any free cell has fewer than two free neighbours (a trap)."""
        return any(len(self.neighbors(c)) < 2 for c in self.free_cells())

    # ------------------------------------------------------------- landmarks
    @property
    def center(self):
        """The centre cell, where the player spawns."""
        return (self.cols // 2, self.rows // 2)

    @property
    def corners(self):
        """The four corner cells, where hunters spawn."""
        return [(0, 0), (self.cols - 1, 0), (0, self.rows - 1),
                (self.cols - 1, self.rows - 1)]


# Wall "pieces" placed in the top-left quadrant and mirrored to the others.
_SHAPES = (
    ((0, 0), (1, 0)),                 # short bar
    ((0, 0), (1, 0), (2, 0)),         # long bar
    ((0, 0), (0, 1)),                 # short pillar
    ((0, 0), (0, 1), (0, 2)),         # long pillar
    ((0, 0), (1, 0), (0, 1)),         # L corner
    ((0, 0),),                        # block
)


def _protected(cols: int, rows: int) -> set:
    """Cells that must stay free: the player spawn area and the 4 corners.

    Args:
        cols: grid width in cells.
        rows: grid height in cells.

    Returns:
        Set of protected (col, row) cells.
    """
    cc, cr = cols // 2, rows // 2
    keep = {(cc + dc, cr + dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1)}
    for (c, r) in ((0, 0), (cols - 1, 0), (0, rows - 1), (cols - 1, rows - 1)):
        keep.add((c, r))
    return keep


def generate_arena(cols: int, rows: int, rng: random.Random,
                   target_density: float = 0.16, max_tries: int = 300) -> Arena:
    """Build a symmetric arena with no dead ends where every free cell is reachable.

    Walls are placed as small pieces in one quadrant and mirrored to the other
    three, which gives balanced, good-looking layouts. Each candidate piece is
    checked with BFS (connectivity + no dead ends) and rejected if it fails.

    Args:
        cols: grid width in cells.
        rows: grid height in cells.
        rng: random.Random, so a seed always gives the same arena.
        target_density: fraction of cells that should become walls.
        max_tries: how many whole layouts to attempt before using the fallback.

    Returns:
        A valid Arena.
    """
    keep = _protected(cols, rows)
    target = int(cols * rows * target_density)
    half_c, half_r = cols // 2, rows // 2

    for _ in range(max_tries):
        walls = set()
        attempts = 0
        while len(walls) < target and attempts < 200:
            attempts += 1
            shape = rng.choice(_SHAPES)
            ox, oy = rng.randint(2, half_c - 1), rng.randint(2, half_r - 1)
            piece = set()
            for dx, dy in shape:
                c, r = ox + dx, oy + dy
                for mc, mr in ((c, r), (cols - 1 - c, r), (c, rows - 1 - r),
                               (cols - 1 - c, rows - 1 - r)):
                    piece.add((mc, mr))
            # keep a free outer ring and the protected cells
            if any(c < 1 or r < 1 or c > cols - 2 or r > rows - 2 or (c, r) in keep
                   for c, r in piece):
                continue
            trial = Arena(cols, rows, walls | piece)
            if trial.is_connected() and not trial.has_dead_ends():
                walls |= piece
        arena = Arena(cols, rows, walls)
        if len(walls) >= target * 0.7 and arena.is_connected() and not arena.has_dead_ends():
            return arena
    return fallback_arena(cols, rows)


def fallback_arena(cols: int, rows: int) -> Arena:
    """A hand-made layout used if generation ever fails (it never should).

    Args:
        cols: grid width in cells.
        rows: grid height in cells.

    Returns:
        An Arena with two rows of short bars.
    """
    walls = set()
    for c in range(3, cols - 3, 4):
        for r in (2, rows - 3):
            walls.add((c, r))
            walls.add((c + 1, r))
    return Arena(cols, rows, walls)
