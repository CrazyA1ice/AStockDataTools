# Start/resume real 2026-01-01 through last verified 2026-10-13 minute Parquet backfill.
# Already SHA-accepted dates are reused by existing GUI worker; no vendor writes.
param([switch]$Run)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
# Retired on 2026-11-03 after the purchased-primary planning audit:
# -Run used to copy complete purchased source days into new private files.
# Starting/resuming such full-rewrite jobs wastes licensed source I/O and disk.
# This guard affects only a NEW invocation. It does not stop an old worker.
if($Run){throw "RETIRED_FULL_PURCHASED_REWRITE: -Run is disabled. Old minute worker duplicates already purchased Parquet days. Inspect existing task read-only; do not resume. First implement H5-only key-delta overlays."}
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\launch-minute-year-backfill.py'
$root='D:\stock'
foreach($file in @($py,$tool)){
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw "Missing private worker requirement: $file"}
}
if(-not (Test-Path -LiteralPath (Join-Path $root 'HikyuuData') -PathType Container)){
    throw "HikyuuData original source absent at $root; edit root in launcher if relocated"
}
$tests=@('test_minute_private_parquet_gui_worker.py','test_launch_minute_year_backfill.py')
foreach($pattern in $tests){
    & $py -m unittest discover -s (Join-Path $module 'tests') -p $pattern -v
    if($LASTEXITCODE -ne 0){throw "Minute GUI/launcher safety test failed: $pattern"}
}
$args_=@('--root',$root,'--start','2026-01-01','--end','2026-10-13',
         '--launch-real-minute-backfill')
if(-not $Run){ $args_+=@('--dry-run') }
& $py $tool @args_
if($LASTEXITCODE -ne 0){
    throw "Background writer not started: check existing minute GUI jobs and writer lock"
}
if($Run){
    Write-Host 'Backfill job requested: existing SHA-verified 41 trading days are re-used; missing actual dates will write new Parquet.'
    Write-Host 'The detached process returns immediately. This is NOT proof of conversion completion.'
    Write-Host 'Open H5ParquetReconciler\start-minute-converter.bat to attach and view live progress or pause after current day.'
    Write-Host 'All per-day actual results and state are under H5ParquetReconciler\work\minute_gui\jobs.'
}else{
    Write-Host 'Dry run only. The obsolete full-purchased-minute -Run workflow is retired; do not start a new duplicate conversion. Read docs/2026_11_03_PURCHASED_PRIMARY_ARCHITECTURE_AUDIT_AND_CORRECTION.md.'
}
