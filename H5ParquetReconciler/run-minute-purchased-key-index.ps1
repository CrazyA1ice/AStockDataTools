# One bounded purchased-primary time-key index from ORIGINAL Parquet (read-only).
# Writes only a small private SQLite key index, never copies purchased OHLCVA.
# After constructing, compare one target day entirely from indexed purchase keys.
param([string]$FromDay='2026-01-05',[string]$ThroughDay='2026-01-07',[string]$CheckDay='2026-01-07')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$builder=Join-Path $module 'tools\build-minute-purchased-key-index.py'
$exact=Join-Path $module 'tools\preview-minute-exact-key-diff-readonly.py'
$root='D:\stock'
foreach($f in @($py,$builder,$exact)){if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing index requirement: $f"}}
$patterns=@('test_write_h5_only_complete_minute_stockdays_to_private_parquet.py','test_run_minute_h5_gap_only_overlay.py','test_preview_minute_exact_key_diff_readonly.py','test_build_minute_purchased_key_index.py')
foreach($pattern in $patterns){
    & $py -B -m unittest discover -s (Join-Path $module 'tests') -p $pattern -v
    if($LASTEXITCODE -ne 0){throw "Index/preview regression failed: $pattern; no original market write started"}
}
$rid=[Guid]::NewGuid().ToString('N').Substring(0,12)
Write-Host "===== One private source-key index: $FromDay to $ThroughDay ====="
$raw=& $py -B $builder --root $root --from-day $FromDay --through-day $ThroughDay --run-id $rid
if($LASTEXITCODE -ne 0){throw 'Purchased minute source-key index build failed, original market untouched'}
$summary=($raw -join [Environment]::NewLine) | ConvertFrom-Json
if(-not (Test-Path -LiteralPath $summary.index_path -PathType Leaf)){throw 'Completed private key-index file missing'}
Write-Host "Private key-only index: $($summary.index_path)"
Write-Host "Purchased OHLCVA copied: $($summary.purchased_ohlcva_rows_copied)"
Write-Host "1min indexed A-share keys: $($summary.periods.'1min'.a_share_unique_keys); 5min: $($summary.periods.'5min'.a_share_unique_keys)"
Write-Host "===== Exact minute diff reusing index without rescanning purchased Parquet ====="
& $py -B $exact --root $root --day $CheckDay --key-index $summary.index_path
if($LASTEXITCODE -ne 0){throw 'Exact indexed source-key comparison failed; original market untouched'}
Write-Host 'PASS: index-only SQLite created in module/work; original purchased Parquet and H5 remain read-only.'
