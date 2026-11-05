# 2025 January purchased 1m/5m exact stock-day time-grid audit.
# Reuse pre-existing private source-key indexes; create missing key-only index.
# No H5 bar reads, no licensed OHLCVA reads or writes, and no market copies.
param([string]$Month='2025-01')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\audit-purchased-2025-minute-source-grid-readonly.py'
$tests=Join-Path $module 'tests'
foreach($f in @($py,$tool)){
    if(-not (Test-Path -LiteralPath $f -PathType Leaf)){
        throw "Missing 2025 purchased-source grid requirement: $f"
    }
}
& $py -B -m unittest discover -s $tests -p 'test_audit_purchased_2025_minute_source_grid_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Synthetic 2025 purchased-minute grid tests FAILED; original source not scanned'}
Write-Host ("===== 2025 purchased minute source grid: "+$Month+" =====")
$raw=@(& $py -B $tool --root 'D:\stock' --month $Month --build-missing-private-index)
if($LASTEXITCODE -ne 0){throw '2025 purchased-minute key grid audit failed; original market files remain read-only'}
$safe=($raw -join [Environment]::NewLine) | ConvertFrom-Json
if($safe.original_purchased_parquet_ohlcva_opened -ne $false -or $safe.h5_source_row_data_opened -ne $false -or $safe.purchased_market_bars_copied -ne 0 -or $safe.new_market_parquet_or_h5_files_written -ne $false -or $safe.production_query_activated -ne $false -or $safe.source_metadata_stable_during_audit -ne $true){
    throw '2025 purchased-minute key audit violated source-only contract'
}
Write-Host ("MONTH="+$safe.month+" INDEX_CREATED="+$safe.private_indexes_created+" REUSED="+$safe.existing_indexes_reused+" 1MIN_STOCKDAYS="+$safe.periods.'1min'.stockdays+" 1MIN_KEYS="+$safe.periods.'1min'.keys+" 5MIN_STOCKDAYS="+$safe.periods.'5min'.stockdays+" 5MIN_KEYS="+$safe.periods.'5min'.keys)
Write-Host ("GRID_COMPLETE="+$safe.complete_time_grid_for_every_observed_stockday+" CROSS_PERIOD_SYMBOLS_AGREE="+$safe.same_stock_symbols_in_both_periods_on_each_date+" WEEKDAY_DATES_WITHOUT_SOURCE="+(@($safe.weekday_dates_without_purchased_source_evidence) -join ',')+" WEEKEND_DATES_WITH_SOURCE="+(@($safe.weekend_dates_with_purchased_source_evidence) -join ','))
if($safe.complete_time_grid_for_every_observed_stockday -ne $true -or $safe.same_stock_symbols_in_both_periods_on_each_date -ne $true -or @($safe.weekend_dates_with_purchased_source_evidence).Count -gt 0){
    throw '2025 purchased minute-source grid exceptions found; review the source before any H5 fill'
}
Write-Host 'PASS: purchased 2025 source stockdays have exact observed grids; checked existing or new private key-only index; never read/write OHLCVA or H5 bars; no exchange-calendar certification.'
