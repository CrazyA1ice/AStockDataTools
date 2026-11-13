param(
  [int]$MaxStocks = 0,
  [int]$MaxHosts = 6,
  [int]$MaxPages = 16
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$b = "feat/qmt-one-minute-history-probe-20261112"
if ((& git branch --show-current).Trim() -ne $b) {throw "Wrong QMT development branch"}
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) {throw "Project .venv Python missing"}
$env:PYTHONPATH = $PSScriptRoot + [IO.Path]::PathSeparator + $env:PYTHONPATH
if ($MaxStocks -lt 0 -or $MaxHosts -lt 1 -or $MaxHosts -gt 8 -or $MaxPages -lt 8 -or $MaxPages -gt 35) {
  throw "Unsafe full-market eltdx window or host budget"
}
Write-Host "QMT_ELTDX_RESUME_STEP_1_OFFLINE_REGRESSION"
& $py -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_qmt*.py" -q
if ($LASTEXITCODE -ne 0) {throw "Offline source regression failed before live work"}
Write-Host "QMT_ELTDX_RESUME_STEP_2_SHA_VERIFY_ALL_PRIOR_184_STOCK_RECOVERY_RECEIPTS"
# Native invocation uses $LASTEXITCODE, not Start-Process .ExitCode. Python
# qmt_recovery_receipt_preflight imports no xtquant and makes no vendor calls.
& $py -u -B "ParquetLiveSync\qmt_recovery_receipt_preflight.py" --root "D:\stock"
if ($LASTEXITCODE -ne 0) {
  throw "SHA verification of already-completed QMT recovery failed; refusing live source download"
}
Write-Host "QMT_ELTDX_RESUME_STEP_3_REUSE_THREE_PILOT_AND_AUDIT_UP_TO_5223_STOCKS"
# This stage audits every QMT/TDX receipt SHA independently. Each new eltdx
# source is privately staged, resume-safe and never merged into market files.
& $py -u -B "ParquetLiveSync\qmt_eltdx_market_audit.py" --root "D:\stock" --limit-stocks $MaxStocks --max-hosts $MaxHosts --max-pages $MaxPages
if ($LASTEXITCODE -ne 0) {throw "eltdx 1m crosscheck failed; private receipts remain reusable"}
$report = Join-Path $PSScriptRoot "work\qmt_1min_market\eltdx_1m_probe\20261014_20261112\latest_market_report.json"
if (-not (Test-Path -LiteralPath $report -PathType Leaf)) {throw "Missing SHA-bound private market report"}
$summary = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
if ($summary.production_merge_authorized -ne $false -or $summary.market_files_modified -ne $false) {
  throw "Source-only production protection flag invalid"
}
if ($summary.stopped_early) {
  Write-Host ("QMT_ELTDX_RESUME_PARTIAL_REUSABLE="+$summary.processed_stocks+"/"+$summary.expected_stocks+"; rerun same command to continue")
} else {
  Write-Host ("QMT_ELTDX_RESUME_ALL_MARKET_CANDIDATES_CHECKED="+$summary.processed_stocks)
}
Write-Host "QMT_ELTDX_OFFICIAL_PARQUET_AND_H5_UNCHANGED"
