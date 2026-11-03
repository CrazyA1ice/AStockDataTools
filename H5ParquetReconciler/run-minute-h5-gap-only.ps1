# New purchased-primary 1min/5min overlay. Default is READ-ONLY preview.
# -Run writes only H5 full stockdays absent in original purchased Parquet.
# Existing full-purchased-day backfill remains permanently retired.
param([string]$Day='2026-01-07',[switch]$Run)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\run-minute-h5-gap-only-overlay.py'
$root='D:\stock'
foreach($f in @($py,$tool)){
    if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing requirement: $f"}
}
foreach($d in @('AllCycleAStockData','HikyuuData')){
    if(-not (Test-Path -LiteralPath (Join-Path $root $d) -PathType Container)){
        throw "Original market source absent: $root\$d"
    }
}
foreach($test in @('test_write_h5_only_complete_minute_stockdays_to_private_parquet.py','test_run_minute_h5_gap_only_overlay.py')){
    & $py -m unittest discover -s (Join-Path $module 'tests') -p $test -v
    if($LASTEXITCODE -ne 0){throw "Gap-only safety tests FAILED: $test; no real market write started"}
}
$rid=[Guid]::NewGuid().ToString('N').Substring(0,12)
$args_=@('--root',$root,'--day',$Day,'--run-id',$rid)
if($Run){$args_+=@('--write-gap-only')}
& $py $tool @args_
if($LASTEXITCODE -ne 0){throw 'New purchased-primary H5-only minute task FAILED; original market sources are read-only'}
if(-not $Run){Write-Host 'READ-ONLY gap preview finished: no Parquet file, original market source or report was written.'}
else{Write-Host 'Gap-only task finished: inspect accepted_new_h5_full_stockday_gap_rows; 0 means no minute Parquet written.'}
