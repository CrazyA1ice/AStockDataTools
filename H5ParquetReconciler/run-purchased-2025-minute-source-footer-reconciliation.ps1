# 2025 five purchased minute-cycle footer versus 12 verified source-key checkpoints.
# Reads 2025 Parquet file footers, never OHLCVA batches or H5 market values.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\reconcile-2025-selected-minute-keys-to-five-cycle-footers-readonly.py'
$tests=Join-Path $module 'tests'
foreach($file in @($py,$tool)){
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw "Missing purchased footer reconciliation requirement: $file"}
}
& $py -B -m unittest discover -s $tests -p 'test_reconcile_2025_selected_minute_keys_to_five_cycle_footers_readonly.py' -v
if($LASTEXITCODE -ne 0){throw '2025 synthetic footer/key conservation tests failed; no original source opened'}
Write-Host '===== Read-only verified 2025 12-month key-index versus five original Parquet footer rows ====='
$json=@(& $py -B $tool --root 'D:\stock')
if($LASTEXITCODE -ne 0){$json | Out-Host;throw '2025 original footer/source-key reconciliation FAILED; source files untouched'}
$safe=($json -join [Environment]::NewLine) | ConvertFrom-Json
if($safe.status -ne '2025_source_footer_and_selected_ashare_key_totals_exactly_conserved' -or @($safe.verified_2025_grid_months).Count -ne 12 -or $safe.original_market_files_modified -ne $false -or $safe.purchased_ohlcva_bars_opened_or_copied -ne $false -or $safe.h5_opened_for_bars -ne $false -or $safe.new_private_index_or_market_files_written -ne $false -or $safe.production_source_activated -ne $false -or $safe.unselected_source_security_categories_classified -ne $false){throw '2025 source footer conservation or no-market-write contract failed'}
foreach($period in @('1min','5min','15min','30min','60min')){
    Write-Host ("PERIOD="+$period+" ALL_SOURCE_FOOTER_ROWS="+$safe.whole_source_footer_rows.PSObject.Properties[$period].Value+" WHOLE_SOURCE_GRID_EQUIVALENTS="+$safe.whole_source_standard_stockday_equivalents_by_cycle.PSObject.Properties[$period].Value)
}
Write-Host ("SELECTED_A_SHARE_STOCKDAYS="+$safe.selected_ashare_stockdays+" A_SHARE_1MIN_KEYS="+$safe.selected_ashare_minute_keys.'1min'+" A_SHARE_5MIN_KEYS="+$safe.selected_ashare_minute_keys.'5min')
Write-Host ("UNSELECTED_SOURCE_1MIN_ROWS="+$safe.unselected_source_rows_unknown_security_class.'1min'+" UNSELECTED_SOURCE_5MIN_ROWS="+$safe.unselected_source_rows_unknown_security_class.'5min'+" UNCLASSIFIED_GRID_EQUIVALENTS="+$safe.unselected_source_standard_grid_equivalents_not_certified_stockdays)
Write-Host 'PASS: 2025 purchased source footer totals conserved across five cycles and selected A-share keys; excluded security categories NOT classified; no market writes or production activation.'
