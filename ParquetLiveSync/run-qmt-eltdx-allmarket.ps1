param(
  [int]$MaxStocks = 0,
  [int]$MaxRecoveryStocks = 0,
  [int]$MaxHosts = 6,
  [int]$MaxPages = 16
)
$ErrorActionPreference="Stop"
$repo=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$b="feat/qmt-one-minute-history-probe-20261112"
if ((& git branch --show-current).Trim() -ne $b) {throw "QMT development branch mismatch"}
$py=Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) {throw "Project Python .venv missing"}
$env:PYTHONPATH=$PSScriptRoot+[IO.Path]::PathSeparator+$env:PYTHONPATH
if ($MaxStocks -lt 0 -or $MaxRecoveryStocks -lt 0) {throw "Invalid negative market limit"}
Write-Host "QMT_ELTDX_ALLMARKET_STEP_1_OFFLINE_TESTS_AND_NATIVE_SDK"
& $py -c "import eltdx,pyarrow,pandas; from xtquant import xtdata; print('QMT_ELTDX_REQUIRED_SDKS_READY='+str(eltdx.__version__))"
if ($LASTEXITCODE -ne 0) {throw "QMT, eltdx or Arrow missing: run previous three-stock eltdx pilot first"}
& $py -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_qmt*.py" -q
if ($LASTEXITCODE -ne 0) {throw "QMT/eltdx offline tests failed: no live source work started"}
$logs=Join-Path $PSScriptRoot "work\qmt_1min_market\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp=Get-Date -Format "yyyyMMdd-HHmmss"
function Invoke-PrivatePython {
  param([string]$Label,[string[]]$Args)
  $stdout=Join-Path $logs ($Label+"-"+$stamp+".stdout.log")
  $stderr=Join-Path $logs ($Label+"-"+$stamp+".stderr.log")
  Write-Host ("QMT_ELTDX_RUNNING_PRIVATE_LOG="+$stdout)
  # Start-Process separates stderr, avoiding PowerShell 5.1 NativeCommandError
  # stopping a recovery script prematurely on benign Python warnings.
  $task=Start-Process -FilePath $py -ArgumentList $Args -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  $lastShown=""
  while (-not $task.HasExited) {
    Start-Sleep -Seconds 15
    $task.Refresh()
    if (Test-Path -LiteralPath $stdout) {
      $msg=Get-Content -LiteralPath $stdout -Tail 40 -ErrorAction SilentlyContinue | Where-Object {$_ -match '^(QMT_RECOVERY_(SUMMARY|PROGRESS|CIRCUIT_BREAKER)|ELTDX_MARKET_(PROGRESS|QUARANTINE|CIRCUIT_BREAKER|SUMMARY))'} | Select-Object -Last 1
      if ($msg -and $msg -ne $lastShown) {Write-Host $msg; $lastShown=$msg}
    }
  }
  $task.WaitForExit()
  if (Test-Path -LiteralPath $stdout) {
    Get-Content -LiteralPath $stdout -Tail 55 -ErrorAction SilentlyContinue | Where-Object {$_ -match '^(QMT_RECOVERY_SUMMARY|ELTDX_MARKET_SUMMARY|ELTDX_MARKET_DAY_STATUS)'} | ForEach-Object {Write-Host $_}
  }
  if ($task.ExitCode -ne 0) {
    Write-Host ("QMT_ELTDX_FAILURE_DIAGNOSTIC_LAST_LINES="+$stderr)
    if (Test-Path -LiteralPath $stderr) {Get-Content -LiteralPath $stderr -Tail 18}
    if (Test-Path -LiteralPath $stdout) {Get-Content -LiteralPath $stdout -Tail 8}
    throw ($Label+" failed; original market data untouched")
  }
  Write-Host ("QMT_ELTDX_PRIVATE_STEP_SUCCESS="+$Label)
}
Write-Host "QMT_ELTDX_ALLMARKET_STEP_2_RECOVER_ONLY_184_QUARANTINED_QMT_STOCKS"
Invoke-PrivatePython -Label "qmt-day-recovery" -Args @("-u","-B","ParquetLiveSync\qmt_1m_recover.py","--root","D:\stock","--start","2026-10-14","--end","2026-11-12","--limit-stocks",[string]$MaxRecoveryStocks)
Write-Host "QMT_ELTDX_ALLMARKET_STEP_3_SHA_BOUND_FULL_MARKET_INDEPENDENT_1MIN_CROSSCHECK"
Invoke-PrivatePython -Label "eltdx-market" -Args @("-u","-B","ParquetLiveSync\qmt_eltdx_market_audit.py","--root","D:\stock","--limit-stocks",[string]$MaxStocks,"--max-hosts",[string]$MaxHosts,"--max-pages",[string]$MaxPages)
Write-Host "QMT_ELTDX_PRIVATE_SOURCES_AND_REPORTS_COMPLETE_PRODUCTION_MARKET_UNCHANGED"
