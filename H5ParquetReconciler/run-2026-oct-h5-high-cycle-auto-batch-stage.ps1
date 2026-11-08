# Next bounded batch after verified 224-row canary: 2026-10-13, first 16
# other complete H5-only stockdays, all three intraday higher cycles.
# No original source writes, production merge, query pointer or H5 mirror.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\auto-batch-2026-oct-h5-high-cycle-private-parquet.py'
$tests=Join-Path $module 'tests'
foreach($f in @($py,$tool)){if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw 'Missing safe private high-cycle autobatch prerequisite'}}
foreach($pattern in @('test_audit_2026_oct_h5_five_minute_high_cycle_candidates_readonly.py','test_stage_2026_oct_verified_h5_high_cycle_private_parquet.py','test_auto_batch_2026_oct_h5_high_cycle_private_parquet.py')){
    & $py -B -m unittest discover -s $tests -p $pattern -q
    if($LASTEXITCODE -ne 0){throw ('Oct private high-cycle autobatch synthetic gate failed: '+$pattern)}
}
$run=[Guid]::NewGuid().ToString('N').Substring(0,12)
$lines=@(& $py -B $tool --root 'D:\stock' --day 2026-10-13 --run-id $run --batch-index 0 --batch-size 16 --write-private-candidates-only)
if($LASTEXITCODE -ne 0){throw 'Real private high-cycle autobatch failed before success receipt'}
$safes=@($lines|Where-Object {$_ -like 'PRIVATE_OCT_HIGH_CYCLE_BATCH=*'})
if($safes.Count -ne 1){throw 'Missing unique high-cycle autobatch SAFE report'}
$o=([string]$safes[0]).Substring('PRIVATE_OCT_HIGH_CYCLE_BATCH='.Length)|ConvertFrom-Json
$s=$o.stage
$i=$o.source_inventory
if($o.status -ne 'oct_2026_private_h5_highcycle_autobatch_staged_readback' -or $o.batch_index -ne 0 -or $o.batch_size -ne 16 -or $o.selected_stockdays -lt 1 -or $o.selected_stockdays -gt 16 -or $o.eligible_stockdays_total_for_day -lt $o.selected_stockdays -or $i.day -ne '2026-10-13' -or $i.status -ne 'oct_2026_sha_verified_private_h5_five_minute_complete_stockdays_inventory' -or $i.strict_receipt_sha_verified -ne $true -or $i.original_market_files_modified -ne $false -or $i.production_activated -ne $false -or $i.vendor_physical_units_certified -ne $false -or $i.purchased_original_high_cycle_absence_checked -ne $false -or $i.source_5min_sha256 -notmatch '^[a-f0-9]{64}$' -or $s.run_id -ne $run -or $s.verified_source_stockdays -ne $o.selected_stockdays -or (@($s.source_days) -join ',') -ne '2026-10-13' -or @($s.symbols).Count -ne $o.selected_stockdays -or @($s.sources).Count -ne 1 -or $s.sources[0].sha256 -ne $i.source_5min_sha256 -or $s.purchased_high_cycle_source_blocks -ne 0 -or $s.source_5min_original_SHA_receipts_verified -ne $true -or $s.all_48_native_start_grid_bars_required -ne $true -or $s.all_purchased_high_cycle_periods_must_be_absent -ne $true -or $s.no_day_week_month_materialized -ne $true -or $s.vendor_physical_units_certified -ne $false -or $s.timestamp_conversion_certified -ne $false -or $s.corporate_adjustments_certified -ne $false -or $s.original_market_files_modified -ne $false -or $s.production_or_private_active_pointer_modified -ne $false -or $s.ready_for_production_merge -ne $false -or $s.ready_for_h5_mirror -ne $false -or $s.raw_OHLCVA_in_report -ne $false){throw 'Unsafe high-cycle autobatch receipt or inventory gate'}
foreach($sym in $s.symbols){if($sym -in @('SH600000','SZ000001')){throw 'Previously materialized canary selected again'}}
$total=0
foreach($period in @('15min','30min','60min')){
    if($period -eq '15min'){$factor=16}elseif($period -eq '30min'){$factor=8}else{$factor=4}
    $expected=$factor*$o.selected_stockdays
    $v=$s.outputs.PSObject.Properties[$period].Value
    if($null -eq $v -or $v.rows -ne $expected -or $v.private_file -ne ('work/unified_parquet/oct_high_cycle_staging/'+$run+'/'+$period+'.parquet') -or $v.complete_row_by_row_readback_exact -ne $true -or $v.sha256 -notmatch '^[a-f0-9]{64}$'){throw 'Private autobatch output count/path/checksum gate failed'}
    $f=Join-Path $module ($v.private_file.Replace('/','\'))
    if(-not (Test-Path -LiteralPath $f -PathType Leaf) -or (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLowerInvariant() -ne $v.sha256){throw 'Private high-cycle Parquet SHA readback mismatch'}
    $total+=$v.rows
    Write-Host ('OCT_13_BATCH_PERIOD='+$period+' CANDIDATE_ROWS='+$v.rows+' SHA256='+$v.sha256+' PRODUCTION_MERGED=FALSE')
}
$r=Join-Path $module ('work\unified_parquet\oct_high_cycle_staging\'+$run+'\receipt.json')
if(-not (Test-Path -LiteralPath $r -PathType Leaf)){throw 'No private autobatch receipt'}
$record=Get-Content -LiteralPath $r -Encoding UTF8 -Raw|ConvertFrom-Json
if($record.run_id -ne $run -or $record.verified_source_stockdays -ne $o.selected_stockdays){throw 'Private autobatch receipt identity mismatch'}
# Python Counter omits zero-valued keys; StrictMode must NOT treat absence as a failure.
$reasonCounts=@{}
foreach($key in @('already_staged_canary_symbol','purchased_five_minute_priority','incomplete_or_invalid_h5_five_minute_grid')){
    $reasonCounts[$key]=0
    $property=$i.excluded_by_reason.PSObject.Properties[$key]
    if($null -ne $property){$reasonCounts[$key]=[int]$property.Value}
}
Write-Host ('OCT_13_H5_SOURCE_INVENTORY ROWS_SCANNED='+$i.private_h5_five_minute_source_rows_scanned+' COMPLETE_ELIGIBLE='+$o.eligible_stockdays_total_for_day+' EXCLUDED_CANARY='+$reasonCounts['already_staged_canary_symbol']+' EXCLUDED_PURCHASED='+$reasonCounts['purchased_five_minute_priority']+' EXCLUDED_INCOMPLETE='+$reasonCounts['incomplete_or_invalid_h5_five_minute_grid'])
Write-Host ('PASS_OCT_13_AUTO_BATCH_PRIVATE_HIGH_CYCLE_PARQUET RUN_ID='+$run+' STOCKDAYS='+$o.selected_stockdays+' TOTAL_ROWS='+$total+' ORIGINAL_MARKET_WRITES=FALSE PRODUCTION_MERGED=FALSE')
Write-Host ('PRIVATE_RECEIPT='+$r)
