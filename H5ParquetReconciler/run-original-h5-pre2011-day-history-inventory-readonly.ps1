# Mainline read-only 1990-2010 native H5 day-key inventory.
# No purchased/H5 market OHLCVA read, no bar conversion, no staging or writes.
# The exact H5 symbol identifiers stay local in memory; only year aggregates.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\inventory-original-h5-1990-2010-day-keys-readonly.py'
$tests=Join-Path $module 'tests'
foreach($file in @($py,$tool)){
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw "Missing pre-2011 historical H5 inventory prerequisite: $file"}
}
& $py -B -m unittest discover -s $tests -p 'test_inventory_original_h5_1990_2010_day_keys_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Pre-2011 daily H5 native-key inventory synthetic regression failed; real market sources not opened'}
Write-Host '===== Historical H5 daily 1990-2010: native datetime key-only scan (source files read-only) ====='
$raw=@(& $py -B $tool --source-root 'D:\stock' --max-rows 30000000 --chunk-rows 16384)
if($LASTEXITCODE -ne 0){$raw | Out-Host;throw 'Pre-2011 H5 original date-key inventory failed closed; no market/source write'}
$safe=($raw -join [Environment]::NewLine) | ConvertFrom-Json
if($safe.state -ne 'pre2011_hikyuu_daily_native_key_inventory_readonly_not_merged' -or $safe.source_period -ne 'day' -or $safe.year_start -ne 1990 -or $safe.year_end -ne 2010 -or $safe.years_in_inventory -ne 21 -or $safe.market_ohlcva_read -ne $false -or $safe.source_security_codes_exported -ne $false -or $safe.original_source_h5_file_stat_unchanged -ne $true -or $safe.market_source_files_written -ne $false -or $safe.private_candidate_or_version_created -ne $false -or $safe.production_query_activated -ne $false -or $safe.ready_to_merge_into_parquet -ne $false -or $safe.purchased_parquet_pre2011_overlap_verified -ne $false){throw 'Pre-2011 H5 historical inventory SAFE or source conservation gate failed'}
$rows=@($safe.annual_coverage)
$sumA=[long]0;$sumOther=[long]0
foreach($r in $rows){$sumA+=[long]$r.h5_a_share_code_candidate_stockdays;$sumOther+=[long]$r.h5_other_code_stockdays; if([long]$r.h5_a_share_code_candidate_stockdays -gt 0 -or [long]$r.h5_other_code_stockdays -gt 0){Write-Host ("YEAR="+$r.year+" H5_A_CODE_CANDIDATE_STOCKDAYS="+$r.h5_a_share_code_candidate_stockdays+" A_CODE_SYMBOLS="+$r.a_share_candidate_source_symbol_count+" A_CODE_DATES="+$r.a_share_candidate_distinct_dates+" OTHER_INSTRUMENT_STOCKDAYS="+$r.h5_other_code_stockdays)}}
if($rows.Count -ne 21 -or $sumA -ne [long]$safe.h5_a_share_code_candidate_stockdays_total -or $sumOther -ne [long]$safe.h5_other_code_stockdays_total -or ($sumA+$sumOther) -ne [long]$safe.source_native_day_keys_projected){throw 'Historical per-year source key counts not conserved'}
Write-Host ("H5_PRE2011_A_CODE_CANDIDATE_STOCKDAYS_TOTAL="+$sumA+" OTHER_INSTRUMENT_STOCKDAYS_TOTAL="+$sumOther+" EARLIEST_NATIVE_SOURCE_KEY="+$safe.first_native_source_key_observed)
Write-Host ("KEY_ONLY_SOURCE_STATE_SHA256="+$safe.source_file_size_mtime_state_sha256+" PRE_1990_SOURCE_KEYS_SEEN="+$safe.source_has_keys_before_1990)
Write-Host 'PASS: 21-year 1990-2010 H5 source native key coverage inventoried; A-code candidates separate from other instruments. No purchased overlap, calendar/security-master certification or production merge implied.'
