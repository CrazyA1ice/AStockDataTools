# Original H5 2025 1min SH/SZ/BJ monthly coverage by native datetime ONLY.
# Does not open purchased Parquet, decode OHLCVA or write market sources.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\inventory-2025-h5-native-1min-month-coverage-readonly.py'
$test=Join-Path $module 'tests'
foreach($path in @($py,$tool)){
    if(-not (Test-Path -LiteralPath $path -PathType Leaf)){
        throw "Required original H5 1min inventory prerequisite missing: $path"
    }
}
foreach($pattern in @('test_inventory_2025_h5_native_1min_month_coverage_readonly.py','test_probe_original_minute_source_ends_readonly.py')){
    & $py -B -m unittest discover -s $test -p $pattern -q
    if($LASTEXITCODE -ne 0){throw "H5 native monthly source inventory synthetic tests failed: $pattern"}
}
$lines=@()
& $py -B $tool --root 'D:\stock' | Tee-Object -Variable lines
if($LASTEXITCODE -ne 0){throw '2025 H5 native 1min timestamp-only monthly inventory failed'}
$monthly=@($lines|Where-Object {$_ -like 'H5_2025_1MIN_MONTH=*'})
$full=@($lines|Where-Object {$_ -like 'H5_2025_1MIN_MONTH_SUMMARY=*'})
if($monthly.Count -ne 12 -or $full.Count -ne 1){throw 'Expected precisely 12 real source-month summaries'}
$result=([string]$full[0]).Substring('H5_2025_1MIN_MONTH_SUMMARY='.Length) | ConvertFrom-Json
if($result.status -ne '2025_original_h5_native_one_minute_monthly_timestamp_coverage_readonly' -or $result.year -ne 2025 -or $result.source_h5_files_checked -ne 3 -or $result.source_market_stat_unchanged -ne $true -or $result.source_row_count_sum_conserved -ne $true -or $result.no_purchased_parquet_opened -ne $true -or $result.no_native_h5_ohlcva_decoded -ne $true -or $result.source_security_ids_or_market_values_exported -ne $false -or $result.source_2025_full_session_completeness_certified -ne $false -or $result.independent_exchange_calendar_certified -ne $false -or $result.new_market_files_written -ne $false -or $result.ready_for_production_query -ne $false){throw 'Native 1min monthly inventory source/read-only guard failed'}
$parsed=@($monthly | ForEach-Object {([string]$_).Substring('H5_2025_1MIN_MONTH='.Length) | ConvertFrom-Json})
$first=@($parsed | Where-Object {($_.native_rows_by_market.sh + $_.native_rows_by_market.sz + $_.native_rows_by_market.bj) -gt 0} | Select-Object -First 1)
if($first.Count -gt 0){Write-Host ('FIRST_MONTH_WITH_A_SHARE_1MIN_NATIVE_ROWS='+$first[0].month)}else{Write-Host 'NO_2025_A_SHARE_1MIN_NATIVE_ROWS_FOUND'}
foreach($row in $parsed){Write-Host ('MONTH='+$row.month+' SH='+$row.native_rows_by_market.sh+' SZ='+$row.native_rows_by_market.sz+' BJ='+$row.native_rows_by_market.bj)}
Write-Host 'PASS_2025_H5_1MIN_NATIVE_MONTHLY_SOURCE_INVENTORY_READONLY NO_PURCHASED_SCAN=TRUE PRODUCTION_MERGED=FALSE'
