"""Acquisition-budget model.

ESPN caps how many add/drops (acquisitions) a team may make. This turns two raw ESPN
inputs -- the league's ``acquisitionSettings`` and the team's ``transactionCounter`` --
into how many moves remain *right now*, so the morning job can size its recommendations
to what can actually be executed instead of proposing moves the league would reject.

Two caps can apply at once:

  - **season cap**  ``acquisitionLimit``        -- total acquisitions for the year
  - **period cap**  ``matchupAcquisitionLimit`` -- applied per *scoring period* (i.e. per
    day) when ``matchupLimitPerScoringPeriod`` is set, otherwise per matchup period

ESPN encodes "no limit" as ``-1`` (sometimes ``0``); both normalize to ``None`` here. The
binding budget is the smaller of the two remaining counts; if both are unlimited the
budget is effectively unlimited (``remaining is None``).

Pure and dependency-free (no espn-api, no network) so it unit-tests against hand-built
dicts. The reader supplies the raw dicts; the morning job consumes the result.
"""
from __future__ import annotations

from dataclasses import dataclass


def _limit(raw) -> int | None:
    """Normalize an ESPN limit field to a positive int cap, or None for 'unlimited'."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


@dataclass(frozen=True)
class AcquisitionBudget:
    """How many add/drops remain, split across the season and the current period."""

    season_used: int
    season_limit: int | None        # None == unlimited
    period_used: int
    period_limit: int | None        # None == unlimited
    period_label: str               # e.g. "today" or "this matchup period"

    @classmethod
    def unlimited(cls) -> "AcquisitionBudget":
        """A budget with no caps -- the safe fallback when ESPN data can't be read."""
        return cls(season_used=0, season_limit=None,
                   period_used=0, period_limit=None, period_label="this period")

    @property
    def season_remaining(self) -> int | None:
        if self.season_limit is None:
            return None
        return max(0, self.season_limit - self.season_used)

    @property
    def period_remaining(self) -> int | None:
        if self.period_limit is None:
            return None
        return max(0, self.period_limit - self.period_used)

    @property
    def remaining(self) -> int | None:
        """Add/drops still allowed right now. None means effectively unlimited."""
        caps = [r for r in (self.season_remaining, self.period_remaining) if r is not None]
        return min(caps) if caps else None

    @property
    def is_capped(self) -> bool:
        return self.remaining is not None

    def allows(self, n: int) -> bool:
        """True if ``n`` more acquisitions are within budget."""
        return self.remaining is None or n <= self.remaining

    def describe(self) -> str:
        """One-line budget summary (the caller supplies the 'Add/drop budget:' label)."""
        if self.remaining is None:
            return "unlimited"
        bits = []
        if self.period_limit is not None:
            bits.append(f"{self.period_remaining} of {self.period_limit} {self.period_label}")
        if self.season_limit is not None:
            bits.append(f"{self.season_remaining} of {self.season_limit} this season")
        return "; ".join(bits)


def compute_budget(
    acq_settings: dict, txn_counter: dict, matchup_period: int
) -> AcquisitionBudget:
    """Build an :class:`AcquisitionBudget` from raw ESPN settings + usage.

    Args:
        acq_settings: ``settings.acquisitionSettings`` from the league.
        txn_counter:  the team's ``transactionCounter`` (acquisitions used, per-period
                      totals, ...). Missing fields are treated as zero.
        matchup_period: the current matchup-period id, used to read this period's usage
                      when the cap is per matchup period.
    """
    season_limit = _limit(acq_settings.get("acquisitionLimit"))
    season_used = int(txn_counter.get("acquisitions", 0) or 0)

    period_limit = _limit(acq_settings.get("matchupAcquisitionLimit"))
    if acq_settings.get("matchupLimitPerScoringPeriod"):
        # Daily cap. ESPN's counter only totals per matchup period, not per day, and the
        # morning job runs before the day's first move -- so treat the daily budget as
        # fresh (zero used) at run time.
        period_used = 0
        period_label = "today"
    else:
        totals = txn_counter.get("matchupAcquisitionTotals", {}) or {}
        period_used = int(totals.get(str(matchup_period), 0) or 0)
        period_label = "this matchup period"

    return AcquisitionBudget(
        season_used=season_used, season_limit=season_limit,
        period_used=period_used, period_limit=period_limit, period_label=period_label,
    )
