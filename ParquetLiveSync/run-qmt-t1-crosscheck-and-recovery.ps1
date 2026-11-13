param(
  [string]$Day = "2026-11-12",
  [string]$Symbols = "600000.SH,000001.SZ,688001.SH,000404.SZ,300318.SZ,688022.SH",
  [int]$MaxQuarantinedStocks = 0
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$b = "feat/qmt-one-minute-history-probe-20261112"
if ((& git branch --show-current).Trim() -ne $b) { throw "Wrong QMT source branch" }
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) { throw "Missing project Python" }
$env:PYTHONPATH = $PSScriptRoot + [IO.Path]::PathSeparator + $env:PYTHONPATH
& $py -c "from xtquant import xtdata; import pandas,pyarrow; print('QMT_AUDIT_PREREQUISITES_READY')"
if ($LASTEXITCODE -ne 0) { throw "Missing QMT/Arrow Python dependencies" }
Write-Host "QMT_T1_STEP_1_RUN_QMT_OFFLINE_AND_SOURCE_INDEPENDENCE_TESTS"
& $py -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_qmt*.py" -q
if ($LASTEXITCODE -ne 0) { throw "QMT offline tests failed; stopping before live work" }
$logs = Join-Path $PSScriptRoot "work\qmt_1min_market\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logs ("qmt-t1-independent-audit-" + $stamp + ".log")
Write-Host ("QMT_T1_PRIVATE_LOG=" + $log)
Write-Host "QMT_T1_STEP_2_CROSSCHECK_YESTERDAY_WITH_QMT_TENCENT_AND_EASTMONEY"
& $py -u -B "ParquetLiveSync\qmt_1m_crosscheck.py" --root "D:\stock" --date $Day --symbols $Symbols 2>&1 | Tee-Object -FilePath $log | Where-Object {
  $_ -match '^QMT_(T1_CROSSCHECK|T1_CROSSCHECK_RESULT)'
}
$crossCode = $LASTEXITCODE
if ($crossCode -ne 0) { throw "T+1 crosscheck failed (no production data modified), inspect $log" }
Write-Host "QMT_T1_STEP_3_RECHECK_5039_SOURCE_SHA_AND_ONLY_184_QUARANTINE_CANDIDATES"
& $py -u -B "ParquetLiveSync\qmt_1m_recover.py" --root "D:\stock" --start 2026-10-14 --end 2026-11-12 --limit-stocks $MaxQuarantinedStocks 2>&1 | Tee-Object -FilePath $log -Append | Where-Object {
  $_ -match '^QMT_RECOVERY_(STEP|EXISTING_SHA_CHECKED|PROGRESS|STOCK_FAILED|CIRCUIT_BREAKER|SUMMARY|PER_DAY)'
}
$recoverCode = $LASTEXITCODE
if ($recoverCode -ne 0) { throw "Day-level recovery failed (original Parquet untouched), inspect $log" }
Write-Host ("QMT_T1_SOURCE_ONLY_COMPLETE_PRIVATE_LOG=" + $log)
Write-Host "Share only QMT_T1_CROSSCHECK_SUMMARY and QMT_RECOVERY_SUMMARY, not raw licensed market rows."
