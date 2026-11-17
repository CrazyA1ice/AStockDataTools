# One 16:30 China-market-time daily trigger; one sequential four-section run.
# Inert without explicit -Apply. The scheduler is managed separately.
# Source freshness checks are per section, not additional clock triggers.
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
if(-not $Apply){
    Write-Host "MARKET_1630_PREVIEW_ONLY=TRUE"
    Write-Host "MARKET_1630_CHINA_NOW=$($chinaNow.ToString('o'))"
    Write-Host "MARKET_1630_MODE=UNIFIED_SINGLE_RUN"
    Write-Host "MARKET_1630_SECTIONS=EIGHT_PERIODS,FINANCIAL_BOUNDED,SECTORS,ADJUSTMENTS_BOUNDED"
    Write-Host "MARKET_1630_ADJUSTMENTS_PER_RUN_LIMIT=$AdjustmentStockLimit"
    Write-Host "MARKET_1630_FINANCIAL_MAX_MINUTES=$FinanceMaxMinutes"
    Write-Host "MARKET_1630_MULTISOURCE=EIGHT_PERIODS_ONLY;OTHER_TYPES_UNVERIFIED"
    return
}
if($chinaNow.TimeOfDay -lt [TimeSpan]::Parse("16:30")){
    throw "Before 16:30 China market time: afternoon update refused"
}
# The primary checkout owns live_sync.WORK and every private progress ledger.
# A detached git worktree has its own ParquetLiveSync/work directory; running
# -Apply there against the SAME D:\stock would fork the source cursors and could
# replay an existing physical month. Fail before any market or extra writes.
$gitMetadata = Join-Path $repo ".git"
if(-not(Test-Path -LiteralPath $gitMetadata -PathType Container)){
    throw "READONLY_PREVIEW_WORKTREE: -Apply requires the primary repository checkout with canonical private ledgers"
}
$requiredState = @(
    (Join-Path $module "work\market_update\commits.json"),
    (Join-Path $module "work\qmt_extra\progress.json"),
    (Join-Path $module "work\qmt_extra\financial-cache-progress.json")
)
foreach($statePath in $requiredState){
    if(-not(Test-Path -LiteralPath $statePath -PathType Leaf)){
        throw "Missing canonical private progress ledger; refusing initial or divergent -Apply: $statePath"
    }
}
if(-not(Test-Path -LiteralPath $update -PathType Leaf)){throw "Missing market entry"}
if(-not(Test-Path -LiteralPath $finance -PathType Leaf)){throw "Missing financial entry"}
if(-not(Test-Path -LiteralPath (Join-Path $repo ".venv\Scripts\python.exe") -PathType Leaf)){throw "Missing project Python"}
if(-not(Test-Path -LiteralPath (Join-Path $Root "AllCycleAStockData\1min") -PathType Container)){throw "Missing original physical market dataset"}
if(Test-Path -LiteralPath (Join-Path $module "work\qmt_extra\schedule-enabled.json") -PathType Leaf){throw "Legacy extras schedule opt-in exists: refuse overlapping supplementary schedule"}
New-Item -ItemType Directory -Path $work -Force | Out-Null
$log = Join-Path $work ("afternoon-" + $chinaNow.ToString("yyyyMMdd-HHmmss") + ".log")
$status = Join-Path $work "last-afternoon-unified.json"
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
    Write-Host "MARKET_1630_MODE=UNIFIED_SINGLE_RUN"
    # Four independent audited stages in one run. Failure in one stage
    # is reported but does not suppress later, independent datasets.
    Invoke-AfternoonStep -Label "EIGHT_PERIODS" -Script $update -Arguments @("-Mode","auto","-Root",$Root)
    Invoke-AfternoonStep -Label "FINANCIAL_DAILY" -Script $finance -Arguments @("-Root",$Root,"-FinanceDir",$FinanceDir,"-MaxMinutes",[string]$FinanceMaxMinutes,"-LookbackDays",[string]$FinanceLookbackDays)
    Invoke-AfternoonStep -Label "SECTORS" -Script $update -Arguments @("-Mode","extras","-Root",$Root,"-ExtraSection","sectors","-ExtraStockLimit","1","-ExtraAssetLimit","0")
    $start = $chinaNow.Date.AddDays(-30).ToString("yyyy-MM-dd")
    # Existing adjustment cursor rotates; not a full-universe claim.
    Invoke-AfternoonStep -Label "ADJUSTMENTS_ROTATING" -Script $update -Arguments @("-Mode","extras","-Root",$Root,"-ExtraSection","adjustments","-ExtraStockLimit",[string]$AdjustmentStockLimit,"-ExtraAssetLimit","0","-ExtraStart",$start)
} finally {
    $state = if($failures.Count){"INCOMPLETE_RETRY_REQUIRED"}else{"EXECUTED_COVERAGE_UNVERIFIED"}
    $result = [ordered]@{
        format = "qmt_afternoon_market_v1"
        status = $state
        mode = "UNIFIED_SINGLE_RUN"
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
