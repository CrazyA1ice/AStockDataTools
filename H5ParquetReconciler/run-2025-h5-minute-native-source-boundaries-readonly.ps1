# Probe H5 original 1m/5m first/last native dates before wasting monthly key scans.
# This does NOT certify source completeness, exchange days, or vendor units.
# Reads only H5 dataset edge datetimes and purchased Parquet footer metadata.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\probe-original-minute-source-ends-readonly.py'
$tests=Join-Path $module 'tests'
foreach($path in @($py,$tool)){if(-not (Test-Path -LiteralPath $path -PathType Leaf)){throw 'Missing native H5 bounds probe prerequisite'}}
foreach($name in @('test_audit_2025_purchased_h5_exact_minute_gap_months_readonly.py','test_probe_original_minute_source_ends_readonly.py')){
    & $py -B -m unittest discover -s $tests -p $name -q
    if($LASTEXITCODE -ne 0){throw ('Native H5 source evidence synthetic test failed: '+$name)}
}
$id=[Guid]::NewGuid().ToString('N').Substring(0,12)
$out=Join-Path $module ('reports\original-minute-native-h5-coverage-2025-2026-'+$id+'.json')
& $py -B $tool --root 'D:\stock' --years 2025 2026 --out $out --inspect-original-minute-source-end-only
if($LASTEXITCODE -ne 0){throw 'Original native minute source edge-only probe failed'}
$report=Get-Content -LiteralPath $out -Raw -Encoding UTF8|ConvertFrom-Json
if($report.status -ne 'original_minute_market_coverage_end_only_readonly' -or $report.original_market_files_modified -ne $false -or $report.production_pointer_modified -ne $false -or $report.complete_trading_calendar_or_intraday_coverage_verified -ne $false -or $report.source_stock_identifiers_or_ohlcva_exported -ne $false){throw 'Native source bounds SAFE status invalid'}
foreach($period in @('1min','5min')){
    $data=$report.periods.PSObject.Properties[$period].Value
    foreach($market in @('sh','sz','bj')){
        $obj=$data.h5_by_market.PSObject.Properties[$market].Value
        Write-Host ('NATIVE_H5_BOUND PERIOD='+$period+' MARKET='+$market+' EXISTS='+$obj.source_file_present+' DATASETS_WITH_ROWS='+$obj.native_tables_with_rows+' FIRST='+$obj.min_of_stock_first_native_stamps+' LAST='+$obj.max_of_stock_last_native_stamps)
        if($obj.source_file_present -eq $true -and $obj.native_tables_bad_first_last_order -gt 0){throw 'H5 source has unsorted stock datasets: reject inferred date envelopes'}
    }
}
Write-Host ('PASS_NATIVE_MINUTE_H5_SOURCE_BOUNDS_READONLY SOURCE_TRADING_CALENDAR_CERTIFIED=FALSE PRODUCTION_MERGED=FALSE SAFE='+$out)
