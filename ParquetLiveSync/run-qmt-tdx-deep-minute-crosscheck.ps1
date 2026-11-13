param(
  [int]$MaxStocks = 0,
  [int]$MaxRecoveryStocks = 0
)
$ErrorActionPreference="Stop"
$repo=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$b="feat/qmt-one-minute-history-probe-20261112"
if ((& git branch --show-current).Trim() -ne $b) {throw "Wrong QMT source branch"}
$py=Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) {throw "Missing project .venv Python"}
$env:PYTHONPATH=$PSScriptRoot+[IO.Path]::PathSeparator+$env:PYTHONPATH
Write-Host "QMT_TDX_STEP_1_PYTHON_DEPS_AND_OFFLINE_TESTS"
& $py -c "import pyarrow,pandas; from xtquant import xtdata; print('QMT_ARROW_READY')"
if ($LASTEXITCODE -ne 0) {throw "QMT and Arrow Python dependencies missing"}
& $py -c "from pytdx.hq import TdxHq_API; print('PYTDX_SOURCE_READY')"
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing public, independent TDX 7709 decoder into project .venv only"
  & $py -m pip install "pytdx>=1.72,<2" -i https://pypi.tuna.tsinghua.edu.cn/simple
  if ($LASTEXITCODE -ne 0) {throw "pytdx SDK installation failed"}
  & $py -c "from pytdx.hq import TdxHq_API; print('PYTDX_SOURCE_READY')"
  if ($LASTEXITCODE -ne 0) {throw "pytdx SDK import failed"}
}
& $py -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_qmt*.py" -q
if ($LASTEXITCODE -ne 0) {throw "QMT/TDX offline regressions failed; no network work"}
$logDir=Join-Path $PSScriptRoot "work\qmt_1min_market\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log=Join-Path $logDir ("qmt-tdx-full-minute-"+(Get-Date -Format "yyyyMMdd-HHmmss")+".log")
Write-Host ("QMT_TDX_PRIVATE_LOG="+$log)
Write-Host "QMT_TDX_STEP_2_3_STOCK_FULL_22_DAY_HISTORICAL_PILOT"
& $py -u -B "ParquetLiveSync\qmt_tdx_1m_depth.py" --root "D:\stock" --limit-stocks 3 2>&1 | Tee-Object -FilePath $log | Where-Object {$_ -match '^QMT_TDX_' }
if ($LASTEXITCODE -ne 0) {throw "TDX 1-minute deep-history pilot failed; full-market query not started"}
$report=Join-Path $PSScriptRoot "work\qmt_1min_market\tdx_1m_crosscheck\20261014_20261112\latest_report.json"
if (-not (Test-Path -LiteralPath $report -PathType Leaf)) {throw "TDX private pilot report missing"}
$pilot=Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
if ($pilot.minute_level_checked_stock_days -lt 30 -or $pilot.strict_matched_stock_days -lt 10) {
  throw "Insufficient independent 1-minute pilot overlap or unstable semantics; cannot trigger full-market requests. Inspect $log"
}
Write-Host ("QMT_TDX_PILOT_PASS_MATCHED_DAYS="+$pilot.strict_matched_stock_days)
Write-Host "QMT_TDX_STEP_3_RECHECK_QMT_SHA_AND_RECOVER_ONLY_184_QUARANTINED_STOCKS"
& $py -u -B "ParquetLiveSync\qmt_1m_recover.py" --root "D:\stock" --start 2026-10-14 --end 2026-11-12 --limit-stocks $MaxRecoveryStocks 2>&1 | Tee-Object -FilePath $log -Append | Where-Object {$_ -match '^QMT_RECOVERY_(STEP|PROGRESS|EXISTING_SHA_CHECKED|STOCK_FAILED|CIRCUIT_BREAKER|SUMMARY|PER_DAY)'}
if ($LASTEXITCODE -ne 0) {throw "QMT day recovery failed; no TDX full-market query started"}
Write-Host "QMT_TDX_STEP_4_ALL_ELIGIBLE_STOCKS_DEEP_ONE_MINUTE_CROSSCHECK"
& $py -u -B "ParquetLiveSync\qmt_tdx_1m_depth.py" --root "D:\stock" --limit-stocks $MaxStocks 2>&1 | Tee-Object -FilePath $log -Append | Where-Object {$_ -match '^QMT_TDX_' }
if ($LASTEXITCODE -ne 0) {throw "TDX market source crosscheck incomplete; private receipts remain for resume"}
Write-Host ("QMT_TDX_COMPLETED_PRIVATE_LOG="+$log)
Write-Host "Share QMT_TDX_DEEP_CROSSCHECK_SUMMARY and QMT_RECOVERY_SUMMARY only; do not share licensed raw OHLCVA."
