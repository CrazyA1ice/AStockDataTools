# Resume-safe multi-batch PRIVATE October 13th intraday high cycle conversion.
# Auto-registers old SHA-verified receipts. Never modifies purchased Parquet,
# Hikyuu H5, query pointers, or any production stock database.
param(
    [ValidateRange(1,100)][int]$BatchSize=100,
    [ValidateRange(1,60)][int]$MaxBatches=8,
    [switch]$PreviewOnly
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\rollout-2026-oct-high-cycle-private-batches.py'
$tests=Join-Path $module 'tests'
foreach($f in @($py,$tool)){if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw 'Missing bounded private rollout prerequisite'}}
foreach($pattern in @(
    'test_audit_2026_oct_h5_five_minute_high_cycle_candidates_readonly.py',
    'test_stage_2026_oct_verified_h5_high_cycle_private_parquet.py',
    'test_auto_batch_2026_oct_h5_high_cycle_private_parquet.py',
    'test_verify_existing_oct_high_cycle_private_batch_readonly.py',
    'test_stage_next_uncovered_oct_h5_high_cycle_private_parquet.py',
    'test_rollout_2026_oct_high_cycle_private_batches.py'
)){
    & $py -B -m unittest discover -s $tests -p $pattern -q
    if($LASTEXITCODE -ne 0){throw ('Bounded high-cycle rollout synthetic tests failed: '+$pattern)}
}
$cli=@('--root','D:\stock','--day','2026-10-13','--batch-size',([string]$BatchSize),'--max-batches',([string]$MaxBatches))
if($PreviewOnly){$cli+='--preview-only'}else{$cli+='--write-private-candidates-only'}
Write-Host ('PRIVATE_ROLLOUT_MODE='+$(if($PreviewOnly){'PREVIEW_ONLY'}else{'WRITE_PRIVATE_CANDIDATES_ONLY'})+' BATCH_SIZE='+$BatchSize+' MAX_BATCHES='+$MaxBatches+' DAY=2026-10-13 ORIGINAL_MARKET_WRITES=FALSE')
# Tee streams each safely bounded per-batch receipt and hash immediately.
# Record only console messages; never write market OHLCVA into a log/report.
& $py -B $tool @cli | Tee-Object -Variable collected
if($LASTEXITCODE -ne 0){
    throw 'Bounded private rollout interrupted. Completed immutable receipts remain; rerun this script to auto-resume, but investigate any incomplete stage folder first.'
}
$summaries=@($collected|Where-Object {$_ -like 'PRIVATE_OCT_BOUNDED_ROLLOUT=*'})
if($summaries.Count -ne 1){throw 'Missing unique final bounded private high-cycle rollout SAFE'}
$j=([string]$summaries[0]).Substring('PRIVATE_OCT_BOUNDED_ROLLOUT='.Length)|ConvertFrom-Json
if($j.status -ne 'oct_2026_bounded_resumable_private_highcycle_rollout' -or $j.day -ne '2026-10-13' -or $j.preview_only -ne [bool]$PreviewOnly -or $j.original_market_files_modified -ne $false -or $j.production_activated -ne $false -or $j.ready_for_production_merge -ne $false -or $j.source_eligible -lt 18 -or $j.preexisting_stockdays -lt 88){
    throw 'Unsafe/inconsistent bounded rollout SAFE'
}
if($PreviewOnly){
    if($j.batches_completed -ne 0 -or $j.new_private_stockdays -ne 0 -or $j.new_rows -ne 0){throw 'Preview attempted changes'}
    Write-Host ('PASS_OCT_13_BOUNDED_ROLLOUT_PREVIEW PREEXISTING_STOCKDAYS='+$j.preexisting_stockdays+' UNCOVERED='+$j.uncovered_before+' NEW_FILES=0')
    return
}
if($j.batch_size -ne $BatchSize -or $j.max_batches -ne $MaxBatches -or $j.batches_completed -lt 0 -or $j.batches_completed -gt $MaxBatches -or $j.new_private_stockdays -lt 0 -or $j.new_private_stockdays -gt ($MaxBatches*$BatchSize) -or $j.new_rows -ne (28*$j.new_private_stockdays) -or $j.uncovered_after -ne ($j.uncovered_before-$j.new_private_stockdays) -or @($j.run_ids).Count -ne $j.batches_completed -or $j.no_raw_ohlcva_printed -ne $true){throw 'Private rollout row/stockday/run count mismatch'}
$seen=@{}
foreach($id in @($j.run_ids)){
    if($id -notmatch '^[a-f0-9]{12}$' -or $seen.ContainsKey($id)){throw 'Unsafe or duplicate private run id'}
    $seen[$id]=$true
    $receipt=Join-Path $module ('work\unified_parquet\oct_high_cycle_staging\'+$id+'\receipt.json')
    if(-not (Test-Path -LiteralPath $receipt -PathType Leaf)){throw ('Missing private batch receipt: '+$id)}
    $v=Get-Content -LiteralPath $receipt -Encoding UTF8 -Raw|ConvertFrom-Json
    if($v.run_id -ne $id -or $v.status -ne 'research_only_private_oct_h5_5min_highcycle_candidates_written_readback' -or $v.ready_for_production_merge -ne $false -or $v.original_market_files_modified -ne $false){throw ('Invalid immutable stage receipt: '+$id)}
    foreach($period in @('15min','30min','60min')){
        $meta=$v.outputs.PSObject.Properties[$period].Value
        if($null -eq $meta -or $meta.complete_row_by_row_readback_exact -ne $true -or $meta.sha256 -notmatch '^[a-f0-9]{64}$'){throw ('Missing output SHA: '+$id+'/'+$period)}
        $path=Join-Path $module ($meta.private_file.Replace('/','\'))
        if(-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $meta.sha256){throw ('Changed private candidate Parquet: '+$id+'/'+$period)}
    }
}
Write-Host ('PASS_OCT_13_BOUNDED_PRIVATE_HIGH_CYCLE_ROLLOUT BATCHES='+$j.batches_completed+' NEW_STOCKDAYS='+$j.new_private_stockdays+' NEW_ROWS='+$j.new_rows+' REMAINING='+$j.uncovered_after+' ORIGINAL_MARKET_WRITES=FALSE PRODUCTION_MERGED=FALSE')
