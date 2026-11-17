param(
    [ValidateSet('Install','Status','Remove')]
    [string]$Action='Status',
    [ValidatePattern('^([01][0-9]|2[0-3]):[0-5][0-9]$')]
    [string]$At='21:30',
    [switch]$AfternoonUnified
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$task='AStockDataTools-ParquetLiveSync'
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
$scheduled=Join-Path $module 'scheduled-update.ps1'
$retryAt=''
if($AfternoonUnified -and $Action -eq 'Install'){
    if($At -ne '21:30'){throw 'AfternoonUnified computes China 16:30 and 20:45 in PC local time; omit -At'}
    if(Test-Path -LiteralPath (Join-Path $module 'work\qmt_extra\schedule-enabled.json') -PathType Leaf){throw 'Legacy extras opt-in exists; refuse duplicate supplementary update'}
    $oldFinance=Get-ScheduledTask -TaskName 'AStockDataTools-QMT-Financial-Daily' -ErrorAction SilentlyContinue
    if($null -ne $oldFinance){throw 'Independent 00:30 finance task exists; resolve schedule conflict before opt-in'}
    $scheduled=Join-Path $module 'scheduled-afternoon-update.ps1'
    $shanghai=[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
    $nowChina=[TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$shanghai)
    $dateChina=$nowChina.Date
    $marketFirstUtc=[TimeZoneInfo]::ConvertTimeToUtc($dateChina.AddHours(16).AddMinutes(30),$shanghai)
    $marketRetryUtc=[TimeZoneInfo]::ConvertTimeToUtc($dateChina.AddHours(20).AddMinutes(45),$shanghai)
    $At=[TimeZoneInfo]::ConvertTimeFromUtc($marketFirstUtc,[TimeZoneInfo]::Local).ToString('HH:mm')
    $retryAt=[TimeZoneInfo]::ConvertTimeFromUtc($marketRetryUtc,[TimeZoneInfo]::Local).ToString('HH:mm')
}
$updater=Join-Path $module 'update-market.ps1'
if($Action -eq 'Status'){
    $entry=Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    if($null -eq $entry){
        Write-Host 'MARKET_SCHEDULE_NOT_INSTALLED'
    }else{
        $entry | Select-Object TaskName,State,TaskPath | Format-List
        Get-ScheduledTaskInfo -TaskName $task |
            Select-Object LastRunTime,LastTaskResult,NextRunTime | Format-List
    }
    $last=Join-Path $module 'work\last-scheduled-run.json'
    if(Test-Path -LiteralPath $last -PathType Leaf){
        Get-Content -LiteralPath $last -Raw -Encoding UTF8
    }
    exit 0
}
if($Action -eq 'Remove'){
    $entry=Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    if($null -ne $entry){
        Unregister-ScheduledTask -TaskName $task -Confirm:$false
        Write-Host 'MARKET_SCHEDULE_REMOVED_OUR_SINGLE_TASK_ONLY'
    }else{Write-Host 'MARKET_SCHEDULE_ALREADY_NOT_INSTALLED'}
    exit 0
}
$python=Join-Path $repo '.venv\Scripts\python.exe'
if(-not (Test-Path -LiteralPath $python -PathType Leaf)){
    throw 'Missing project .venv Python; cannot install market schedule'
}
if(-not (Test-Path -LiteralPath 'D:\stock\AllCycleAStockData\1min' -PathType Container)){
    throw 'Missing physical stock Parquet dataset; cannot install market schedule'
}
if(-not (Test-Path -LiteralPath $scheduled -PathType Leaf) -or
   -not (Test-Path -LiteralPath $updater -PathType Leaf)){
    throw 'Unified market updater or schedule runner missing'
}
$engine=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments=('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $scheduled)
$taskExecAction=New-ScheduledTaskAction -Execute $engine -Argument $arguments -WorkingDirectory $repo
$trigger=New-ScheduledTaskTrigger -Daily -At $At
$triggers=@($trigger)
if($AfternoonUnified){$triggers+=New-ScheduledTaskTrigger -Daily -At $retryAt}
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 4)
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal=New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$description='Single QMT+eltdx+Tencent source validation, TDX DAY, calibrated 5/15/30/60m, closed WEEK/MONTH. Interactive QMT session required. Never runs old DAY-only path.'
if($AfternoonUnified){$description='16:30 China market four-section guarded update plus 20:45 market-only retry; financial/adjustments partial until source coverage audited'}
Register-ScheduledTask -TaskName $task -Action $taskExecAction -Trigger $triggers -Settings $settings -Principal $principal -Description $description -Force | Out-Null
Write-Host ('MARKET_SCHEDULE_INSTALLED task='+$task+' local_time='+$At+' user='+$identity)
if($AfternoonUnified){Write-Host ('MARKET_1630_INSTALLED china_start=16:30 china_retry=20:45 pc_local_start='+$At+' pc_local_retry='+$retryAt)}
Write-Host 'MARKET_SCHEDULE_QMT_REQUIREMENT=Windows must be logged in, QMT connected, machine awake; missed runs resume on next opportunity'
Write-Host 'MARKET_SCHEDULE_MODE=UNIFIED_ALL_EIGHT_PERIODS one task only; status: install-schedule.ps1 -Action Status'
