# Advanced Pitcher Modeling: Mathematical Foundations, Applications, and Strategic Perspectives

> Source: converted from "Pitcher Modeling Perspectives Research" (Google Doc export). The
> original document's formulas were embedded as images and did not survive the text export;
> they have been reconstructed below from primary sabermetric sources (Tango, FanGraphs
> Sabermetrics Library, Baseball Prospectus, Statcast documentation) and are flagged where
> exact coefficients are estimated/refit periodically rather than fixed constants. Use this
> doc as the reference layer when implementing `analysis/` modules for pitcher valuation.

## Introduction

The evaluation and modeling of pitching performance represents the most mathematically
mature domain in modern sports analytics. Because the interaction between a pitcher and a
batter exists as a series of isolated, highly structured stochastic events, it lends itself
organically to advanced mathematical modeling, machine learning, and physical kinematics.
From the rudimentary outcome-based statistics of the early twentieth century to the
biomechanical and aerodynamic pitch-tracking models of the modern era, pitcher evaluation
has undergone profound transformations.

By partitioning the variance of a pitcher's performance into skill, luck, environmental
factors, and raw physical characteristics, analysts can isolate the precise mechanisms that
drive run prevention. This isolation allows organizations and analysts to exploit
inefficiencies in player development, optimize fantasy baseball strategies, and construct
high-fidelity algorithmic models for sports betting and prediction markets.

## Quick Reference: Formulas for Implementation

| Model | Formula | Inputs |
|---|---|---|
| Pythagorean expectation | `Win% = RS^2 / (RS^2 + RA^2)` | RS, RA |
| Pythagenpat exponent | `x = ((RS + RA) / G) ^ 0.287` | RS, RA, G |
| Pythagenpat win% | `Win% = RS^x / (RS^x + RA^x)` | RS, RA, x |
| BaseRuns (pitcher) | `BsR = A*B/(B+C) + D` (components below) | H, BB, HR, IP |
| Game Score 2.0 | `40 + 2*Outs + 1*K - 2*BB - 2*H - 3*R - 6*HR` | Outs, K, BB, H, R, HR |
| FIP | `(13*HR + 3*(BB+HBP) - 2*K)/IP + cFIP` | HR, BB, HBP, K, IP |
| xFIP | `(13*(FB*lgHR/FB) + 3*(BB+HBP) - 2*K)/IP + cFIP` | FB, BB, HBP, K, IP |
| SIERA | Quadratic regression on K/PA, BB/PA, netGB/PA (refit periodically — see below) | K, BB, GB, FB, PU, PA |
| Marcel reliability | `r = min(1, weighted_IP / threshold)` | IP history |
| VAA | `-arctan(vz_f / vy_f) * (180/pi)` | vy0, vz0, ay, az |
| Log5 / odds ratio | `O_match = (O_pitcher * O_batter) / O_league`, `P = O_match/(1+O_match)` | pitcher/batter/league rates |
| Markov run expectancy | `N = (I - Q)^-1` | 24x24 transition submatrix Q |

---

## Part I: Historical Foundations — Macroscopic Modeling and Early Sabermetrics

Before the advent of pitch-tracking technology, evaluating pitching required separating a
pitcher's individual contribution from the macroscopic run environment of the team. The
initial waves of sabermetric thought focused on defining the mathematical relationship
between runs, wins, and single-game dominance. Analysts working from a historical
perspective rely on these fundamental theorems to normalize performance across disparate
eras, ballparks, and defensive environments.

### Pythagorean Expectation and Pythagenpat

Bill James established the foundational link between run differentials and expected
outcomes with the **Pythagorean expectation** model. The theorem posits that a team's
winning percentage is a non-linear function of runs scored and runs allowed:

```
Win% = RS^2 / (RS^2 + RA^2)
```

While empirically sound and highly correlated with actual winning percentages, the exponent
of 2 was an approximation — statisticians noted a routine error of roughly three games per
season. The degree to which sports contestants win in proportion to their quality depends on
how much chance shapes the sport's outcomes; moving the exponent slightly accounts for the
variance inherent to baseball specifically.

The most widely accepted refinement is **Pythagenpat**, developed by David Smyth, which
makes the exponent dynamic — scaling with the run environment of the league so the formula
holds even in extreme run-scoring eras:

```
x = ((RS + RA) / G) ^ 0.287
Win% = RS^x / (RS^x + RA^x)
```

For historical researchers, applying Pythagorean models to starting pitchers yields
"second-order wins" — the number of wins a pitcher's team should have accumulated given the
runs allowed during their time on the mound, stripping away bullpen failures and run-support
variance. Plugging expected runs scored/allowed into the formula generates second- and
third-order winning percentages, which predict future actual winning percentage better than
raw historical win-loss records.

### BaseRuns: Modeling the Run Environment

While Pythagorean expectation translates runs into wins, predicting the runs themselves
requires a different approach. **BaseRuns (BsR)**, also designed by David Smyth, estimates
the number of runs a team or pitcher should have scored/allowed based on underlying
offensive/defensive statistics. Linear-weights metrics (like wOBA) measure individual
performance well, but run scoring at the systemic level is not entirely linear.

BaseRuns models run scoring through baseball's fundamental identity: baserunners multiplied
by their scoring rate, plus home runs. This structure organically caps the scoring rate
between 0% and 100%, preventing the formula from breaking down at extremes — a common
failure point for static linear-weights equations:

```
BsR = A*B / (B+C) + D
```

When adapted for pitchers (Tom Tango's version), the components are:

```
A  = H + BB − HR                              (baserunners, excluding HR)
B  = (1.4*TBe − 0.6*H − 3*HR + 0.1*BB) * 1.1  (advancement factor)
TBe = 1.12*H + 4*HR                            (estimated total bases)
C  = 3 * IP                                    (outs)
D  = HR                                        (runs that skip the bases entirely)
```

The fraction `B/(B+C)` estimates the rate at which baserunners advance to home plate through
non-home-run means, balanced against the outs that strand runners. Once the raw BaseRuns
value is generated, a league adjustment factor is applied to align the output with actual
league-wide run totals. For pitcher evaluation, BaseRuns converts a pitcher's underlying
component stats directly into an expected Runs Allowed per 9 Innings (RA9), which is
frequently used in projection algorithms.

### Single-Game Modeling: Game Score and Game Score 2.0

To evaluate isolated starts without the contamination of win-loss records or inherited
runners, Bill James introduced **Game Score** in his 1988 Baseball Abstract — a macroscopic
gauge centered on a baseline of 50 points, rewarding outs and strikeouts while penalizing
hits, walks, and runs.

James's original version failed to properly weight individual events, particularly the
disproportionate damage of home runs. Tom Tango mathematically updated the metric in 2014 —
**Game Score 2.0** — aligning it with modern Defense-Independent Pitching Statistics (DIPS)
theory. The baseline shifts to 40 (closer to replacement level than average), preventing
pitchers from being overly penalized for leaving a game early due to injury:

```
GameScore2.0 = 40 + 2*Outs + 1*K − 2*BB − 2*H − 3*R − 6*HR
```

By assigning a massive −6 penalty to home runs and scaling outs to 2 points, Game Score 2.0
rewards efficiency and strikeout dominance while heavily taxing home-run susceptibility.

| Event Variable | Original Weight | Game Score 2.0 Weight | Rationale |
|---|---|---|---|
| Starting Baseline | 50 points | 40 points | Aligns baseline closer to replacement level rather than average. |
| Out Recorded | +1 point | +2 points | Increases the reward for inning consumption and efficiency. |
| Inning After 4th | +2 points | 0 points | Eliminated in favor of a flat per-out reward structure. |
| Strikeout | +1 point | +1 point | Retained as the primary marker of pitcher dominance. |
| Walk Allowed | −1 point | −2 points | Punishes unearned baserunners more severely, matching linear run values. |
| Hit Allowed | −2 points | −2 points | Retained, though modern DIPS theory suggests limited pitcher control. |
| Run Allowed | −4 (earned), −2 (unearned) | −3 points (all runs) | Streamlines the penalty, ignoring defensive-error distinctions. |
| Home Run Allowed | 0 (already in runs/hits) | −6 points | Introduces a targeted penalty for the ultimate pitcher failure. |

---

## Part II: The Defense-Independent Pitching Revolution

The most significant theoretical shift in pitcher modeling occurred at the turn of the 21st
century, transitioning the focus of evaluation from outcomes to process. The historical
reliance on Earned Run Average (ERA) was deeply flawed because it intertwined a pitcher's
performance with the quality of the defense behind them, park dimensions, and the
sequencing of events.

### DIPS Theory

Voros McCracken introduced **Defense-Independent Pitching Statistics (DIPS)** theory in 1999
by hypothesizing that pitchers exercise negligible control over the outcome of a ball once
it is in play (BABIP). McCracken partitioned variance into distinct elements — pitcher-
controlled true outcomes versus defense/luck-driven balls in play — and found a high
year-to-year correlation for strikeout and walk rates, a medium correlation for home-run
rates, and a remarkably low correlation for hits allowed on balls in play. By removing balls
in play from the equation, McCracken showed a pitcher's true talent is isolated within
strikeouts, walks, hit batters, and home runs — the "Three True Outcomes."

### FIP: Fielding Independent Pitching

**FIP** formalizes DIPS theory into a linear formula, assigning linear weights to the events
a pitcher strictly controls and scaling to the ERA scale via a league-specific constant:

```
FIP = (13*HR + 3*(BB+HBP) − 2*K) / IP + cFIP
```

The weights come from linear run values: a home run is worth roughly a full run (scaled to
13), a walk/HBP is roughly a third of a run (scaled to 3), and a strikeout removes the
chance of any defense-aided outcome (scaled to −2). The constant `cFIP` exists solely to
align league-average FIP with league-average ERA in a given season:

```
cFIP = lgERA − (13*lgHR + 3*(lgBB+lgHBP) − 2*lgK) / lgIP
```

`cFIP` typically lands in the 3.10–3.20 range. For fantasy managers, the gap between a
pitcher's ERA and FIP signals imminent regression: ERA exceeding FIP by 0.50+ usually means
poor defense or bad batted-ball luck is temporarily inflating runs allowed (ERA should fall);
ERA well below FIP implies the pitcher is surviving on unsustainable luck (correction likely
negative).

### xFIP: Expected Fielding Independent Pitching

FIP retains a structural vulnerability: it assumes the rate at which fly balls leave the
yard as home runs purely reflects pitcher skill. In reality, HR/FB rate is highly volatile
and heavily influenced by park, wind, and temperature. **xFIP** corrects for this by
replacing actual home runs with an expected total — the pitcher's fly balls allowed times the
league-average HR/FB rate:

```
xFIP = (13*(FB * lgHR_per_FB) + 3*(BB+HBP) − 2*K) / IP + cFIP
```

This strips out home-run variance noise, but extreme groundball pitchers or those with elite
command can suppress their personal HR/FB rate below league average, causing xFIP to
chronically underestimate their true talent.

### SIERA: Skill-Interactive Earned Run Average

FIP and xFIP operate on linear weights, but run scoring is fundamentally non-linear — the
damage of a walk depends entirely on the sequence of events that follows. Matt Swartz and
Eric Seidman developed **SIERA** to model batted-ball types (ground balls, fly balls,
pop-ups) interacting dynamically with walk and strikeout rates: a high ground-ball rate
mitigates a high walk rate via double plays; a high strikeout rate prevents runners from
advancing, making the occasional baserunner less dangerous; pop-ups behave like automatic
outs that suppress run scoring similarly to strikeouts.

SIERA's structural form is a quadratic regression on three rate inputs:

```
K_rate    = K / PA
BB_rate   = BB / PA
netGB_rate = (GB − FB) / PA

SIERA = b0
       + b1*K_rate     + b2*K_rate^2
       + b3*BB_rate    + b4*BB_rate^2
       + b5*netGB_rate ± b6*netGB_rate^2   (sign flips on whether GB >= FB)
       + b7*(K_rate * BB_rate)
       + b8*(K_rate * netGB_rate)
       + b9*(BB_rate * netGB_rate)
```

> **Implementation note:** FanGraphs and Baseball Prospectus each maintain their own fitted
> coefficients (fgSIERA vs. bpSIERA), and FanGraphs has re-estimated the regression more than
> once as run environments shifted. Rather than hard-coding a specific decade's published
> coefficients into a valuation model, treat SIERA as *this regression structure* and either
> pull the metric directly from FanGraphs/Baseball Prospectus or refit the quadratic on
> current league-wide data if building it from scratch — stale coefficients will silently
> drift as the run environment changes.

| Estimator | Primary Inputs | Structural Assumption | Strength |
|---|---|---|---|
| FIP | K, BB, HBP, HR, IP | Linear run environment; isolated true outcomes only. | Quick skill read; effective for near-term mid-season regression calls. |
| xFIP | K, BB, HBP, FB, IP | Fly-ball luck is volatile and normalizes to league average. | Best for spotting extreme HR/FB bad luck in small samples. |
| SIERA | K, BB, GB, FB, PU, PA | Run scoring is non-linear; batted-ball profile dictates outcome severity. | Most accurate for forecasting future-year performance. |

---

## Part III: Systemic Forecasting — Projection Algorithms

To anticipate a pitcher's future value, analysts use projection models that aggregate
historical data, apply chronological decay weights, and regress outputs toward a league
mean based on sample-size reliability.

### Marcel the Monkey Forecasting System

**Marcel**, engineered by Tom Tango, represents the "minimum level of competence" for
projection algorithms — deliberately simple, with no minor-league translations or
machine-learning biomechanics, yet robust enough to serve as the baseline that more advanced
proprietary systems are tested against.

For pitchers, Marcel uses an innings-pitched-weighted average of the past three seasons with
a 5/4/3 recency distribution (most recent year ≈ 42% weight, prior year ≈ 33%, oldest year ≈
25%), with each season's weight additionally multiplied by that season's innings pitched so
injury-shortened seasons don't dominate:

```
WeightedStat = Σ(recency_weight_i * IP_i * Stat_i) / Σ(recency_weight_i * IP_i)
```

Because raw weighted averages are overconfident in small samples, Marcel regresses to the
mean using a reliability score:

```
reliability = min(1.0, weighted_IP / threshold)
Projected_Stat = reliability * WeightedStat + (1 − reliability) * LeagueAverage
```

Pitchers need roughly 150 IP to cross the reliability threshold for most rate stats (K and BB
rates stabilize faster — threshold ≈ 120 IP). A pitcher at or above the threshold gets
reliability 1.0 (no regression); at exactly half the threshold, the projection is blended
50/50 with league average.

Marcel handles pitcher aging via an inverted curve: because a declining age factor means
deteriorating physical skills, "lower is better" stats (ERA, FIP, WHIP, BB/9) are *divided*
by the age factor (pushing the expected value higher/worse) while "higher is better" stats
(K/9) are *multiplied* by it (pushing the expected value lower/worse). E.g., a 34-year-old
with a 0.95 age factor gets ERA divided by 0.95 and K/9 multiplied by 0.95.

### The ATC (Average Total Cost) Consensus Model

Modern projection systems (Steamer, ZiPS, PECOTA) layer in pitch-level data and minor-league
translations, but each harbors blind spots based on its proprietary architecture. **ATC**,
engineered by Ariel Cohen, instead applies *consensus optimization*: rather than building a
new ground-up projection, it assigns dynamic weights to existing systems based on each
system's historical accuracy for specific metric categories (e.g., favoring Steamer's
strikeout-rate projections but ZiPS's home-run projections, if backtesting shows that split).
This blending reduces predictive volatility, making ATC a strong foundation for fantasy
drafting and season-long outlooks where minimizing downside risk is prioritized over
capturing extreme upside.

---

## Part IV: The Modern Era — Kinematics, Physics, and Aerodynamics

High-speed optical tracking (Statcast, Hawk-Eye) evaluates the raw physical characteristics
of every pitch in three-dimensional space, letting analysts determine *why* a pitch succeeds
based on biomechanical and aerodynamic profile rather than only its outcome.

### Pitch Shape: Vertical and Horizontal Approach Angles (VAA / HAA)

**Approach angles** are the final trajectory vectors at which a pitch crosses the front
plane of home plate — a more complete descriptor of deception than total inches of break.

**Vertical Approach Angle (VAA)** measures the downward slope of the pitch as it crosses the
plate, in degrees. Because pitchers throw off an elevated mound, VAA is always negative;
hitters swing on an upward plane of roughly 10–12 degrees. A "flat" VAA (closer to 0, e.g.
−3.5 to −4.0) thrown at the top of the zone creates a mismatch with the hitter's swing plane
— the batter swings under a ball that drops less than expected, creating the illusion of
"rise."

The Statcast derivation, evaluated at the plate (yf, typically 17/12 ft from the back tip of
home plate) using velocity/acceleration components captured at y0 = 50 ft:

```
vy_f = -sqrt(vy0^2 - 2*ay*(y0 - yf))
t    = (vy_f - vy0) / ay
vz_f = vz0 + az*t
VAA  = -arctan(vz_f / vy_f) * (180/pi)
```

**Horizontal Approach Angle (HAA)** measures the side-to-side entry angle as the pitch
crosses the plate. Elite sweepers and sliders leverage high absolute HAA, initiating their
flight path off the plate and sweeping sharply into the zone late. It uses the same time `t`
derived above, applied to the x-dimension:

```
vx_f = vx0 + ax*t
HAA  = arctan(vx_f / vy_f) * (180/pi)
```

For pitch design, VAA and HAA have superseded simple movement metrics: a fastball lacking
elite induced vertical break can still generate elite swinging-strike rates at the top of the
zone if thrown from a low release height with high extension (flat VAA); conversely,
pitchers with steep release points are encouraged to throw sinkers low in the zone to
maximize VAA steepness and induce ground balls.

### The Physics of Seam-Shifted Wake (SSW)

Classical aerodynamic modeling held that a pitched ball's movement was strictly a product of
gravity, drag, and the Magnus effect (transverse spin creating pressure differentials).
Optical tracking, however, uncovered large discrepancies between a pitch's *inferred* spin
axis (the axis mathematically required to produce the observed movement via Magnus alone)
and its *observed* spin axis (the actual physical rotation out of the hand).

This discrepancy is driven by **Seam-Shifted Wake (SSW)**: as a baseball travels at high
velocity, airflow separates into a turbulent wake, and the raised seams act as discrete
roughness elements. When seams are oriented asymmetrically near the boundary-layer
separation point, they prematurely trip one side of the ball into turbulence, forcing earlier
separation on that side — generating an aerodynamic force entirely independent of Magnus
spin. SSW lets sinkers and changeups produce massive arm-side run and diving depth despite
gyro-heavy spin axes that, under classical physics, would predict relatively straight
flight. Pitching coordinators now run dedicated "pitch design" sessions to manipulate grip,
seam orientation, and wrist supination to weaponize SSW even when raw spin efficiency is
average.

### Machine Learning Pitch Evaluators

By synthesizing kinematics, approach angles, velocity, and aerodynamic forces, analysts have
built holistic "Pitch Quality" models — typically gradient-boosting frameworks (e.g.
XGBoost) — that assign expected run values to individual pitches based purely on physical
traits, blinded to outcome, defense, sequencing, and luck.

- **PitchingBot** (Cameron Grove): trains on millions of Statcast pitches using pitch type,
  velocity, spin rate, horizontal/vertical movement, release point, count, and batter
  handedness to predict expected run value per pitch. Splits into a "Stuff" sub-model
  (location stripped out, isolating raw nastiness) and a "Command" sub-model (locating on
  the margins of the zone). Notably shows that for sliders/curveballs, horizontal movement
  is far more valuable than vertical depth for generating whiffs, while high VAA is
  penalized for breaking balls.
- **Stuff+ / Location+ / Pitching+** (Eno Sarris & Max Bay): Stuff+ evaluates only physical
  traits (velocity, movement, release extension, spin rate), with secondary pitches measured
  relative to the pitcher's primary fastball (mirroring how a batter calibrates timing) and
  an "axis differential" term implicitly capturing SSW-driven deception. Location+ evaluates
  intent/execution of pitch location given count and handedness. Pitching+ combines both.
  Outputs are scaled so 100 = league average for that pitch type.
- **Pitch Level Value (PLV)** (Pitcher List): grades every pitch 0–10 (5 = average) from
  velocity, movement, release, count, and handedness, predicting swing/miss/quality-contact
  probability. Translates to **Pitch Level Average (PLA)**, a traditional ERA-scale
  estimator, for readable run-prevention context.

| Pitch Metric Category | Primary Inputs | Target Prediction | Core Value |
|---|---|---|---|
| Stuff models (Stuff+) | Velocity, break, spin rate, release point, SSW differentials | Expected whiff rate / run value, independent of location | Highest year-over-year stickiness; stabilizes in well under 100 pitches. |
| Command models | Pitch coordinates, count, batter handedness | Location value relative to zone borders/attack zones | Evaluates strategy/execution; penalizes middle-middle mistakes, rewards edge execution. |

---

## Part V: Applied Strategies — Scouting, Gambling, and Fantasy

The evolution from macroscopic ERA to FIP and finally to microscopic ML pitch models
represents a massive acceleration in statistical stabilization: ERA needs hundreds of
innings to stabilize; FIP needs roughly 70 innings; Stuff+ stabilizes in roughly 80 pitches.
This granular acceleration is the edge applied across scouting, betting, and fantasy.

### Scouting and Player Development

Front offices deploy pitch-level models and kinematics (SSW, VAA) to run targeted "Pitch
Design Phases" (PDP). A prospect with a low release height but poor fastball command may
still be drafted aggressively, because the release-height-driven VAA profile is an
unteachable physical trait that generates "invisible" ride. Development has shifted from the
abstract notion of "throwing strikes" toward manipulating seam orientation on high-speed
cameras to maximize SSW on a sinker — though pitch design introduces real neuromuscular and
connective-tissue stress, so organizations constrain the development phase using workload
metrics like the acute:chronic workload ratio (ACWR) to limit arm-injury risk.

For fantasy managers, SIERA, xFIP, and Stuff+ together identify regression candidates: a
pitcher with a 4.50 ERA but a 3.10 SIERA and a 115 Stuff+ rating is a prime acquisition
target — the underlying stuff and batted-ball interactions predict imminent run suppression
behind a temporarily inflated ERA.

### Gambling and Algorithmic Prediction Markets

Vegas lines and DFS salaries still heavily weight macroscopic historical performance (ERA,
WHIP, traditional splits); sharp bettors and algorithmic syndicates exploit the latency
between descriptive stats and predictive pitch modeling.

**Markov chain run expectancy.** For exhaustive simulation (common in algorithmic betting),
a half-inning is modeled as a discrete-time Markov chain: 24 transient states (runner
configuration × 0–2 outs) plus one absorbing state (3 outs). A transition matrix is built
from single-pitching-event probabilities (strikeout, walk, double play, etc.). Run
expectancy uses the fundamental matrix:

```
N = (I - Q)^-1
```

where `Q` is the 24x24 submatrix of transitions between non-absorbing states and `I` is the
identity matrix. `N` gives the expected number of visits to each state before absorption;
tracking run-scoring transitions against `N` lets algorithms simulate billions of
half-innings and predict expected runs surrendered from a pitcher's specific transition
probabilities.

**Matchup modeling (Log5 / odds ratio).** For single-game outcome forecasts, bettors project
specific pitcher-vs-batter interactions with the Log5 model, feeding resulting probabilities
into the Markov transition matrix. Given a pitcher's rate `P`, a batter's rate `B`, and the
league-average rate `L` for some event (e.g., strikeout), convert each to odds and combine:

```
O_pitcher = P / (1 - P)
O_batter  = B / (1 - B)
O_league  = L / (1 - L)

O_matchup = (O_pitcher * O_batter) / O_league
P_matchup = O_matchup / (1 + O_matchup)
```

Calculating exact Log5 matchups for every plate appearance in a simulated game produces
probabilistic outcomes far sharper than generic team-level projections.

DFS players also use microscopic models (PitchingBot, PLV) to spot imminent "blow-up" risk:
a pitcher riding a strong recent ERA (keeping DFS salary high) may have a Stuff+ quietly
degraded by a mechanical flaw, reduced spin efficiency, or lost SSW manipulation — predictive
models flag this well before macroscopic ERA catches up, creating leverage for fading that
pitcher in tournament play.

---

## Conclusion

The mathematical modeling of baseball pitching has evolved from macroscopic run
distributions to microscopic aerodynamic physics. Early frameworks like Pythagenpat and Game
Score provided the theoretical infrastructure to normalize historical evaluations, while the
DIPS revolution — FIP, xFIP, SIERA — partitioned pure pitcher skill from defensive variance
and luck. Today the analytical frontier is dominated by kinematics and machine learning:
VAA/HAA and Seam-Shifted Wake let scouts and development coordinators engineer specific pitch
trajectories with mathematical precision, while ATC, PitchingBot, Stuff+/Location+/Pitching+,
and PLV process three-dimensional pitch data instantaneously to predict expected run values
before contact. Whether the goal is a minor-league development pipeline, a fantasy breakout
list, or a structural betting-market inefficiency, modern pitcher modeling turns the
stochastic noise of a baseball game into a tractable mathematical structure — and gives a
layered toolkit (macro estimators → DIPS estimators → projection systems → pitch-level
physics/ML) for building a from-scratch pitcher valuation model.

---

## Works Cited

1. Akousmatikoi Win Estimators, pt. 1: Pythagorean - Walk Like a Sabermetrician, http://walksaber.blogspot.com/2020/10/akousmatikoi-win-estimators-pt-1.html
2. Pythagorean expectation - Wikipedia, https://en.wikipedia.org/wiki/Pythagorean_expectation
3. Pythagorean expectation - wikidoc, https://www.wikidoc.org/index.php/Pythagorean_expectation
4. What Are BaseRuns and How Do They Apply to Baseball Betting? | The Action Network, https://www.actionnetwork.com/mlb/what-are-baseruns-baseball-betting
5. BaseRuns | Sabermetrics Library, https://library.fangraphs.com/features/baseruns/
6. Base runs - Grokipedia, https://grokipedia.com/page/base_runs
7. How are Runs Really Created - Third Installment - Tango on Baseball, https://tangotiger.net/rc3.html
8. Creating Custom BaseRuns Coefficients : r/Sabermetrics - Reddit, https://www.reddit.com/r/Sabermetrics/comments/15n06kh/creating_custom_baseruns_coefficients/
9. Game score - Wikipedia, https://en.wikipedia.org/wiki/Game_score
10. OLYAS: A New and Improved Game Score Metric - Wharton Sports Analytics and Business Initiative, https://wsb.wharton.upenn.edu/wp-content/uploads/2021/11/Diamond-Dollars-Case-Competition-Resnick-Resnick-Federman-Mehere.pdf
11. The Greatest Game José Fernández Ever Pitched | The Hardball Times, https://tht.fangraphs.com/the-greatest-game-jose-fernandez-ever-pitched/
12. A consideration of the 2018 Cy Young races - Redband Sports, https://www.redbandsports.net/2018/09/27/a-consideration-of-the-2018-cy-young-races/
13. FIP Calculator Baseball (Free, With Rating Scale) - Striveon, https://joinstriveon.com/blog/fip-calculator-baseball
14. Baseball Therapy: Credit Where It's Due, Part 1, https://www.baseballprospectus.com/news/article/10387/baseball-therapy-credit-where-its-due-part-1/
15. Sabermetrics - Wikipedia, https://en.wikipedia.org/wiki/Sabermetrics
16. The Many Flavors of DIPS: A History and an Overview - SABR.org, https://sabr.org/journal/article/the-many-flavors-of-dips-a-history-and-an-overview/
17. Pitcher ERA: A look at FIP, xFIP and SIERA - Fantasy Index, https://fantasyindex.com/2023/12/24/fantasy-baseball-index/pitcher-era-a-look-at-fip-xfip-and-siera
18. Introducing SIERA: Part 1 - Baseball Prospectus, https://www.baseballprospectus.com/news/article/10027/introducing-siera-part-1/
19. Marcel-style Pitcher Projections 2024-2033 : r/baseball - Reddit, https://www.reddit.com/r/baseball/comments/17wpgyh/marcelstyle_pitcher_projections_20242033/
20. Marcel the Monkey Forecasting System - Baseball-Reference.com, https://www.baseball-reference.com/about/marcels.shtml
21. Baseball Player Projections: Our Marcel + Statcast Model Explained - Birdland Metrics, https://birdlandmetrics.com/articles/player-projections
22. Behind the numbers - Sports Illustrated, https://www.si.com/mlb/2007/02/19/fangraphs-projections
23. Oliver | Glossary - MLB.com, https://www.mlb.com/glossary/projection-systems/oliver
24. Fantasy MLB Today: ATC Volatility Metrics with Ariel Cohen - SportsEthos, https://sportsethos.com/audio-video/podcasts/fantasy-mlb-today-atc-volatility-metrics-with-ariel-cohen/
25. OVERVALUED & UNDERVALUED Players! 2025 ATC Projections w/ Ariel Cohen! | Fantasy Baseball Advice - YouTube, https://www.youtube.com/watch?v=xffiSxtkznI
26. 2021 Projections – How the Experts are Handling the 2020 Season | RotoGraphs Fantasy Baseball, https://fantasy.fangraphs.com/2021-projections-how-the-experts-are-handling-the-2020-season/
27. PitchIQ — MiLB Pitch Intelligence | ProspectTilt, https://pitchiq.prospecttilt.com/
28. Author: Alex Chamberlain | FanGraphs Baseball, https://blogs.fangraphs.com/author/alexchamberlain/
29. A Visualized Primer on Vertical Approach Angle (VAA) - FanGraphs Baseball, https://blogs.fangraphs.com/a-visualized-primer-on-vertical-approach-angle-vaa/
30. Avoid the Dead Zone: Fastball Stuff Characteristics and Utility - Magnus, https://www.seemagnus.com/blog-posts-test/avoid-the-dead-zone-an-extensive-analysis-of-the-relationship-between-fastball-stuff-characteristics-and-utility-through-four-logistic-regression-models
31. Examining Pitching Approach Angles | Ethan Moore | Something Tangible | Medium, https://medium.com/something-tangible/examining-pitching-approach-angles-e2ab7a3b9c15
32. Thinking About Horizontal Approach Angle - FanGraphs Baseball, https://blogs.fangraphs.com/thinking-about-horizontal-approach-angle/
33. A Visual Primer on Horizontal Approach Angle (HAA) - FanGraphs Baseball, https://blogs.fangraphs.com/a-visual-primer-on-horizontal-approach-angle-haa/
34. Velo vs. injury: Is there a better way for pitchers? - theScore, https://www.thescore.com/mlb/news/2896907
35. The Seam-Shifted Revolution Is Headed for the Mainstream | FanGraphs Baseball, https://blogs.fangraphs.com/the-seam-shifted-revolution-is-headed-for-the-mainstream/
36. Numerical investigation of the aerodynamic force variations during rotation of a pitched baseball, https://d-nb.info/1375131575/34
37. Making Sense of Seam-Shifted Wake: A Physicist's Perspective (Part 1), https://www.laphysiquedubaseball.ca/2026/04/05/making-sense-of-seam-shifted-wake-a-physicists-perspective-part-1/
38. Reverse-Engineering the Perfect Sinker | Colin Hofmeister | Medium, https://medium.com/@colinhofmeister/reverse-engineering-the-perfect-sinker-b5fbcbe06f2e
39. Simulating the Movement of a Major League Fastball - ScholarWorks at UMass Boston, https://scholarworks.umb.edu/cgi/viewcontent.cgi?article=1966&context=masters_theses
40. Seam-shifted wake - Wikipedia, https://en.wikipedia.org/wiki/Seam-shifted_wake
41. UCLA Electronic Theses and Dissertations - eScholarship.org, https://escholarship.org/content/qt6mz24386/qt6mz24386.pdf
42. An Introduction to Seam-Shifted Wakes and their Effect on Sinkers - Driveline Baseball, https://www.drivelinebaseball.com/2020/11/more-than-what-it-seams-an-introduction-to-seam-shifted-wakes-and-their-effect-on-sinkers/
43. The Pitch Design Phase in Baseball - Premier Pitching, https://premierpitching.com/blogs/premier-pitching-chronicles/the-pitch-design-phase-in-baseball-developmental-fit-workload-informed-timing-biomechanical-determinants-of-effectiveness-and-evidence-based-evaluation-thresholds
44. Introducing My Stuff+ Model | Adam Salorio | Medium, https://medium.com/@adamsalorio/introducing-my-stuff-model-2840f196cf01
45. PitchingBot: Using Machine Learning To Understand What Makes a Good Pitch - FanGraphs, https://community.fangraphs.com/pitchingbot-using-machine-learning-to-understand-what-makes-a-good-pitch/
46. PitchingBot - An Overview, https://baseballaheadinthecount.blogspot.com/2021/03/pitchingbot-overview.html
47. A PitchingBot Overhaul, https://baseballaheadinthecount.blogspot.com/2021/10/a-pitchingbot-overhaul.html
48. Stuff+, Location+, and Pitching+ Primer | Sabermetrics Library, https://library.fangraphs.com/pitching/stuff-location-and-pitching-primer/
49. Introducing Stuff+, Location+, and Pitching+ - Max's Sporting Studio, https://maxsportingstudio.com/introducing-stuff-location-and-pitching/
50. Does Swinging Less Mean Swinging at Better Pitches? - FanGraphs Baseball, https://blogs.fangraphs.com/does-swinging-less-mean-swinging-at-better-pitches/
51. Using PLA to Evaluate Pitchers - Set Up Guys Edition, https://pitcherlist.com/using-pla-to-evaluate-pitchers-set-up-guys-edition/
52. Welcome To PL8 - Here's What New On Our Website - Pitcher List, https://pitcherlist.com/welcome-to-pl8-heres-what-new-on-our-website/
53. Nastiest Fastballs in Baseball - Pitcher List, https://pitcherlist.com/nastiest-fastballs-in-baseball/
54. PitchingBot Pitch Modeling Primer | Sabermetrics Library, https://library.fangraphs.com/pitching/pitchingbot-pitch-modeling-primer/
55. Using Linear Weights to Evaluate Swing Decisions | Matthew Creally | Medium, https://medium.com/@mattjcreally/using-linear-weights-to-evaluate-swing-decisions-956ea6c14105
56. The Markov Chain Model of Baseball - statshacker, http://statshacker.com/blog/2018/05/07/the-markov-chain-model-of-baseball/
57. Markov chain - Wikipedia, https://en.wikipedia.org/wiki/Markov_chain
58. Baseball Analysis Using Markov Chains - Digital Commons @ Cal Poly, https://digitalcommons.calpoly.edu/cgi/viewcontent.cgi?article=1063&context=statsp
59. A Markov Chain Model for Run Production in Baseball - Winthrop University, http://faculty.winthrop.edu/polaskit/Spring13/Baseball.pdf
60. Optimal Pitch Selection Policies Via Markov Decision Processes - Harvard DASH, https://dash.harvard.edu/bitstreams/d93a8996-9c66-45a0-94cf-e7db9d36831b/download
61. The Impacts of Increasingly Complex Matchup Models on Baseball Win Probability - arXiv, https://arxiv.org/html/2511.17733v1
62. need the right formula - OOTP Developments Forums, https://forums.ootpdevelopments.com/showthread.php?t=165767
