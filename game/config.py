"""Global constants: screen layout, colours, timings and the level table.

Keeping every tunable number in one file makes the game easy to balance and
lets the tests and the experiment script reuse exactly the same settings.
"""

from dataclasses import dataclass

# Author details (the brief asks for name + student ID on every component)
AUTHOR = "Balasubramanian Ayyappan"
STUDENT_ID = "3073JDDJ"

# Support / feedback form (hosted on Vercel; reports are stored privately and synced to the Mac)
SUPPORT_URL = "https://predictable-pi.vercel.app/support"

# --------------------------------------------------------------------------
# Screen layout (logical pixels; the web build scales the canvas to fit)
# --------------------------------------------------------------------------
COLS, ROWS = 17, 13          # arena size in cells (odd numbers -> a true centre)
CELL = 40                    # cell size in pixels
FPS = 60
ARENA_W, ARENA_H = COLS * CELL, ROWS * CELL

# Three layouts share the same arena; only the screen around it changes.
#   desktop   - 1000x620, keyboard
#   landscape - 1000x684, phone held sideways: swipe + a bar of touch buttons
#   portrait  - 720x1280, phone held upright: info cards below the arena + a D-pad
LAYOUTS = ("desktop", "landscape", "portrait")
LAYOUT = "desktop"
TOUCH = False
PORTRAIT = False
WIDTH, HEIGHT = 1000, 620
ARENA_X, ARENA_Y = 20, 80
CARD_BRAIN = CARD_MODEL = CARD_ACC = (0, 0, 0, 0)


def apply_layout(name: str):
    """Switch every screen-position constant to the given layout.

    Args:
        name: "desktop" (1000x620, keyboard), "landscape" (1000x684, phone held
            sideways with a touch bar) or "portrait" (720x1280 with a D-pad).
            Unknown names fall back to "desktop".
    """
    global LAYOUT, TOUCH, PORTRAIT, WIDTH, HEIGHT, ARENA_X, ARENA_Y
    global CARD_BRAIN, CARD_MODEL, CARD_ACC
    if name not in LAYOUTS:
        name = "desktop"
    LAYOUT, TOUCH, PORTRAIT = name, name != "desktop", name == "portrait"
    if PORTRAIT:
        WIDTH, HEIGHT = 720, 1280
        ARENA_X, ARENA_Y = 20, 150
        top = ARENA_Y + ARENA_H + 16                       # 686
        CARD_BRAIN = (20, top, 330, 170)
        CARD_ACC = (370, top, 330, 170)
        CARD_MODEL = (20, top + 180, 680, 140)             # ends at 1006; D-pad below
    else:
        WIDTH, HEIGHT = 1000, (684 if TOUCH else 620)
        ARENA_X, ARENA_Y = 20, 80
        px = ARENA_X + ARENA_W + 20
        CARD_BRAIN = (px, ARENA_Y, 260, 170)
        CARD_MODEL = (px, ARENA_Y + 180, 260, 200)
        CARD_ACC = (px, ARENA_Y + 390, 260, ARENA_H - 390)


apply_layout("desktop")

# --------------------------------------------------------------------------
# Colour palette (neon on deep navy)
# --------------------------------------------------------------------------
BG = (7, 10, 20)
ARENA_BG = (12, 17, 32)
GRID_DOT = (32, 42, 72)
CARD_BG = (15, 21, 40)
CARD_EDGE = (34, 44, 78)
WALL = (36, 46, 84)
WALL_TOP = (58, 72, 128)
WALL_EDGE = (82, 102, 176)

TEXT = (232, 238, 255)
MUTED = (128, 140, 182)
DIM = (74, 84, 120)

PLAYER = (64, 226, 255)
HUNTER = (255, 62, 128)
HUNTER_2 = (255, 150, 52)
ORB = (178, 255, 90)
FREEZE_C = (110, 190, 255)
DECOY_C = (190, 130, 255)
SHIELD_C = (255, 214, 84)
MIRROR_C = (236, 238, 255)
CHAOS_C = (176, 120, 255)
GOOD = (110, 240, 160)
WARN = (255, 196, 80)

# --------------------------------------------------------------------------
# Movement directions
# --------------------------------------------------------------------------
DIRS = {"U": (0, -1), "R": (1, 0), "D": (0, 1), "L": (-1, 0)}
DIR_ORDER = ("U", "R", "D", "L")
OPPOSITE = {"U": "D", "D": "U", "L": "R", "R": "L"}

# --------------------------------------------------------------------------
# Timings (seconds)
# --------------------------------------------------------------------------
PLAYER_STEP = 0.125          # player moves 8 cells per second
INTRO_TIME = 2.0             # level banner, hunters paused
CLEAR_TIME = 1.3             # "level clear" celebration
DEATH_TIME = 1.0             # explosion before the kill-cam replay
COMBO_WINDOW = 4.0           # collect orbs within this window to grow the combo
MAX_COMBO = 5
FREEZE_TIME = 3.0
DECOY_TIME = 4.0
POWERUP_LIFETIME = 8.0
POWERUP_MIN_GAP, POWERUP_MAX_GAP = 9.0, 14.0
CLOSE_CALL_COOLDOWN = 2.0
KILLCAM_TIME = 3.6           # replay shown after being caught (skippable)
TAUNT_COOLDOWN = 4.5         # minimum gap between hunter speech bubbles
TAUNT_TIME = 2.0             # how long a speech bubble stays up
CONFUSE_TIME = 2.5           # hunters wander randomly when the chaos meter fills
CATCH_DISTANCE = 0.6         # caught when the sprites are this close (in cells)

# Scoring
ORB_POINTS = 100
CLOSE_CALL_POINTS = 50
LEVEL_BONUS = 500
SURPRISE_POINTS = 25

# Chaos meter: surprising the AI fills it; when full the hunters get confused
CHAOS_PER_SURPRISE = 0.2
CHAOS_DECAY = 0.04           # per second
SURPRISE_MIN_CONFIDENCE = 0.4   # the AI must have been fairly sure to count as a surprise
SURPRISE_COOLDOWN = 0.35
MIN_TRAINING = 20            # moves the model needs before surprises count

# Prediction / interception
PREDICT_ORDER = 2            # Markov chain order (uses the last 2 moves)
LOOKAHEAD = 8                # how far ahead the Mind Reader forecasts the player


@dataclass(frozen=True)
class Level:
    number: int
    name: str
    technique: str
    blurb: str
    brains: tuple            # one brain id per hunter
    orbs: int                # orbs needed to clear the level
    hunter_step: float       # seconds per hunter move (lower = faster)


LEVELS = (
    Level(1, "WANDERER", "Random walk",
          "Moves randomly. Learn the controls.", ("wanderer",), 3, 0.24),
    Level(2, "CHASER", "Greedy hill-climbing",
          "Always steps closer. Walls trap it.", ("greedy",), 6, 0.19),
    Level(3, "TRACKER", "A* pathfinding",
          "Finds the shortest path to you.", ("astar",), 7, 0.18),
    Level(4, "MIND READER", "A* + Markov prediction",
          "Predicts where you'll be, then cuts you off.", ("mindreader",), 8, 0.18),
    Level(5, "THE PACK", "Multi-agent: chase + intercept",
          "One hunts you, one ambushes you.", ("astar", "mindreader"), 10, 0.20),
    Level(6, "THE MIRROR", "Generative model of YOU",
          "An AI copy that moves with your habits.", ("mirror", "astar"), 10, 0.20),
)


def level_config(n: int) -> Level:
    """Return the settings for level `n`.

    Args:
        n: level number, starting at 1.

    Returns:
        The Level tuple (name, AI label, description, hunter brains, orbs to
        collect, hunter step time). After the Mirror (level 6) the endless
        Gauntlet levels keep getting faster.
    """
    if n <= len(LEVELS):
        return LEVELS[n - 1]
    step = max(0.15, 0.19 - 0.01 * (n - len(LEVELS) - 1))
    return Level(n, "THE GAUNTLET", "Mind Reader + Mirror",
                 "Endless mode. They only get faster.", ("mindreader", "mirror"), 10, step)
