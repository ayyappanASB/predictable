"""What the hunters say. Every taunt is triggered by the real AI state, so the
jokes double as a live explanation of what the Markov model has learned."""

DIR_WORDS = {"U": "UP", "R": "RIGHT", "D": "DOWN", "L": "LEFT"}

LINES = {
    "called_it": (
        "Called it.",
        "I knew you'd go {move}.",
        "{move} again? Classic.",
        "Predictable.",
        "Saw that coming.",
        "Your habits are showing.",
        "Too easy to read.",
    ),
    "streak": (
        "You're SO predictable.",
        "{n} moves in a row. I know you.",
        "Are you even trying to surprise me?",
        "I could do this with my eyes closed.",
    ),
    "surprise": (
        "Wait, WHAT?",
        "That wasn't in my model...",
        "Hmm. Interesting.",
        "Updating my beliefs...",
        "Okay, you got me there.",
        "Unexpected move detected.",
    ),
    "close_call": ("So close!", "Next time.", "Lucky.", "I felt that.", "Grr."),
    "confused": ("Error: human too random", "My model is melting!", "WHERE DID YOU GO?",
                 "???", "Recalculating..."),
    "shield": ("A shield?! Rude.", "Not fair!"),
    "decoy": ("Wait... there are two of you?", "Which one is real?!"),
    "freeze": ("C-c-cold...", "I can't m-move..."),
    "opener_wanderer": ("I'm just vibing.", "La la la..."),
    "opener_greedy": ("I go where you are. Simple.",),
    "opener_astar": ("I always find the shortest path.",),
    "opener_mindreader": ("I've been studying you.", "Let's see how predictable you are."),
    "opener_mirror": ("I learned to move like you. Hello, me.",),
    "gotcha": ("Gotcha.", "Tag. You're it.", "Was that the plan?"),
}


def line(kind, rng, **fmt):
    """Pick a random line of the given kind and fill in its fields.

    Args:
        kind: key into LINES, e.g. "called_it" or "opener_astar".
        rng: random.Random used to choose the line.
        **fmt: values for the {fields} in the line, e.g. move="LEFT", n=6.

    Returns:
        The finished text; if a needed field is missing, a line without fields.
    """
    options = LINES[kind]
    text = rng.choice(options)
    try:
        return text.format(**fmt)
    except (KeyError, IndexError):
        # a line needing a field we were not given: use one that needs none
        plain = [o for o in options if "{" not in o]
        return rng.choice(plain) if plain else text


def death_line(predictor, rng):
    """A personalised line using the habits the model actually found.

    Args:
        predictor: the MarkovPredictor with this run's turn statistics.
        rng: random.Random for the fallback line.

    Returns:
        e.g. "You turned RIGHT after UP 10 times. I noticed."
    """
    if predictor.turns:
        (prev, move), count = predictor.turns.most_common(1)[0]
        if count >= 3:
            return f"You turned {DIR_WORDS[move]} after {DIR_WORDS[prev]} {count} times. I noticed."
    if predictor.run_total >= 10 and predictor.straight_ratio >= 0.6:
        return f"You went straight {predictor.straight_ratio * 100:.0f}% of the time. Easy."
    return line("gotcha", rng)
