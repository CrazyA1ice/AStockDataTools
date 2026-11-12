param([ValidateSet('Install','Status','Remove')][string]$Action='Status')
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
$arg=('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $script)
$action=New-ScheduledTaskAction -Execute $engine -Argument $arg -WorkingDirectory $root
$trigger=New-ScheduledTaskTrigger -Daily -At '21:30'
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings -Description 'Append only TDX official DAY into SHA-checked private Parquet overlay; retry latest 90 days; do not edit original purchased Parquet/H5' -Force | Out-Null
Write-Host 'INSTALLED_LOCAL_DAILY_PARQUET_TASK 21:30 local clock; private logs: ParquetLiveSync\work\scheduled-update.log'
