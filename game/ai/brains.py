"""Hunter 'brains': each level gives the hunter a smarter decision procedure.

Every brain implements `decide(hunter, world) -> next cell` and records what it
was thinking (`hunter.plan`, `hunter.target`, `hunter.expanded`) so the game can
draw it in AI-Vision mode and show it in the side panel.
"""

import math

from .astar import astar, greedy_step, manhattan
from ..config import LOOKAHEAD, OPPOSITE


class Brain:
    id = "base"
    label = "Brain"

    def decide(self, hunter, world):
        raise NotImplementedError

    @staticmethod
    def _follow(hunter, world, goal):
        result = astar(hunter.cell, goal, world.arena.neighbors)
        hunter.expanded = result.expanded
        hunter.plan = result.path[1:]
        hunter.target = goal
        if len(result.path) >= 2:
            return result.path[1]
        return None


class Wanderer(Brain):
    """Level 1 - random walk that prefers to keep going straight.

    With probability `drift` it takes a greedy step towards the player instead,
    so the first level is not completely harmless. `drift=0` gives a pure random
    walk, which is also what confused hunters use.
    """
    id, label = "wanderer", "Random walk"

    def __init__(self, drift: float = 0.3):
        self.drift = drift

    def decide(self, hunter, world):
        arena, rng = world.arena, world.rng
        moves = arena.moves(hunter.cell)
        hunter.plan, hunter.target, hunter.expanded = [], None, 0
        if not moves:
            return None
        no_reverse = [m for m in moves if m != OPPOSITE.get(hunter.facing)] or moves
        if self.drift and rng.random() < self.drift:
            goal = world.hunter_goal()
            move = min(no_reverse, key=lambda m: (manhattan(arena.step(hunter.cell, m), goal),
                                                  rng.random()))
        elif hunter.facing in moves and rng.random() < 0.65:
            move = hunter.facing
        else:
            move = rng.choice(no_reverse)
        return arena.step(hunter.cell, move)


class Greedy(Brain):
    """Level 2 - greedy hill-climbing on Manhattan distance (no look-ahead)."""
    id, label = "greedy", "Greedy hill-climbing"

    def decide(self, hunter, world):
        goal = world.hunter_goal()
        nxt = greedy_step(hunter.cell, goal, world.arena.neighbors, world.rng,
                          avoid=hunter.prev)
        hunter.plan = [nxt] if nxt else []
        hunter.target, hunter.expanded = goal, 1
        return nxt


class AStarChaser(Brain):
    """Level 3 - A* to the player's current cell."""
    id, label = "astar", "A* pathfinding"

    def decide(self, hunter, world):
        return self._follow(hunter, world, world.hunter_goal())


class MindReader(Brain):
    """Level 4 - forecast the player with the Markov model, then intercept.

    1. Roll the predictor forward to get the player's likely next cells.
    2. For each forecast cell, compare when the player arrives with when the
       hunter could arrive (BFS distance x step time).
    3. Head for the first cell the hunter can reach in time; if none, pick the
       one where it arrives least late. Then plan the route with A*.
    """
    id, label = "mindreader", "A* + Markov prediction"

    def decide(self, hunter, world):
        player = world.player
        hunter.forecast = []
        if world.decoy_active or manhattan(hunter.cell, player.cell) <= 2:
            return self._follow(hunter, world, world.hunter_goal())

        forecast = world.predictor.rollout(player.cell, world.arena, LOOKAHEAD)
        hunter.forecast = forecast
        if not forecast:
            return self._follow(hunter, world, player.cell)

        dist = world.arena.distances(hunter.cell)
        best, best_slack = player.cell, float("inf")
        for i, cell in enumerate(forecast, start=1):
            if cell not in dist:
                continue
            slack = dist[cell] * hunter.step_time - i * player.step_time
            if slack <= 0:
                best = cell
                break
            if slack < best_slack:
                best, best_slack = cell, slack
        return self._follow(hunter, world, best)


class Mirror(Brain):
    """Level 6 - an AI copy of the player.

    It *generates* movement from the player's own Markov model instead of only
    predicting with it. Each candidate move m is scored by

        score(m) = log P_you(m | mirror's last moves) - BETA * (change in distance to you)

    i.e. "move the way you would move, but towards you" (a Boltzmann-style
    policy that mixes imitation with a goal). The best-scoring move is taken.
    """
    id, label = "mirror", "Your habits (generative)"
    BETA = 1.6
    PLAN_STEPS = 6

    def _choose(self, cell, history, world, dist):
        arena = world.arena
        moves = [m for m in arena.moves(cell) if arena.step(cell, m) in dist]
        if not moves:
            return None
        probs = world.predictor.distribution(moves, history=history)
        here = dist.get(cell, 0)

        def score(m):
            gain = dist[arena.step(cell, m)] - here
            return math.log(probs[m]) - self.BETA * gain

        return max(moves, key=lambda m: (score(m), -"URDL".index(m)))

    def decide(self, hunter, world):
        goal = world.hunter_goal()
        dist = world.arena.distances(goal)
        move = self._choose(hunter.cell, hunter.memory, world, dist)
        if move is None:
            hunter.plan, hunter.target = [], goal
            return None
        # preview: what this policy will do next (drawn in AI Vision)
        plan, cell, history = [], hunter.cell, list(hunter.memory)
        for _ in range(self.PLAN_STEPS):
            m = self._choose(cell, history, world, dist)
            if m is None:
                break
            cell = world.arena.step(cell, m)
            history.append(m)
            plan.append(cell)
            if cell == goal:
                break
        hunter.plan, hunter.target, hunter.expanded = plan, goal, len(dist)
        hunter.memory = (hunter.memory + [move])[-4:]
        return world.arena.step(hunter.cell, move)


BRAINS = {cls.id: cls for cls in (Wanderer, Greedy, AStarChaser, MindReader, Mirror)}


def make_brain(brain_id: str) -> Brain:
    return BRAINS[brain_id]()
