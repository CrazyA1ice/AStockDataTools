# Installs only a SECONDARY independent WeCom monitor. Never edits 20:05 task.
param([ValidateSet('Status','Install')][string]$Action='Status',[switch]$ApproveDailySelfSend)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$name='AStockDataTools-WeCom-Report'
$module=Split-Path -Parent $MyInvocation.MyCommand.Path
$repo=Split-Path -Parent $module
$monitor=Join-Path $module 'run-market-wecom-monitor.ps1'
$remote='/home/ubuntu/.local/bin/astock-market-wecom-once.py'
$dest='ubuntu@43.142.32.208'
$key=Join-Path $env:USERPROFILE '.ssh\astock-market-wecom-only'
$main=Get-ScheduledTask -TaskName 'AStockDataTools-ParquetLiveSync' -TaskPath '\' -ErrorAction Stop
$existing=Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
if($Action -eq 'Status'){
    [pscustomobject]@{MonitorInstalled=[bool]$existing;MainTaskState=[string]$main.State;SshKeyExists=[bool](Test-Path -LiteralPath $key -PathType Leaf);RemoteCodePath=$remote;MainTaskUntouched=$true}|Format-List
    return
}
if(-not $ApproveDailySelfSend){throw 'EXPLICIT_DAILY_SELF_SEND_APPROVAL_REQUIRED'}
if($existing){throw 'SECONDARY_TASK_EXISTS_NO_OVERWRITE'}
if(!(Test-Path -LiteralPath $monitor -PathType Leaf)){throw 'MONITOR_NOT_INSTALLED'}
if(!(Test-Path -LiteralPath (Join-Path $module 'market_wecom_report.py') -PathType Leaf)){throw 'OBSERVER_NOT_INSTALLED'}
if(!(Test-Path -LiteralPath (Join-Path $repo '.venv\Scripts\python.exe') -PathType Leaf)){throw 'PYTHON_NOT_INSTALLED'}
if(!(Test-Path -LiteralPath $key -PathType Leaf)){throw 'BATCH_SSH_KEY_MISSING_STOP'}
# All explicit HostKeyChecking and SSH BatchMode; no prompt in background.
$probe='{"mode":"preflight"}' | & ssh.exe -T -p 22 -o BatchMode=yes -o PreferredAuthentications=publickey -o StrictHostKeyChecking=yes -o ClearAllForwardings=yes -o ConnectTimeout=10 -i $key $dest 'id -un'
if($LASTEXITCODE -ne 0 -or @($probe).Count -ne 1 -or [string](@($probe)[0]) -ne 'WECOM_MARKET_PREFLIGHT_OK'){throw 'FORCED_COMMAND_OR_SSH_KEY_NOT_READY_NO_INSTALL'}
$tz=[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$today=[TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$tz).Date
$utc=[TimeZoneInfo]::ConvertTimeToUtc($today.AddHours(20).AddMinutes(10),$tz)
$at=[TimeZoneInfo]::ConvertTimeFromUtc($utc,[TimeZoneInfo]::Local)
$exe=(Get-Command powershell.exe -ErrorAction Stop).Source
$arguments='-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$monitor+'" -ApproveSelfSend'
$action=New-ScheduledTaskAction -Execute $exe -Argument $arguments -WorkingDirectory $repo
$trigger=New-ScheduledTaskTrigger -Daily -At $at
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::FromHours(8))
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal=New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -TaskPath '\' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Read-only post-market receipt monitor: one owner WeCom message after 20:05 task' -ErrorAction Stop | Out-Null
Write-Host 'MARKET_WECOM_SECONDARY_TASK_INSTALLED_NO_MAIN_TASK_MODIFICATION'
