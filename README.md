# Fantasy Baseball Assistant

Automates the tedious parts of managing an ESPN fantasy baseball team, driven from the
terminal (and by Claude in chat). It computes the optimal daily lineup and auto-applies
it, and surfaces streaming-pitcher and waiver-pickup recommendations.

- **Lineup optimization** — starts players who actually play today and aren't injured,
  fills the scarcest slots first, benches the rest, parks the injured on the IL.
  Auto-applied.
- **Waivers & streaming** — free-agent starters with an upcoming start, and hitters who
  out-project your weakest bats. **Recommendations only** (ask-first; you confirm before
  any add/drop).

## How it works

| Concern | Source |
|---|---|
| Reads (roster, free agents, matchup, settings) | [`espn-api`](https://github.com/cwendt94/espn-api) library |
| "Who plays today", probable pitchers, opponents, venues | MLB Stats API (`statsapi.mlb.com`, no auth) |
| Team offense (matchup quality) | MLB Stats API team hitting stats |
| Writes (set lineup, add/drop) | ESPN's authenticated transactions API (a direct POST) |
| Notifications | Email via the dedicated agent Gmail (SMTP) |

### Streaming model

Free-agent starters are scored, not just ranked by projection. Each upcoming start gets a
0–100 score blending four components (50 = league average):

- **talent** (30%) — ESPN season *projection* (ERA / WHIP / K-9)
- **form** (25%) — actual *season-to-date* stats
- **matchup** (30%) — opponent team OPS (weaker lineup → higher)
- **park** (15%) — run park factor of the game's venue (pitcher park → higher)

`gain` is the score minus the skill of the weakest arm you'd drop, so only genuine
upgrades surface. Weights/constants live at the top of [analysis/streaming.py](analysis/streaming.py).

ESPN has no official API. The community library reliably *reads* a league but can't
*write*, so writes are a direct POST to ESPN's transactions endpoint. The same
`espn_s2`/`SWID` cookies authenticate both the read and write hosts — so once cookies are
saved, no browser is involved. Run all automation as a dedicated **co-manager** account to
keep it isolated from your personal login.

> Note: we initially tried browser automation (Playwright) for writes, but ESPN's website
> needs a full Disney login session that bot-detection blocks, while the API authenticates
> with just the two cookies. So the API is both simpler and the path that actually works.

```
config.py          settings + cookie loading        cli.py         on-demand commands
setup_cookies.py   save ESPN auth cookies           daily_job.py   scheduled morning run
notify.py          email notifications              pipeline.py    shared orchestration
espn_client/       ESPN API reader + writer         analysis/      lineup, streaming, waivers
data/              schedule, team offense, parks    tests/         offline unit tests
```

## Setup

### 1. Create a dedicated co-manager account
1. Make a new email (e.g. Gmail) and a new **ESPN/Disney account** with it at
   <https://www.espn.com>.
2. From your **personal** ESPN account that owns the team, invite the new account as a
   **co-manager**: League → Members/Manager Tools → *Manage Co-Managers* (or the
   "Invite" flow), and accept the invite from the new account.
   *(Co-managers can set lineups and make roster moves — exactly what the tool needs.)*

### 2. Install
```powershell
cd "C:\Users\molus\projects\fantasy baseball"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
(The `.venv` is already created. If recreating: `py -3.12 -m venv .venv` first.)

### 3. Configure
Copy `.env.example` to `.env` and fill in:
- `ESPN_LEAGUE_ID` — from the league URL (`...?leagueId=123456`)
- `ESPN_TEAM_ID` — from your team URL (`...&teamId=7`)
- `ESPN_YEAR` — season (e.g. `2026`)
- `TIMEZONE` — e.g. `America/Toronto`

### 4. Authenticate once

Paste the two ESPN auth cookies from a browser where you're already logged in:

```powershell
.\.venv\Scripts\python.exe setup_cookies.py
```
Find them in your normal browser: DevTools (F12) → Application → Cookies →
`https://fantasy.espn.com` → copy the values of **`espn_s2`** and **`SWID`** (SWID looks
like `{AAAA-BBBB-...}`). Log in with the **co-manager** account for full read+write; your
personal account also works for read-only testing. Your cookie values stay on this
machine, in `.auth/cookies.json` (git-ignored). Re-run when the cookies expire.

### 5. Email notifications (optional)

The daily job emails a summary (lineup changes + recommendations) from your dedicated
agent Gmail. In `.env` set `EMAIL_SENDER` (that Gmail), `EMAIL_RECIPIENT` (your inbox), and
`EMAIL_APP_PASSWORD` — a Gmail **App Password**:
1. Enable 2-Step Verification on the agent account.
2. <https://myaccount.google.com/apppasswords> → create one → paste the 16 chars.

Leave blank to disable (the job still runs and writes its report).

## Usage

```powershell
python cli.py status            # record, current matchup, standings
python cli.py team              # roster with today's availability + projections
python cli.py lineup            # show optimal moves (dry run — nothing submitted)
python cli.py lineup --execute  # apply the moves on ESPN
python cli.py waivers           # streaming + best-available recommendations
python cli.py waivers --days 3  # widen the look-ahead window for starts
```

Run the scheduled job manually any time:
```powershell
python daily_job.py             # auto-set lineup + write reports/YYYY-MM-DD.md
```
To schedule it every morning, see [scheduler_setup.md](scheduler_setup.md).

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest
```
Tests run fully offline against hand-built fixtures (no ESPN/network) — they cover the
optimizer (benching, eligibility, scarcity, points vs category ranking, IL handling),
the waiver logic, and the MLB schedule parser.

## Notes & caveats

- **Writes are an undocumented API.** ESPN can change it; if a write is rejected, the
  tools report ESPN's response and you can apply the move in the app. Reads and
  recommendations keep working regardless.
- **Cookie expiry:** the saved cookies last a while but not forever; when reads/writes
  start failing auth, re-run `setup_cookies.py`.
- **Scheduled runs need this machine on** at run time (kept local so cookies never go to
  the cloud).
- **Secrets** (`.env`, `.auth/`) and `reports/` are git-ignored. Never commit them.
- Use is personal management of your own team via a co-manager account; keep run
  frequency human-like.
