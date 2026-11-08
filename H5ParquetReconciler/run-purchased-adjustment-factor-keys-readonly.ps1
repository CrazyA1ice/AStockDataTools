# Bounded ORIGINAL factor (symbol,d,hfq_factor) audit: no Kline OHLCVA.
# Source factor semantics are UNVERIFIED and no adjustments are produced.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\audit-purchased-adjustment-factor-keys-readonly.py'
$tests=Join-Path $module 'tests'
foreach($f in @($py,$tool)){
    if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing HFQ source key audit prerequisite: $f"}
}
foreach($pattern in @('test_inspect_purchased_adjustment_factor_parquet_schema_readonly.py','test_audit_purchased_adjustment_factor_keys_readonly.py')){
    & $py -B -m unittest discover -s $tests -p $pattern -q
    if($LASTEXITCODE -ne 0){throw "Factor source regression failed before real read: $pattern"}
}
$lines=@(& $py -B $tool --root 'D:\stock')
if($LASTEXITCODE -ne 0){throw 'Real factor source-only key audit failed'}
$safe=@($lines|Where-Object {$_ -like 'FACTOR_KEY_AUDIT_READONLY=*'})
if($safe.Count -ne 1){throw 'Missing single accepted factor-key read-only report'}
$j=([string]$safe[0]).Substring('FACTOR_KEY_AUDIT_READONLY='.Length)|ConvertFrom-Json
if($j.status -ne 'original_purchased_hfq_factor_key_coverage_and_value_health_readonly_not_certified' -or $j.factor_rows_examined -ne $j.rows_from_footer -or $j.factor_row_scan_only_not_Kline -ne $true -or $j.purchased_ohlcva_files_or_rows_opened -ne $false -or $j.original_factor_parquet_stat_unchanged -ne $true -or $j.original_market_files_modified -ne $false -or $j.new_market_or_index_files_written -ne $false -or $j.individual_security_identifiers_or_factor_values_exported -ne $false -or $j.factor_row_day_keys_verified_against_official_actions -ne $false -or $j.factor_direction_base_date_and_adjustment_semantics_certified -ne $false -or $j.source_fingerprint_is_content_sha -ne $false -or $j.production_activated -ne $false){
    throw 'Unsafe HFQ factor key audit or unsupported factor semantics'
}
Write-Host ('FACTOR_KEYS ROWS='+$j.factor_rows_examined+' DISTINCT_SYMBOLS='+$j.distinct_raw_source_symbols+' DISTINCT_SYMBOL_DAYS='+$j.distinct_raw_symbol_date_keys+' FIRST='+$j.earliest_valid_original_factor_date+' LAST='+$j.latest_valid_original_factor_date)
foreach($year in $j.observed_rows_by_year.PSObject.Properties){
    Write-Host ('FACTOR_YEAR='+$year.Name+' ROWS='+$year.Value)
}
$c=$j.counts
Write-Host ('FACTOR_HEALTH DUPLICATE_SYMBOL_DAYS='+$c.duplicate_exact_symbol_day_keys+' INVALID_SYMBOL='+$c.null_or_invalid_symbols+' INVALID_DATE='+$c.null_or_invalid_dates+' NONFINITE='+$c.nonfinite_factors+' NONPOSITIVE='+$c.nonpositive_factors+' NULL_OR_NONNUMERIC='+$c.null_or_nonnumeric_factors+' POSITIVE_ONE='+$c.positive_factor_equal_one_rows+' POSITIVE_NONONE='+$c.positive_factor_not_one_rows)
Write-Host 'PASS_PURCHASED_FACTOR_SOURCE_KEYS_READONLY ACTUAL_CORPORATE_ACTION_SEMANTICS_CERTIFIED=FALSE NO_KLINE_READ=TRUE NO_MARKET_WRITES=TRUE PRODUCTION_MERGED=FALSE'
