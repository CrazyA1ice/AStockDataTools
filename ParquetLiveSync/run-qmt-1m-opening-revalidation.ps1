param(
    [string]$Datadir = "D:\software\JHQMT\datadir",
    [int]$LimitStocks = 0,
    [switch]$WritePrivate
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Project Python missing" }
if ($LimitStocks -lt 0 -or $LimitStocks -gt 184) { throw "Invalid limit" }
$env:PYTHONPATH = $PSScriptRoot + [IO.Path]::PathSeparator + $env:PYTHONPATH
Write-Host "QMT_OPENING_STEP_0_OFFLINE_TESTS"
& $python -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_qmt_1m_opening_revalidate.py" -q
if ($LASTEXITCODE -ne 0) { throw "Opening revalidation offline tests failed; no private write" }
Write-Host "QMT_OPENING_STEP_1_LOCAL_DAT_REVALIDATION"
$argsList = @("-u", "-B", "ParquetLiveSync\qmt_1m_opening_revalidate.py", "--datadir", $Datadir, "--limit-stocks", [string]$LimitStocks)
if ($WritePrivate) {
    $argsList += "--write-private"
    Write-Host "QMT_OPENING_OUTPUT=SHA-pinned private opening_first_trade_v1 (NO production writes)"
} else {
    Write-Host "QMT_OPENING_OUTPUT=READ_ONLY_PREVIEW"
}
& $python @argsList
if ($LASTEXITCODE -ne 0) { throw "QMT opening native revalidation failed" }
Write-Host "QMT_OPENING_STEP_COMPLETE"
