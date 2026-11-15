# Safe Windows PowerShell 5.1 mock: NEVER creates a scheduled task.
# The installed task must run ONE QMT + all-eight-cycle updater, not
# the old day-only three-cycle script. No second scheduler is created.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$installer=Join-Path (Split-Path -Parent $PSScriptRoot) 'install-schedule.ps1'
if(-not ([System.IO.File]::Exists($installer))){throw 'Cannot find Task Scheduler installer'}
$global:MarketMockRegistrations=New-Object System.Collections.ArrayList
function Test-Path {
    param([string]$LiteralPath,[string]$Path,[string]$PathType)
    $item=if($LiteralPath){$LiteralPath}else{$Path}
    if($item -eq 'D:\stock\AllCycleAStockData\1min' -or
       $item.EndsWith('.venv\Scripts\python.exe')){
        return $true
    }
    return [System.IO.File]::Exists($item)
}
function New-ScheduledTaskAction {
    param([string]$Execute,[string]$Argument,[string]$WorkingDirectory)
    return [pscustomobject]@{
        Kind='MockTaskExecAction';Execute=$Execute
        Argument=$Argument;WorkingDirectory=$WorkingDirectory
    }
}
function New-ScheduledTaskTrigger {
    param([switch]$Daily,[string]$At)
    return [pscustomobject]@{Kind='MockTrigger';Daily=[bool]$Daily;At=$At}
}
function New-ScheduledTaskSettingsSet {
    param([switch]$StartWhenAvailable,[string]$MultipleInstances,
          [TimeSpan]$ExecutionTimeLimit)
    return [pscustomobject]@{
        Kind='MockSettings';StartWhenAvailable=[bool]$StartWhenAvailable
        MultipleInstances=$MultipleInstances;ExecutionTimeLimit=$ExecutionTimeLimit
    }
}
function New-ScheduledTaskPrincipal {
    param([string]$UserId,[string]$LogonType,[string]$RunLevel)
    return [pscustomobject]@{UserId=$UserId;LogonType=$LogonType;RunLevel=$RunLevel}
}
function Register-ScheduledTask {
    param([string]$TaskName,$Action,$Trigger,$Settings,$Principal,
          [string]$Description,[switch]$Force)
    if($Action.Kind -ne 'MockTaskExecAction'){
        throw 'Task argument is not mock exec action'
    }
    [void]$global:MarketMockRegistrations.Add([pscustomobject]@{
        Name=$TaskName;Action=$Action;Trigger=$Trigger
        Settings=$Settings;Principal=$Principal
        Description=$Description;Force=[bool]$Force
    })
    return [pscustomobject]@{MockRegistered=$true}
}
& $installer -Action Install
& $installer -Action Install -At '20:45'
if($global:MarketMockRegistrations.Count -ne 2){
    throw 'Expected exactly two mocked task-install calls'
}
$default=$global:MarketMockRegistrations[0]
$custom=$global:MarketMockRegistrations[1]
if($default.Name -ne 'AStockDataTools-ParquetLiveSync' -or
   $custom.Name -ne 'AStockDataTools-ParquetLiveSync'){
    throw 'Must replace ONLY the documented existing stock data task'
}
if($default.Action.Argument -notmatch 'scheduled-update.ps1'){
    throw 'Scheduler must launch the unified scheduled runner'
}
if($default.Action.Argument -match 'IncludeClosedWeekMonth' -or
   $default.Action.Argument -match 'live_sync.py'){
    throw 'Scheduler still uses legacy day-only updates'
}
if($default.Trigger.At -ne '21:30' -or
   $custom.Trigger.At -ne '20:45'){
    throw 'Scheduling local time invalid'
}
if(-not $default.Trigger.Daily -or
   -not $default.Settings.StartWhenAvailable -or
   $default.Settings.MultipleInstances -ne 'IgnoreNew' -or
   $default.Settings.ExecutionTimeLimit.TotalHours -ne 4){
    throw 'Task catchup/overlap/runtime policy invalid'
}
if($default.Principal.LogonType -ne 'Interactive' -or
   $default.Principal.RunLevel -ne 'Limited' -or
   [string]::IsNullOrEmpty($default.Principal.UserId)){
    throw 'QMT scheduler must run in logged-in user session'
}
if(-not $default.Force -or -not $custom.Force){
    throw 'Installer cannot update original task name idempotently'
}
Write-Host 'PASS_INSTALL_SCHEDULE_MOCK_NO_REAL_TASKS UNIFIED_EIGHT_PERIOD_2130'
Remove-Variable -Name MarketMockRegistrations -Scope Global -ErrorAction SilentlyContinue
