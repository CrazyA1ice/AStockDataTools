# First persistent new Hikyuu minute H5 write, using verified private
# 22dc038f17a2 1min/5min candidate. Copies it only ONCE into a long-lived
# workspace, then journaled per-stock updates resume without six-file copies.
# All D:\stock Parquet and native H5 sources stay READ-ONLY.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$mod=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $mod
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $mod 'tools\resume-purchased-minute-parquet-into-private-native-h5.py'
$test='test_resume_purchased_minute_parquet_into_private_native_h5.py'
$manifest=Join-Path $mod 'work\unified_parquet\datasets\eight_cycle_asof_20261013_a4987bba0ce3a1f6\manifest.json'
$base=Join-Path $mod 'reports\purchased-minute-native-h5-copy-20260924-22dc038f17a2.json'
$workspace=Join-Path $mod 'work\h5_mirror\minute_resumable_22dc038f17a2'
$done=Join-Path $workspace 'batches\batch_2026-09-23_2026-09-23\done.json'
foreach($f in @($py,$tool,$manifest,$base)){if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw ('Missing verified existing H5/Parquet input: '+$f)}}
Write-Host '===== EIGHT TEMP NATIVE H5 CRASH-RECOVERY / SOURCE PRIORITY TESTS ====='
& $py -B -m unittest discover -s (Join-Path $mod 'tests') -p $test -q
if($LASTEXITCODE -ne 0){throw 'Ongoing private H5 stock transaction regression failed; no real source touched'}
Write-Host '===== ONE-TIME PERSISTENT SIX-H5 COPY, THEN 2026-09-23 REAL PURCHASED 1MIN/5MIN WRITE ====='
& $py -B $tool --root 'D:\stock' --manifest $manifest --from-day '2026-09-23' --through-day '2026-09-23' --write-resumable-private-h5
if($LASTEXITCODE -ne 0){throw '2026-09-23 Parquet to continuous native H5 failed; retained resumable journal and original market unchanged'}
if(-not (Test-Path -LiteralPath $done -PathType Leaf)){throw 'Missing committed continuous real native minute H5 SAFE'}
$r=Get-Content -LiteralPath $done -Raw -Encoding UTF8 | ConvertFrom-Json
if($r.status -ne 'private_resumable_native_minute_H5_parquet_purchased_wave_committed' -or $r.dataset_sha256 -ne 'a4987bba0ce3a1f6da05242f64cc21b94b070b193b5590ddb7bbd7f9197f5b01' -or $r.window[0] -ne '2026-09-23' -or $r.window[1] -ne '2026-09-23' -or $r.all_stock_swaps_completed_and_journal_committed -ne $true -or $r.original_purchased_parquet_or_hikyuu_H5_modified -ne $false -or $r.original_markets_never_opened_in_write_mode -ne $true -or $r.production_H5_activated -ne $false -or $r.numeric_unit_mapping_vendor_certified -ne $false -or $r.complete_2011_2026_minute_history -ne $false -or @($r.full_private_six_file_H5_sha256.PSObject.Properties).Count -ne 6 -or [long]$r.purchased_parquet_rows_processed_by_period.'1min' -le 0 -or [long]$r.purchased_parquet_rows_processed_by_period.'5min' -le 0){throw 'Continuous native H5 real-window safety/row/checkpoint gate failed'}
Write-Host ('PASS_CONTINUOUS_NATIVE_H5_MINUTE_PARQUET_20260923 PURCHASED_1MIN='+$r.purchased_parquet_rows_processed_by_period.'1min'+' PURCHASED_5MIN='+$r.purchased_parquet_rows_processed_by_period.'5min'+' STOCKS='+$r.committed_stock_tables+' NO_MARKET_SOURCE_WRITES=TRUE')
Write-Host ('PERSISTENT_HIKYUU_MINUTE_H5='+$workspace)
Write-Host ('CONTINUOUS_H5_COMMITTED_SAFE='+$done)
