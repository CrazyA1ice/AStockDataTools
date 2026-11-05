# Full 2025 purchased FIVE-minute ts/symbol-only excluded-code audit.
# Revalidate twelve source-key receipts and full five-cycle footer totals
# before a bounded 5min key-only stream; no 1min rescan or OHLCVA/H5 read.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\audit-purchased-2025-unselected-5min-code-prefixes-readonly.py'
$tests=Join-Path $module 'tests'
foreach($f in @($py,$tool)){
    if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing 2025 excluded-code audit prerequisite: $f"}
}
foreach($pattern in @('test_reconcile_2025_selected_minute_keys_to_five_cycle_footers_readonly.py','test_audit_purchased_2025_unselected_5min_code_prefixes_readonly.py')){
    & $py -B -m unittest discover -s $tests -p $pattern -v
    if($LASTEXITCODE -ne 0){throw "Source code-prefix synthetic safety tests failed: $pattern; no real source opened"}
}
Write-Host '===== Original purchased 2025 5min ts/symbol-only streaming source classification ====='
Write-Host 'Preflight: twelve month receipts + five cycle footers; max source rows 70,000,000; price/volume/amount NOT read.'
$json=@(& $py -B $tool --root 'D:\stock' --max-source-rows 70000000)
$exit=$LASTEXITCODE
if($exit -ne 0){
    $json | Out-Host
    throw 'Unselected 2025 5min source-code audit detected an exception. Source files untouched.'
}
$safe=($json -join [Environment]::NewLine) | ConvertFrom-Json
if($safe.status -ne '2025_5min_unselected_source_code_prefixes_audited_not_security_master' -or $safe.selected_ashare_code_candidate_rows -ne 63200928 -or $safe.scanned_source_rows -ne 64081920 -or $safe.unselected_source_rows -ne 880992 -or $safe.unselected_all_observed_stockdays_match_48_key_grid -ne $true -or $safe.no_ohlcva_columns_opened -ne $true -or $safe.original_market_files_modified -ne $false -or $safe.h5_market_bars_opened -ne $false -or $safe.new_private_index_or_market_files_written -ne $false -or $safe.production_source_activated -ne $false -or $safe.security_type_by_code_prefix_certified -ne $false){
    throw '2025 excluded-code source totals, security-master caveats or safety invariant failed'
}
Write-Host ("PASS 5MIN_ALL="+$safe.scanned_source_rows+" A_SHARE_SELECTED="+$safe.selected_ashare_code_candidate_rows+" UNSELECTED="+$safe.unselected_source_rows+" UNSELECTED_STOCKDAYS="+$safe.unselected_observed_stockdays+" FULL_48_KEY_STOCKDAYS="+$safe.unselected_complete_48_key_stockdays)
Write-Host ("GROUP_COUNT="+@($safe.unselected_code_groups.PSObject.Properties).Count+" DISTINCT_UNSELECTED_RAW_SYMBOLS="+$safe.unselected_distinct_raw_symbols+" UNKNOWN_OR_UNRECOGNIZED_ROWS="+$safe.unselected_recognized_or_unknown_code_categories.unrecognized_raw_symbol+" CLASS_MASTER_CERTIFIED=False")
$groups=@($safe.unselected_code_groups.PSObject.Properties | Sort-Object { $_.Value.source_rows } -Descending)
foreach($g in $groups){
    Write-Host ("RAW_CODE_PREFIX="+$g.Name+" ROWS="+$g.Value.source_rows+" STOCKDAYS="+$g.Value.observed_unselected_stockday_count+" DISTINCT_CODES="+$g.Value.distinct_raw_symbol_count+" ASSET_CLASS_UNCERTIFIED=True")
}
Write-Host 'PASS: 2025 unselected source code-prefix and 5min key-grid audit complete. Prefix NOT securities master; 1min remainder still footer-only; no market source writes.'
