param(
    [string]$Root = "D:\stock"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Project Python not found" }
$env:PYTHONPATH = $PSScriptRoot + [IO.Path]::PathSeparator + $env:PYTHONPATH
Write-Host "QMT_PHYSICAL_PREFLIGHT_STEP_0_OFFLINE_TESTS"
& $python -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_qmt_1m_physical_month_preflight.py" -q
if ($LASTEXITCODE -ne 0) { throw "Physical preflight offline tests failed; market not accessed" }
Write-Host "QMT_PHYSICAL_PREFLIGHT_STEP_1_VERIFY_PRIVATE_MONTHS_AND_SCAN_EXISTING_1MIN"
& $python -u -B "ParquetLiveSync\qmt_1m_physical_month_preflight.py" --root $Root
if ($LASTEXITCODE -ne 0) { throw "Physical target preflight failed; NO changes were written" }
Write-Host "QMT_PHYSICAL_PREFLIGHT_COMPLETE_READ_ONLY"
