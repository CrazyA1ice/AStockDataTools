# Exact physical row census over the already accepted eight PyArrow datasets.
# No full-market OHLCVA scan, historical 21-year row rescan, market writes,
# TDX or Oct 14-31 time window. Reads only verified Parquet file SHA/footers.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$testDir=Join-Path $module 'tests'
$testName='test_audit_asof20261013_eight_cycle_parquet_physical_rows_readonly.py'
$tool=Join-Path $module 'tools\audit-asof20261013-eight-cycle-parquet-physical-rows-readonly.py'
$datasetSha='a4987bba0ce3a1f6da05242f64cc21b94b070b193b5590ddb7bbd7f9197f5b01'
$manifest=Join-Path $module 'work\unified_parquet\datasets\eight_cycle_asof_20261013_a4987bba0ce3a1f6\manifest.json'
foreach($item in @($py,$tool,$manifest)){if(-not (Test-Path -LiteralPath $item -PathType Leaf)){throw ('Missing actual accepted dataset input: '+$item)}}
& $py -B -m unittest discover -s $testDir -p $testName -q
if($LASTEXITCODE -ne 0){throw 'Physical all-market eight-cycle row census nine regression cases failed'}
$lines=@(& $py -B $tool --root 'D:\stock' --manifest $manifest --dataset-sha256 $datasetSha)
if($LASTEXITCODE -ne 0){throw 'Real existing eight-cycle Parquet row/source/time cutoff census failed'}
$reports=@($lines|Where-Object {$_ -like 'EIGHT_CYCLE_PHYSICAL_PARQUET_FOOTER_CENSUS=*'})
if($reports.Count -ne 1){throw 'Missing uniquely identified all-eight-cycle source/footer result'}
$r=([string]$reports[0]).Substring('EIGHT_CYCLE_PHYSICAL_PARQUET_FOOTER_CENSUS='.Length)|ConvertFrom-Json
if($r.status -ne 'asof_20261013_eight_cycle_physical_arrow_parquet_footer_row_census_v1' -or $r.dataset_sha256 -ne $datasetSha -or $r.dataset_coverage_end_inclusive -ne '2026-10-13' -or $r.period_count -ne 8 -or $r.source_rowgroup_timestamp_bounds_all_before_2026_10_14 -ne $true -or $r.source_rows_counted_from_actual_Parquet_footers -ne $true -or $r.original_purchased_sources_checked_by_stat_not_full_content_SHA -ne $true -or $r.private_parquet_bytes_rechecked_by_content_SHA -ne $true -or $r.separate_historical_1990_2010_unverified_rows -ne 3682327 -or $r.historical_source_not_merged_into_standard_day -ne $true -or $r.exact_stockday_time_key_coverage_certified -ne $false -or $r.exchange_trading_calendar_certified -ne $false -or $r.vendor_physical_units_or_adjustments_certified -ne $false -or $r.new_market_or_source_files_written -ne $false -or $r.ready_for_production_query -ne $false){throw 'Unsafe or incomplete actual eight-period Parquet row census'}
$expected=[ordered]@{
    '1min'=3452748739L
    '5min'=687688817L
    '15min'=229229608L
    '30min'=114614804L
    '60min'=57307404L
    'day'=14137981L
    'week'=2996956L
    'month'=711331L
}
$sum=[long]0
foreach($cycle in $expected.Keys){
    $v=$r.periods.PSObject.Properties[$cycle]
    if($null -eq $v){throw ('Missing registered physical K-line cycle: '+$cycle)}
    $x=$v.Value
    if([long]$x.physical_rows -ne [long]$expected[$cycle] -or [long]$x.physical_files -le 0 -or [long]$x.row_groups -le 0){throw ('Original/H5 physical row counts differ from accepted whole-dataset receipts: '+$cycle)}
    $sum+=[long]$x.physical_rows
    Write-Host ('PASS_PHYSICAL_ASOF_PERIOD CYCLE='+$cycle+' FILES='+$x.physical_files+' PHYSICAL_FOOTER_ROWS='+$x.physical_rows)
}
if([long]$r.physical_source_rows_all_requested_periods -ne $sum){throw 'Physical eight-cycle total rows do not conserve'}
Write-Host ('PASS_EIGHT_CYCLE_PHYSICAL_SOURCE_ROW_CENSUS DATASET_SHA256='+$datasetSha+' EIGHT_PERIOD_PHYSICAL_ROWS='+$sum+' HISTORICAL_SEPARATE_UNVERIFIED_ROWS=3682327 ASOF=2026-10-13 NO_KLINE_FILES_WRITTEN=TRUE PRODUCTION_ACTIVATED=FALSE')
