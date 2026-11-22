"""Search algorithms used by the hunters.

* `astar`   - A* search with the Manhattan heuristic (optimal on a 4-way grid).
* `greedy_step` - one step of greedy hill-climbing (the level-2 "Chaser").

Both work on any graph given by a `neighbors(cell)` function, which keeps them
independent of the game and easy to unit-test.
"""

import heapq
from dataclasses import dataclass, field


def manhattan(a, b) -> int:
    """Admissible and consistent heuristic for 4-connected grids with unit cost."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


@dataclass
class SearchResult:
    path: list = field(default_factory=list)   # start ... goal, [] if unreachable
    expanded: int = 0                          # nodes taken off the frontier
    cost: float = float("inf")

    @property
    def found(self) -> bool:
        return bool(self.path)


def astar(start, goal, neighbors, heuristic=manhattan, cost=None) -> SearchResult:
    """A* search.

    f(n) = g(n) + h(n), where g is the cost so far and h the heuristic estimate.
    `cost(a, b)` optionally gives the step cost (default 1); it must be >= 1 for
    the Manhattan heuristic to stay admissible.
    Ties on f are broken towards larger g (deeper nodes), which reduces the
    number of expanded nodes on open grids.
    """
    if start == goal:
        return SearchResult([start], 0, 0)

    counter = 0
    frontier = [(heuristic(start, goal), 0, counter, start)]
    came_from = {start: None}
    g_score = {start: 0}
    closed = set()
    expanded = 0

    while frontier:
        _, neg_g, _, current = heapq.heappop(frontier)
        if current in closed:
            continue
        closed.add(current)
        expanded += 1

        if current == goal:
            path = []
            node = current
            while node is not None:
                path.append(node)
                node = came_from[node]
            path.reverse()
            return SearchResult(path, expanded, g_score[goal])

        for nxt in neighbors(current):
            if nxt in closed:
                continue
            step_cost = 1 if cost is None else cost(current, nxt)
            tentative = g_score[current] + step_cost
            if tentative < g_score.get(nxt, float("inf")):
                g_score[nxt] = tentative
                came_from[nxt] = current
                counter += 1
                heapq.heappush(frontier,
                               (tentative + heuristic(nxt, goal), -tentative, counter, nxt))

    return SearchResult([], expanded, float("inf"))


def greedy_step(current, goal, neighbors, rng, avoid=None):
    """Greedy hill-climbing: move to the neighbour closest to the goal.

    It only looks one step ahead, so it gets stuck behind walls (a local
    minimum). When no neighbour improves on the current distance it makes a
    random move instead - this is what makes level 2 beatable.
    """
    options = [n for n in neighbors(current) if n != avoid] or neighbors(current)
    if not options:
        return None
    here = manhattan(current, goal)
    best = min(manhattan(n, goal) for n in options)
    if best >= here:
        return rng.choice(options)
    return rng.choice([n for n in options if manhattan(n, goal) == best])
