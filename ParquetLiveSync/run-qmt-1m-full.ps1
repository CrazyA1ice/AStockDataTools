param(
  [string]$StartDate = "2026-10-14",
  [string]$EndDate = "2026-11-12",
  [int]$MaxStocks = 0
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Missing project .venv Python" }
$branch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne "feat/qmt-one-minute-history-probe-20261112") {
  throw "Wrong Git branch; expected feat/qmt-one-minute-history-probe-20261112"
}
$logDir = Join-Path $PSScriptRoot "work\qmt_1min_market\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir ("qmt-one-shot-" + $stamp + ".log")
Write-Host "QMT_ONE_SHOT_STEP_1_DEPENDENCY_PREFLIGHT"
& $python -c "import pandas; from xtquant import xtdata; import pyarrow; print('QMT_PYTHON_DEPENDENCIES_READY')"
if ($LASTEXITCODE -ne 0) {
  Write-Host "Missing Python dependency; attempting isolated project pyarrow installation."
  & $python -m pip install "pyarrow>=15,<30" -i "https://pypi.tuna.tsinghua.edu.cn/simple"
  if ($LASTEXITCODE -ne 0) { throw "QMT dependency installation failed" }
  & $python -c "import pandas; from xtquant import xtdata; import pyarrow; print('QMT_PYTHON_DEPENDENCIES_READY')"
  if ($LASTEXITCODE -ne 0) { throw "QMT dependency preflight failed" }
}
Write-Host "QMT_ONE_SHOT_STEP_2_OFFLINE_TESTS"
& $python -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_qmt*.py" -v
if ($LASTEXITCODE -ne 0) { throw "QMT offline tests failed; live source staging not started" }
Write-Host "QMT_ONE_SHOT_STEP_3_UPDATE_PRIVATE_OFFICIAL_DAY_OVERLAY"
Write-Host ("PRIVATE_LOG=" + $log)
& $python -u -B "ParquetLiveSync\\live_sync.py" --root "D:\\stock" --from-day $StartDate --through-day $EndDate --max-days 60 --sync-day-overlay 2>&1 | Tee-Object -FilePath $log | Where-Object {
  $_ -match "^(PASS_NEW_DAY_PARQUET|RETRYABLE_404_NOT_A_HOLIDAY_PROOF|PARQUET_LIVE_SYNC_RESULT|TDX_CALIBRATION)"
}
$dayCode = $LASTEXITCODE
if ($dayCode -ne 0) { Write-Host ("PRIVATE_DAY_OVERLAY_INCOMPLETE_EXIT=" + $dayCode + "; trying existing verified day references") }
Write-Host "QMT_ONE_SHOT_STEP_4_PAID_OVERLAP_AND_RESUMABLE_MARKET_INTAKE"
& $python -u -B "ParquetLiveSync\qmt_1m_pipeline.py" --root "D:\stock" --start $StartDate --end $EndDate --limit-stocks $MaxStocks 2>&1 | Tee-Object -FilePath $log -Append | Where-Object {
  $_ -match '^QMT_(CALIBRATION|SOURCE_WINDOW|PAID_CALIBRATION|PRIVATE_QUARANTINE|CIRCUIT_BREAKER|ONE_MINUTE_MARKET_RESULT|SINGLE_COMMAND)'
}
$code = $LASTEXITCODE
if ($code -ne 0) {
  Write-Host ("QMT_ONE_SHOT_FAILED_EXIT=" + $code + " PRIVATE_LOG=" + $log)
  throw "QMT source-only pipeline failed; no market Parquet write"
}
Write-Host ("QMT_ONE_SHOT_DONE_PRIVATE_LOG=" + $log)
Write-Host "Please share QMT_CALIBRATION_SUMMARY and QMT_ONE_MINUTE_MARKET_RESULT only; do not upload private market data."
