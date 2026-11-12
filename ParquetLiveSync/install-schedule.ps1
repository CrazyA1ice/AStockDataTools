param([ValidateSet('Install','Status','Remove')][string]$Action='Status',[switch]$IncludeClosedWeekMonth)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$task='AStockDataTools-ParquetLiveSync'
$module=Split-Path -Parent $PSCommandPath
$script=Join-Path $module 'scheduled-update.ps1'
if($Action -eq 'Status'){
    $entry=Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    if($null -eq $entry){Write-Host 'NOT_INSTALLED AStockDataTools-ParquetLiveSync'}
    else{$entry | Select-Object TaskName,State,TaskPath | Format-List; Get-ScheduledTaskInfo -TaskName $task | Select-Object LastRunTime,LastTaskResult,NextRunTime | Format-List}
    exit 0
}
if($Action -eq 'Remove'){
    $entry=Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    if($null -ne $entry){Unregister-ScheduledTask -TaskName $task -Confirm:$false; Write-Host 'REMOVED_ONLY_OUR_DAILY_PARQUET_TASK'}
    exit 0
}
$root=Split-Path -Parent $module
$python=Join-Path $root '.venv\Scripts\python.exe'
if(-not (Test-Path -LiteralPath $python -PathType Leaf)){throw 'Missing existing .venv Python'}
if(-not (Test-Path -LiteralPath 'D:\stock' -PathType Container)){throw 'Missing original local stock root'}
$engine=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arg=('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $script)
if($IncludeClosedWeekMonth){$arg+=' -IncludeClosedWeekMonth'}
$taskExecAction=New-ScheduledTaskAction -Execute $engine -Argument $arg -WorkingDirectory $root
$trigger=New-ScheduledTaskTrigger -Daily -At '21:30'
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable
$description=if($IncludeClosedWeekMonth){'Opt-in SHA-checked TDX DAY plus purchased-calibrated closed WEEK/MONTH local Parquet; no minutes/H5'}else{'TDX official DAY monthly physical Parquet only; WEEK/MONTH excluded until explicit -IncludeClosedWeekMonth installation'}
Register-ScheduledTask -TaskName $task -Action $taskExecAction -Trigger $trigger -Settings $settings -Description $description -Force | Out-Null
Write-Host ('INSTALLED_LOCAL_DAILY_PARQUET_TASK 21:30 local time; MODE='+$(if($IncludeClosedWeekMonth){'DAY_WEEK_MONTH'}else{'DAY_ONLY'})+'; private log: ParquetLiveSync\work\scheduled-update.log')
