# Purchased-first EIGHT-cycle + immutable registered 22,274 daily H5-only.
# Reuse two EXISTING user Windows registered SHA versions, no new Kline copies.
# Research-only: full live H5/PQ daily gate creates only non-price SAFE reports.
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$CatalogSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$DayVersionSha256
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tests=Join-Path $module 'tests'
$tool=Join-Path $module 'tools\query-catalog-bound-registered-day-22274-readonly.py'
$helper=Join-Path $module 'verify-catalog-bound-eight-cycle-sources.ps1'
foreach($file in @($py,$tool,$helper)){if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw ('Missing paired eight-cycle original source prerequisite: '+$file)}}
. $helper
foreach($pattern in @(
    'test_query_catalog_bound_purchased_primary_eight_cycles_readonly.py',
    'test_resolve_registered_day_22274_evidence_offline.py',
    'test_query_purchased_primary_all_eight_cycles_registered_day_overlay_readonly.py',
    'test_query_catalog_bound_registered_day_22274_readonly.py'
)){
    & $py -B -m unittest discover -s $tests -p $pattern -q
    if($LASTEXITCODE -ne 0){throw ('Paired registered-day source gate test failed: '+$pattern)}
}
& (Join-Path $tests 'test_catalog_bound_eight_cycle_safe_summary.ps1')
if($LASTEXITCODE -ne 0){throw 'Windows empty-H5 provenance-count safety tests failed'}
# One per-security real day with existing 1m,5m,15m,30m,60m private gaps;
# day H5 entry is the registered 22191 whole-day +83 mixed-day version.
# The DAY 22274 bridge rechecks original source H5 and purchased Parquet LIVE.
Write-Host '===== REAL SOURCE-VERIFIED PAIRED EIGHT-CYCLE QUERY ====='
$rows=@(& $py -B $tool --root 'D:\stock' --catalog-sha256 $CatalogSha256 --registered-day-version-sha256 $DayVersionSha256 --symbol SH600000 --periods 1min 5min 15min 30min 60min day week month --from-day 2026-10-09 --through-day 2026-10-09 --allow-registered-private-day --allow-private-minute-highcycle --max-result-bars 1000)
if($LASTEXITCODE -ne 0){$rows|Out-Host;throw 'Paired eight-cycle/private registered daily full live-source check failed'}
$matches=@($rows|Where-Object {$_ -like 'CATALOG_REGISTERED_DAY_PAIRED_QUERY=*'})
if($matches.Count -ne 1){throw 'Missing unique paired eight-cycle/day-source SHA SAFE'}
$r=([string]$matches[0]).Substring('CATALOG_REGISTERED_DAY_PAIRED_QUERY='.Length)|ConvertFrom-Json
if($r.status -ne 'purchased_primary_catalog_and_registered_22274_day_live_research_query_v1' -or $r.original_eight_cycle_catalog_sha256 -ne $CatalogSha256 -or $r.registered_private_day_version_sha256 -ne $DayVersionSha256 -or $r.paired_research_version_sha256 -notmatch '^[a-f0-9]{64}$' -or $r.registered_private_day_candidates -ne 22274 -or $r.registered_whole_day_candidates -ne 22191 -or $r.registered_mixed_stockday_candidates -ne 83 -or $r.quarantined_2026_07_16_daily_candidates_excluded -ne 5 -or $r.symbol -ne 'SH600000' -or $r.from_day -ne '2026-10-09' -or $r.through_day -ne '2026-10-09' -or @($r.periods).Count -ne 8 -or $r.purchased_source_priority -ne $true -or $r.base_catalog_source_revalidated_at_start_and_end -ne $true -or $r.registered_day_live_original_source_reverified -ne $true -or $r.only_research_SAFE_reports_may_be_created -ne $true -or $r.original_market_files_modified -ne $false -or $r.new_market_or_index_files_written -ne $false -or $r.production_query_activated -ne $false -or $r.ready_for_production_query -ne $false -or $r.ready_for_h5_mirror -ne $false -or $r.physical_units_certified -ne $false -or $r.corporate_adjustments_certified -ne $false -or $r.time_label_semantics_certified -ne $false -or $r.no_raw_ohlcva_in_safe_summary -ne $true){throw 'Paired catalog/22274 source integrity flags invalid'}
$expected=@{
    '1min'=@(240,0,240);
    '5min'=@(48,0,48);
    '15min'=@(16,0,16);
    '30min'=@(8,0,8);
    '60min'=@(4,0,4);
    'day'=@(1,0,1);
    'week'=@(0,0,0);
    'month'=@(0,0,0)
}
$seen=@{}
$total=0
foreach($entry in @($r.periods)){
    $period=[string]$entry.period
    if(-not $expected.ContainsKey($period) -or $seen.ContainsKey($period)){throw ('Unexpected/repeated research cycle: '+$period)}
    $seen[$period]=$true
    $counts=Get-CatalogBoundEightCycleSourceCounts -PeriodSummary $entry -AllowPrivate ($period -notin @('week','month'))
    $want=$expected[$period]
    if($counts.Purchased -ne $want[1] -or $counts.Private -ne $want[0] -or $counts.Total -ne $want[2] -or $entry.candidate_vendor_units_certified -ne $false -or $entry.production_activated -ne $false){throw ('Wrong purchased vs H5-private bar counts: '+$period)}
    if($period -eq 'day'){
        $base=$entry.bars_by_source.PSObject.Properties['purchased_parquet']
        $whole=$entry.bars_by_source.PSObject.Properties['private_h5_whole_date_candidate']
        $mixed=$entry.bars_by_source.PSObject.Properties['private_h5_mixed_stockday_candidate']
        if($null -eq $base -or $null -eq $whole -or $null -eq $mixed -or $base.Value -ne 0 -or $whole.Value -ne 1 -or $mixed.Value -ne 0 -or $entry.full_original_H5_Parquet_day_source_live_reverified -ne $true){throw 'Registered 22,274 source daily provenance not live-verified'}
    }
    $total += [long]$counts.Total
    Write-Host ('PASS_PAIRED_EIGHT_CYCLE_PERIOD '+$period+' PURCHASED='+$counts.Purchased+' REGISTERED_H5_PRIVATE='+$counts.Private+' ROWS='+$counts.Total)
}
if($seen.Count -ne 8 -or $total -ne $r.matching_bars_across_requested_cycles){throw 'Eight-cycle paired catalog source conservation failed'}
Write-Host ('PASS_CATALOG_BOUND_REGISTERED_22274_DAY_EIGHT_CYCLES PAIR_SHA256='+$r.paired_research_version_sha256+' BASE_CATALOG='+$CatalogSha256+' DAY_REGISTERED_VERSION='+$DayVersionSha256+' RESEARCH_ONLY=TRUE ORIGINAL_MARKET_WRITES=FALSE PRODUCTION_MERGED=FALSE')
