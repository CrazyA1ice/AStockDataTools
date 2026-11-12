# Windows UI, runs ONLY offline synthetic tests before opening.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
$python=Join-Path $repo '.venv\Scripts\python.exe'
if(-not (Test-Path -LiteralPath $python -PathType Leaf)){throw "Missing repo Python .venv. Existing AStockDataTools virtualenv must provide pyarrow."}
$base=Join-Path $repo 'H5ParquetReconciler\work\unified_parquet\datasets\eight_cycle_asof_20261013_a4987bba0ce3a1f6\manifest.json'
if(-not (Test-Path -LiteralPath $base -PathType Leaf)){throw "Required already accepted 2026-10-13 eight-period Parquet dataset manifest missing"}
Write-Host '===== OFFLINE SAFE TDX BINARY / AUTO UNIT-CALIBRATION / ARROW OVERLAY TESTS ====='
& $python -B -m unittest discover -s (Join-Path $module 'tests') -p 'test_*.py' -q
if($LASTEXITCODE -ne 0){throw 'ParquetLiveSync offline regression failed; GUI will not start'}
Write-Host '===== OPEN NEW A-STOCK-DATA PARQUET GUI ====='
& $python -B (Join-Path $module 'gui.py')
if($LASTEXITCODE -ne 0){throw 'ParquetLiveSync GUI exited with nonzero status'}
