"""Tests for taunts, surprise/chaos, kill-cam, the Mirror, player types and saving."""

import random

from game import config as C
from game import profile, storage, taunts
from game.ai.brains import Mirror, Wanderer
from game.ai.predictor import MarkovPredictor
from game.entities import Hunter
from game.grid import Arena
from game.world import World


def open_world(seed=1, level=4):
    """A world on an empty arena (every inner cell is a junction), intro skipped."""
    w = World(seed=seed)
    w.start_level(level)
    w.arena = Arena(C.COLS, C.ROWS)
    w.player.place(w.arena.center)
    for h, corner in zip(w.hunters, w.arena.corners):
        h.place(corner)
    w.orb = None
    w.powerup_timer = 1e9
    w.phase = "play"
    w.pop_events()
    return w


def train(predictor, move="R", n=30):
    for _ in range(n):
        predictor.observe(move)


def step_player(w, direction):
    """Advance frames until the player has taken exactly one step."""
    start = w.player.cell
    w.steer(direction)
    for _ in range(60):
        w.update(1 / 60)
        if w.player.cell != start:
            return
    raise AssertionError("player did not move")


# ------------------------------------------------------------------ taunts
def test_taunt_lines_fill_fields_and_fall_back():
    rng = random.Random(0)
    for _ in range(50):
        text = taunts.line("called_it", rng, move="LEFT")
        assert "{" not in text
    for _ in range(50):                      # missing field -> a line without fields
        assert "{" not in taunts.line("streak", rng)


def test_every_brain_has_an_opener():
    from game.ai.brains import BRAINS
    for brain_id in BRAINS:
        assert ("opener_" + brain_id) in taunts.LINES


def test_death_line_uses_real_habits():
    p = MarkovPredictor()
    for _ in range(4):
        for m in "UUL":
            p.observe(m)
    line = taunts.death_line(p, random.Random(0))
    assert "LEFT after UP" in line and "times" in line


def test_opener_taunt_when_level_starts():
    w = World(seed=2)
    for _ in range(int(C.INTRO_TIME * 60) + 5):
        w.update(1 / 60)
    assert any(ev[0] == "taunt" for ev in w.pop_events())


def test_streak_taunt_when_player_is_predictable():
    w = open_world()
    train(w.predictor, "R")
    w.freeze_timer = 1e9                     # hunters stay put
    w.player.place((1, C.ROWS // 2))
    events = []
    for _ in range(8):
        step_player(w, "R")
        events += w.pop_events()
    assert any(ev[0] == "taunt" for ev in events)
    assert w.junction_streak >= 6


# --------------------------------------------------------- surprise & chaos
def test_predictor_observe_returns_guess_and_confidence():
    p = MarkovPredictor()
    train(p, "R", 20)
    guess, conf = p.observe("U")
    assert guess == "R" and conf > 0.5


def test_surprise_gives_points_and_chaos():
    w = open_world()
    train(w.predictor, "R")
    score = w.score
    step_player(w, "U")
    events = w.pop_events()
    assert any(ev[0] == "surprise" for ev in events)
    assert w.score == score + C.SURPRISE_POINTS
    assert abs(w.chaos - C.CHAOS_PER_SURPRISE) < 1e-6 and w.surprises == 1


def test_no_surprise_before_model_is_trained():
    w = open_world()
    step_player(w, "U")
    assert w.surprises == 0


def test_surprise_cooldown_limits_spam():
    w = open_world()
    train(w.predictor, "R", 200)
    step_player(w, "U")
    w.surprise_cooldown = 10
    step_player(w, "L")
    assert w.surprises == 1


def test_full_chaos_meter_confuses_hunters():
    w = open_world()
    train(w.predictor, "R")
    w.chaos = 1.0 - C.CHAOS_PER_SURPRISE + 0.01   # a little extra: the meter decays each frame
    step_player(w, "U")
    events = w.pop_events()
    assert w.confused and w.chaos == 0.0
    assert any(ev[0] == "confused" for ev in events)
    for _ in range(60):                      # confused hunters move randomly without errors
        w.update(1 / 60)
        assert all(h.forecast == [] for h in w.hunters)


def test_chaos_decays_over_time():
    w = open_world()
    w.chaos = 0.5
    w.freeze_timer = 1e9
    for _ in range(60):
        w.update(1 / 60)
    assert w.chaos < 0.5


# ---------------------------------------------------------------- kill-cam
def test_death_goes_through_killcam_then_over():
    w = open_world(level=3)
    w.hunters[0].place(w.arena.step(w.player.cell, "R"))
    phases = set()
    for _ in range(int((C.DEATH_TIME + C.KILLCAM_TIME + 2) * 60)):
        w.update(1 / 60)
        phases.add(w.phase)
        if w.phase == "over":
            break
    assert {"dead", "killcam", "over"} <= phases
    kc = w.killcam
    assert kc["caption"] and kc["sub"] and kc["quote"]
    assert kc["path"] and kc["catch"] == w.player.cell
    assert w.summary()["quote"] == kc["quote"]


def test_killcam_can_be_skipped():
    w = open_world(level=3)
    w.hunters[0].place(w.arena.step(w.player.cell, "R"))
    for _ in range(120):
        w.update(1 / 60)
        if w.phase == "dead":
            break
    w.skip_killcam()
    assert w.phase == "over"
    assert any(ev[0] == "game_over" for ev in w.pop_events())


def test_killcam_reports_how_early_it_was_predicted():
    w = open_world(level=4)
    h = w.hunters[0]
    now = w.predictor.total_observed
    forecast = (w.arena.step(w.player.cell, "R"), w.player.cell)
    h.seen = {w.player.cell: (now - 5, forecast)}
    kc = w._build_killcam(h)
    assert kc["caption"] == "IT SAW THIS COMING 5 MOVES AGO"
    assert kc["forecast"] == list(forecast)


def test_hunter_remembers_forecast_until_contact():
    w = open_world(level=4)
    train(w.predictor, "R")
    h = w.hunters[0]
    h.forecast = [(3, 3), (4, 3)]
    h._remember_forecast(w)
    first = dict(h.seen)
    h.forecast = []                          # close range: no new forecast...
    h._remember_forecast(w)
    assert h.seen == first                   # ...but the earlier prediction is kept


# ------------------------------------------------------------------ mirror
def test_mirror_hunts_a_still_player():
    w = open_world(level=6)
    w.hunters = [h for h in w.hunters if h.brain.id == "mirror"]
    for _ in range(60 * 12):
        w.update(1 / 60)
        if w.phase != "play":
            break
    assert w.phase in ("dead", "killcam")


def test_mirror_copies_habits_when_moves_are_equally_good():
    for habit in ("R", "D"):
        w = open_world(level=6)
        train(w.predictor, habit, 40)
        w.player.place((10, 10))
        mirror = Hunter((5, 5), 0.2, Mirror(), C.MIRROR_C)
        nxt = mirror.brain.decide(mirror, w)
        assert nxt == w.arena.step((5, 5), habit)   # R and D both get closer; habit decides
        assert mirror.plan and mirror.memory == [habit]


def test_wanderer_drift_and_pure_random():
    w = open_world(level=1)
    h = w.hunters[0]
    h.place((2, 6))
    w.player.place((12, 6))
    chaser = Wanderer(drift=1.0)
    before = abs(h.cell[0] - 12)
    nxt = chaser.decide(h, w)
    assert abs(nxt[0] - 12) < before
    rand = Wanderer(drift=0.0)
    for _ in range(50):
        assert w.arena.passable(rand.decide(h, w))


def test_danger_rises_when_hunter_is_close():
    w = open_world(level=3)
    w.freeze_timer = 0
    w.hunters[0].place((w.player.cell[0] + 2, w.player.cell[1]))
    w.hunters[0].timer = -10                 # keep it still
    for _ in range(30):
        w.update(1 / 60)
    assert w.danger > 0.3


# ------------------------------------------------------------ player types
def summary(**kw):
    base = {"moves": 50, "accuracy": 0.6, "close_calls": 0, "surprises": 0, "straight": 0.5,
            "turns_total": 10, "favourite_share": 0.2, "favourite_turn": ("U", "L")}
    base.update(kw)
    return base


def test_player_types():
    assert profile.classify(summary(moves=5)) == "mystery"
    assert profile.classify(summary(accuracy=0.3)) == "gremlin"
    assert profile.classify(summary(close_calls=3)) == "daredevil"
    assert profile.classify(summary(surprises=8)) == "zigzag"
    assert profile.classify(summary(accuracy=0.8)) == "habit"
    assert profile.classify(summary(straight=0.75)) == "express"
    assert profile.classify(summary(favourite_share=0.5)) == "loyalist"
    assert profile.classify(summary()) == "strategist"
    # regression: a very readable player is never called a zigzagger (81% read, many surprises)
    assert profile.classify(summary(accuracy=0.81, surprises=47, moves=390)) == "habit"
    assert profile.classify(summary(accuracy=0.7, surprises=60)) != "zigzag"


def test_loyalist_name_uses_turn_direction():
    name, _, _ = profile.describe("loyalist", summary(favourite_turn=("U", "R")))
    assert name == "THE RIGHT-TURN LOYALIST"
    for type_id in profile.TYPES:
        name, tagline, colour = profile.describe(type_id, summary())
        assert "{" not in name and tagline and len(colour) == 3


def test_world_summary_has_everything_the_card_needs():
    w = open_world()
    s = w.summary()
    for key in ("score", "time", "orbs", "level", "level_name", "accuracy", "moves", "straight",
                "favourite_turn", "favourite_share", "turns_total", "close_calls", "surprises",
                "quote"):
        assert key in s
    assert profile.classify(s) in profile.TYPES


# ---------------------------------------------------------------- storage
def test_storage_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DESKTOP_FILE", str(tmp_path / "save.json"))
    assert storage.load() == {"best": 0, "runs": [], "types": []}
    storage.save({"best": 1234, "runs": [{"accuracy": 0.5}], "types": ["habit"]})
    data = storage.load()
    assert data["best"] == 1234 and data["types"] == ["habit"] and len(data["runs"]) == 1


def test_storage_survives_corrupt_file(tmp_path, monkeypatch):
    bad = tmp_path / "save.json"
    bad.write_text("{not json")
    monkeypatch.setattr(storage, "DESKTOP_FILE", str(bad))
    assert storage.load() == {"best": 0, "runs": [], "types": []}
