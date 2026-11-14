param(
    [string]$Root = "D:\stock",
    [switch]$WritePrivate
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Project Python not found" }
$env:PYTHONPATH = $PSScriptRoot + [IO.Path]::PathSeparator + $env:PYTHONPATH
Write-Host "QMT_PRIVATE_MONTH_STEP_0_OFFLINE_TESTS"
& $python -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_qmt_1m_private_month_bridge.py" -q
if ($LASTEXITCODE -ne 0) { throw "QMT private month offline tests failed; no private output written" }
Write-Host "QMT_PRIVATE_MONTH_STEP_1_BIND_5039_184_181_RECEIPTS"
$arguments = @("-u", "-B", "ParquetLiveSync\qmt_1m_private_month_bridge.py", "--root", $Root)
if ($WritePrivate) {
    $arguments += "--write-private"
    Write-Host "QMT_PRIVATE_MONTH_MODE=PRIVATE_MONTH_WRITE_ONLY"
} else {
    Write-Host "QMT_PRIVATE_MONTH_MODE=READONLY_MANIFEST_PREFLIGHT"
}
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "QMT private monthly bridge failed; physical Parquet/H5 unchanged" }
Write-Host "QMT_PRIVATE_MONTH_STEP_COMPLETE"
