# Reuse the existing eight-period updater in bounded <=30-calendar-day windows.
# Called ONLY by scheduled-afternoon-update.ps1 inside the shared exclusive mutex.
# Never schedules another task, deletes a source, or rewrites accepted history.
param(
    [string]$Root='D:\stock',
    [ValidateRange(1,12)][int]$MaxWindows=12
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
$ledger=Join-Path $module 'work\market_update\commits.json'
$updater=Join-Path $module 'update-market.ps1'
$engine=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if(-not(Test-Path -LiteralPath $updater -PathType Leaf)){throw 'Missing original eight-period updater'}
if(-not(Test-Path -LiteralPath $ledger -PathType Leaf)){throw 'Missing accepted minute ledger; no speculative bootstrap in catch-up'}
function Get-LatestCommittedDay {
    $state=Get-Content -LiteralPath $ledger -Raw -Encoding UTF8 | ConvertFrom-Json
    if($state.format -ne 'one_command_market_parquet_incremental_v1' -or $null -eq $state.periods.'1min'){
        throw 'Market minute ledger format changed'
    }
    $dates=New-Object System.Collections.ArrayList
    foreach($month in $state.periods.'1min'.PSObject.Properties){
        foreach($item in @($month.Value.days)){
            if([string]$item -notmatch '^\d{4}-\d{2}-\d{2}$'){throw 'Market ledger day malformed'}
            [void]$dates.Add([datetime]::ParseExact([string]$item,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture))
        }
    }
    if($dates.Count -eq 0){throw 'No previously accepted minute day for safe catch-up'}
    return [datetime](($dates | Sort-Object -Descending | Select-Object -First 1))
}
$china=[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$now=[TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$china)
# Do not request a current-day refresh before the user's 20:05 China-time run.
$target=$now.Date
if($now.TimeOfDay -lt (New-TimeSpan -Hours 20 -Minutes 5)){
    $target=$target.AddDays(-1)
}
while($target.DayOfWeek -in @([DayOfWeek]::Saturday,[DayOfWeek]::Sunday)){
    $target=$target.AddDays(-1)
}
$latest=Get-LatestCommittedDay
Write-Host ('MARKET_CATCHUP_TARGET_CHINA='+$target.ToString('yyyy-MM-dd'))
Write-Host ('MARKET_CATCHUP_LAST_ACCEPTED='+$latest.ToString('yyyy-MM-dd'))
Write-Host 'MARKET_CATCHUP_USE_EXISTING_UPDATE_ENGINE=TRUE'
if($latest -gt $target){throw 'Accepted market ledger day exceeds 20:05 safe refresh cutoff'}
if($latest -eq $target){
    Write-Host 'MARKET_CATCHUP_ALREADY_AT_TARGET=TRUE'
    exit 0
}
$windows=0
while($latest -lt $target){
    if($windows -ge $MaxWindows){
        throw ('MARKET_CATCHUP_WINDOW_LIMIT_REACHED='+$MaxWindows+
               '; last accepted='+$latest.ToString('yyyy-MM-dd')+
               '; rerun manually after reviewing source logs')
    }
    $end=$latest.AddDays(30)
    if($end -gt $target){$end=$target}
    $windows++
    Write-Host ('MARKET_CATCHUP_WINDOW_START='+$windows+' from='+
        $latest.AddDays(1).ToString('yyyy-MM-dd')+' to='+$end.ToString('yyyy-MM-dd'))
    & $engine -NoProfile -ExecutionPolicy Bypass -File $updater -Mode auto -Root $Root -Day $end.ToString('yyyy-MM-dd') -MaxDays 30
    if($LASTEXITCODE -ne 0){throw ('Market incremental window failed: '+$end.ToString('yyyy-MM-dd')+' exit='+$LASTEXITCODE)}
    $after=Get-LatestCommittedDay
    if($after -eq $latest -and $end -eq $target){
        # Existing eight-cycle engine exits zero ONLY after checking the QMT
        # exchange calendar and rejecting any missing latest required trade.
        # A holiday can therefore be current without adding new ledger dates.
        Write-Host ('MARKET_CATCHUP_NO_NEW_EXCHANGE_TRADING_DAY_THROUGH='+$end.ToString('yyyy-MM-dd'))
        break
    }
    if($after -le $latest){
        throw ('MARKET_CATCHUP_NO_LEDGER_PROGRESS expected window through '+$end.ToString('yyyy-MM-dd'))
    }
    if($after -gt $end){throw 'Market update advanced beyond explicitly bounded window'}
    Write-Host ('MARKET_CATCHUP_WINDOW_COMMITTED='+$after.ToString('yyyy-MM-dd'))
    $latest=$after
}
Write-Host ('MARKET_CATCHUP_WINDOWS_COMPLETED='+$windows)
Write-Host ('MARKET_CATCHUP_LATEST_ACCEPTED='+$latest.ToString('yyyy-MM-dd'))
