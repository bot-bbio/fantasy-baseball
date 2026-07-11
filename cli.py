"""On-demand command line interface.

    python cli.py status              # team record, matchup, standings
    python cli.py team                # full roster with today's availability
    python cli.py lineup [--execute]  # show optimal lineup moves (default: dry run)
    python cli.py waivers [--days N]  # streaming + best-available recommendations

This is also what Claude calls in chat to pull live data before giving advice.
"""
from __future__ import annotations

import argparse
import sys

from tabulate import tabulate
from espn_api.requests.espn_requests import ESPNAccessDenied

import apply as apply_mod
import apply_job
import config
import pipeline
from analysis.lineup import is_probable_today
from analysis.scoring import compute_category_scores
from data import mlb_schedule
from espn_client.reader import LeagueReader
from models import RosterPlayer, normalize_name
from pending import LINEUP, PendingQueue, parse_numbers
from streamer_state import StreamerLog


def _availability(player, schedule) -> str:
    if player.is_out:
        return f"OUT ({player.injury_status})"
    plays = schedule.team_plays(player.pro_team)
    if player.is_pitcher:
        if is_probable_today(player, schedule):
            return "Starting"
        if "RP" in player.eligible_slots and plays:
            return "RP avail"
        return "-"
    return "Plays" if plays else "-"


def cmd_status(args: argparse.Namespace) -> int:
    reader = LeagueReader()
    league = reader.league
    team = reader.my_team()
    print(f"League : {league.settings.name}  ({reader.scoring_format()})")
    print(f"Team   : {team.team_name}  [{team.wins}-{team.losses}-{team.ties}]  "
          f"standing #{team.standing}")

    box = reader.current_box_score()
    if box is not None:
        home, away = box.home_team, box.away_team
        print(f"\nMatchup: {getattr(home, 'team_name', home)} "
              f"vs {getattr(away, 'team_name', away)}")
        if hasattr(box, "home_score"):
            print(f"  score: {box.home_score} - {box.away_score}")

    print("\nStandings:")
    rows = [(i + 1, t.team_name, f"{t.wins}-{t.losses}-{t.ties}")
            for i, t in enumerate(reader.standings())]
    print(tabulate(rows, headers=["#", "Team", "Record"], tablefmt="simple"))
    return 0


def cmd_team(args: argparse.Namespace) -> int:
    reader = LeagueReader()
    schedule = mlb_schedule.fetch_day(config.local_today(reader.settings.timezone))
    roster = reader.roster()

    if reader.is_points_league():
        value_header = "Proj"
        value_of = lambda p: round(p.projected_points, 1)  # noqa: E731
    else:
        scores = compute_category_scores(roster, reader.scored_categories())
        value_header = "Val"  # composite category z-score (what the optimizer ranks on)
        value_of = lambda p: round(scores.get(p.player_id, 0.0), 1)  # noqa: E731

    rows = [
        [p.lineup_slot or "-", p.name, p.pro_team, _availability(p, schedule), value_of(p)]
        for p in sorted(roster, key=lambda x: (x.lineup_slot == "BE", x.lineup_slot))
    ]
    print(tabulate(rows, headers=["Slot", "Player", "Team", "Today", value_header],
                   tablefmt="simple"))
    return 0


def cmd_lineup(args: argparse.Namespace) -> int:
    reader = LeagueReader()
    schedule = mlb_schedule.fetch_day(config.local_today(reader.settings.timezone))
    plan, _ = pipeline.build_lineup_plan(reader, schedule)

    if not plan.has_changes:
        print("Lineup already optimal - no moves needed.")
    else:
        print("Proposed moves:")
        rows = [[m.name, m.from_slot, "->", m.to_slot] for m in plan.moves]
        print(tabulate(rows, headers=["Player", "From", "", "To"], tablefmt="simple"))
    if plan.empty_slots:
        print(f"\n! Could not fill: {', '.join(plan.empty_slots)} (no one available today)")

    if not args.execute:
        print("\n(dry run - use --execute to apply)")
        return 0
    if not plan.has_changes:
        return 0

    from espn_client.writer import LineupWriter, WriteError

    try:
        result = LineupWriter(reader.settings).set_lineup(
            plan, reader.scoring_period, dry_run=False
        )
    except WriteError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 4

    print(f"\n{result.message}")
    if not result.ok:
        return 4

    # Verify via a fresh read.
    after_plan, _ = pipeline.build_lineup_plan(LeagueReader(), schedule)
    if after_plan.has_changes:
        print("! Verification: lineup still differs from optimal after write:")
        for move in after_plan.moves:
            print(f"    {move}")
    else:
        print("Verified: ESPN lineup now matches the optimal plan.")
    return 0


def cmd_waivers(args: argparse.Namespace) -> int:
    reader = LeagueReader()
    schedules = pipeline.upcoming_schedules(reader.settings.timezone, days=args.days)
    streams, hitters = pipeline.gather_waiver_recs(reader, schedules, size=args.size)

    try:
        print(f"Add/drop budget: {reader.acquisition_budget().describe()}.\n")
    except Exception:
        pass  # informational only; never block the recommendations on it

    print("Streaming pitchers (model: talent + form + matchup + park):")
    if streams:
        rows = [[s.evaluation.player.name, s.evaluation.player.pro_team,
                 s.evaluation.start_label or s.evaluation.start_day,
                 round(s.evaluation.score), round(s.evaluation.talent),
                 round(s.evaluation.form), s.evaluation.summary,
                 _drop_label(s), round(s.value_gain, 1)]
                for s in streams]
        print(tabulate(rows, headers=["Add", "Team", "Start", "Score", "Tal", "Form",
                                      "Matchup", "Drop", "Gain"], tablefmt="simple"))
        print("  (research deep-links are included in the daily report)")
        print("  Drop key: 'streamer slot' = recycles a tracked streamer; "
              "'NEW slot' = would become your streamer slot.")
    else:
        print("  (none worth streaming right now)")

    print("\nBest available hitters (upgrades over your weakest bats):")
    if hitters:
        rows = [[r.add.name, r.add.pro_team,
                 r.drop.name if r.drop else "-", round(r.value_gain, 1)]
                for r in hitters]
        print(tabulate(rows, headers=["Add", "Team", "Drop", "Gain"],
                       tablefmt="simple"))
    else:
        print("  (no clear upgrades available)")

    print("\nThese are recommendations only. Adds/drops are ask-first - confirm before executing.")
    return 0


def _drop_label(rec) -> str:
    """Human-readable drop cell that flags whether it recycles the streamer slot."""
    if rec.drop is None:
        return "-"
    tag = "streamer slot" if rec.drop_is_streamer else "NEW slot"
    return f"{rec.drop.name} ({tag})"


def _maybe_int(token: str) -> int | None:
    try:
        return int(token)
    except (TypeError, ValueError):
        return None


def _resolve_player(token: str, pool: list[RosterPlayer]) -> RosterPlayer | None:
    """Find a player in `pool` by exact player id or normalized name."""
    pid = _maybe_int(token)
    if pid is not None:
        for p in pool:
            if p.player_id == pid:
                return p
    target = normalize_name(token)
    for p in pool:
        if normalize_name(p.name) == target:
            return p
    return None


def cmd_streamer(args: argparse.Namespace) -> int:
    """View the tracked streamer slot(s), or record an add/drop you made on ESPN."""
    reader = LeagueReader()
    roster = reader.roster()
    log = StreamerLog.load()
    changed = log.sync(roster)  # forget streamers no longer on the roster

    if args.add:
        pool = roster + reader.free_agents(size=200)
        player = _resolve_player(args.add, pool)
        if player is None:
            print(f"Could not find a player matching {args.add!r}.", file=sys.stderr)
            return 1
        log.record_add(player)
        changed = True
        print(f"Tracking {player.name} as the current streamer slot.")

    if args.drop:
        player = _resolve_player(args.drop, roster)
        target_id = player.player_id if player else _maybe_int(args.drop)
        if target_id is None:
            print(f"Could not find a streamer matching {args.drop!r}.", file=sys.stderr)
            return 1
        log.record_drop(target_id)
        changed = True
        print(f"Stopped tracking {player.name if player else target_id} as a streamer.")

    if changed:
        log.save()

    if not log.entries:
        print("No streamer slots tracked yet. They populate as you stream pitchers in.")
        return 0

    roster_ids = {p.player_id for p in roster}
    current = log.current(roster_ids)
    rows = [["->" if e["player_id"] == current else "", e["name"], e.get("pro_team", ""),
             e.get("added_on", ""), e.get("start_day") or "-",
             "on roster" if e["player_id"] in roster_ids else "off roster"]
            for e in log.entries]
    print(tabulate(rows, headers=["", "Streamer", "Team", "Added", "Start", "Status"],
                   tablefmt="simple"))
    print("\n'->' marks the slot a new streamer would recycle (protects your core arms).")
    return 0


def cmd_pending(args: argparse.Namespace) -> int:
    """Show the queued, awaiting-confirmation changes (no ESPN call)."""
    queue = PendingQueue.load()
    if queue is None or queue.is_empty:
        print("No pending changes queued.")
        return 0
    print(f"Queue token: {queue.token}  (created {queue.created})")
    for item in queue.items:
        print(f"\n{item.n}. {item.description}")
        if item.kind == LINEUP:
            for m in item.payload.get("moves", []):
                print(f"     {m['name']}: {m['from_slot']} -> {m['to_slot']}")
    print("\nApply with: python cli.py apply --all   (or --only 1,3)")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Apply queued changes from a computer (the no-phone fallback for `poll`)."""
    queue = PendingQueue.load()
    if queue is None or queue.is_empty:
        print("No pending changes to apply.")
        return 0

    if args.all:
        selection: str | set[int] = "all"
    elif args.only:
        selection = parse_numbers(args.only)
    else:
        print("Specify --all or --only N[,N-M] (see `python cli.py pending`).",
              file=sys.stderr)
        return 1

    items = queue.select(selection)
    if not items:
        print("Selection matched no queued items.", file=sys.stderr)
        return 1

    settings = config.get_settings(require_cookies=True)
    reader = LeagueReader(settings)
    for line in apply_mod.apply_selection(items, reader=reader, settings=settings):
        print(line)

    applied = {i.n for i in items}
    queue.items = [i for i in queue.items if i.n not in applied]
    if queue.items:
        queue.save()
    else:
        queue.consume()
    return 0


def cmd_poll(args: argparse.Namespace) -> int:
    """Check the inbox once for a confirmation reply and apply what was approved."""
    settings = config.get_settings(require_cookies=True)
    print(apply_job.poll_once(settings))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ESPN fantasy baseball assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="team record, matchup, standings").set_defaults(func=cmd_status)
    sub.add_parser("team", help="roster with today's availability").set_defaults(func=cmd_team)

    p_lineup = sub.add_parser("lineup", help="optimal lineup (dry run by default)")
    p_lineup.add_argument("--execute", action="store_true", help="apply the moves on ESPN")
    p_lineup.set_defaults(func=cmd_lineup)

    p_waivers = sub.add_parser("waivers", help="streaming + best-available recs")
    p_waivers.add_argument("--days", type=int, default=config.STREAM_LOOKAHEAD_DAYS,
                           help="rolling look-ahead window (days) for probable starts")
    p_waivers.add_argument("--size", type=int, default=75, help="free-agent pool size")
    p_waivers.set_defaults(func=cmd_waivers)

    p_streamer = sub.add_parser("streamer", help="view/track the disposable streamer slot")
    p_streamer.add_argument("--add", metavar="NAME_OR_ID",
                            help="record a pitcher you streamed in (becomes the streamer slot)")
    p_streamer.add_argument("--drop", metavar="NAME_OR_ID",
                            help="record a streamer you dropped (stops tracking it)")
    p_streamer.set_defaults(func=cmd_streamer)

    sub.add_parser("pending", help="show queued, awaiting-confirmation changes") \
        .set_defaults(func=cmd_pending)

    p_apply = sub.add_parser("apply", help="apply queued changes (computer fallback)")
    group = p_apply.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="apply every queued item")
    group.add_argument("--only", metavar="N[,N-M]", help="apply only these item numbers")
    p_apply.set_defaults(func=cmd_apply)

    sub.add_parser("poll", help="check email for a confirmation reply and apply it") \
        .set_defaults(func=cmd_poll)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except config.ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except ESPNAccessDenied:
        print(
            "ESPN denied access (this is a private league). Run "
            "`python setup_login.py` and log in as a league member first.",
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
