"""The in-game user guide ("How to play"), opened with the info button or the H key.

Each page has a title, a short body text and the name of the illustration the
renderer draws for it. Numbers in the text come from config, so the guide always
matches the real game rules.
"""

from . import config as C

PAGES = (
    {"art": "welcome", "accent": C.PLAYER, "title": "WELCOME TO PREDICTABLE",
     "body": "Collect every green orb to clear the level, and don't let a hunter touch you. "
             "Easy at first - but the hunters learn how you move."},
    {"art": "controls", "accent": C.PLAYER, "title": "CONTROLS",
     "body": "Move with the arrow keys or WASD, or swipe anywhere / use the D-pad on a phone. "
             "Press a turn early and you take it at the next junction. "
             "V = AI Vision, P = pause, M = sound, H = this guide, F = support."},
    {"art": "levels", "accent": C.HUNTER, "title": "THE HUNTERS GET SMARTER",
     "body": "Every level brings a smarter AI: a random wanderer, a greedy chaser, A* pathfinding, "
             "a Mind Reader that predicts your next moves, a team of two, and the Mirror that moves like you."},
    {"art": "surprise", "accent": C.CHAOS_C, "title": "SURPRISE THE AI",
     "body": f"At junctions the AI guesses your next move. Do what it doesn't expect: +{C.SURPRISE_POINTS} "
             f"points and the CHAOS meter fills. Fill it and the hunters are confused for "
             f"{C.CONFUSE_TIME:g} seconds."},
    {"art": "powerups", "accent": C.SHIELD_C, "title": "POWER-UPS",
     "body": "From level 2, power-ups appear for a few seconds. Grab them before they blink out."},
    {"art": "vision", "accent": C.PLAYER, "title": "READ THE AI'S MIND",
     "body": "Press V (or AI VISION) to see each hunter's plan. The side cards show its guess for your "
             "next move and how much of you it has read - the lower that number, the better."},
    {"art": "caught", "accent": C.GOOD, "title": "WHEN YOU'RE CAUGHT",
     "body": "The kill-cam replays the moment and names the habit that gave you away. You also get a "
             "player type - collect all 8. The AI remembers you, so keep changing your style!"},
)

POWERUPS = (
    ("freeze", "FREEZE", f"stops hunters {C.FREEZE_TIME:g} s"),
    ("decoy", "DECOY", f"fools them {C.DECOY_TIME:g} s"),
    ("shield", "SHIELD", "saves you once"),
)
