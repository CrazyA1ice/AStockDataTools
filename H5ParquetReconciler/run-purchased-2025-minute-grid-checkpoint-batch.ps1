# Bounded/checkpointed purchased 2025 1m/5m source-key-only grid verification.
# Reuses January index, verifies existing private month receipts, builds at most
# two new monthly key-only indexes per call; repeat exact command to continue.
# Original licensed Parquet/H5 bar values are never read/written.
param([string]$FromMonth='2025-01',[string]$ThroughMonth='2025-12',[int]$MaxNewIndexMonths=2)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$runner=Join-Path $module 'tools\run-purchased-2025-minute-grid-checkpoint-batch.py'
$tests=Join-Path $module 'tests'
foreach($f in @($py,$runner)){
    if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing 2025 checkpoint requirement: $f"}
}
foreach($pattern in @('test_audit_purchased_2025_minute_source_grid_readonly.py','test_run_purchased_2025_minute_grid_checkpoint_batch.py')){
    & $py -B -m unittest discover -s $tests -p $pattern -v
    if($LASTEXITCODE -ne 0){throw "Source-only synthetic checkpoint safety tests FAILED: $pattern"}
}
Write-Host ("===== 2025 source-key checkpoint batch "+$FromMonth+".."+$ThroughMonth+" =====")
& $py -B $runner --root 'D:\stock' --from-month $FromMonth --through-month $ThroughMonth --max-new-index-months $MaxNewIndexMonths --build-missing-private-index
if($LASTEXITCODE -ne 0){throw 'Source-key-only monthly batch audit FAILED; do not duplicate a partial index or auto-fill H5'}
Write-Host 'SAFE: no purchased OHLCVA copy, no H5 bar read, no production activation. PARTIAL status means repeat the same command to resume verified months.'
