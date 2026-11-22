"""Tests for the arena generator and the game rules (run headless)."""

import random

import pytest

from game import config as C
from game.grid import generate_arena, _protected
from game.world import World


# ------------------------------------------------------------------ arena
@pytest.mark.parametrize("seed", range(60))
def test_generated_arenas_are_playable(seed):
    """Generated arenas are connected, have no dead ends, keep spawn cells free and have walls.

    Args:
        seed: random seed for the arena (60 different arenas).
    """
    arena = generate_arena(C.COLS, C.ROWS, random.Random(seed))
    assert arena.is_connected()
    assert not arena.has_dead_ends()
    assert not (_protected(C.COLS, C.ROWS) & arena.walls)
    assert len(arena.walls) > 10


def test_arena_is_mirror_symmetric():
    """Every wall has its mirror image left-right and top-bottom."""
    arena = generate_arena(C.COLS, C.ROWS, random.Random(5))
    for (c, r) in arena.walls:
        assert (C.COLS - 1 - c, r) in arena.walls
        assert (c, C.ROWS - 1 - r) in arena.walls


def test_generation_is_deterministic_per_seed():
    """The same seed always produces the same arena."""
    a = generate_arena(C.COLS, C.ROWS, random.Random(9))
    b = generate_arena(C.COLS, C.ROWS, random.Random(9))
    assert a.walls == b.walls


# ------------------------------------------------------------------- world
def skip_intro(world):
    """Jump `world` straight past the level intro into the play phase."""
    world.phase = "play"
    world.phase_timer = 0


def test_new_world_starts_on_level_one():
    """A new world starts on level 1 in the intro, player in the centre, one hunter and an orb."""
    w = World(seed=1)
    assert w.level_no == 1 and w.phase == "intro"
    assert w.player.cell == w.arena.center
    assert w.orb is not None and w.arena.passable(w.orb.cell)
    assert len(w.hunters) == 1


def test_hunters_pause_during_intro():
    """Hunters do not move while the level intro banner is showing."""
    w = World(seed=1)
    start = [h.cell for h in w.hunters]
    for _ in range(int(C.INTRO_TIME * 30)):
        w.update(1 / 60)
    assert [h.cell for h in w.hunters] == start


def test_player_moves_and_stops_at_walls():
    """The player keeps moving in the steered direction until a wall blocks it."""
    w = World(seed=2)
    skip_intro(w)
    w.hunters = []
    w.steer("R")
    for _ in range(400):
        w.update(1 / 60)
    c, r = w.player.cell
    # kept going right until something blocked it
    assert not w.arena.passable((c + 1, r))
    assert w.predictor.run_total > 0


def test_collecting_orb_scores_and_respawns():
    """Collecting an orb adds points and spawns the next orb elsewhere."""
    w = World(seed=3)
    skip_intro(w)
    w.hunters = []
    target = w.arena.step(w.player.cell, "R")
    w.orb.cell = target
    w.steer("R")
    w.update(C.PLAYER_STEP + 0.001)
    assert w.orbs_level == 1 and w.score == C.ORB_POINTS
    assert w.orb is not None and w.orb.cell != target


def test_combo_multiplies_points():
    """Quick consecutive orbs multiply the points (100, then +200)."""
    w = World(seed=3)
    skip_intro(w)
    w.hunters = []
    for expected in (100, 300):       # 100*1 then +100*2
        w.orb.cell = w.arena.step(w.player.cell, w.arena.moves(w.player.cell)[0])
        w.steer(w.arena.moves(w.player.cell)[0])
        for _ in range(3):
            w.update(C.PLAYER_STEP / 2)
            if w.score >= expected:
                break
        assert w.score == expected


def run_until(world, cond, seconds=3.0, dt=1 / 60):
    """Update `world` until `cond()` is true or time runs out.

    Args:
        world: the World to simulate.
        cond: function returning True when the wanted state is reached.
        seconds: maximum simulated time.
        dt: frame time in seconds.

    Returns:
        True if the condition was reached in time.
    """
    for _ in range(int(seconds / dt)):
        world.update(dt)
        if cond():
            return True
    return False


def test_caught_when_hunter_reaches_player():
    """An A* hunter next to the player catches it."""
    w = World(seed=4)
    w.start_level(3)                  # A* hunter: always steps towards the player
    skip_intro(w)
    h = w.hunters[0]
    move = w.arena.moves(w.player.cell)[0]
    h.place(w.arena.step(w.player.cell, move))
    assert run_until(w, lambda: w.phase == "dead", 1.0)


def test_not_caught_before_sprites_touch():
    """The hunter may *logically* enter your cell, but you are only caught on visual contact."""
    w = World(seed=4)
    w.start_level(3)
    skip_intro(w)
    h = w.hunters[0]
    move = w.arena.moves(w.player.cell)[0]
    h.place(w.arena.step(w.player.cell, move))
    h.timer = h.step_time
    w.update(0.001)                   # hunter steps: logically on the player's cell
    assert h.cell == w.player.cell
    assert w.phase == "play"          # ...but it is still visually a full cell away
    assert run_until(w, lambda: w.phase == "dead", 0.5)


def test_head_on_crossing_is_caught():
    """Player and hunter walking through each other cannot tunnel past."""
    w = World(seed=4)
    w.start_level(3)
    skip_intro(w)
    move = w.arena.moves(w.player.cell)[0]
    h = w.hunters[0]
    h.place(w.arena.step(w.player.cell, move))
    w.player.facing = move
    w.player.timer = w.player.step_time
    assert run_until(w, lambda: w.phase == "dead", 0.6, dt=0.05)   # worst-case frame time


def test_shield_saves_once():
    """A shield absorbs one catch, breaks, and sends the hunter away."""
    w = World(seed=5)
    skip_intro(w)
    w.shield = True
    h = w.hunters[0]
    h.place(w.player.cell)
    w._check_caught()
    assert w.phase == "play" and not w.shield
    assert h.cell != w.player.cell
    assert any(ev[0] == "shield_break" for ev in w.pop_events())


def test_freeze_stops_hunters():
    """Hunters do not move while Freeze is active."""
    w = World(seed=6)
    skip_intro(w)
    w.freeze_timer = 1.0
    start = [h.cell for h in w.hunters]
    for _ in range(30):
        w.update(1 / 60)
    assert [h.cell for h in w.hunters] == start


def test_decoy_redirects_hunters():
    """While a decoy is active the hunters chase the decoy cell instead of the player."""
    w = World(seed=7)
    skip_intro(w)
    w.decoy_timer, w.decoy_cell = 3.0, w.arena.corners[0]
    assert w.hunter_goal() == w.arena.corners[0]


def test_level_clear_advances_level():
    """Collecting all orbs clears the level and starts the next one."""
    w = World(seed=8)
    skip_intro(w)
    w.hunters = []
    w.orbs_level = w.level.orbs
    w.update(0.01)
    assert w.phase == "clear"
    for _ in range(200):
        w.update(1 / 60)
    assert w.level_no == 2 and len(w.hunters) == 1


def test_levels_unlock_each_brain():
    """Each level uses the intended AI brains and the Gauntlet speeds up (with a cap)."""
    ids = [tuple(C.level_config(n).brains) for n in range(1, 8)]
    assert ids[0] == ("wanderer",) and ids[1] == ("greedy",)
    assert ids[2] == ("astar",) and ids[3] == ("mindreader",)
    assert ids[4] == ("astar", "mindreader")
    assert ids[5] == ("mirror", "astar")
    assert ids[6] == ("mindreader", "mirror")
    assert C.level_config(10).hunter_step < C.level_config(7).hunter_step
    assert C.level_config(50).hunter_step >= 0.15


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5, 6, 7, 9])
def test_long_random_play_never_crashes(level):
    """Fuzz test: random input for a minute of game time on every level.

    Checks that nothing crashes and nobody ever stands inside a wall.

    Args:
        level: level number to play (1-7 and 9).
    """
    rng = random.Random(level)
    w = World(seed=level)
    w.start_level(level)
    for frame in range(3600):
        if frame % 7 == 0:
            w.steer(rng.choice("URDL"))
        w.update(1 / 60)
        for ev in w.pop_events():
            assert isinstance(ev, tuple)
        # invariants
        assert w.arena.passable(w.player.cell)
        for h in w.hunters:
            assert w.arena.passable(h.cell)
        if w.orb:
            assert w.arena.passable(w.orb.cell)
        if w.phase == "over":
            break
    assert w.summary()["level"] >= 1
