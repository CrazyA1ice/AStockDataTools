# Exact timestamp-key diagnostic for 1min/5min: NEVER writes market files.
# Compares only one date; not a batch scanner or production activation.
param([string]$Day='2026-01-07')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\preview-minute-exact-key-diff-readonly.py'
$root='D:\stock'
foreach($f in @($py,$tool)){if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing diagnostic requirement: $f"}}
foreach($d in @('HikyuuData','AllCycleAStockData')){if(-not (Test-Path -LiteralPath (Join-Path $root $d) -PathType Container)){throw "Market source missing: $root\$d"}}
foreach($test in @('test_write_h5_only_complete_minute_stockdays_to_private_parquet.py','test_run_minute_h5_gap_only_overlay.py','test_preview_minute_exact_key_diff_readonly.py')){
    & $py -B -m unittest discover -s (Join-Path $module 'tests') -p $test -v
    if($LASTEXITCODE -ne 0){throw "Synthetic exact-key prerequisite tests failed: $test; REAL preview not started"}
}
Write-Host "===== Read-only purchased vs H5 minute time-key comparison for $Day ====="
& $py -B $tool --root $root --day $Day
if($LASTEXITCODE -ne 0){throw 'Real exact-key diagnostic failed; original vendor/H5 still read-only'}
Write-Host 'READ-ONLY exact time-key diagnostic complete; 0 new market files, 0 purchased bars copied.'
