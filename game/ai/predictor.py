"""The "Mind Reader": an n-gram Markov model of the player's moves.

The model counts how often each move (U/R/D/L) follows each short history of
previous moves. For order 2 it estimates

    P(next move | last two moves)

using Laplace (add-alpha) smoothing, and backs off to shorter histories when
a context has not been seen often enough. It learns online - every move the
player makes is an extra training example - and it keeps learning across
runs, so the hunter really does get to know the player.
"""

from collections import Counter, defaultdict

from ..config import DIR_ORDER, OPPOSITE


class MarkovPredictor:
    def __init__(self, order: int = 2, alpha: float = 0.5, min_count: int = 3):
        """Create an empty model.

        Args:
            order: length of the move history used as context (2 = last two moves).
            alpha: Laplace (add-alpha) smoothing strength, so unseen moves never
                get probability 0.
            min_count: observations a context needs before it is trusted; with
                fewer the model backs off to a shorter context.
        """
        self.order = order
        self.alpha = alpha            # Laplace smoothing strength
        self.min_count = min_count    # observations needed before trusting a context
        # counts[k][context] -> Counter of next moves, for context length k
        self.counts = [defaultdict(Counter) for _ in range(order + 1)]
        self.history = []             # moves in the current run (context)
        self.total_observed = 0       # lifetime training examples
        self.run_hits = 0
        self.run_total = 0
        self.run_straight = 0
        self.turns = Counter()        # (previous, next) for direction changes

    # ------------------------------------------------------------- lifecycle
    def new_run(self):
        """Forget the short-term context and per-run stats; keep what was learned."""
        self.history = []
        self.run_hits = self.run_total = self.run_straight = 0
        self.turns = Counter()

    # ------------------------------------------------------------- inference
    def _context(self, history, k):
        """Return the last `k` moves of a history as a hashable tuple.

        Args:
            history: list of moves ("U", "R", "D", "L").
            k: context length; 0 gives the empty context ().

        Returns:
            Tuple of the last k moves.
        """
        return tuple(history[-k:]) if k else ()

    def distribution(self, valid=DIR_ORDER, history=None) -> dict:
        """Probability of each valid next move given the recent history.

        Backs off from the longest context to the shortest one with enough data,
        then applies Laplace smoothing.

        Args:
            valid: moves that are physically possible from the current cell;
                walls are excluded so probability is only spread over real options.
            history: move history to condition on; None uses the player's own
                history for this run (the Mirror passes its own history instead).

        Returns:
            Dict move -> probability (sums to 1), or {} if no move is valid.
        """
        valid = [m for m in DIR_ORDER if m in valid]
        if not valid:
            return {}
        history = self.history if history is None else history
        # back off from the longest context to the shortest one that has data
        counter = Counter()
        for k in range(min(self.order, len(history)), -1, -1):
            seen = self.counts[k].get(self._context(history, k))
            if seen and sum(seen[m] for m in valid) >= self.min_count:
                counter = seen
                break
        total = sum(counter[m] for m in valid) + self.alpha * len(valid)
        return {m: (counter[m] + self.alpha) / total for m in valid}

    def predict(self, valid=DIR_ORDER, history=None):
        """Most likely next move (ties broken by a fixed order for determinism).

        Args:
            valid: moves that are possible from the current cell.
            history: move history to condition on; None uses the player's history.

        Returns:
            The predicted move ("U", "R", "D" or "L"), or None if nothing is valid.
        """
        dist = self.distribution(valid, history)
        if not dist:
            return None
        return max(DIR_ORDER, key=lambda m: (dist.get(m, -1), -DIR_ORDER.index(m)))

    def rollout(self, start, arena, steps: int) -> list:
        """Forecast the player's next `steps` cells by chaining predictions.

        Each predicted move is appended to a copy of the history, so later steps are
        conditioned on the earlier predictions.

        Args:
            start: the player's current cell.
            arena: the Arena, used for valid moves and for stepping between cells.
            steps: how many cells ahead to forecast.

        Returns:
            List of forecast cells (may be shorter than `steps` at a dead end).
        """
        history = list(self.history)
        cell = start
        cells = []
        for _ in range(steps):
            valid = arena.moves(cell)
            move = self.predict(valid, history)
            if move is None:
                break
            cell = arena.step(cell, move)
            history.append(move)
            cells.append(cell)
        return cells

    # -------------------------------------------------------------- learning
    def observe(self, move: str, valid=DIR_ORDER):
        """Score the prediction we would have made, then learn from the move.

        Updates the counts for every context length (online learning), the run's
        accuracy, straight-line ratio and turn statistics.

        Args:
            move: the move the player actually made.
            valid: moves that were possible at that moment (for a fair prediction).

        Returns:
            (guess, confidence): the move the model expected and the probability it
            gave that move, which the game uses for taunts and the surprise bonus.
        """
        dist = self.distribution(valid)
        guess = max(DIR_ORDER, key=lambda m: (dist.get(m, -1), -DIR_ORDER.index(m))) if dist else None
        confidence = dist.get(guess, 0.0) if guess else 0.0
        self.run_total += 1
        if guess == move:
            self.run_hits += 1
        if self.history:
            prev = self.history[-1]
            if prev == move:
                self.run_straight += 1
            elif move != OPPOSITE[prev]:
                self.turns[(prev, move)] += 1

        for k in range(0, min(self.order, len(self.history)) + 1):
            self.counts[k][self._context(self.history, k)][move] += 1
        self.history.append(move)
        self.total_observed += 1
        return guess, confidence

    # ----------------------------------------------------------------- stats
    @property
    def accuracy(self) -> float:
        """Share of this run's moves the model predicted correctly (0..1)."""
        return self.run_hits / self.run_total if self.run_total else 0.0

    @property
    def straight_ratio(self) -> float:
        """Share of this run's moves that continued in the same direction (0..1)."""
        n = self.run_total - 1
        return self.run_straight / n if n > 0 else 0.0

    @property
    def turns_total(self) -> int:
        """Number of turns (direction changes, excluding reversals) this run."""
        return sum(self.turns.values())

    def favourite_share(self) -> float:
        """Share of all turns taken by the most common turn (0..1)."""
        total = self.turns_total
        return self.turns.most_common(1)[0][1] / total if total else 0.0

    def favourite_turn(self):
        """The most common (previous move, next move) turn, or None if no turns yet."""
        if not self.turns:
            return None
        return self.turns.most_common(1)[0][0]
