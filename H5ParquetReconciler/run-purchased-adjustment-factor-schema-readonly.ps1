# Inspect original purchased corporate adjustment factor Parquet SCHEMA/FOOTER only.
# Factor source not a ninth K-line, and factor direction is NOT certified.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\inspect-purchased-adjustment-factor-parquet-schema-readonly.py'
$test=Join-Path $module 'tests'
foreach($f in @($py,$tool)){
    if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing adjustment factor schema preflight: $f"}
}
& $py -B -m unittest discover -s $test -p 'test_inspect_purchased_adjustment_factor_parquet_schema_readonly.py' -q
if($LASTEXITCODE -ne 0){throw 'Adjustment factor synthetic schema and no-write gates FAILED'}
$data=@(& $py -B $tool --root 'D:\stock')
if($LASTEXITCODE -ne 0){throw 'Original adjustment factor schema-only inventory FAILED'}
$report=($data -join [Environment]::NewLine)|ConvertFrom-Json
if($report.status -ne 'purchased_adjustment_factor_parquet_footer_schema_only_not_certified' -or $report.source_files -lt 1 -or $report.source_file_stat_unchanged -ne $true -or $report.original_parquet_row_groups_read -ne $false -or $report.original_parquet_ohlcva_or_factor_values_read -ne $false -or $report.original_market_files_modified -ne $false -or $report.new_market_files_written -ne $false -or $report.source_file_years_and_exact_trade_date_coverage_certified -ne $false -or $report.factor_value_semantics_and_adjustment_direction_certified -ne $false -or $report.corporate_action_adjusted_kline_materialized -ne $false -or $report.production_activated -ne $false){
    throw 'Factor source schema SAFE has unsafe or misleading source state'
}
Write-Host ('FACTOR_SOURCE_FILES='+$report.source_files+' ROWS_FROM_FOOTERS='+$report.source_footer_rows+' ROWGROUPS='+$report.source_rowgroups+' FACTOR_ADJUSTMENT_SEMANTICS_CERTIFIED=FALSE')
foreach($f in @($report.file_schemas)){
    $fields=@($f.arrow_fields|ForEach-Object {$_.name+':'+$_.type})
    Write-Host ('FACTOR_FILE_ORDINAL='+$f.file_ordinal+' FOOTER_ROWS='+$f.footer_rows+' ROWGROUPS='+$f.row_groups+' ARROW_SCHEMA='+($fields -join ','))
}
Write-Host 'PASS_FACTOR_PARQUET_FOOTER_SCHEMA_ONLY NO_FACTOR_VALUES_READ=TRUE NO_MARKET_WRITES=TRUE PRODUCTION_MERGED=FALSE'
