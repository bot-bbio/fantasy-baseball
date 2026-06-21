"""Best-available hitter recommendations.

Surfaces free-agent hitters who out-project your weakest rostered bat, paired with that
bat as the drop. Pitcher streaming lives in `analysis/streaming.py`.

Recommendations only -- executing an add/drop is confirm-gated elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass

from analysis.scoring import compute_category_scores
from models import RosterPlayer


@dataclass
class Recommendation:
    add: RosterPlayer
    drop: RosterPlayer | None
    reason: str
    value_gain: float


def _value_fn(roster, free_agents, is_points, categories):
    """A value(player) callable comparable across roster and FA pools."""
    if is_points:
        return lambda p: p.projected_points or p.percent_owned
    scores = compute_category_scores(list(roster) + list(free_agents), categories)
    return lambda p: scores.get(p.player_id, 0.0)


def find_best_available_hitters(
    roster: list[RosterPlayer],
    free_agents: list[RosterPlayer],
    *,
    is_points: bool = True,
    categories: tuple[str, ...] = (),
    limit: int = 5,
) -> list[Recommendation]:
    """Free-agent hitters who out-project your weakest rostered hitter."""
    value = _value_fn(roster, free_agents, is_points, categories)

    fas = sorted(
        (fa for fa in free_agents if fa.is_hitter and not fa.is_out),
        key=value,
        reverse=True,
    )
    droppable = sorted((p for p in roster if p.is_hitter), key=value)  # weakest first

    recommendations: list[Recommendation] = []
    for index, fa in enumerate(fas):
        if len(recommendations) >= limit:
            break
        drop = droppable[index] if index < len(droppable) else None
        if not drop or value(fa) <= value(drop):
            continue
        recommendations.append(
            Recommendation(fa, drop, f"Upgrade over {drop.name}", value(fa) - value(drop))
        )
    return recommendations
