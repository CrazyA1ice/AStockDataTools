# Windows PowerShell 5.1 non-destructive regression for PowerShell's case-insensitive
# variable names. Must exercise the real Install control flow, not only parse.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$installer=Join-Path (Split-Path -Parent $PSScriptRoot) 'install-schedule.ps1'
if(-not ([System.IO.File]::Exists($installer))){throw 'Cannot find Task Scheduler installer'}
$global:ParquetLiveSyncMockRegistrations=New-Object System.Collections.ArrayList
# Register-ScheduledTask and all dependency cmdlets are shadowed by these
# harmless functions. This CI test NEVER installs a Windows task.
function Test-Path {
    param([string]$LiteralPath,[string]$Path,[string]$PathType)
    $item=if($LiteralPath){$LiteralPath}else{$Path}
    if($item -eq 'D:\stock' -or $item.EndsWith('.venv\Scripts\python.exe')){
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
    param([switch]$StartWhenAvailable)
    return [pscustomobject]@{Kind='MockSettings';StartWhenAvailable=[bool]$StartWhenAvailable}
}
function Register-ScheduledTask {
    param([string]$TaskName,$Action,$Trigger,$Settings,
          [string]$Description,[switch]$Force)
    if($Action.Kind -ne 'MockTaskExecAction'){
        throw 'Task argument is not mock exec action'
    }
    [void]$global:ParquetLiveSyncMockRegistrations.Add([pscustomobject]@{
        Name=$TaskName;Action=$Action;Trigger=$Trigger;
        Settings=$Settings;Description=$Description;Force=[bool]$Force
    })
    return [pscustomobject]@{MockRegistered=$true}
}
# Original bug: param([ValidateSet('Install',..)]$Action) then assigning
# $action=New-ScheduledTaskAction raises ValidateSetFailure on Windows.
& $installer -Action Install -IncludeClosedWeekMonth
& $installer -Action Install
if($global:ParquetLiveSyncMockRegistrations.Count -ne 2){
    throw 'Both mock installation paths must register exactly one action'
}
$three=$global:ParquetLiveSyncMockRegistrations[0]
$day=$global:ParquetLiveSyncMockRegistrations[1]
if($three.Name -ne 'AStockDataTools-ParquetLiveSync' -or
   $day.Name -ne 'AStockDataTools-ParquetLiveSync'){
    throw 'Installer changed its documented task name'
}
if(-not $three.Action.Argument.Contains(' -IncludeClosedWeekMonth')){
    throw 'Opt-in three-period flag missing in scheduled command'
}
if($day.Action.Argument.Contains('-IncludeClosedWeekMonth')){
    throw 'Default task unexpectedly enables WEEK/MONTH instead of DAY_ONLY'
}
if($three.Trigger.At -ne '21:30' -or $day.Trigger.At -ne '21:30'){
    throw 'Daily 21:30 local-time trigger changed'
}
if(-not $three.Trigger.Daily -or -not $three.Settings.StartWhenAvailable){
    throw 'Task trigger/recovery configuration invalid'
}
if(-not $three.Force -or -not $day.Force){
    throw 'Task update/installation cannot reuse existing task name'
}
Write-Host 'PASS_INSTALL_SCHEDULE_MOCK_NO_REAL_TASKS THREE_PERIOD_AND_DAY_ONLY'
Remove-Variable -Name ParquetLiveSyncMockRegistrations -Scope Global -ErrorAction SilentlyContinue
