# One daily 20:05 China-time trigger. No midnight finance task or delayed re-run.
param([ValidateSet('Install','Status','Remove')][string]$Action='Status')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$task='AStockDataTools-ParquetLiveSync'
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
$scheduled=Join-Path $module 'scheduled-afternoon-update.ps1'
if($Action -eq 'Status'){
    $entry=Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    if($null -eq $entry){
        Write-Host 'MARKET_SCHEDULE_NOT_INSTALLED'
    }else{
        $entry | Select-Object TaskName,State,TaskPath | Format-List
        $entry.Actions | Select-Object Execute,Arguments,WorkingDirectory | Format-List
        $entry.Triggers | Select-Object StartBoundary,Enabled | Format-List
        $entry.Settings | Select-Object ExecutionTimeLimit,MultipleInstances | Format-List
        # CIM ExecutionTimeLimit is commonly an ISO-8601 duration string,
        # not a .NET TimeSpan. Inspect task XML instead of comparing types.
        $taskXml=[xml](Export-ScheduledTask -TaskName $task)
        $xmlNode=$taskXml.SelectSingleNode("/*[local-name()='Task']/*[local-name()='Settings']/*[local-name()='ExecutionTimeLimit']")
        $xmlLimit=if($null -ne $xmlNode){[string]$xmlNode.InnerText}else{'MISSING'}
        Write-Host ('MARKET_TASK_XML_EXECUTION_TIME_LIMIT='+$xmlLimit)
        Write-Host ('MARKET_TASK_XML_RUNTIME_BOUNDED='+($xmlLimit -ne 'PT0S'))
        Get-ScheduledTaskInfo -TaskName $task |
            Select-Object LastRunTime,LastTaskResult,NextRunTime | Format-List
    }
    foreach($name in @('last-afternoon-unified.json','last-precutoff-market-only.json','last-scheduled-run.json')){
        $recent=Join-Path (Join-Path $module 'work') $name
        if(Test-Path -LiteralPath $recent -PathType Leaf){
            Write-Host ('MARKET_LAST_STATUS='+$name)
            Get-Content -LiteralPath $recent -Raw -Encoding UTF8
        }
    }
    $standalone=Get-ScheduledTask -TaskName 'AStockDataTools-QMT-Financial-Daily' -ErrorAction SilentlyContinue
    if($null -ne $standalone){
        Write-Host ('MARKET_STANDALONE_FINANCE_TASK_STATE='+[string]$standalone.State)
    }else{Write-Host 'MARKET_STANDALONE_FINANCE_TASK=NOT_INSTALLED'}
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
if(Test-Path -LiteralPath (Join-Path $module 'work\qmt_extra\schedule-enabled.json') -PathType Leaf){
    throw 'Legacy extras schedule opt-in exists; refuse overlapping supplementary update'
}
$python=Join-Path $repo '.venv\Scripts\python.exe'
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw 'Missing project Python'}
if(-not(Test-Path -LiteralPath 'D:\stock\AllCycleAStockData\1min' -PathType Container)){
    throw 'Missing original physical market dataset'
}
foreach($relative in @('scheduled-afternoon-update.ps1','run-market-catchup.ps1','run-qmt-financial-daily.ps1','qmt_extra_financial_cache_import.py','market_update_push.py','notify-market-update.ps1','market_daily_verification.py','update-market.ps1')){
    if(-not(Test-Path -LiteralPath (Join-Path $module $relative) -PathType Leaf)){
        throw 'Required unified market script missing: '+$relative
    }
}
# Only after validating every mandatory component, disable the old separate
# 00:30 finance task. Preserve registration for rollback; refuse overlap.
$oldFinance=Get-ScheduledTask -TaskName 'AStockDataTools-QMT-Financial-Daily' -ErrorAction SilentlyContinue
if($null -ne $oldFinance -and [string]$oldFinance.State -ne 'Disabled'){
    # User explicitly requires no separate 00:30 finance run. Disable only
    # this known, named task; preserve its registration for easy rollback.
    Disable-ScheduledTask -TaskName 'AStockDataTools-QMT-Financial-Daily' -ErrorAction Stop | Out-Null
    $afterDisable=Get-ScheduledTask -TaskName 'AStockDataTools-QMT-Financial-Daily' -ErrorAction Stop
    if([string]$afterDisable.State -ne 'Disabled'){throw 'Standalone finance task remains active'}
    Write-Host 'MARKET_0030_STANDALONE_FINANCE_TASK_DISABLED=TRUE'
}
# Convert once to PC-local clock time. There is exactly ONE trigger.
$shanghai=[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$todayChina=([TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$shanghai)).Date
$utc=[TimeZoneInfo]::ConvertTimeToUtc($todayChina.AddHours(20).AddMinutes(5),$shanghai)
$at=[TimeZoneInfo]::ConvertTimeFromUtc($utc,[TimeZoneInfo]::Local).ToString('HH:mm')
$engine=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments=('-NoProfile -WindowStyle Normal -ExecutionPolicy Bypass -File "{0}" -Apply' -f $scheduled)
$taskExecAction=New-ScheduledTaskAction -Execute $engine -Argument $arguments -WorkingDirectory $repo
$trigger=New-ScheduledTaskTrigger -Daily -At $at
# Absolute latest task runtime from normal 20:05 start: 23:45 China time.
# No StartWhenAvailable: do not replay a missed evening job after midnight.
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3 -Minutes 40)
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal=New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$description='One 20:05 China-time K-lines/sectors/adjustments/finance-last run; before-midnight bounded, WeCom push and durable receipt'
Register-ScheduledTask -TaskName $task -Action $taskExecAction -Trigger $trigger -Settings $settings -Principal $principal -Description $description -Force | Out-Null
Write-Host ('MARKET_2005_INSTALLED task='+$task+' china_start=20:05 pc_local_start='+$at+' triggers=1 runtime_limit=03:40:00 user='+$identity)
Write-Host 'MARKET_SCHEDULE_MODE=ONE_DAILY_2005_ALL_FOUR_SECTIONS; TASK_NOTIFICATIONS=WECOM_PRIVATE_OPT_IN; WINDOWS_TOAST=OFF; MISSED_NIGHTLY_CATCHUP=OFF'
Write-Host 'MARKET_QMT_REQUIREMENT=Logged-in Windows user and connected QMT; machine awake for execution'
