# Pure mock: do NOT create or modify Windows scheduled tasks.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$installer=Join-Path (Split-Path -Parent $PSScriptRoot) 'install-schedule.ps1'
$global:AfternoonMock=New-Object System.Collections.ArrayList
function Test-Path {
    param([string]$LiteralPath,[string]$Path,[string]$PathType)
    $p=if($LiteralPath){$LiteralPath}else{$Path}
    if($p -like '*schedule-enabled.json'){return $false}
    if($p -eq 'D:\stock\AllCycleAStockData\1min' -or
       $p.EndsWith('.venv\Scripts\python.exe')){return $true}
    return [System.IO.File]::Exists($p)
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
    return [pscustomobject]@{At=$At;Daily=[bool]$Daily}
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
    [void]$global:AfternoonMock.Add([pscustomobject]@{
        Name=$TaskName;Action=$Action;Triggers=@($Trigger)
        Settings=$Settings;Principal=$Principal;Force=[bool]$Force
    })
    return [pscustomobject]@{MockOnly=$true}
}
& $installer -Action Install -AfternoonUnified
if($global:AfternoonMock.Count -ne 1){throw 'Afternoon installer must register exactly one existing task'}
$reg=$global:AfternoonMock[0]
if($reg.Name -ne 'AStockDataTools-ParquetLiveSync'){throw 'Afternoon scheduler created an unexpected task'}
if($reg.Action.Argument -notmatch 'scheduled-afternoon-update.ps1'){throw 'Incorrect afternoon entry'}
if($reg.Action.Argument -notmatch ' -Apply$'){throw 'Installed afternoon task must explicitly authorize apply'}
if($reg.Triggers.Count -ne 1){throw 'Expected exactly one 16:30 China-market trigger'}
$china=[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$chinaToday=([TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$china)).Date
$firstUtc=[TimeZoneInfo]::ConvertTimeToUtc($chinaToday.AddHours(16).AddMinutes(30),$china)
$firstLocal=[TimeZoneInfo]::ConvertTimeFromUtc($firstUtc,[TimeZoneInfo]::Local).ToString('HH:mm')
if($reg.Triggers[0].At -ne $firstLocal){throw 'Single China 16:30 trigger time invalid'}
if($reg.Settings.MultipleInstances -ne 'IgnoreNew' -or $reg.Principal.LogonType -ne 'Interactive' -or $reg.Settings.ExecutionTimeLimit.TotalHours -ne 8){throw 'Overlapping/noninteractive QMT task or incorrect unified runtime'}
if(-not $reg.Force){throw 'Existing task must be reused, not duplicated'}
Write-Host 'PASS_INSTALL_AFTERNOON_MOCK_NO_REAL_TASKS CST_1630_SINGLE'
Remove-Variable -Name AfternoonMock -Scope Global -ErrorAction SilentlyContinue
