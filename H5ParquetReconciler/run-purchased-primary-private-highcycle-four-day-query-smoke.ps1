# Research-only real original purchased 15/30/60 + four completed H5-5min
# candidate dates in one existing-source / no-new-market-file query.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tests=Join-Path $module 'tests'
$tool=Join-Path $module 'tools\query-purchased-primary-with-private-highcycle-readonly.py'
foreach($f in @($py,$tool)){if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw ('Missing eight-cycle highcycle research query prerequisite: '+$f)}}
foreach($pattern in @('test_query_purchased_primary_all_eight_cycles_readonly.py','test_audit_2026_oct_high_cycle_private_day_coverage_readonly.py','test_query_purchased_primary_with_private_highcycle_readonly.py')){
    & $py -B -m unittest discover -s $tests -p $pattern -q
    if($LASTEXITCODE -ne 0){throw ('Purchased/highcycle query synthetic test failed: '+$pattern)}
}
$marker='research_derived_candidate_from_sha_verified_h5_5min'
foreach($pair in @(@('15min',16,64),@('30min',8,32),@('60min',4,16))){
    $period=[string]$pair[0]
    $bought=[int]$pair[1]
    $derived=[int]$pair[2]
    $lines=@(& $py -B $tool --root 'D:\stock' --symbol SH600000 --period $period --from-day 2026-09-30 --through-day 2026-10-13 --allow-private-highcycle --max-result-bars 200 --max-candidate-rows 30000000)
    if($LASTEXITCODE -ne 0){throw ('Real purchased/highcycle mixed query failed: '+$period)}
    $all=($lines -join [Environment]::NewLine)|ConvertFrom-Json
    $p=$all.bars_by_source.PSObject.Properties['purchased_parquet']
    $h=$all.bars_by_source.PSObject.Properties[$marker]
    if($null -eq $p -or $null -eq $h -or $all.status -ne 'purchased_primary_eight_cycle_private_highcycle_explicit_readonly_v1' -or $all.symbol -ne 'SH600000' -or $all.period -ne $period -or $all.from_date -ne '2026-09-30' -or $all.to_date -ne '2026-10-13' -or $p.Value -ne $bought -or $h.Value -ne $derived -or $all.matching_bar_count -ne ($bought+$derived) -or @($all.private_candidate_source_days_checked).Count -ne 4 -or $all.private_highcycle_explicitly_enabled -ne $true -or $all.purchased_stockday_priority -ne $true -or $all.private_source_5min_sha_rederived_for_selected_symbol_day -ne $true -or $all.vendor_physical_units_certified -ne $false -or $all.time_label_semantics_certified -ne $false -or $all.corporate_adjustments_certified -ne $false -or $all.ready_for_production_query -ne $false -or $all.ready_for_h5_mirror -ne $false -or $all.original_market_files_modified -ne $false -or $all.new_market_or_index_files_written -ne $false -or $all.private_or_production_active_pointer_modified -ne $false -or $all.no_raw_ohlcva_in_summary -ne $true){throw ('Unsafe original bought/private highcycle research query counts: '+$period)}
    Write-Host ('PASS_ORIGINAL_PARQUET_PLUS_PRIVATE_OCT_HIGH_CYCLE PERIOD='+$period+' PURCHASED='+$p.Value+' H5_DERIVED='+$h.Value+' TOTAL='+$all.matching_bar_count+' PRODUCTION_ACTIVATED=FALSE')
}
Write-Host 'PASS_EIGHT_CYCLE_15_30_60_PURCHASED_PRIMARY_WITH_OCT_PRIVATE_HIGHCYCLE QUERY_ONLY=TRUE ORIGINAL_MARKET_WRITES=FALSE PRODUCTION_MERGED=FALSE'
