# Pure Windows PowerShell 5.1 mock. Never touches a real scheduled task.
# Legacy test filename retained because update-market.ps1 invokes it.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$installer=Join-Path (Split-Path -Parent $PSScriptRoot) 'install-schedule.ps1'
if(-not [IO.File]::Exists($installer)){throw 'Installer missing'}
$global:MarketMockRegistrations=New-Object System.Collections.ArrayList
function Test-Path {
    param([string]$LiteralPath,[string]$Path,[string]$PathType)
    $p=if($LiteralPath){$LiteralPath}else{$Path}
    if($p -like '*schedule-enabled.json'){return $false}
    if($p -eq 'D:\stock\AllCycleAStockData\1min' -or
       $p.EndsWith('.venv\Scripts\python.exe')){return $true}
    return [IO.File]::Exists($p)
}
function Get-ScheduledTask {
    param([string]$TaskName,[string]$ErrorAction)
    return $null
}
function New-ScheduledTaskAction {
    param([string]$Execute,[string]$Argument,[string]$WorkingDirectory)
    return [pscustomobject]@{Execute=$Execute;Argument=$Argument;WorkingDirectory=$WorkingDirectory}
}
function New-ScheduledTaskTrigger {
    param([switch]$Daily,[string]$At)
    return [pscustomobject]@{Daily=[bool]$Daily;At=$At}
}
function New-ScheduledTaskSettingsSet {
    param([switch]$StartWhenAvailable,[string]$MultipleInstances,[TimeSpan]$ExecutionTimeLimit)
    return [pscustomobject]@{StartWhenAvailable=[bool]$StartWhenAvailable;MultipleInstances=$MultipleInstances;ExecutionTimeLimit=$ExecutionTimeLimit}
}
function New-ScheduledTaskPrincipal {
    param([string]$UserId,[string]$LogonType,[string]$RunLevel)
    return [pscustomobject]@{UserId=$UserId;LogonType=$LogonType;RunLevel=$RunLevel}
}
function Register-ScheduledTask {
    param([string]$TaskName,$Action,$Trigger,$Settings,$Principal,[string]$Description,[switch]$Force)
    [void]$global:MarketMockRegistrations.Add([pscustomobject]@{
        Name=$TaskName;Action=$Action;Trigger=$Trigger;Settings=$Settings
        Principal=$Principal;Force=[bool]$Force
    })
    return [pscustomobject]@{MockOnly=$true}
}
& $installer -Action Install
if($global:MarketMockRegistrations.Count -ne 1){throw 'Expected exactly ONE mocked install'}
$reg=$global:MarketMockRegistrations[0]
if($reg.Name -ne 'AStockDataTools-ParquetLiveSync'){throw 'Must reuse original task name'}
if($reg.Action.Argument -notmatch 'scheduled-afternoon-update.ps1.* -Apply$'){
    throw 'Must invoke single daily script with Apply'
}
$china=[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$day=([TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$china)).Date
$utc=[TimeZoneInfo]::ConvertTimeToUtc($day.AddHours(20).AddMinutes(5),$china)
$pc=[TimeZoneInfo]::ConvertTimeFromUtc($utc,[TimeZoneInfo]::Local).ToString('HH:mm')
if($reg.Trigger.At -ne $pc -or -not $reg.Trigger.Daily){
    throw 'Expected exactly one daily China 20:05 trigger'
}
if($reg.Settings.ExecutionTimeLimit -ne [TimeSpan]::Zero -or
   $reg.Settings.MultipleInstances -ne 'IgnoreNew' -or
   -not $reg.Settings.StartWhenAvailable){
    throw 'Expected unlimited task runtime and no overlapping instances'
}
if($reg.Principal.LogonType -ne 'Interactive' -or
   $reg.Principal.RunLevel -ne 'Limited' -or -not $reg.Force){
    throw 'Expected interactive QMT task replacing same task'
}
Write-Host 'PASS_INSTALL_SCHEDULE_MOCK_NO_REAL_TASKS ONLY_CST_2005_NO_TIMEOUT'
Remove-Variable -Name MarketMockRegistrations -Scope Global -ErrorAction SilentlyContinue
