"""Unit tests for the AI: A* search, greedy step and the Markov predictor."""

import random
from collections import deque

import pytest

from game.ai.astar import astar, greedy_step, manhattan
from game.ai.predictor import MarkovPredictor
from game.grid import Arena, generate_arena


def bfs_length(arena, start, goal):
    return arena.distances(start).get(goal)


# ---------------------------------------------------------------------- A*
def test_astar_straight_line():
    arena = Arena(10, 5)
    res = astar((0, 2), (9, 2), arena.neighbors)
    assert res.found
    assert res.path[0] == (0, 2) and res.path[-1] == (9, 2)
    assert len(res.path) - 1 == 9


def test_astar_start_is_goal():
    arena = Arena(5, 5)
    res = astar((2, 2), (2, 2), arena.neighbors)
    assert res.path == [(2, 2)] and res.cost == 0


def test_astar_goes_around_wall():
    walls = {(3, r) for r in range(0, 4)}     # wall with a gap at the bottom row
    arena = Arena(7, 5, walls)
    res = astar((0, 0), (6, 0), arena.neighbors)
    assert res.found
    assert not any(cell in walls for cell in res.path)
    assert len(res.path) - 1 == bfs_length(arena, (0, 0), (6, 0))


def test_astar_unreachable_returns_empty():
    walls = {(2, r) for r in range(5)}
    arena = Arena(5, 5, walls)
    res = astar((0, 0), (4, 4), arena.neighbors)
    assert not res.found and res.path == []


def test_astar_path_is_valid_and_contiguous():
    arena = generate_arena(17, 13, random.Random(3))
    res = astar((0, 0), (16, 12), arena.neighbors)
    for a, b in zip(res.path, res.path[1:]):
        assert manhattan(a, b) == 1
        assert arena.passable(b)


@pytest.mark.parametrize("seed", range(25))
def test_astar_is_optimal_on_random_arenas(seed):
    rng = random.Random(seed)
    arena = generate_arena(17, 13, rng)
    free = arena.free_cells()
    for _ in range(10):
        a, b = rng.choice(free), rng.choice(free)
        res = astar(a, b, arena.neighbors)
        assert len(res.path) - 1 == bfs_length(arena, a, b)


def test_astar_expands_fewer_nodes_than_bfs():
    arena = Arena(30, 30)
    res = astar((0, 0), (29, 29), arena.neighbors)
    # an uninformed BFS explores the whole 900-cell grid for this corner-to-corner query
    assert res.expanded < 900


def test_astar_respects_costs():
    arena = Arena(3, 3)
    expensive = {(1, 1)}
    res = astar((0, 1), (2, 1), arena.neighbors,
                cost=lambda a, b: 50 if b in expensive else 1)
    assert (1, 1) not in res.path


# ------------------------------------------------------------------ greedy
def test_greedy_moves_closer_in_open_space():
    arena = Arena(9, 9)
    rng = random.Random(0)
    nxt = greedy_step((0, 0), (5, 0), arena.neighbors, rng)
    assert manhattan(nxt, (5, 0)) < manhattan((0, 0), (5, 0))


def test_greedy_gets_stuck_behind_wall_and_moves_randomly():
    # goal directly behind a wall: no neighbour gets closer
    walls = {(2, 0), (2, 1), (2, 2)}
    arena = Arena(5, 3, walls)
    rng = random.Random(1)
    nxt = greedy_step((1, 1), (3, 1), arena.neighbors, rng)
    assert nxt in arena.neighbors((1, 1))


# --------------------------------------------------------------- predictor
def test_untrained_predictor_is_uniform():
    p = MarkovPredictor()
    dist = p.distribution()
    assert set(dist) == {"U", "R", "D", "L"}
    assert all(abs(v - 0.25) < 1e-9 for v in dist.values())


def test_distribution_sums_to_one_and_respects_valid_moves():
    p = MarkovPredictor()
    for m in "RRDDLLUU" * 5:
        p.observe(m)
    dist = p.distribution(valid=["U", "L"])
    assert set(dist) == {"U", "L"}
    assert abs(sum(dist.values()) - 1.0) < 1e-9


def test_predictor_learns_a_repeating_pattern():
    p = MarkovPredictor(order=2)
    pattern = list("RRDDLLUU")
    for m in pattern * 40:
        p.observe(m)
    p.new_run()
    for m in pattern * 10:
        p.observe(m)
    # after the context fills (2 moves) every prediction should be right
    assert p.accuracy > 0.9


def test_predictor_is_near_chance_on_random_moves():
    rng = random.Random(42)
    p = MarkovPredictor()
    for _ in range(4000):
        p.observe(rng.choice("URDL"))
    assert 0.15 < p.accuracy < 0.35


def test_order_two_beats_order_zero_on_turn_pattern():
    seq = list("RRD" * 300)          # R is most common, but D always follows RR
    o0, o2 = MarkovPredictor(order=0), MarkovPredictor(order=2)
    for m in seq:
        o0.observe(m)
        o2.observe(m)
    assert o2.accuracy > o0.accuracy + 0.25


def test_new_run_keeps_learning_but_resets_stats():
    p = MarkovPredictor()
    for m in "RRRR":
        p.observe(m)
    trained = p.total_observed
    p.new_run()
    assert p.run_total == 0 and p.history == []
    assert p.total_observed == trained
    assert p.predict() == "R"


def test_backoff_when_context_unseen():
    p = MarkovPredictor(order=2, min_count=1)
    for m in "UUUUUUU":
        p.observe(m)
    # context ('L', 'L') was never seen -> falls back to overall frequency (U)
    assert p.predict(history=["L", "L"]) == "U"


def test_rollout_follows_walls():
    arena = Arena(5, 1)            # a 1-row corridor
    p = MarkovPredictor()
    for m in "RRRR":
        p.observe(m)
    cells = p.rollout((0, 0), arena, 6)
    assert cells[:4] == [(1, 0), (2, 0), (3, 0), (4, 0)]
    assert all(arena.passable(c) for c in cells)


def test_straight_ratio_and_favourite_turn():
    p = MarkovPredictor()
    for m in "RRRRU":
        p.observe(m)
    assert abs(p.straight_ratio - 0.75) < 1e-9
    assert p.favourite_turn() == ("R", "U")
