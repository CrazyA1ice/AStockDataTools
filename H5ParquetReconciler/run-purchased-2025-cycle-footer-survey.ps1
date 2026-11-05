# Read-only 2025/2026 ALL-PERIOD purchased Parquet footer discovery.
# Runs synthetic tests; then reads only original source Parquet FOOTERS.
# No OHLCVA row-batch reads, no indexes, no market files or reports written.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$script=Join-Path $module 'tools\survey-purchased-all-cycle-footers-readonly.py'
$tests=Join-Path $module 'tests'
foreach($file in @($py,$script)){
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw "Missing footer-only inventory requirement: $file"}
}
& $py -B -m unittest discover -s $tests -p 'test_survey_purchased_all_cycle_footers_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Synthetic all-cycle footer inventory tests failed; original source not opened'}
$json=@(& $py -B $script --root 'D:\stock' --years 2025 2026)
if($LASTEXITCODE -ne 0){throw 'Read-only 2025/2026 source footer inventory failed'}
$info=($json -join [Environment]::NewLine) | ConvertFrom-Json
if($info.only_original_parquet_file_footers_read -ne $true -or $info.original_h5_opened -ne $false -or $info.original_market_files_modified -ne $false -or $info.new_market_or_index_files_written -ne $false -or $info.actual_stockday_and_full_exchange_calendar_coverage_certified -ne $false){throw 'Unsafe or overclaimed footer-only inventory'}
if($info.noncanonical_directory_names_not_automatically_mapped -ne $true){throw 'Unverified period-label mapping safety contract absent'}
Write-Host ("PERIOD_DIRECTORIES="+($info.source_root_period_directories -join ',')+" YEAR_ASSIGNED_FILES="+$info.total_year_assigned_parquet_files)
if(@($info.noncanonical_period_directory_labels_semantics_unverified).Count -gt 0){
    Write-Host ("UNMAPPED_PERIOD_LABELS="+($info.noncanonical_period_directory_labels_semantics_unverified -join ',')+" (inventories only; NO period semantic mapping)")
}
foreach($name in $info.source_root_period_directories){
    $annual=$info.period_years.PSObject.Properties[$name].Value
    foreach($year in @('2025','2026')){
        $x=$annual.PSObject.Properties[$year].Value
        Write-Host ("PERIOD="+$name+" YEAR="+$year+" FILES="+$x.source_files+" ROWS_FROM_FOOTERS="+$x.source_rows_from_parquet_footers+" ROWGROUPS="+$x.row_groups+" EARLIEST_ENVELOPE="+$x.earliest_known_raw_beijing_timestamp+" LATEST_ENVELOPE="+$x.latest_known_raw_beijing_timestamp+" UNKNOWN_TS_GROUPS="+$x.nonempty_row_groups_without_usable_ts_bounds+" FULL_STOCKDAY_CERTIFIED="+$x.full_calendar_coverage_certified)
    }
}
Write-Host 'PASS: purchased source folder and 2025/2026 per-cycle footer envelopes inventoried; no OHLCVA read, source modification, index build or market-data output.'
