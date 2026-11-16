param(
    [ValidateSet("auto","bootstrap","daily","cycles","sources","extras")]
    [string]$Mode = "auto",
    [string]$Root = "D:\stock",
    [string]$Day = "",
    [string]$Config = "",
    [ValidateRange(1,30)]
    [int]$MaxDays = 30,
    [ValidateRange(0,100000)]
    [int]$ExtraStockLimit = 40,
    [ValidateRange(0,100000)]
    [int]$ExtraAssetLimit = 5,
    [ValidateSet("all","sectors","financial","adjustments","index","etf")]
    [string]$ExtraSection = "all",
    [string]$ExtraStart = "2011-01-01",
    [ValidateRange(30,3600)]
    [int]$ExtraFinancialTimeoutSeconds = 180,
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Missing project Python .venv" }
$env:PYTHONPATH = $PSScriptRoot + [IO.Path]::PathSeparator + $env:PYTHONPATH
Write-Host "MARKET_UPDATE_ONE_COMMAND mode=$Mode dry_run=$DryRun"
if ($Mode -eq "extras") {
    & $python -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_qmt_extra_data.py" -q
    if ($LASTEXITCODE -ne 0) { throw "QMT supplementary data safety tests failed" }
    $extra = @("-u","-B","ParquetLiveSync\qmt_extra_data.py","--root",$Root,"--start",$ExtraStart,"--stock-limit",[string]$ExtraStockLimit,"--asset-limit",[string]$ExtraAssetLimit,"--section",$ExtraSection,"--financial-timeout-seconds",[string]$ExtraFinancialTimeoutSeconds)
    if ($Day) { $extra += @("--day",$Day) }
    if (-not $DryRun) { $extra += "--apply" }
    & $python @extra
    if ($LASTEXITCODE -ne 0) { throw "QMT supplementary data updater failed; eight purchased market periods unchanged" }
    Write-Host "MARKET_QMT_EXTRA_ONE_COMMAND_SUCCESS"
    exit 0
}
$ledger = "ParquetLiveSync\work\market_update\commits.json"
if ($Mode -in @("bootstrap", "sources", "cycles") -or -not (Test-Path -LiteralPath $ledger -PathType Leaf)) {
    & $python -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_market_updater.py" -q
    if ($LASTEXITCODE -ne 0) { throw "Market updater source safety tests failed" }
    & $python -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_market_derived_cycles.py" -q
    if ($LASTEXITCODE -ne 0) { throw "Market eight-cycle derivation safety tests failed" }
    & $python -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_rollup_week_month.py" -q
    if ($LASTEXITCODE -ne 0) { throw "Market week/month source safety tests failed" }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\tests\test_install_schedule_mock.ps1"
    if ($LASTEXITCODE -ne 0) { throw "Windows all-cycle Task Scheduler mock tests failed" }
} else {
    Write-Host "MARKET_DAILY_SKIP_REPEATED_OFFLINE_TESTS"
}
$a = @("-u","-B","ParquetLiveSync\update_market.py","--mode",$Mode,"--root",$Root,"--max-days",[string]$MaxDays)
if ($Day) { $a += @("--day",$Day) }
if ($Config) { $a += @("--config",$Config) }
elseif (Test-Path -LiteralPath "ParquetLiveSync\work\market_update\sources.local.json" -PathType Leaf) {
    $a += @("--config","ParquetLiveSync\work\market_update\sources.local.json")
}
if ($DryRun) { $a += "--dry-run" }
& $python @a
if ($LASTEXITCODE -ne 0) { throw "Market updater did not complete; source and transactional state retained" }
Write-Host "MARKET_UPDATE_ONE_COMMAND_SUCCESS"
