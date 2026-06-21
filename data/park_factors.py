"""Run park factors, keyed by the home team's MLB id.

100 = neutral; >100 favors hitters; <100 favors pitchers. A start in a pitcher-friendly
park is worth more for streaming. These are approximate, well-established multi-year run
factors -- good enough to nudge rankings, and easy to tune. (A game is played in the home
team's park, so we key by home team rather than venue id.)
"""
from __future__ import annotations

NEUTRAL = 100

PARK_FACTORS: dict[int, int] = {
    115: 112,  # Colorado Rockies - Coors Field (extreme hitter)
    111: 108,  # Boston Red Sox - Fenway Park
    113: 108,  # Cincinnati Reds - Great American Ball Park
    143: 103,  # Philadelphia Phillies - Citizens Bank Park
    118: 104,  # Kansas City Royals - Kauffman Stadium
    109: 103,  # Arizona Diamondbacks - Chase Field
    110: 102,  # Baltimore Orioles - Camden Yards
    140: 102,  # Texas Rangers - Globe Life Field
    108: 101,  # LA Angels - Angel Stadium
    120: 101,  # Washington Nationals - Nationals Park
    144: 101,  # Atlanta Braves - Truist Park
    147: 100,  # NY Yankees - Yankee Stadium
    141: 100,  # Toronto Blue Jays - Rogers Centre
    117: 100,  # Houston Astros - Daikin Park
    112: 100,  # Chicago Cubs - Wrigley Field
    142: 100,  # Minnesota Twins - Target Field
    145: 100,  # Chicago White Sox - Rate Field
    158: 100,  # Milwaukee Brewers - American Family Field
    138:  99,  # St. Louis Cardinals - Busch Stadium
    119:  99,  # LA Dodgers - Dodger Stadium
    114:  98,  # Cleveland Guardians - Progressive Field
    121:  97,  # NY Mets - Citi Field
    116:  97,  # Detroit Tigers - Comerica Park
    134:  97,  # Pittsburgh Pirates - PNC Park
    146:  97,  # Miami Marlins - loanDepot park
    133: 100,  # Athletics - Sutter Health Park (Sacramento; uncertain, treat neutral)
    139:  97,  # Tampa Bay Rays - Steinbrenner Field
    135:  95,  # San Diego Padres - Petco Park
    137:  95,  # San Francisco Giants - Oracle Park
    136:  93,  # Seattle Mariners - T-Mobile Park (pitcher)
}


def park_factor(home_team_id: int | None) -> int:
    return PARK_FACTORS.get(home_team_id, NEUTRAL) if home_team_id is not None else NEUTRAL


def describe(factor: int) -> str:
    if factor >= 104:
        return "hitter-friendly"
    if factor <= 96:
        return "pitcher-friendly"
    return "neutral"
