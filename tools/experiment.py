"""Experiments for the report (headless, reproducible with fixed seeds).

Experiment 1 - How predictable are different movement styles?
    Feed the Markov predictor moves from four bot "players" and measure
    its accuracy over time (learning curve).

Experiment 2 - Which hunter brain is the strongest?
    An evasive bot (A* to the orb, avoiding cells near hunters) plays against
    each hunter brain at the SAME speed. We measure survival time, orbs
    collected and how often it is caught within 60 seconds.

    python tools/experiment.py            -> results/*.csv and results/*.png
"""

import csv
import dataclasses
import os
import random
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from game import config as C  # noqa: E402
from game.ai.astar import astar, manhattan  # noqa: E402
from game.ai.brains import make_brain  # noqa: E402
from game.ai.predictor import MarkovPredictor  # noqa: E402
from game.grid import generate_arena  # noqa: E402
from game.world import World  # noqa: E402

OUT = os.path.join(ROOT, "results")
DT = 1 / 30
VEC = {(1, 0): "R", (-1, 0): "L", (0, 1): "D", (0, -1): "U"}


# ------------------------------------------------------------------ bots
def random_bot(arena, cell, last, rng):
    """Simulated player that picks a random valid move every step.

    Args:
        arena: the Arena the bot is walking in.
        cell: the bot's current cell.
        last: the bot's previous move (None at the start).
        rng: random.Random for random choices.

    Returns:
        The chosen move.
    """
    return rng.choice(arena.moves(cell))


def straight_bot(arena, cell, last, rng):
    """Simulated player that keeps going straight and turns randomly at walls.

    Args:
        arena: the Arena the bot is walking in.
        cell: the bot's current cell.
        last: the bot's previous move (None at the start).
        rng: random.Random for random choices.

    Returns:
        The chosen move.
    """
    moves = arena.moves(cell)
    return last if last in moves else rng.choice(moves)


def pattern_bot_factory():
    """Create a simulated player that repeats a fixed loop of moves (RRRDDLLLUU).

    Returns:
        A bot function with its own position in the pattern.
    """
    pattern = "RRRDDLLLUU"
    state = {"i": 0}

    def bot(arena, cell, last, rng):
        """Next move of the looping pattern, or a random move if a wall blocks it.

        Args:
            arena: the Arena the bot is walking in.
            cell: the bot's current cell.
            last: the bot's previous move (None at the start).
            rng: random.Random for random choices.
        """
        moves = arena.moves(cell)
        want = pattern[state["i"] % len(pattern)]
        state["i"] += 1
        return want if want in moves else rng.choice(moves)
    return bot


def orb_seeker_factory():
    """Create a simulated player that walks shortest paths to random targets - like a player chasing orbs.

    Returns:
        A bot function that remembers its current target.
    """
    state = {"target": None}

    def bot(arena, cell, last, rng):
        """First step of the A* path to the current target (a new target when reached).

        Args:
            arena: the Arena the bot is walking in.
            cell: the bot's current cell.
            last: the bot's previous move (None at the start).
            rng: random.Random for random choices.
        """
        if state["target"] in (None, cell):
            state["target"] = rng.choice(arena.free_cells())
        path = astar(cell, state["target"], arena.neighbors).path
        if len(path) < 2:
            state["target"] = None
            return rng.choice(arena.moves(cell))
        return VEC[(path[1][0] - cell[0], path[1][1] - cell[1])]
    return bot


def experiment_predictability(steps=1500, seeds=5):
    """Experiment 1: how well the Markov model predicts different movement styles.

    Args:
        steps: moves each simulated player makes per trial.
        seeds: number of trials (different arenas) per player type.

    Returns:
        (curves, finals): accuracy per 100-move window for the learning-curve
        chart, and (mean, sd) accuracy over the last 500 moves per player type.
    """
    bots = {
        "Random mover": lambda: random_bot,
        "Straight-line mover": lambda: straight_bot,
        "Orb-seeker (A* paths)": orb_seeker_factory,
        "Looping pattern": pattern_bot_factory,
    }
    curves, finals = {}, {}
    for name, factory in bots.items():
        window_acc = [[] for _ in range(steps // 100)]
        final = []
        for seed in range(seeds):
            rng = random.Random(seed)
            arena = generate_arena(C.COLS, C.ROWS, rng)
            pred = MarkovPredictor(order=C.PREDICT_ORDER)
            bot, cell, last, hits = factory(), arena.center, None, []
            for _ in range(steps):
                valid = arena.moves(cell)
                move = bot(arena, cell, last, rng)
                hits.append(pred.predict(valid) == move)
                pred.observe(move, valid)
                cell, last = arena.step(cell, move), move
            for w in range(len(window_acc)):
                chunk = hits[w * 100:(w + 1) * 100]
                window_acc[w].append(sum(chunk) / len(chunk))
            final.append(sum(hits[-500:]) / 500)
        curves[name] = [statistics.mean(v) for v in window_acc]
        finals[name] = (statistics.mean(final), statistics.pstdev(final))
    return curves, finals


# --------------------------------------------------------- hunter benchmark
def evasive_direction(world):
    """Steering for the benchmark bot: A* to the orb where cells near a hunter are very expensive.

    Args:
        world: the World being simulated.

    Returns:
        The direction to steer this frame.
    """
    arena, p = world.arena, world.player.cell
    hunters = [h.cell for h in world.hunters]

    def cost(a, b):
        """Step cost into cell `b`: 1, plus a penalty the closer `b` is to a hunter.

        Args:
            a: the cell being left (unused, required by astar).
            b: the cell being entered.
        """
        d = min((manhattan(b, h) for h in hunters), default=99)
        return 1 + (40 if d <= 1 else 12 if d == 2 else 3 if d == 3 else 0)

    goal = world.orb.cell if world.orb else p
    path = astar(p, goal, arena.neighbors, cost=cost).path
    if len(path) >= 2:
        return VEC[(path[1][0] - p[0], path[1][1] - p[1])]
    moves = arena.moves(p)
    return max(moves, key=lambda m: min(manhattan(arena.step(p, m), h) for h in hunters))


def play_trial(brain_ids, seed, step_time=0.18, limit=60.0):
    """One benchmark game: the evasive bot against the given hunters, at equal speed.

    Args:
        brain_ids: hunter brain ids to put in the arena, e.g. ("mindreader",).
        seed: random seed for the arena and spawns.
        step_time: seconds per cell for the hunters.
        limit: maximum game length in seconds.

    Returns:
        (survival time in seconds, orbs collected, True if caught).
    """
    world = World(seed=seed)
    world.start_level(3)
    world.hunters = world.hunters[:1]
    template = world.hunters[0]
    world.hunters = []
    corners = sorted(world.arena.corners, key=lambda c: -manhattan(c, world.player.cell))
    for i, bid in enumerate(brain_ids):
        h = type(template)(corners[i], step_time, make_brain(bid), template.color)
        world.hunters.append(h)
    world.phase = "play"
    world.powerup_timer = 1e9          # no power-ups: compare the brains only
    world.level = dataclasses.replace(world.level, orbs=10 ** 6)   # endless level
    while world.time_alive < limit and world.phase == "play":
        world.steer(evasive_direction(world))
        world.update(DT)
        world.pop_events()
    return world.time_alive, world.orbs_total, world.phase == "dead"


def experiment_hunters(trials=30):
    """Experiment 2: compare every hunter brain against the same evasive bot.

    Args:
        trials: games per brain (each with a different seed).

    Returns:
        Dict brain name -> mean survival, its SD and SE, mean orbs and catch rate.
    """
    lineup = {
        "Random walk": ("wanderer",),
        "Greedy": ("greedy",),
        "A*": ("astar",),
        "A* + Markov": ("mindreader",),
        "Mirror": ("mirror",),
    }
    results = {}
    for name, brains in lineup.items():
        times, orbs, caught = [], [], 0
        for seed in range(trials):
            t, o, dead = play_trial(brains, 1000 + seed)
            times.append(t)
            orbs.append(o)
            caught += dead
        results[name] = {"survival": statistics.mean(times), "survival_sd": statistics.pstdev(times),
                         "survival_se": statistics.stdev(times) / len(times) ** 0.5,
                         "orbs": statistics.mean(orbs), "catch_rate": caught / trials}
        print(f"  {name:14s} survival {results[name]['survival']:5.1f}s  "
              f"orbs {results[name]['orbs']:5.1f}  caught {caught}/{trials}")
    return results


# ------------------------------------------------------------------ output
def save(curves, finals, hunters):
    """Write both experiments to CSV files and draw the charts with matplotlib.

    Args:
        curves: learning curves from experiment_predictability().
        finals: final accuracies from experiment_predictability().
        hunters: results from experiment_hunters().
    """
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "predictability.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["player", "accuracy_last_500", "sd"])
        for k, (m, s) in finals.items():
            w.writerow([k, f"{m:.3f}", f"{s:.3f}"])
    with open(os.path.join(OUT, "hunters.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["brain", "mean_survival_s", "sd", "mean_orbs", "catch_rate_60s"])
        for k, r in hunters.items():
            w.writerow([k, f"{r['survival']:.1f}", f"{r['survival_sd']:.1f}",
                        f"{r['orbs']:.1f}", f"{r['catch_rate']:.2f}"])
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed - CSVs only")
        return

    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    colours = ["#3a86ff", "#ff006e", "#fb8500", "#8338ec", "#6c757d"]

    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    xs = [(i + 1) * 100 for i in range(len(next(iter(curves.values()))))]
    for (name, ys), col in zip(curves.items(), colours):
        ax.plot(xs, [y * 100 for y in ys], marker="o", ms=3, lw=2, label=name, color=col)
    ax.axhline(25, ls="--", color="grey", lw=1)
    ax.text(xs[-1], 26.5, "chance (25%)", ha="right", color="grey", fontsize=9)
    ax.set_xlabel("Moves observed")
    ax.set_ylabel("Prediction accuracy (%)")
    ax.set_title("Markov model learning curve by movement style")
    ax.set_ylim(0, 100)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "learning_curve.png"), dpi=160)

    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    names = list(hunters)
    vals = [hunters[n]["survival"] for n in names]
    errs = [hunters[n]["survival_se"] for n in names]
    bars = ax.bar(names, vals, yerr=errs, capsize=4, color=colours)
    for b, n in zip(bars, names):
        ax.text(b.get_x() + b.get_width() / 2, 2, f"caught\n{hunters[n]['catch_rate'] * 100:.0f}%",
                ha="center", va="bottom", color="white", fontsize=9, fontweight="bold")
    ax.set_ylabel("Mean survival time (s, max 60, ±1 SE)")
    ax.set_ylim(0, 62)
    ax.set_title("Evasive bot vs each hunter brain (same speed)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "hunter_comparison.png"), dpi=160)
    print("charts saved to", OUT)


def main():
    """Run both experiments, print a summary and save the results to results/."""
    print("Experiment 1: predictability of movement styles")
    curves, finals = experiment_predictability()
    for k, (m, s) in finals.items():
        print(f"  {k:24s} {m * 100:5.1f}%  (sd {s * 100:.1f})")
    print("Experiment 2: hunter brains")
    hunters = experiment_hunters()
    save(curves, finals, hunters)


if __name__ == "__main__":
    main()
