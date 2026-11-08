# 2026 high-cycle candidate preflight: source-only purchased 5min reference vs.
# purchased 15/30/60m/day + SHA-verified H5 2026-10-13 5min, NO writes.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\audit-2026-oct-h5-five-minute-high-cycle-candidates-readonly.py'
$tests=Join-Path $module 'tests'
foreach($f in @($py,$tool)){if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing source-only higher-cycle calibration prerequisite: $f"}}
foreach($pattern in @('test_query_purchased_primary_all_eight_cycles_readonly.py','test_audit_2026_oct_h5_five_minute_high_cycle_candidates_readonly.py')){
    & $py -B -m unittest discover -s $tests -p $pattern -q
    if($LASTEXITCODE -ne 0){throw "High-cycle calibration synthetic gate failed: $pattern"}
}
$lines=@(& $py -B $tool --root 'D:\stock' --symbols SH600000 SZ000001)
if($LASTEXITCODE -ne 0){throw 'Real source-only Oct 2026 high-cycle candidate calibration failed'}
$safe=@($lines|Where-Object {$_ -like 'HIGH_CYCLE_2026_OCT_SOURCE_GATE=*'})
if($safe.Count -ne 1){throw 'Missing unique read-only calibration SAFE summary'}
$j=([string]$safe[0]).Substring('HIGH_CYCLE_2026_OCT_SOURCE_GATE='.Length)|ConvertFrom-Json
if($j.status -ne '2026_oct_13_verified_h5_5min_high_cycle_derived_candidates_readonly_not_certified' -or $j.reference_day -ne '2026-09-30' -or $j.candidate_day -ne '2026-10-13' -or $j.security_count -ne 2 -or $j.week_month_not_derived_from_single_day -ne $true -or $j.raw_purchased_time_labels_hypotheses_not_vendor_certified -ne $true -or $j.reference_OHLCVA_agreement_is_not_vendor_unit_certification -ne $true -or $j.verified_private_5min_vendor_units_certified -ne $false -or $j.independent_calendar_and_corporate_adjustment_certified -ne $false -or $j.original_H5_files_opened -ne $false -or $j.original_market_files_modified -ne $false -or $j.new_market_or_index_files_written -ne $false -or $j.no_licensed_OHLCVA_values_exported -ne $true -or $j.production_activated -ne $false){
    throw 'Unsafe 2026 high-cycle calibration or unsupported certification flags'
}
foreach($s in $j.per_security){
    if($s.purchased_anchor_5min_rows -ne 48 -or $s.verified_private_H5_candidate_5min_rows -ne 48){throw 'Incomplete purchased/H5 5min stockday'}
    foreach($period in @('15min','30min','60min','day')){
        $a=$s.purchased_reference_agreement.PSObject.Properties[$period].Value
        $x=$s.private_derived_target_day.PSObject.Properties[$period].Value
        if($x.five_minute_H5_SHA_checked_by_existing_query -ne $true -or $x.candidate_source_full_native_session_grid -ne $true -or $x.not_materialized_and_not_vendor_unit_certified -ne $true){throw "Unsafe source provenance for $period"}
        Write-Host ('OCT_HIGH_CYCLE SYMBOL='+$s.symbol+' PERIOD='+$period+' REFERENCE_PURCHASED='+$a.original_purchased_rows+' REFERENCE_HYPOTHESIS='+$a.candidate_buckets+' MATCH_RAW_LABELS='+$a.matched_raw_label_keys+' MATCH_ALL_SIX_FIELDS='+$a.bars_matching_all_six_fields+' OCT_PURCHASED='+$x.existing_original_purchased_target_day_bars+' OCT_POTENTIAL_H5_DERIVED='+$x.candidate_derived_buckets_when_purchased_absent+' VENDOR_UNITS_CERTIFIED=FALSE')
    }
}
Write-Host 'PASS_2026_OCT_HIGH_CYCLE_5MIN_CANDIDATE_SOURCE_CALIBRATION_READONLY NO_MARKET_WRITES=TRUE PRODUCTION_MERGED=FALSE'
