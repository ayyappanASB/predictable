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
        """Choose the hunter's next cell. Every brain overrides this.

        Args:
            hunter: the Hunter being controlled (its cell, memory and plan).
            world: the World, giving access to the arena, player, predictor and rng.

        Returns:
            The next cell to move to, or None to stay put.
        """
        raise NotImplementedError

    @staticmethod
    def _follow(hunter, world, goal):
        """Plan an A* path to `goal` and return its first step.

        Also stores the plan, target and number of expanded nodes on the hunter so
        AI Vision and the side panel can show what it is thinking.

        Args:
            hunter: the Hunter being controlled.
            world: the World (for the arena's neighbours).
            goal: the cell to head for.

        Returns:
            The next cell on the path, or None if the hunter is already there or
            the goal is unreachable.
        """
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
        """Create a random-walk brain.

        Args:
            drift: probability (0..1) of taking a greedy step towards the player
                instead of a random one; 0 gives a pure random walk.
        """
        self.drift = drift

    def decide(self, hunter, world):
        """Random walk: keep going straight most of the time, sometimes drift to the player.

        Args:
            hunter: the Hunter being controlled.
            world: the World (arena, rng, and the goal cell for drift steps).

        Returns:
            The next cell, or None if the hunter is boxed in.
        """
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
        """Take one greedy hill-climbing step towards the player.

        Args:
            hunter: the Hunter being controlled (its previous cell is avoided).
            world: the World (arena, rng and goal cell).

        Returns:
            The next cell, or None if it has nowhere to go.
        """
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
        """Follow the A* shortest path to the player's current cell.

        Args:
            hunter: the Hunter being controlled.
            world: the World (arena and goal cell).

        Returns:
            The next cell on the shortest path.
        """
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
        """Forecast the player with the Markov model and move to intercept.

        Evaluates each forecast cell: the first one the hunter can reach before the
        player is chosen; otherwise the one where it arrives least late. Close to
        the player, or when a decoy is active, it simply chases with A*.

        Args:
            hunter: the Hunter being controlled (its forecast is stored for AI Vision).
            world: the World (player, predictor, arena and step times).

        Returns:
            The next cell on the A* path to the chosen interception cell.
        """
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
        """Score every legal move from `cell` and return the best one.

        score(m) = log P_you(m | history) - BETA * (change in distance to the goal),
        so the chosen move is the one that looks most like the player's habits while
        getting closer to the player - the move "closest to victory".

        Args:
            cell: the cell the mirror is deciding from.
            history: the mirror's own recent moves, used as the Markov context.
            world: the World (arena and the player's predictor).
            dist: BFS distance map from the goal cell (from Arena.distances).

        Returns:
            The best move ("U", "R", "D" or "L"), or None if no move is possible.
        """
        arena = world.arena
        moves = [m for m in arena.moves(cell) if arena.step(cell, m) in dist]
        if not moves:
            return None
        probs = world.predictor.distribution(moves, history=history)
        here = dist.get(cell, 0)

        def score(m):
            """Score of move `m`: habit log-probability minus BETA times the change in distance to the goal."""
            gain = dist[arena.step(cell, m)] - here
            return math.log(probs[m]) - self.BETA * gain

        return max(moves, key=lambda m: (score(m), -"URDL".index(m)))

    def decide(self, hunter, world):
        """Move like the player would, but towards the player.

        Also simulates the next PLAN_STEPS moves of the same policy so AI Vision can
        draw where the mirror is going.

        Args:
            hunter: the Hunter being controlled (its memory holds its last moves).
            world: the World (arena, goal cell and predictor).

        Returns:
            The next cell, or None if it cannot move.
        """
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
    """Create a fresh brain object from its id.

    Args:
        brain_id: one of "wanderer", "greedy", "astar", "mindreader", "mirror".

    Returns:
        A new Brain instance.
    """
    return BRAINS[brain_id]()
