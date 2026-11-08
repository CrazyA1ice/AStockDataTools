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
$lines=@(& $py -B $tool --root 'D:\stock' --symbols SH600000 SZ000001 --oct-four-day-intraday-sweep --oct-four-day-one-to-five-consistency)
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
        if($a.full_reference_count_and_keys_agree -eq $true -and $a.bars_matching_all_six_fields -lt $a.candidate_buckets){
            $fc=$a.matching_fields_count
            Write-Host ('OCT_HIGH_CYCLE_REFERENCE_FIELD_DIAGNOSTIC SYMBOL='+$s.symbol+' PERIOD='+$period+' OPEN='+$fc.open+' HIGH='+$fc.high+' LOW='+$fc.low+' CLOSE='+$fc.close+' VOLUME='+$fc.volume+' AMOUNT='+$fc.amount+' RAW_SOURCE_VALUES_NOT_PRINTED=TRUE')
        }
    }
}

$sweep=$j.october_intraday_source_sweep
$wanted=@('2026-10-08','2026-10-09','2026-10-12','2026-10-13')
if($null -eq $sweep -or $sweep.status -ne 'oct_2026_four_sha_verified_h5_5min_days_intraday_only_research_candidates' -or (@($sweep.requested_days) -join ',') -ne ($wanted -join ',') -or $sweep.security_count -ne 2 -or $sweep.one_to_five_crosscheck_opted_in -ne $true -or $sweep.one_to_five_same_vendor_not_independent_certification -ne $true -or $sweep.only_complete_48_5min_source_stockdays_accepted -ne $true -or $sweep.existing_minute_source_receipt_and_sha_gate_reused -ne $true -or $sweep.daily_candidate_not_certified_or_materialized -ne $true -or $sweep.week_month_not_derived -ne $true -or $sweep.original_market_files_modified -ne $false -or $sweep.new_market_or_index_files_written -ne $false -or $sweep.verified_private_5min_vendor_units_certified -ne $false -or $sweep.no_licensed_OHLCVA_values_exported -ne $true -or $sweep.production_activated -ne $false){
    throw 'Unsafe/incomplete 2026 four-day H5 private intraday candidate sweep'
}
foreach($item in $sweep.per_security){
    if(@($item.verified_days).Count -ne 4){throw 'Missing a 2026 October verified 5min source day'}
    foreach($d in $item.verified_days){
        if($d.day -notin $wanted){throw 'Unexpected October candidate date'}
        foreach($period in @('15min','30min','60min')){
            $c=$d.cycles.PSObject.Properties[$period].Value
            if($c.source_h5_complete_5min_bars -ne 48 -or $c.purchased_has_priority_even_if_partial -ne $true -or $c.all_candidates_discarded_after_readonly_inspection -ne $true -or $c.original_purchased_target_bars -lt 0 -or $c.candidate_buckets_if_purchased_absent -lt 0){throw 'Invalid H5 candidate/provenance for October intraday source'}
            if($c.original_purchased_target_bars -gt 0 -and $c.candidate_buckets_if_purchased_absent -ne 0){throw 'Purchased high-cycle rows would be overwritten'}
            Write-Host ('OCT_INTRADAY_SOURCE_SYMBOL='+$item.symbol+' DAY='+$d.day+' PERIOD='+$period+' SOURCE_5MIN=48 PURCHASED_HIGH_CYCLE='+$c.original_purchased_target_bars+' PROVISIONAL_HIGH_CYCLE='+$c.candidate_buckets_if_purchased_absent+' NO_NEW_PARQUET=TRUE')

        }
        $m=$d.one_to_five_crosscheck
        if($null -eq $m -or $m.status -notin @('same_h5_source_diagnostic_only','no_one_minute_source_not_comparable','purchased_first_one_minute_not_same_h5_source') -or $m.source_5min_rows -ne 48 -or $m.expected_1min_grid_slots -ne 240 -or $m.source_1min_rows -lt 0 -or $m.source_1min_rows -gt 241 -or $m.complete_5min_windows -lt 0 -or $m.complete_5min_windows -gt 48 -or $m.incomplete_5min_windows -ne (48-$m.complete_5min_windows) -or $m.matched_six_field_windows -lt 0 -or $m.matched_six_field_windows -gt $m.complete_5min_windows -or $m.assumed_1min_end_5min_start_label_only -ne $true -or $m.same_vendor_not_independent_unit_certification -ne $true -or $m.vendor_physical_units_certified -ne $false -or $m.original_market_files_modified -ne $false -or $m.new_market_or_index_files_written -ne $false -or $m.no_licensed_OHLCVA_values_exported -ne $true -or $m.production_activated -ne $false){throw 'Unsafe/inconsistent H5 1min->5min source crosscheck'}
        if($m.status -eq 'same_h5_source_diagnostic_only' -and ($m.source_1min_rows -lt 1 -or $m.source_1min_rows -gt 240)){throw 'H5 1min source count invalid'}
        if($m.status -ne 'same_h5_source_diagnostic_only' -and ($m.complete_5min_windows -ne 0 -or $m.matched_six_field_windows -ne 0)){throw 'Uncomparable minute source incorrectly counted as H5 match'}
        foreach($f in @('open','high','low','close','volume','amount')){
            $match=$m.matching_fields_count.PSObject.Properties[$f].Value
            if($null -eq $match -or $match -lt 0 -or $match -gt $m.complete_5min_windows -or ($m.status -ne 'same_h5_source_diagnostic_only' -and $match -ne 0)){throw 'Invalid H5 1-to-5 per-field match count'}
        }
        $a=$m.amount_mismatch_diagnostic
        $relativeLabels=@('at_most_1e_minus_7','up_to_1e_minus_6','up_to_1e_minus_5','up_to_1e_minus_4','up_to_1e_minus_3','up_to_1e_minus_2','over_1e_minus_2')
        if($null -eq $a -or $a.only_original_tolerance_mismatches_counted -ne $true -or $a.relative_error_denominator -ne 'max(abs(sum_1min_amount),abs(source_5min_amount))' -or $a.different_complete_windows -ne ($m.complete_5min_windows-$m.matching_fields_count.amount) -or $a.different_complete_windows -lt 0 -or $a.different_complete_windows -gt 48 -or $a.minute_sum_greater_than_five -lt 0 -or $a.minute_sum_less_than_five -lt 0 -or ($a.minute_sum_greater_than_five+$a.minute_sum_less_than_five) -ne $a.different_complete_windows -or $a.morning -lt 0 -or $a.afternoon -lt 0 -or ($a.morning+$a.afternoon) -ne $a.different_complete_windows -or $a.one_side_zero -lt 0 -or $a.one_side_zero -gt $a.different_complete_windows){throw 'Amount residual session/sign accounting invalid'}
        if(@($a.relative_error_bins.PSObject.Properties.Name).Count -ne $relativeLabels.Count){throw 'Unknown amount residual relative-error tier'}
        $counts=@()
        $buckets=0
        foreach($key in $relativeLabels){
            $p=$a.relative_error_bins.PSObject.Properties[$key]
            if($null -eq $p -or $p.Value -lt 0 -or $p.Value -gt $a.different_complete_windows){throw 'Invalid H5 amount relative-error tier'}
            $buckets+=$p.Value
            $counts+=($key+'='+$p.Value)
        }
        if($buckets -ne $a.different_complete_windows){throw 'H5 amount mismatch relative-error bins do not conserve'}
        Write-Host ('OCT_H5_ONE_TO_FIVE_DIAGNOSTIC SYMBOL='+$item.symbol+' DAY='+$d.day+' STATUS='+$m.status+' SOURCE_1MIN='+$m.source_1min_rows+' COMPLETE_WINDOWS='+$m.complete_5min_windows+' SIX_FIELD_MATCH='+$m.matched_six_field_windows+' OPEN_MATCH='+$m.matching_fields_count.open+' HIGH_MATCH='+$m.matching_fields_count.high+' LOW_MATCH='+$m.matching_fields_count.low+' CLOSE_MATCH='+$m.matching_fields_count.close+' VOLUME_MATCH='+$m.matching_fields_count.volume+' AMOUNT_MATCH='+$m.matching_fields_count.amount+' AMOUNT_FAIL='+$a.different_complete_windows+' SUM_GT_5MIN='+$a.minute_sum_greater_than_five+' SUM_LT_5MIN='+$a.minute_sum_less_than_five+' ONE_SIDE_ZERO='+$a.one_side_zero+' AM='+$a.morning+' PM='+$a.afternoon+' AMOUNT_REL_BINS='+($counts -join ',')+' SAME_VENDOR_ONLY=TRUE CERTIFIED=FALSE')
    }
}
$all=$sweep.total_candidate_buckets_by_cycle
Write-Host ('OCT_FOUR_DAY_INTRADAY_CANDIDATES SECURITIES=2 DATES=4 15MIN='+$all.'15min'+' 30MIN='+$all.'30min'+' 60MIN='+$all.'60min'+' PURCHASED_SOURCE_BLOCKS='+$sweep.purchased_high_cycle_source_blocks+' DAILY_WEEKLY_MONTHLY_NOT_AUTHORIZED=TRUE')
Write-Host 'PASS_2026_OCT_FOUR_DAY_15_30_60MIN_SOURCE_CANDIDATES_READONLY NOT_MATERIALIZED=TRUE VENDOR_UNITS_CERTIFIED=FALSE'
Write-Host 'PASS_2026_OCT_H5_ONE_TO_FIVE_COUNT_ONLY_DIAGNOSTIC SAME_VENDOR_ONLY=TRUE PHYSICAL_UNITS_CERTIFIED=FALSE'

Write-Host 'PASS_2026_OCT_HIGH_CYCLE_5MIN_CANDIDATE_SOURCE_CALIBRATION_READONLY NO_MARKET_WRITES=TRUE PRODUCTION_MERGED=FALSE'
