# Scheduling the daily job (Windows Task Scheduler)

The daily job auto-sets your lineup and writes a recommendations report. It runs
**locally** so your ESPN session/cookies never leave your machine. Your computer must
be on (and awake) at the scheduled time.

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
  -Description "ESPN fantasy: auto-lineup + waiver report"
```

`-StartWhenAvailable` runs the task late if the machine was off at 9:00am; `-WakeToRun`
lets it wake the machine from sleep.

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

## Where to read results

Each run writes `reports/YYYY-MM-DD.md`. If the session has expired, the report says
so and lists the lineup moves to apply manually until you re-run `setup_login.py`.
