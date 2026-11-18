# One Windows task, one daily 20:05 China-time trigger. No other time modes.
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
        $entry.Triggers | Select-Object StartBoundary,Enabled | Format-List
        $entry.Settings | Select-Object ExecutionTimeLimit,MultipleInstances | Format-List
        # CIM ExecutionTimeLimit is commonly an ISO-8601 duration string,
        # not a .NET TimeSpan. Inspect task XML instead of comparing types.
        $taskXml=[xml](Export-ScheduledTask -TaskName $task)
        $xmlNode=$taskXml.SelectSingleNode("/*[local-name()='Task']/*[local-name()='Settings']/*[local-name()='ExecutionTimeLimit']")
        $xmlLimit=if($null -ne $xmlNode){[string]$xmlNode.InnerText}else{'MISSING'}
        Write-Host ('MARKET_TASK_XML_EXECUTION_TIME_LIMIT='+$xmlLimit)
        Write-Host ('MARKET_TASK_XML_RUNTIME_UNLIMITED='+($xmlLimit -eq 'PT0S'))
        Get-ScheduledTaskInfo -TaskName $task |
            Select-Object LastRunTime,LastTaskResult,NextRunTime | Format-List
    }
    foreach($name in @('last-afternoon-unified.json','last-scheduled-run.json')){
        $recent=Join-Path (Join-Path $module 'work') $name
        if(Test-Path -LiteralPath $recent -PathType Leaf){
            Write-Host ('MARKET_LAST_STATUS='+$name)
            Get-Content -LiteralPath $recent -Raw -Encoding UTF8
        }
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
if(Test-Path -LiteralPath (Join-Path $module 'work\qmt_extra\schedule-enabled.json') -PathType Leaf){
    throw 'Legacy extras schedule opt-in exists; refuse overlapping supplementary update'
}
$oldFinance=Get-ScheduledTask -TaskName 'AStockDataTools-QMT-Financial-Daily' -ErrorAction SilentlyContinue
if($null -ne $oldFinance){throw 'Independent finance scheduled task exists; resolve overlap before install'}
$python=Join-Path $repo '.venv\Scripts\python.exe'
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw 'Missing project Python'}
if(-not(Test-Path -LiteralPath 'D:\stock\AllCycleAStockData\1min' -PathType Container)){
    throw 'Missing original physical market dataset'
}
foreach($relative in @('scheduled-afternoon-update.ps1','notify-market-update.ps1','market_daily_verification.py','update-market.ps1')){
    if(-not(Test-Path -LiteralPath (Join-Path $module $relative) -PathType Leaf)){
        throw 'Required unified market script missing: '+$relative
    }
}
# Convert once to PC-local clock time. There is exactly ONE trigger.
$shanghai=[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$todayChina=([TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$shanghai)).Date
$utc=[TimeZoneInfo]::ConvertTimeToUtc($todayChina.AddHours(20).AddMinutes(5),$shanghai)
$at=[TimeZoneInfo]::ConvertTimeFromUtc($utc,[TimeZoneInfo]::Local).ToString('HH:mm')
$engine=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments=('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Apply' -f $scheduled)
$taskExecAction=New-ScheduledTaskAction -Execute $engine -Argument $arguments -WorkingDirectory $repo
$trigger=New-ScheduledTaskTrigger -Daily -At $at
# Zero means no Task Scheduler runtime cap; IgnoreNew prevents overlap.
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal=New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$description='One daily 20:05 China-time market-finance-sectors-adjustments update, with completion/failure desktop notification and durable receipt'
Register-ScheduledTask -TaskName $task -Action $taskExecAction -Trigger $trigger -Settings $settings -Principal $principal -Description $description -Force | Out-Null
Write-Host ('MARKET_2005_INSTALLED task='+$task+' china_start=20:05 pc_local_start='+$at+' triggers=1 runtime_limit=NONE user='+$identity)
Write-Host 'MARKET_SCHEDULE_MODE=ONE_DAILY_2005_ALL_FOUR_SECTIONS; TASK_NOTIFICATIONS=WINDOWS_DESKTOP'
Write-Host 'MARKET_QMT_REQUIREMENT=Logged-in Windows user and connected QMT; machine awake for execution'
