# Fastest actual DAY backfill: use already-built 14,137,981-row native H5
# from the accepted 2011..2026 physical Parquet. Preserve original H5
# 1990..2010 history and non-purchased securities in NEW isolated H5.
# NO original D:\stock H5 replacement, NO re-read of Parquet OHLCVA.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\merge-existing-native-day-h5-original-history-and-2011-2026-parquet-mirror.py'
$tests='test_merge_existing_native_day_h5_original_history_and_2011_2026_parquet_mirror.py'
$daySafe=Join-Path $module 'reports\full-2011-2026-native-h5-day-3dc5044a4122.json'
$dayMirror=Join-Path $module 'work\h5_mirror\full_day_3dc5044a4122'
foreach($file in @($py,$tool,$daySafe)){
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw ('Missing previous already-verified H5 result: '+$file)}
}
if(-not (Test-Path -LiteralPath $dayMirror -PathType Container)){throw 'Missing already completed 14,137,981-row native DAY H5 directory'}
Write-Host '==== SIX SAFE NATIVE H5 ORIGINAL-HISTORY + PARQUET-PRIORITY TESTS ===='
& $py -B -m unittest discover -s (Join-Path $module 'tests') -p $tests -q
if($LASTEXITCODE -ne 0){throw 'Native DAY H5 source-preserving real-write tests failed; no original market writes'}
$rid=[Guid]::NewGuid().ToString('N').Substring(0,12)
$safe=Join-Path $module ("reports\complete-day-original-plus-parquet-native-$rid.json")
Write-Host '==== COPY ORIGINAL THREE DAY H5 + REUSE PREBUILT 16-YEAR MIRROR, PRESERVE EARLY HISTORY ===='
& $py -B $tool --root 'D:\stock' --modern-day-safe $daySafe --modern-day-h5-root $dayMirror --run-id $rid --out $safe --write-isolated-complete-day
if($LASTEXITCODE -ne 0){throw 'Standalone complete DAY H5 build failed. Original D:\stock H5 unaffected'}
if(-not (Test-Path -LiteralPath $safe -PathType Leaf)){throw 'Missing complete DAY native H5 SHA/write receipt'}
$report=Get-Content -LiteralPath $safe -Raw -Encoding UTF8 | ConvertFrom-Json
if($report.status -ne 'isolated_full_day_h5_original_history_plus_2011_2026_parquet_native_merged_and_integer_verified' -or $report.modern_purchased_first_2011_2026_rows -ne 14137981 -or $report.three_native_hikyuu_day_files -ne 3 -or $report.native_full_table_readback_in_copied_h5 -ne $true -or $report.original_hikyuu_h5_or_purchased_parquet_modified -ne $false -or $report.historical_original_native_rows_discarded -ne 0 -or $report.production_h5_active_replacement_performed -ne $false -or $report.ready_for_production_h5_swap -ne $false -or @($report.new_h5_files_sha256.PSObject.Properties).Count -ne 3){throw 'Merged native DAY H5 conservation/safety acceptance failed'}
Write-Host ('PASS_ISOLATED_FULL_DAY_NATIVE_H5_WITH_PURCHASED_PARQUET_PRIORITY RUNID='+$rid+' MODERN_PARQUET_DAY_ROWS='+$report.modern_purchased_first_2011_2026_rows+' PRE2011_ORIGINAL_PRESERVED='+$report.preserved_original_native_1990_2010_rows_in_overlapping_A_share_stocks+' ORIGINAL_ONLY_NON_PURCHASED_ROWS='+$report.original_h5_2011_plus_only_native_keys_preserved+' NO_SOURCE_WRITES=TRUE')
Write-Host ('ISOLATED_COMPLETE_DAY_H5='+ (Join-Path $module ("work\h5_mirror\complete_day_$rid")))
Write-Host ('DAY_H5_MERGE_SAFE='+$safe)
