# Real Parquet -> same resumable native 1min/5min Hikyuu H5 workspace:
# exact already-verified purchased 2026-09-01..09-22 weekday windows.
# 2026-09-23 is already committed; 09-24 is in accepted original-copy base;
# 09-28..30 are in previously SHA-verified native H5. No other dates scanned.
# Four full purchased weeks (bounded <=12m source bars / <=7 calendar days)
# are committed one at a time with per-stock SQLite/H5 crash recovery.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$mod=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $mod
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$manifest=Join-Path $mod 'work\unified_parquet\datasets\eight_cycle_asof_20261013_a4987bba0ce3a1f6\manifest.json'
$workspace=Join-Path $mod 'work\h5_mirror\minute_resumable_22dc038f17a2'
$state=Join-Path $workspace 'initialized.json'
$previous=Join-Path $workspace 'batches\batch_2026-09-23_2026-09-23\done.json'
$worker=Join-Path $mod 'tools\resume-purchased-minute-parquet-into-private-native-h5.py'
$orchestrator=Join-Path $mod 'tools\run-real-2026-september-purchased-minute-h5-resumable-waves.py'
$tests=Join-Path $mod 'tests'
foreach($item in @($py,$manifest,$state,$previous,$worker,$orchestrator)){if(-not (Test-Path -LiteralPath $item -PathType Leaf)){throw ('Missing accepted ongoing native-H5 source: '+$item)}}
$prior=Get-Content -LiteralPath $previous -Raw -Encoding UTF8 | ConvertFrom-Json
if($prior.status -ne 'private_resumable_native_minute_H5_parquet_purchased_wave_committed' -or $prior.window[0] -ne '2026-09-23' -or $prior.window[1] -ne '2026-09-23' -or [long]$prior.purchased_parquet_rows_processed_by_period.'1min' -ne 1341647 -or [long]$prior.purchased_parquet_rows_processed_by_period.'5min' -ne 267216 -or $prior.original_purchased_parquet_or_hikyuu_H5_modified -ne $false -or $prior.production_H5_activated -ne $false){throw 'Requires prior actual 2026-09-23 native H5 commit, source untrusted'}
Write-Host '===== 10 NATIVE H5 STOCK RECOVERY/WEEK SOURCE TESTS ====='
& $py -B -m unittest discover -s $tests -p 'test_resume_purchased_minute_parquet_into_private_native_h5.py' -q
if($LASTEXITCODE -ne 0){throw 'Real PyTables/sqlite weekly purchase H5 tests failed before market read'}
Write-Host '===== 9 DETERMINISTIC CONFIRMED-TRADEDATE WEEK / CRASH RESTART TESTS ====='
& $py -B -m unittest discover -s $tests -p 'test_run_real_2026_september_purchased_minute_h5_resumable_waves.py' -q
if($LASTEXITCODE -ne 0){throw 'Four-week real purchased H5 batch plan tests failed'}
Write-Host '===== REAL PARQUET -> CONTINUOUS 1MIN/5MIN H5 SEPTEMBER 2026 FOUR WAVES ====='
& $py -B $orchestrator --root 'D:\stock' --manifest $manifest --max-waves 4 --write-verified-september-purchased-private-h5 | Tee-Object -Variable progress
if($LASTEXITCODE -ne 0){throw 'Actual September source-to-private-H5 batch failed; restart SAME command to resume safely'}
$lines=@($progress|Where-Object {$_ -like 'PASS_2026_SEPTEMBER_PURCHASED_1MIN_5MIN_NATIVE_H5_RESUMABLE_WAVES=*'})
if($lines.Count -ne 1){throw 'Four-week private minute H5 acceptance receipt missing'}
$summary=([string]$lines[0]).Substring('PASS_2026_SEPTEMBER_PURCHASED_1MIN_5MIN_NATIVE_H5_RESUMABLE_WAVES='.Length)|ConvertFrom-Json
if($summary.status -ne 'accepted_purchased_2026_september_minute_H5_rolling_windows' -or $summary.window_count -ne 4 -or $summary.purchased_source_days_in_full_explicit_plan -ne 16 -or $summary.previous_sep23_24_and_sep28_30_not_rebuilt -ne $true -or $summary.original_purchased_or_hikyuu_market_files_modified -ne $false -or $summary.native_minute_units_vendor_certified -ne $false -or $summary.production_h5_activated -ne $false -or @($summary.completed_or_reused_windows).Count -ne 4 -or [long]$summary.purchased_source_rows_processed_in_these_windows.'1min' -le 0 -or [long]$summary.purchased_source_rows_processed_in_these_windows.'5min' -le 0){throw 'Four purchased-week H5 transaction summary did not pass safety/readback gates'}
Write-Host ('PASS_SEPTEMBER_PURCHASED_PRIVATE_H5_REFILLED_16_CONFIRMED_DAYS PURCHASED_1MIN='+$summary.purchased_source_rows_processed_in_these_windows.'1min'+' PURCHASED_5MIN='+$summary.purchased_source_rows_processed_in_these_windows.'5min'+' WORKSPACE='+$workspace+' ORIGINAL_MARKET_WRITES=0')
Write-Host ('NATIVE_H5_COMPLETE_DAY_SEPARATE='+ (Join-Path $mod 'work\h5_mirror\complete_day_cd7633cd99cb'))
Write-Host ('H5_SIX_FILE_CONTINUOUS_WORKSPACE='+$workspace)
