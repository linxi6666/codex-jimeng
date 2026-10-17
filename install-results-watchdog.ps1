$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$python=Join-Path $HOME '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe'
$script=Join-Path $root 'results_watchdog.py'
if(-not (Test-Path -LiteralPath $python)){throw 'pythonw.exe not found'}
$action=New-ScheduledTaskAction -Execute $python -Argument ('"'+$script+'"') -WorkingDirectory $root
$trigger=New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings=New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'DreaminaCanvasResultsWatchdog' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Same-user Dreamina results supervisor, port 8769; restarts exited servers without generation.' -Force | Out-Null
Start-ScheduledTask -TaskName 'DreaminaCanvasResultsWatchdog'
Write-Output 'TASK_INSTALLED'
