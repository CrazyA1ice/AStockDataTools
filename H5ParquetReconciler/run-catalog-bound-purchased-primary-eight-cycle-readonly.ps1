# Query ALL eight Kline cycles bound to ONE previously accepted immutable
# SHA catalog: paid original Parquet first; Oct private H5 candidate opt-in.
# Foreground only. NO purchased data copy, H5 mirror, index or pointer write.
param([Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$CatalogSha256)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\query-catalog-bound-purchased-primary-eight-cycles-readonly.py'
$tests=Join-Path $module 'tests'
foreach($path in @($py,$tool)){if(-not (Test-Path -LiteralPath $path -PathType Leaf)){throw ('Missing catalog-bound query prerequisite: '+$path)}}
foreach($pattern in @(
    'test_query_purchased_primary_all_eight_cycles_readonly.py',
    'test_query_purchased_primary_with_private_highcycle_readonly.py',
    'test_build_purchased_primary_eight_cycle_private_source_catalog.py',
    'test_query_catalog_bound_purchased_primary_eight_cycles_readonly.py'
)){
    & $py -B -m unittest discover -s $tests -p $pattern -q
    if($LASTEXITCODE -ne 0){throw ('Catalog-bound eight-cycle query safety tests failed: '+$pattern)}
}
# ONE invocation, ONE catalog source SHA/receipt preflight, EIGHT periods.
# Live prices never go to stdout. Only bound aggregate source counts are shown.
$lines=@(& $py -B $tool --root 'D:\stock' --catalog-sha256 $CatalogSha256 --symbol SH600000 --periods 1min 5min 15min 30min 60min day week month --from-day 2026-09-30 --through-day 2026-10-13 --max-result-bars 5000 --max-candidate-rows 30000000 --allow-private-gap)
if($LASTEXITCODE -ne 0){throw 'SHA-catalog-bound purchased/H5 eight-cycle real research query failed'}
$found=@($lines|Where-Object {$_ -like 'CATALOG_BOUND_EIGHT_CYCLE_READONLY_QUERY=*'})
if($found.Count -ne 1){throw 'Unique catalog-bound eight-cycle SAFE missing'}
$r=([string]$found[0]).Substring('CATALOG_BOUND_EIGHT_CYCLE_READONLY_QUERY='.Length)|ConvertFrom-Json
if($r.status -ne 'purchased_primary_catalog_sha_bound_eight_cycle_research_query_v1' -or $r.catalog_sha256 -ne $CatalogSha256 -or $r.symbol -ne 'SH600000' -or $r.from_day -ne '2026-09-30' -or $r.through_day -ne '2026-10-13' -or @($r.periods).Count -ne 8 -or $r.catalog_all_purchased_and_private_sources_revalidated_at_start -ne $true -or $r.purchased_original_file_refs -ne 192 -or $r.h5_private_minute_refs -ne 8 -or $r.highcycle_private_candidate_stockdays -ne 22191 -or $r.highcycle_private_candidate_rows -ne 621348 -or $r.private_h5_gap_explicitly_enabled -ne $true -or $r.private_candidate_source_and_file_shas_revalidated -ne $true -or $r.purchase_reference_identity_is_stat_not_full_content_sha256 -ne $true -or $r.vendor_physical_units_certified -ne $false -or $r.time_label_semantics_certified -ne $false -or $r.corporate_adjustments_certified -ne $false -or $r.day_week_month_candidate_overlays_not_registered_here -ne $true -or $r.ready_for_production_query -ne $false -or $r.ready_for_h5_mirror -ne $false -or $r.original_market_files_modified -ne $false -or $r.new_market_or_index_files_written -ne $false -or $r.production_query_activated -ne $false -or $r.no_raw_ohlcva_in_safe_summary -ne $true){throw 'Unsafe catalog-bound eight-cycle query provenance'}
$expected=@{
  '1min'=@(241,960,1201);
  '5min'=@(48,192,240);
  '15min'=@(16,64,80);
  '30min'=@(8,32,40);
  '60min'=@(4,16,20)
}
$actual=@{}
$sum=0
foreach($item in @($r.periods)){
    $cycle=[string]$item.period
    if($actual.ContainsKey($cycle)){throw ('Duplicate cycle in catalog response: '+$cycle)}
    $actual[$cycle]=$item
    if($item.production_activated -ne $false -or $item.candidate_vendor_units_certified -ne $false -or $item.matching_bar_count -lt 0){throw ('Unsafe cycle: '+$cycle)}
    $sum+=[int]$item.matching_bar_count
    if($expected.ContainsKey($cycle)){
        $paid=$item.bars_by_source.PSObject.Properties['purchased_parquet']
        $h5=@($item.bars_by_source.PSObject.Properties | Where-Object {$_.Name -ne 'purchased_parquet'} | Measure-Object -Property Value -Sum)[0].Sum
        $want=$expected[$cycle]
        if($null -eq $paid -or $paid.Value -ne $want[0] -or $h5 -ne $want[1] -or $item.matching_bar_count -ne $want[2] -or $item.private_gap_requested -ne $true){throw ('Purchased-first/catalog H5 source counts changed: '+$cycle)}
        Write-Host ('PASS_SHA_BOUND_PERIOD CYCLE='+$cycle+' PURCHASED='+$paid.Value+' VERIFIED_H5_PRIVATE='+$h5+' ROWS='+$item.matching_bar_count)
    }else{
        if($cycle -notin @('day','week','month') -or $item.private_gap_requested -ne $false){throw ('Unknown or private day/week/month source: '+$cycle)}
        $h5=(@($item.bars_by_source.PSObject.Properties | Where-Object {$_.Name -ne 'purchased_parquet'} | Measure-Object -Property Value -Sum)[0].Sum)
        if($h5 -ne 0){throw ('Unregistered day/week/month H5 overlay: '+$cycle)}
        Write-Host ('PASS_SHA_BOUND_PURCHASED_NATIVE_PERIOD CYCLE='+$cycle+' ROWS='+$item.matching_bar_count)
    }
}
if($actual.Count -ne 8 -or $r.matching_bars_across_requested_cycles -ne $sum){throw 'Eight-cycle combined stockday/row conservation failed'}
Write-Host ('PASS_CATALOG_SHA_BOUND_PURCHASED_PRIMARY_EIGHT_CYCLES SHA256='+$r.catalog_sha256+' PERIODS=8 ORIGINAL_PAID_PARQUET_REFS=192 RESEARCH_HIGHCYCLE_ROWS=621348 NEW_MARKET_FILES=0 ORIGINAL_MARKET_WRITES=FALSE PRODUCTION_MERGED=FALSE')
