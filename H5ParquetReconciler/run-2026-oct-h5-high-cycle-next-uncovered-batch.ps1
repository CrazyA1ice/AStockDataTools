# Oct 13 verified 24-stockday baseline -> next up to 64 NEW H5-only
# 5min complete stockdays in isolated 15/30/60min PRIVATE Parquet ONLY.
# Separate read-only plan runs before any candidate files are written.
param([switch]$PreviewOnly)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\stage-next-uncovered-oct-h5-high-cycle-private-parquet.py'
$tests=Join-Path $module 'tests'
foreach($p in @($py,$tool)){if(-not (Test-Path -LiteralPath $p -PathType Leaf)){throw ('Missing next-uncovered private high-cycle prerequisite: '+$p)}}
foreach($pattern in @('test_audit_2026_oct_h5_five_minute_high_cycle_candidates_readonly.py','test_stage_2026_oct_verified_h5_high_cycle_private_parquet.py','test_auto_batch_2026_oct_h5_high_cycle_private_parquet.py','test_verify_existing_oct_high_cycle_private_batch_readonly.py','test_stage_next_uncovered_oct_h5_high_cycle_private_parquet.py')){
    & $py -B -m unittest discover -s $tests -p $pattern -q
    if($LASTEXITCODE -ne 0){throw ('Next-uncovered high-cycle stage tests failed: '+$pattern)}
}
$day='2026-10-13'
$batchSize=64
$lines=@(& $py -B $tool --root 'D:\stock' --day $day --batch-size $batchSize --preview-only)
if($LASTEXITCODE -ne 0){throw 'Read-only October high-cycle next-uncovered plan failed'}
$report=@($lines|Where-Object {$_ -like 'PRIVATE_OCT_NEXT_UNSTAGED_PLAN=*'})
if($report.Count -ne 1){throw 'Missing unique next-uncovered private inventory plan'}
$p=([string]$report[0]).Substring('PRIVATE_OCT_NEXT_UNSTAGED_PLAN='.Length)|ConvertFrom-Json
if($p.status -ne 'oct_2026_only_unstaged_sha_verified_h5_5min_stockdays_private_research' -or $p.day -ne $day -or $p.batch_size -ne $batchSize -or $p.previous_private_runs_sha_rechecked -lt 2 -or $p.previous_private_stockdays_sha_rechecked -lt 24 -or $p.already_staged_complete_eligible_this_day -lt 18 -or $p.h5_5min_complete_eligible_stockdays -lt $p.already_staged_complete_eligible_this_day -or $p.uncovered_complete_eligible_this_day -ne ($p.h5_5min_complete_eligible_stockdays-$p.already_staged_complete_eligible_this_day) -or $p.chosen_stockdays -lt 0 -or $p.chosen_stockdays -gt $batchSize -or $p.chosen_stockdays -gt $p.uncovered_complete_eligible_this_day -or $p.remaining_uncovered_stockdays_after_selection -ne ($p.uncovered_complete_eligible_this_day-$p.chosen_stockdays) -or $p.source_5min_private_SHA_checked -ne $true -or $p.source_sha256 -notmatch '^[a-f0-9]{64}$' -or $p.original_market_files_modified -ne $false -or $p.new_private_or_production_files_written -ne $false -or $p.production_activated -ne $false -or $p.vendor_physical_units_certified -ne $false){throw 'Untrusted or unexpected October next-uncovered plan'}
Write-Host ('OCT_13_NEXT_UNCOVERED_PREVIEW PREVIOUS_RUNS='+$p.previous_private_runs_sha_rechecked+' PREVIOUS_STOCKDAYS='+$p.previous_private_stockdays_sha_rechecked+' COMPLETE_ELIGIBLE='+$p.h5_5min_complete_eligible_stockdays+' STAGED_THIS_DAY='+$p.already_staged_complete_eligible_this_day+' UNSTAGED='+$p.uncovered_complete_eligible_this_day+' SELECTED='+$p.chosen_stockdays+' REMAINING='+$p.remaining_uncovered_stockdays_after_selection+' PREVIEW_ONLY=TRUE')
if($PreviewOnly){Write-Host 'PASS_OCT_13_NEXT_UNCOVERED_PREVIEW_ONLY NEW_FILES=0';return}
if($p.chosen_stockdays -lt 1){Write-Host 'PASS_OCT_13_NEXT_UNCOVERED_ALREADY_COMPLETE NO_NEW_STOCKDAYS=TRUE NEW_FILES=0';return}
$run=[Guid]::NewGuid().ToString('N').Substring(0,12)
Write-Host ('PRIVATE_BATCH_RUN_ID_BEFORE_STAGE='+$run)
$real=@(& $py -B $tool --root 'D:\stock' --day $day --batch-size $batchSize --run-id $run --write-private-candidates-only)
if($LASTEXITCODE -ne 0){throw ('Actual Oct private next-uncovered batch not accepted; check incomplete private stage '+$run+' before rerun')}
$matched=@($real|Where-Object {$_ -like 'PRIVATE_OCT_NEXT_UNSTAGED_STAGE=*'})
if($matched.Count -ne 1){throw ('Missing candidate stage SAFE; check run ID '+$run+' before rerun')}
$o=([string]$matched[0]).Substring('PRIVATE_OCT_NEXT_UNSTAGED_STAGE='.Length)|ConvertFrom-Json
$s=$o.stage
$a=$o.plan
$receipt=Join-Path $module ('work\unified_parquet\oct_high_cycle_staging\'+$run+'\receipt.json')
Write-Host ('PRIVATE_BATCH_RECEIPT_BEFORE_FINAL_CHECK='+$receipt)
if($o.status -ne 'oct_2026_next_uncovered_private_highcycle_written_readback' -or $o.only_unstaged_candidates_selected -ne $true -or $o.original_market_files_modified -ne $false -or $o.production_activated -ne $false -or $a.day -ne $day -or $a.chosen_stockdays -ne $p.chosen_stockdays -or $a.previous_private_stockdays_sha_rechecked -lt 24 -or $a.source_5min_private_SHA_checked -ne $true -or $s.run_id -ne $run -or $s.status -ne 'research_only_private_oct_h5_5min_highcycle_candidates_written_readback' -or $s.verified_source_stockdays -ne $a.chosen_stockdays -or @($s.symbols).Count -ne $a.chosen_stockdays -or (@($s.source_days) -join ',') -ne $day -or @($s.sources).Count -ne 1 -or $s.sources[0].sha256 -ne $a.source_sha256 -or $s.purchased_high_cycle_source_blocks -ne 0 -or $s.source_5min_original_SHA_receipts_verified -ne $true -or $s.all_48_native_start_grid_bars_required -ne $true -or $s.all_purchased_high_cycle_periods_must_be_absent -ne $true -or $s.no_day_week_month_materialized -ne $true -or $s.vendor_physical_units_certified -ne $false -or $s.timestamp_conversion_certified -ne $false -or $s.corporate_adjustments_certified -ne $false -or $s.original_market_files_modified -ne $false -or $s.production_or_private_active_pointer_modified -ne $false -or $s.ready_for_production_merge -ne $false -or $s.ready_for_h5_mirror -ne $false -or $s.raw_OHLCVA_in_report -ne $false){throw ('Candidate stage safety flags failed; inspect existing receipt '+$receipt)}
if(-not (Test-Path -LiteralPath $receipt -PathType Leaf)){throw 'Expected existing next-uncovered receipt missing after write'}
$received=Get-Content -LiteralPath $receipt -Encoding UTF8 -Raw|ConvertFrom-Json
if($received.run_id -ne $run -or $received.verified_source_stockdays -ne $a.chosen_stockdays){throw 'Written next-uncovered receipt identity mismatch'}
$total=0
foreach($period in @('15min','30min','60min')){
    if($period -eq '15min'){$factor=16}elseif($period -eq '30min'){$factor=8}else{$factor=4}
    $out=$s.outputs.PSObject.Properties[$period].Value
    $expected=$a.chosen_stockdays*$factor
    if($null -eq $out -or $out.rows -ne $expected -or $out.complete_row_by_row_readback_exact -ne $true -or $out.sha256 -notmatch '^[a-f0-9]{64}$' -or $out.private_file -ne ('work/unified_parquet/oct_high_cycle_staging/'+$run+'/'+$period+'.parquet')){throw 'Private next-uncovered Parquet receipt incorrect'}
    $file=Join-Path $module ($out.private_file.Replace('/','\'))
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw 'Expected next-uncovered Parquet file absent'}
    if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $out.sha256){throw 'Next-uncovered Parquet physical file SHA mismatch'}
    $total+=$out.rows
    Write-Host ('OCT_NEXT_UNCOVERED_PERIOD='+$period+' ROWS='+$out.rows+' SHA256='+$out.sha256+' PRIVATE_ONLY=TRUE')
}
Write-Host ('PASS_OCT_13_NEXT_UNCOVERED_PRIVATE_HIGH_CYCLE_PARQUET RUN_ID='+$run+' NEW_STOCKDAYS='+$a.chosen_stockdays+' NEW_ROWS='+$total+' PREVIOUS_STOCKDAYS='+$a.previous_private_stockdays_sha_rechecked+' ORIGINAL_MARKET_WRITES=FALSE PRODUCTION_MERGED=FALSE')
Write-Host ('PRIVATE_RECEIPT='+$receipt)
