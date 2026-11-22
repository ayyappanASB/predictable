"""Sample input -> output traces of the AI, used in the report (section 3).

Every number printed here comes from the real game code, with fixed seeds,
so the traces are reproducible:

    python tools/sample_io.py
"""

import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from game import config as C  # noqa: E402
from game import profile, taunts  # noqa: E402
from game.ai.astar import astar  # noqa: E402
from game.ai.brains import Mirror  # noqa: E402
from game.ai.predictor import MarkovPredictor  # noqa: E402
from game.entities import Hunter  # noqa: E402
from game.grid import Arena, generate_arena  # noqa: E402
from game.world import World  # noqa: E402

SEED = 11   # seed of the example run in trace_run()


def trace_predictor():
    """Feed a habit ("after R, R it goes U") to the Markov model and print each prediction.

    Prints one row per move: the context (last two moves), the model's guess,
    the probability it gave that guess, the actual move and whether it was right.
    """
    print("== 1. Markov predictor: input = player moves, output = prediction ==")
    p = MarkovPredictor(order=2)
    habit = list("RRU") * 12                     # the player's habit, 36 moves
    rows = []
    for i, move in enumerate(habit, start=1):
        context = "".join(p.history[-2:]) or "-"
        guess, conf = p.observe(move)
        rows.append((i, context, guess, conf, move))
    for i, context, guess, conf, move in rows[:3] + rows[-6:]:
        print(f"move {i:2d}  context {context:>2}  predicted {guess}  P={conf:.2f}  "
              f"actual {move}  {'HIT' if guess == move else 'miss'}")
    dist = p.distribution(history=["R", "R"])
    print("P(next | R,R) =", {m: round(v, 3) for m, v in dist.items()})
    print(f"run accuracy {p.accuracy:.0%} over {p.run_total} moves")
    print("death quote:", taunts.death_line(p, random.Random(0)))


def trace_mirror():
    """Show the Mirror scoring every legal move and choosing the one closest to victory."""
    print("\n== 2. Mirror: evaluates every possible move ==")
    w = World(seed=1)
    w.start_level(6)
    w.arena = Arena(C.COLS, C.ROWS)              # open arena: every move is legal
    w.player.place((12, 9))
    for _ in range(30):                          # the player's habit: mostly RIGHT
        w.predictor.observe("R")
    for _ in range(10):
        w.predictor.observe("D")
    mirror = Hunter((5, 5), 0.2, Mirror(), C.MIRROR_C)
    dist = w.arena.distances(w.player.cell)
    here = dist[mirror.cell]
    probs = w.predictor.distribution(w.arena.moves(mirror.cell), history=[])
    print(f"mirror at {mirror.cell}, player at {w.player.cell}, BFS distance {here}")
    for m in w.arena.moves(mirror.cell):
        nxt = w.arena.step(mirror.cell, m)
        gain = dist[nxt] - here
        score = math.log(probs[m]) - Mirror.BETA * gain
        print(f"move {m}: next {nxt}  distance change {gain:+d}  P_you={probs[m]:.3f}  "
              f"score={score:+.2f}")
    chosen = mirror.brain.decide(mirror, w)
    print("chosen next cell:", chosen)


def trace_astar():
    """A* on a generated arena: path length, nodes expanded, and the BFS check of optimality."""
    print("\n== 3. A* search on a generated arena ==")
    arena = generate_arena(C.COLS, C.ROWS, random.Random(3))
    start, goal = (0, 0), (16, 12)
    res = astar(start, goal, arena.neighbors)
    print(f"start {start} goal {goal}: path length {len(res.path) - 1}, "
          f"nodes expanded {res.expanded} of {len(arena.free_cells())} free cells, "
          f"BFS shortest = {arena.distances(start)[goal]}")


def trace_run():
    """Play one seeded run with an orb-chasing bot and print the end-of-run output card data."""
    print("\n== 4. A full run: input = orb-chasing player, output = game-over card ==")
    w = World(seed=SEED)
    w.start_level(4)
    for frame in range(60 * 120):
        if w.orb:                                # play like a person: head for the orb
            path = astar(w.player.cell, w.orb.cell, w.arena.neighbors).path
            if len(path) >= 2:
                d = (path[1][0] - path[0][0], path[1][1] - path[0][1])
                w.steer({(1, 0): "R", (-1, 0): "L", (0, 1): "D", (0, -1): "U"}[d])
        w.update(1 / 60)
        w.pop_events()
        if w.phase in ("killcam", "over"):
            break
    s = w.summary()
    name, tagline, _ = profile.describe(profile.classify(s), s)
    print(f"caught on level {s['level']} ({s['level_name']}) after {s['time']:.1f} s, score {s['score']}")
    print(f"AI read {s['accuracy']:.0%} of {s['moves']} moves, surprises {s['surprises']}")
    if w.killcam:
        print("kill-cam caption:", w.killcam["caption"])
    print("quote:", s["quote"])
    print("player type:", name, "-", tagline)


if __name__ == "__main__":
    trace_predictor()
    trace_mirror()
    trace_astar()
    trace_run()
