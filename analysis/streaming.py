"""Streaming-pitcher model.

Scores a free-agent starter's upcoming start 0-100 (50 = league average) by blending:

  - talent   : season skill -- FanGraphs SIERA/xFIP/K-BB% when available, else ESPN proj
  - form     : last-30-day skill -- FanGraphs recent metrics, else ESPN season-to-date
  - matchup  : opponent OPS, platoon-adjusted to the pitcher's handedness when known
  - park     : run park factor of the game's venue

Plus a **two-start bonus** (a start-heavy week is worth far more in weekly leagues) and
**category-aware** weighting (a K-league rewards strikeout upside more than a ratio league).
Weights live in the WEIGHTS block below for easy tuning. `gain` is the score minus the
weakest droppable arm's skill, so only genuine upgrades surface.

A **bullpen floor** (``MIN_RELIEVERS``) guards roster construction: streaming adds
starters, so the drop side must never fall below two dedicated relievers -- only surplus
relievers above the floor are ever offered as drops.

If research data is unavailable the model degrades to ESPN stats automatically.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from analysis.lineup import is_probable_today
from data import park_factors
from data.mlb_offense import league_average_ops
from data.mlb_schedule import DaySchedule
from models import RosterPlayer
from research import research as research_api

# League reference points (ERA/SIERA/xFIP share a scale; K-BB% and K/9 in their own).
LG_ERA = 4.10
LG_WHIP = 1.30
LG_KBB_PCT = 13.5
LG_K9 = 8.6

# Top-level component weights (sum to 1.0) -- tune here.
W_TALENT, W_FORM, W_MATCHUP, W_PARK = 0.28, 0.27, 0.30, 0.15
TWO_START_BONUS = 12.0

# Bullpen floor: never propose a drop that would leave the roster with fewer than this
# many dedicated relievers. Streaming adds starters, so without this guard the model can
# pick a reliever as the "weakest" non-starting arm and quietly gut the bullpen.
MIN_RELIEVERS = 2


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _era_like(m: dict) -> float | None:
    for key in ("SIERA", "xFIP", "FIP", "ERA"):
        if m.get(key) is not None:
            return m[key]
    return None


def _k_per_9(m: dict) -> float | None:
    if m.get("K9") is not None:
        return m["K9"]
    k, outs = m.get("K"), m.get("OUTS")
    if k and outs and outs > 0:
        return k / (outs / 3) * 9
    return m.get("K/9")


def _k_subscore(m: dict) -> float | None:
    if m.get("KBB") is not None:               # FanGraphs K-BB% (decimal, .153 == 15.3%)
        return _clamp(50 + (m["KBB"] * 100 - LG_KBB_PCT) * 2.2)
    k9 = _k_per_9(m)
    return _clamp(50 + (k9 - LG_K9) * 5) if k9 is not None else None


def _skill_score(m: dict | None, *, k_weight: float = 1.0) -> float | None:
    """Blend ERA-estimator, strikeouts and WHIP into a 0-100 skill score."""
    if not m:
        return None
    parts: list[tuple[float, float]] = []
    if (era := _era_like(m)) is not None:
        parts.append((_clamp(50 + (LG_ERA - era) * 14), 1.0))
    if (ks := _k_subscore(m)) is not None:
        parts.append((ks, k_weight))
    if (whip := m.get("WHIP")) is not None:
        parts.append((_clamp(50 + (LG_WHIP - whip) * 70), 1.0))
    if not parts:
        return None
    total = sum(w for _, w in parts)
    return _clamp(sum(s * w for s, w in parts) / total)


def _k_weight(scored_categories: tuple[str, ...]) -> float:
    """Reward strikeout upside more when the league scores Ks (and not just ratios)."""
    cats = set(scored_categories)
    if "K" in cats:
        return 1.6
    if cats & {"ERA", "WHIP"}:
        return 0.8
    return 1.0


def _matchup_score(opponent_ops: float | None, league_ops: float) -> float:
    if opponent_ops is None:
        return 50.0
    return _clamp(50 + (league_ops - opponent_ops) * 300)


def _park_score(factor: int) -> float:
    return _clamp(50 + (park_factors.NEUTRAL - factor) * 1.2)


def _is_starter(player: RosterPlayer) -> bool:
    return "SP" in player.eligible_slots or player.position == "SP"


def _is_reliever(player: RosterPlayer) -> bool:
    """A dedicated reliever -- RP-eligible but not a starter.

    Swingmen (SP+RP) count as starters here: they can still be streamed/started, so
    dropping one does not erode the relief corps the ``MIN_RELIEVERS`` floor protects.
    """
    return ("RP" in player.eligible_slots or player.position == "RP") and not _is_starter(player)


def _talent_metrics(player: RosterPlayer, research) -> dict:
    if research and (m := research.season_metrics(player.name)):
        return m
    return player.projected_stats


def _form_metrics(player: RosterPlayer, research) -> dict:
    if research and (m := research.recent_metrics(player.name)):
        return m
    return player.season_stats or player.projected_stats


def _skill_baseline(player: RosterPlayer, research, k_weight: float = 1.0) -> float:
    parts = [
        s for s in (
            _skill_score(_talent_metrics(player, research), k_weight=k_weight),
            _skill_score(_form_metrics(player, research), k_weight=k_weight),
        ) if s is not None
    ]
    return statistics.fmean(parts) if parts else 50.0


@dataclass
class StreamerEvaluation:
    player: RosterPlayer
    start_day: str
    opponent: str
    opponent_ops: float | None
    park_factor: int
    talent: float
    form: float
    matchup: float
    park: float
    score: float
    two_start: bool = False
    links: dict = field(default_factory=dict)

    @property
    def summary(self) -> str:
        opp = f"@ {self.opponent}" if self.opponent else "@ TBD"
        if self.opponent_ops is not None:
            opp += f" ({self.opponent_ops:.3f} OPS)"
        text = f"{self.start_day} {opp}, {park_factors.describe(self.park_factor)} park"
        if self.two_start:
            text += " - 2 starts"
        return text


def evaluate(
    player: RosterPlayer, day: DaySchedule, offense: dict[int, float], league_ops: float,
    *, research=None, opp_ops: float | None = None,
    scored_categories: tuple[str, ...] = (), two_start: bool = False,
    links: dict | None = None,
) -> StreamerEvaluation:
    kw = _k_weight(scored_categories)
    talent = _skill_score(_talent_metrics(player, research), k_weight=kw)
    form = _skill_score(_form_metrics(player, research), k_weight=kw)
    talent = talent if talent is not None else (form if form is not None else 50.0)
    form = form if form is not None else talent

    if opp_ops is None:
        opp_ops = offense.get(day.opponent_id(player.pro_team))
    matchup = _matchup_score(opp_ops, league_ops)
    factor = park_factors.park_factor(day.home_team_id(player.pro_team))
    park = _park_score(factor)

    base = W_TALENT * talent + W_FORM * form + W_MATCHUP * matchup + W_PARK * park
    score = _clamp(base + (TWO_START_BONUS if two_start else 0.0))

    return StreamerEvaluation(
        player=player, start_day=day.date,
        opponent=day.team_name(day.opponent_id(player.pro_team)) or "TBD",
        opponent_ops=opp_ops, park_factor=factor,
        talent=talent, form=form, matchup=matchup, park=park, score=score,
        two_start=two_start, links=links or {},
    )


@dataclass
class StreamerRecommendation:
    evaluation: StreamerEvaluation
    drop: RosterPlayer | None
    value_gain: float
    drop_is_streamer: bool = False  # True if the drop recycles a tracked streamer slot


def _first_start_day(player: RosterPlayer, schedules: list[DaySchedule]) -> DaySchedule | None:
    for day in schedules:
        if is_probable_today(player, day):
            return day
    return None


def _matchup_ops(player, day, offense, research) -> float | None:
    """Opponent OPS, platoon-adjusted to the pitcher's hand when we can determine it."""
    opponent_id = day.opponent_id(player.pro_team)
    if research is not None:
        hand = research_api.pitcher_hand(day.probable_pitcher_id(player.pro_team))
        platoon = research.opponent_platoon_ops(opponent_id, hand)
        if platoon is not None:
            return platoon
    return offense.get(opponent_id)


def recommend_streamers(
    roster: list[RosterPlayer],
    free_agents: list[RosterPlayer],
    schedules: list[DaySchedule],
    offense: dict[int, float],
    *,
    research=None,
    scored_categories: tuple[str, ...] = (),
    streamer_ids: frozenset[int] = frozenset(),
    min_relievers: int = MIN_RELIEVERS,
    limit: int = 6,
) -> list[StreamerRecommendation]:
    """Rank free-agent starters and pair each with the safest drop.

    ``streamer_ids`` are the rostered pitchers we previously picked up as streamers
    (the disposable slots). They are recycled before any core arm is ever proposed as
    a drop, so an ace in a slump -- which can look like the weakest pitcher on raw
    skill -- is protected from accidental churn.

    ``min_relievers`` enforces a bullpen floor: only the weakest *surplus* relievers
    (those above the floor) are ever offered as drops, so a streaming add can never
    take the roster below ``min_relievers`` dedicated relief pitchers.
    """
    league_ops = league_average_ops(offense)
    k_weight = _k_weight(scored_categories)

    # Two-start = probable on 2+ days in the window.
    start_counts = {
        fa.player_id: sum(1 for d in schedules if is_probable_today(fa, d))
        for fa in free_agents
    }

    evaluations = []
    for fa in free_agents:
        if fa.is_out or not _is_starter(fa):
            continue
        day = _first_start_day(fa, schedules)
        if day is None:
            continue
        evaluation = evaluate(
            fa, day, offense, league_ops,
            research=research, opp_ops=_matchup_ops(fa, day, offense, research),
            scored_categories=scored_categories,
            two_start=start_counts.get(fa.player_id, 0) >= 2,
            links=research_api.deep_links(fa.name) if research is not None else {},
        )
        evaluations.append(evaluation)
    evaluations.sort(key=lambda e: e.score, reverse=True)

    today = schedules[0]
    candidates = [p for p in roster if p.is_pitcher and not is_probable_today(p, today)]
    by_skill = lambda p: _skill_baseline(p, research, k_weight)  # noqa: E731

    # Bullpen floor: keep at least ``min_relievers`` relievers. Of the relievers on the
    # roster, only the weakest surplus (count above the floor) may be dropped; the rest
    # are filtered out of the candidate pool entirely so they're never proposed. Because
    # at most ``surplus`` relievers remain droppable, the floor holds even across the
    # several recommendations a single report can make.
    roster_relievers = sorted((p for p in roster if _is_reliever(p)), key=by_skill)
    surplus = max(0, len(roster_relievers) - max(0, min_relievers))
    droppable_reliever_ids = {p.player_id for p in roster_relievers[:surplus]}
    candidates = [
        p for p in candidates
        if not _is_reliever(p) or p.player_id in droppable_reliever_ids
    ]

    # Recycle tracked streamer slots first; only then touch (the weakest) core arms.
    recyclable = sorted((p for p in candidates if p.player_id in streamer_ids), key=by_skill)
    core = sorted((p for p in candidates if p.player_id not in streamer_ids), key=by_skill)
    droppable = recyclable + core

    recommendations: list[StreamerRecommendation] = []
    for index, evaluation in enumerate(evaluations):
        if len(recommendations) >= limit:
            break
        drop = droppable[index] if index < len(droppable) else None
        baseline = _skill_baseline(drop, research, k_weight) if drop else 50.0
        gain = evaluation.score - baseline
        if gain <= 0:
            continue
        drop_is_streamer = drop is not None and drop.player_id in streamer_ids
        recommendations.append(
            StreamerRecommendation(evaluation, drop, gain, drop_is_streamer)
        )
    return recommendations
