"""Player valuation used to rank candidates for slots and waiver pickups.

- Points leagues: rank by projected fantasy points (simple and accurate).
- Category / roto leagues: there are no "points", so rank by a composite z-score
  across the categories the league actually scores. Because a hitting category's
  pool is only hitters (and a pitching category's pool is only pitchers), the
  composite is comparable *within* a group -- which is all we ever compare.
"""
from __future__ import annotations

import statistics

from models import LOWER_IS_BETTER, RosterPlayer


def compute_category_scores(
    players: list[RosterPlayer], categories: tuple[str, ...]
) -> dict[int, float]:
    """Sum of per-category z-scores for each player (higher = better)."""
    scores: dict[int, float] = {p.player_id: 0.0 for p in players}
    for cat in categories:
        values = [
            (p.player_id, p.projected_stats[cat])
            for p in players
            if isinstance(p.projected_stats.get(cat), (int, float))
        ]
        if len(values) < 2:
            continue
        numbers = [v for _, v in values]
        mean = statistics.fmean(numbers)
        stdev = statistics.pstdev(numbers)
        if stdev == 0:
            continue
        invert = cat in LOWER_IS_BETTER
        for player_id, value in values:
            z = (value - mean) / stdev
            scores[player_id] += -z if invert else z
    return scores


def player_value(
    player: RosterPlayer,
    is_points: bool,
    category_scores: dict[int, float] | None = None,
) -> float:
    """Single comparable value for ranking a player."""
    if is_points:
        # Fall back to ownership only if projections are missing.
        return player.projected_points or player.percent_owned
    if category_scores is not None:
        return category_scores.get(player.player_id, 0.0)
    return player.projected_points or player.percent_owned
