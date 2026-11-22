"""Player types: a fun personality label for the end-of-run card.

The label comes from the same statistics the AI collected during the run, so
it is a playful summary of how the Markov model sees the player.
"""

from .taunts import DIR_WORDS

TYPES = {
    "mystery": ("THE MYSTERY", "Gone before the AI could learn you.", (150, 160, 200)),
    "gremlin": ("THE CHAOS GREMLIN", "Pure randomness. The model has a headache.", (176, 120, 255)),
    "daredevil": ("THE DAREDEVIL", "Lives for close calls. Respect.", (255, 150, 52)),
    "zigzag": ("THE ZIGZAG GOBLIN", "Keeps surprising the model. Annoying!", (110, 240, 160)),
    "habit": ("THE CREATURE OF HABIT", "Same moves, every time. The AI loves you.", (255, 62, 128)),
    "express": ("THE STRAIGHT-LINE EXPRESS", "Why turn when you can go straight?", (255, 196, 80)),
    "loyalist": ("THE {DIR}-TURN LOYALIST", "You have a favourite turn. It noticed.", (64, 226, 255)),
    "strategist": ("THE STRATEGIST", "Balanced and hard to pin down.", (232, 238, 255)),
}
ORDER = tuple(TYPES)


def classify(summary: dict) -> str:
    """Return the player-type id for a finished run (rules are checked in priority order).

    Args:
        summary: the dict from World.summary() (moves, accuracy, close_calls,
            surprises, straight, turns_total, favourite_share).

    Returns:
        One of the keys of TYPES, e.g. "habit" or "gremlin".
    """
    moves = summary.get("moves", 0)
    if moves < 12:
        return "mystery"
    acc = summary.get("accuracy", 0.0)
    if acc < 0.35:
        return "gremlin"
    if acc >= 0.75:                       # mostly predictable: that wins over everything else
        return "habit"
    if summary.get("close_calls", 0) >= 3:
        return "daredevil"
    if acc < 0.65 and summary.get("surprises", 0) / moves >= 0.12:
        return "zigzag"
    if summary.get("straight", 0.0) >= 0.7:
        return "express"
    if summary.get("turns_total", 0) >= 5 and summary.get("favourite_share", 0.0) >= 0.4:
        return "loyalist"
    return "strategist"


def describe(type_id: str, summary: dict):
    """Name, tagline and colour of a player type, with dynamic parts filled in.

    Args:
        type_id: a key of TYPES.
        summary: the run summary, used for the favourite turn of the Loyalist.

    Returns:
        (name, tagline, colour) tuple.
    """
    name, tagline, colour = TYPES[type_id]
    if "{DIR}" in name:
        fav = summary.get("favourite_turn")
        name = name.replace("{DIR}", DIR_WORDS[fav[1]] if fav else "LEFT")
    return name, tagline, colour
