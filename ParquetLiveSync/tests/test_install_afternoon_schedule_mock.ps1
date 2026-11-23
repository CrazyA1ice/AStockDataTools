# Pure mock: do NOT create or modify Windows scheduled tasks.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$installer=Join-Path (Split-Path -Parent $PSScriptRoot) 'install-schedule.ps1'
$global:AfternoonMock=New-Object System.Collections.ArrayList
$global:OldFinanceMock=$null
$global:OldFinanceDisableCalls=0
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
    if($TaskName -eq 'AStockDataTools-QMT-Financial-Daily'){
        return $global:OldFinanceMock
    }
    return $null
}
function Disable-ScheduledTask {
    param([string]$TaskName,[string]$ErrorAction)
    if($TaskName -ne 'AStockDataTools-QMT-Financial-Daily'){
        throw 'Unexpected independent task disabled'
    }
    $global:OldFinanceDisableCalls++
    $global:OldFinanceMock.State='Disabled'
    return [pscustomobject]@{Disabled=$true}
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
& $installer -Action Install
if($global:AfternoonMock.Count -ne 1){throw 'Afternoon installer must register exactly one existing task'}
$reg=$global:AfternoonMock[0]
if($reg.Name -ne 'AStockDataTools-ParquetLiveSync'){throw 'Afternoon scheduler created an unexpected task'}
if($reg.Action.Argument -notmatch 'scheduled-afternoon-update.ps1'){throw 'Incorrect afternoon entry'}
if($reg.Action.Argument -notmatch ' -Apply$'){throw 'Installed afternoon task must explicitly authorize apply'}
if($reg.Triggers.Count -ne 1){throw 'Expected exactly one 20:05 China-market trigger'}
$china=[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$chinaToday=([TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$china)).Date
$firstUtc=[TimeZoneInfo]::ConvertTimeToUtc($chinaToday.AddHours(20).AddMinutes(5),$china)
$firstLocal=[TimeZoneInfo]::ConvertTimeFromUtc($firstUtc,[TimeZoneInfo]::Local).ToString('HH:mm')
if($reg.Triggers[0].At -ne $firstLocal){throw 'Single China 20:05 trigger time invalid'}
if($reg.Settings.MultipleInstances -ne 'IgnoreNew' -or $reg.Principal.LogonType -ne 'Interactive' -or $reg.Settings.ExecutionTimeLimit -ne (New-TimeSpan -Hours 3 -Minutes 40) -or $reg.Settings.StartWhenAvailable){throw 'Task schedule must be bounded and must not replay after midnight'}
if(-not $reg.Force){throw 'Existing task must be reused, not duplicated'}
$global:OldFinanceMock=[pscustomobject]@{State='Ready'}
& $installer -Action Install
if($global:OldFinanceDisableCalls -ne 1 -or
   [string]$global:OldFinanceMock.State -ne 'Disabled'){
    throw 'Old 00:30 task must be disabled once without deleting'
}
if($global:AfternoonMock.Count -ne 2 -or
   $global:AfternoonMock[1].Name -ne 'AStockDataTools-ParquetLiveSync'){
    throw 'Installing with old finance task must still register one 20:05 entry'
}
Write-Host 'PASS_INSTALL_AFTERNOON_MOCK_2005_ONE_TRIGGER_0030_OLD_DISABLED_NO_REAL_TASKS'
Remove-Variable -Name AfternoonMock -Scope Global -ErrorAction SilentlyContinue
Remove-Variable -Name OldFinanceMock -Scope Global -ErrorAction SilentlyContinue
Remove-Variable -Name OldFinanceDisableCalls -Scope Global -ErrorAction SilentlyContinue
