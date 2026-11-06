# Mainline pre-2011 purchased DAILY Parquet physical coverage audit.
# Every day Parquet file and rowgroup footer is inspected irrespective of name;
# suspicious or missing-footer rowgroups project ts/symbol ONLY (never OHLCVA).
# Fail closed on source anomalies and hard budgets; NEVER merge market files.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\audit-purchased-parquet-day-pre2011-source-keys-readonly.py'
$tests=Join-Path $module 'tests'
foreach($file in @($py,$tool)){if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw "Missing purchased pre2011 day source audit prerequisite: $file"}}
& $py -B -m unittest discover -s $tests -p 'test_audit_purchased_parquet_day_pre2011_source_keys_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Synthetic original purchased day pre-2011 key-only audit tests failed; real market files not opened'}
Write-Host '===== ALL original purchased day parquet files: exact physical 1990..2010 key coverage (NO OHLCVA) ====='
$raw=@(& $py -B $tool --source-root 'D:\stock' --max-project-rows 10000000 --max-stockdays 6000000)
if($LASTEXITCODE -ne 0){$raw | Out-Host;throw 'Original purchased day Parquet footer/key audit failed closed; no market files changed'}
$safe=($raw -join [Environment]::NewLine) | ConvertFrom-Json
if($safe.state -ne 'pre2011_purchased_parquet_original_day_keys_audited_readonly' -or $safe.years -ne '1990-2010' -or $safe.all_source_day_parquet_paths_scanned_irrespective_of_filename -ne $true -or $safe.source_key_only_no_ohlcva_read -ne $true -or $safe.exact_security_codes_or_prices_exported -ne $false -or $safe.h5_stockday_key_overlap_ever_compared -ne $false -or $safe.historical_candidate_staged_or_merged -ne $false -or $safe.market_files_written -ne $false -or $safe.production_activated -ne $false -or $safe.purchased_original_source_stat_unchanged -ne $true){throw 'Purchased pre-2011 source SAFE guard failed'}
$yearrows=@($safe.annual_coverage)
if($yearrows.Count -ne 21){throw 'Purchased pre-2011 audit must cover exactly 21 calendar years'}
$sumCandidate=[long]0;$sumOther=[long]0
foreach($item in $yearrows){$sumCandidate+=[long]$item.purchased_a_share_code_candidate_stockdays;$sumOther+=[long]$item.purchased_other_instrument_stockdays;if([long]$item.purchased_a_share_code_candidate_stockdays -gt 0 -or [long]$item.purchased_other_instrument_stockdays -gt 0){Write-Host ('PURCHASED_YEAR='+$item.year+' A_CODE_STOCKDAYS='+$item.purchased_a_share_code_candidate_stockdays+' OTHER_CODE_STOCKDAYS='+$item.purchased_other_instrument_stockdays+' DISTINCT_DATES='+$item.purchased_distinct_native_date_labels)}}
if($sumCandidate -ne [long]$safe.purchased_1990_2010_a_share_code_candidate_stockdays -or $sumOther -ne [long]$safe.purchased_1990_2010_other_instrument_stockdays -or ($sumCandidate+$sumOther) -ne [long]$safe.purchased_1990_2010_all_stockday_keys -or ([long]$safe.physical_rows_pruned_by_footer+[long]$safe.physical_rows_key_projected) -ne [long]$safe.physical_rows_in_all_purchased_day_files){throw 'Purchased historical per-year/footer physical counts are not conserved'}
Write-Host ('PURCHASED_DAY_PARQUET_FILES='+$safe.source_files+' ROWGROUPS='+$safe.rowgroups_total+' FOOTER_PRUNED='+$safe.rowgroups_pruned_proven_by_min_ts_ge_2011+' KEY_PROJECTED='+$safe.rowgroups_key_projected+' ROWS_KEY_PROJECTED='+$safe.physical_rows_key_projected)
Write-Host ('PURCHASED_PRE2011_A_CODE_STOCKDAYS='+$sumCandidate+' OTHER_STOCKDAYS='+$sumOther+' BEFORE_1990_ROWS='+$safe.pre1990_physical_rows_detected+' ALL_DAY_FILES_CHECKED='+$safe.all_source_day_parquet_paths_scanned_irrespective_of_filename)
Write-Host ('PURCHASED_DAY_ORIGINAL_SOURCE_STAT_SHA256='+$safe.source_file_size_mtime_state_sha256)
if($safe.no_1990_2010_purchased_keys_in_audited_files -eq $true -and [long]$safe.pre1990_physical_rows_detected -eq 0){Write-Host 'PURCHASED_PRE2011_PHYSICAL_KEYS_ABSENT_IN_AUDITED_FILES=TRUE'}else{Write-Host 'PURCHASED_PRE2011_PHYSICAL_KEYS_ABSENT_IN_AUDITED_FILES=FALSE; EXACT_H5_PARQUET_STOCKDAY_OVERLAP_GATE_REQUIRED'}
Write-Host 'PASS: purchased 1990-2010 physical Parquet source-key coverage audited read-only; no OHLCVA, no candidate promotion, no production change.'
