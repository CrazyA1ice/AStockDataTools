# 16:30 China-market-time early update; 20:45 source-readiness retry.
# This runner is inert unless explicitly invoked with -Apply by the opt-in
# AfternoonUnified Task Scheduler installer. Existing 21:30 task unchanged.
param(
    [switch]$Apply,
    [string]$Root = "D:\stock",
    [string]$FinanceDir = "D:\software\JHQMT\datadir\Finance",
    [ValidateRange(1,1000)][int]$AdjustmentStockLimit = 80,
    [ValidateRange(1,240)][int]$FinanceMaxMinutes = 150,
    [ValidateRange(1,1095)][int]$FinanceLookbackDays = 120
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$module = Split-Path -Parent $PSCommandPath
$repo = Split-Path -Parent $module
$update = Join-Path $module "update-market.ps1"
$finance = Join-Path $module "run-qmt-financial-daily.ps1"
$work = Join-Path $module "work"
$china = [TimeZoneInfo]::FindSystemTimeZoneById("China Standard Time")
$chinaNow = [TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow, $china)
$mode = if($chinaNow.TimeOfDay -ge [TimeSpan]::Parse("20:00")){"RETRY_MARKET_ONLY"}else{"AFTERNOON_ALL"}
if(-not $Apply){
    Write-Host "MARKET_1630_PREVIEW_ONLY=TRUE"
    Write-Host "MARKET_1630_CHINA_NOW=$($chinaNow.ToString('o'))"
    Write-Host "MARKET_1630_MODE=$mode"
    Write-Host "MARKET_1630_SECTIONS=EIGHT_PERIODS,SECTORS,ADJUSTMENTS_BOUNDED,FINANCIAL_BOUNDED"
    Write-Host "MARKET_1630_ADJUSTMENTS_PER_RUN_LIMIT=$AdjustmentStockLimit"
    Write-Host "MARKET_1630_FINANCIAL_MAX_MINUTES=$FinanceMaxMinutes"
    Write-Host "MARKET_1630_MULTISOURCE=EIGHT_PERIODS_ONLY;OTHER_TYPES_UNVERIFIED"
    return
}
if($chinaNow.TimeOfDay -lt [TimeSpan]::Parse("16:30")){
    throw "Before 16:30 China market time: afternoon update refused"
}
if(-not(Test-Path -LiteralPath $update -PathType Leaf)){throw "Missing market entry"}
if(-not(Test-Path -LiteralPath $finance -PathType Leaf)){throw "Missing financial entry"}
if(-not(Test-Path -LiteralPath (Join-Path $repo ".venv\Scripts\python.exe") -PathType Leaf)){throw "Missing project Python"}
if(-not(Test-Path -LiteralPath (Join-Path $Root "AllCycleAStockData\1min") -PathType Container)){throw "Missing original physical market dataset"}
if(Test-Path -LiteralPath (Join-Path $module "work\qmt_extra\schedule-enabled.json") -PathType Leaf){throw "Legacy extras schedule opt-in exists: refuse overlapping supplementary schedule"}
New-Item -ItemType Directory -Path $work -Force | Out-Null
$log = Join-Path $work ("afternoon-" + $chinaNow.ToString("yyyyMMdd-HHmmss") + ".log")
$status = Join-Path $work ("last-afternoon-" + $mode.ToLowerInvariant() + ".json")
$failures = New-Object System.Collections.ArrayList
$completed = New-Object System.Collections.ArrayList
$engine = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$started = (Get-Date).ToString("o")
function Invoke-AfternoonStep {
    param([string]$Label,[string]$Script,[string[]]$Arguments)
    Write-Host ("MARKET_1630_STEP_START=" + $Label)
    try {
        & $engine -NoProfile -ExecutionPolicy Bypass -File $Script @Arguments
        if($LASTEXITCODE -ne 0){throw ("Exit code " + $LASTEXITCODE)}
        [void]$completed.Add($Label)
        Write-Host ("MARKET_1630_STEP_DONE=" + $Label)
    }catch{
        $detail = $Label + ": " + $_.Exception.Message
        [void]$failures.Add($detail)
        Write-Host ("MARKET_1630_STEP_FAILED=" + $detail)
    }
}
Start-Transcript -Path $log -ErrorAction Stop | Out-Null
try {
    Set-Location -LiteralPath $repo
    Write-Host "MARKET_1630_CHINA_NOW=$($chinaNow.ToString('o'))"
    Write-Host "MARKET_1630_MODE=$mode"
    Invoke-AfternoonStep "EIGHT_PERIODS" $update @("-Mode","auto","-Root",$Root)
    if($mode -eq "AFTERNOON_ALL"){
        # Independent QMT snapshots. No unsupported cross-source claims.
        Invoke-AfternoonStep "SECTORS" $update @("-Mode","extras","-Root",$Root,"-ExtraSection","sectors","-ExtraStockLimit","1","-ExtraAssetLimit","0")
        $start = $chinaNow.Date.AddDays(-30).ToString("yyyy-MM-dd")
        # Existing adjustments cursor rotates; do not label this all-market completion.
        Invoke-AfternoonStep "ADJUSTMENTS_ROTATING" $update @("-Mode","extras","-Root",$Root,"-ExtraSection","adjustments","-ExtraStockLimit",[string]$AdjustmentStockLimit,"-ExtraAssetLimit","0","-ExtraStart",$start)
        Invoke-AfternoonStep "FINANCIAL_DAILY" $finance @("-Root",$Root,"-FinanceDir",$FinanceDir,"-MaxMinutes",[string]$FinanceMaxMinutes,"-LookbackDays",[string]$FinanceLookbackDays)
    }
} finally {
    $state = if($failures.Count){"INCOMPLETE_RETRY_REQUIRED"}else{"EXECUTED_COVERAGE_UNVERIFIED"}
    $result = [ordered]@{
        format = "qmt_afternoon_market_v1"
        status = $state
        mode = $mode
        started_local = $started
        finished_local = (Get-Date).ToString("o")
        china_start = $chinaNow.ToString("o")
        steps_completed = @($completed.ToArray())
        errors = @($failures.ToArray())
        adjustments_complete_universe = $false
        finance_source_completeness_verified = $false
        other_extra_multisource_verified = $false
        log_path = $log
    }
    $temp = $status + ".part"
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $status -Force
    Write-Host ("MARKET_1630_SUMMARY=" + ($result | ConvertTo-Json -Compress -Depth 6))
    Stop-Transcript | Out-Null
}
if($failures.Count){throw ("Market afternoon steps failed: " + ($failures -join "; "))}
