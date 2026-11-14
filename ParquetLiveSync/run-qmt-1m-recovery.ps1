param(
    [string]$StartDate = "2026-10-14",
    [string]$EndDate = "2026-11-12",
    [int]$MaxStocks = 0
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$b = "feat/qmt-one-minute-history-probe-20261112"
if ((& git branch --show-current).Trim() -ne $b) { throw "QMT branch mismatch" }
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Project Python not found" }
$env:PYTHONPATH = $PSScriptRoot + [IO.Path]::PathSeparator + $env:PYTHONPATH
Write-Host "QMT_RECOVERY_STEP_0_OFFLINE_REGRESSION"
& $python -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_qmt*.py" -q
if ($LASTEXITCODE -ne 0) { throw "QMT offline tests failed; no QMT recovery writes" }
Write-Host "QMT_RECOVERY_STEP_1_VERIFY_EXISTING_AND_RECHECK_ONLY_QUARANTINED"
$logDir = Join-Path $PSScriptRoot "work\qmt_1min_market\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir ("qmt-day-recovery-" + $stamp + ".log")
Write-Host ("QMT_RECOVERY_PRIVATE_LOG=" + $log)
& $python -u -B "ParquetLiveSync\qmt_1m_recover.py" --root "D:\stock" --start $StartDate --end $EndDate --limit-stocks $MaxStocks 2>&1 | Tee-Object -FilePath $log | Where-Object {
    $_ -match '^QMT_(RECOVERY|ONE_MINUTE)'
}
$code = $LASTEXITCODE
if ($code -ne 0) { throw "QMT day-level recovery failed; inspect private log (production unchanged)" }
Write-Host ("QMT_RECOVERY_COMPLETE_LOG=" + $log)
Write-Host "Send only QMT_RECOVERY_SUMMARY and QMT_RECOVERY_PER_DAY, not licensed source parquet."
