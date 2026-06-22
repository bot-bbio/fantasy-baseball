# Scheduling the jobs (Windows Task Scheduler)

Two tasks work together:

1. **Daily job** (`daily_job.py`) -- each morning, builds the optimal lineup and the
   waiver/add-drop recommendations, **queues** them, and emails you the proposal. It does
   **not** touch ESPN.
2. **Approval poller** (`apply_job.py`) -- runs frequently, checks the agent Gmail for your
   reply (`apply all` / `apply 1,3` / `no`), and applies only what you approved.

Both run **locally** so your ESPN session/cookies never leave your machine. Your computer
must be on (and awake) at the scheduled times.

## Register the task

Run this once in **PowerShell** (adjust the time if you like):

```powershell
$root    = "C:\Users\molus\projects\fantasy baseball"
$python  = Join-Path $root ".venv\Scripts\python.exe"
$script  = Join-Path $root "daily_job.py"

$action  = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun

Register-ScheduledTask -TaskName "FantasyBaseballDaily" -Action $action `
  -Trigger $trigger -Settings $settings `
  -Description "ESPN fantasy: build proposal + email for approval"
```

`-StartWhenAvailable` runs the task late if the machine was off at 9:00am; `-WakeToRun`
lets it wake the machine from sleep.

## Register the approval poller

Run this once. The repetition trigger checks your inbox every 20 minutes all day, so a
reply is picked up soon after you send it:

```powershell
$root    = "C:\Users\molus\projects\fantasy baseball"
$python  = Join-Path $root ".venv\Scripts\python.exe"
$script  = Join-Path $root "apply_job.py"

$action  = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At 9:05am `
  -RepetitionInterval (New-TimeSpan -Minutes 20) -RepetitionDuration (New-TimeSpan -Hours 14)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable

Register-ScheduledTask -TaskName "FantasyBaseballPoller" -Action $action `
  -Trigger $trigger -Settings $settings `
  -Description "ESPN fantasy: apply approved changes from email replies"
```

Requires the confirmation settings in `.env` (`IMAP_HOST`, `CONFIRM_FROM`, and IMAP enabled
on the agent Gmail). Set `LINEUP_FALLBACK_MINUTES` if you want the poller to auto-apply the
lineup (only) when you haven't replied in time.

## Run a second time each day (optional)

Lineups can change with late scratches. To also run at, say, 4:00pm, add a trigger:

```powershell
$t2 = New-ScheduledTaskTrigger -Daily -At 4:00pm
Set-ScheduledTask -TaskName "FantasyBaseballDaily" `
  -Trigger @((Get-ScheduledTask -TaskName "FantasyBaseballDaily").Triggers + $t2)
```

## Manage the task

```powershell
Start-ScheduledTask     -TaskName "FantasyBaseballDaily"   # run now
Get-ScheduledTaskInfo   -TaskName "FantasyBaseballDaily"   # last run / result
Unregister-ScheduledTask -TaskName "FantasyBaseballDaily" -Confirm:$false   # remove
```

## Approving changes

The daily email lists every proposed change as a numbered item. Reply with `apply all`,
`apply 1,3` (or `apply 1-2`), or `no`. The poller applies your selection and emails the
result. No reply means nothing happens (unless `LINEUP_FALLBACK_MINUTES` is set).

From a computer you can skip email entirely: `python cli.py pending` to see the queue and
`python cli.py apply --all` (or `--only 1,3`) to apply it; `python cli.py poll` runs one
inbox check on demand.

## Where to read results

Each run writes `reports/YYYY-MM-DD.md`. If the session has expired, the report says so;
re-run `setup_cookies.py` to refresh the login.
