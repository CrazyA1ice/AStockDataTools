# Finish Oct 08/09/12 SHA-backed H5 5min->15/30/60min PRIVATE candidates.
# All original purchased, market, H5 and production/query pointer writes forbidden.
param([switch]$PreviewOnly)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\finish-three-oct-2026-high-cycle-private-days.py'
$tests=Join-Path $module 'tests'
foreach($file in @($py,$tool)){if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw ('Three-day stage prerequisite missing: '+$file)}}
foreach($pattern in @(
    'test_audit_2026_oct_h5_five_minute_high_cycle_candidates_readonly.py',
    'test_stage_2026_oct_verified_h5_high_cycle_private_parquet.py',
    'test_auto_batch_2026_oct_h5_high_cycle_private_parquet.py',
    'test_verify_existing_oct_high_cycle_private_batch_readonly.py',
    'test_stage_next_uncovered_oct_h5_high_cycle_private_parquet.py',
    'test_rollout_2026_oct_high_cycle_private_batches.py',
    'test_audit_2026_oct_high_cycle_private_day_coverage_readonly.py',
    'test_finish_three_oct_2026_high_cycle_private_days.py'
)){
    & $py -B -m unittest discover -s $tests -p $pattern -q
    if($LASTEXITCODE -ne 0){throw ('Three-day stage synthetic safety gate failed: '+$pattern)}
}
$cli=@('--root','D:\stock','--preview-only')
$lines=@(& $py -B $tool @cli)
if($LASTEXITCODE -ne 0){throw 'Three-day SHA-verified read-only preflight failed; no private files written'}
$matches=@($lines|Where-Object {$_ -like 'PRIVATE_OCT_THREE_DAY_FINAL=*'})
if($matches.Count -ne 1){throw 'Three-day read-only baseline summary missing'}
$p=([string]$matches[0]).Substring('PRIVATE_OCT_THREE_DAY_FINAL='.Length)|ConvertFrom-Json
if($p.status -ne 'oct_2026_three_day_private_highcycle_coverage_verified_readonly' -or $p.preview_only -ne $true -or $p.baseline_day_verified -ne $true -or $p.original_verified_stockdays_all_oct -lt 5555 -or $p.original_market_files_modified -ne $false -or $p.production_activated -ne $false -or $p.ready_for_production_merge -ne $false -or $p.new_stockdays -ne 0 -or $p.new_candidate_rows -ne 0){throw 'Unsafe three-day read-only source baseline'}
$daySpecs=@(
    @('2026-10-08',5546),
    @('2026-10-09',5547),
    @('2026-10-12',5549)
)
foreach($spec in $daySpecs){
    $day=[string]$spec[0]
    $expected=[int]$spec[1]
    $r=$p.per_day.PSObject.Properties[$day].Value
    if($null -eq $r -or $r.source_eligible -ne $expected -or $r.previous_stockdays -lt 2 -or $r.uncovered_at_start -ne ($expected-$r.previous_stockdays) -or $r.needed_batches -gt 60 -or $r.needed_batches -lt 0 -or $r.new_stockdays -ne 0){throw ('Unsafe three-day baseline: '+$day)}
    Write-Host ('OCT_THREE_DAY_READY DATE='+$day+' ELIGIBLE='+$expected+' STAGED='+$r.previous_stockdays+' UNSTAGED='+$r.uncovered_at_start+' BATCHES='+$r.needed_batches+' PREVIEW_ONLY=TRUE')
}
if($PreviewOnly){
    Write-Host 'PASS_OCT_THREE_DAY_PRIVATE_CANDIDATE_PREFLIGHT_ONLY NEW_FILES=0 ORIGINAL_MARKET_WRITES=FALSE'
    return
}
# Stream all per-batch IDs, receipts and SHA lines so interrupted writes can be
# resumed by running this entry again; never delete staged candidate folders.
& $py -B $tool --root 'D:\stock' --write-private-candidates-only | Tee-Object -Variable collected
if($LASTEXITCODE -ne 0){throw 'Oct three-day run stopped. Existing receipts remain; re-run after inspecting the error. DO NOT delete or restage completed private candidates.'}
$ok=@($collected|Where-Object {$_ -like 'PRIVATE_OCT_THREE_DAY_FINAL=*'})
if($ok.Count -ne 1){throw 'No unique three-day final candidate SAFE receipt'}
$j=([string]$ok[0]).Substring('PRIVATE_OCT_THREE_DAY_FINAL='.Length)|ConvertFrom-Json
if($j.status -ne $p.status -or $j.preview_only -ne $false -or $j.baseline_day_verified -ne $true -or $j.all_four_dates_source_complete -ne $true -or $j.final_verified_stockdays_all_oct -ne 22191 -or $j.final_candidate_rows_all_oct -ne 621348 -or $j.new_candidate_rows -ne (28*$j.new_stockdays) -or $j.original_verified_stockdays_all_oct -ne $p.original_verified_stockdays_all_oct -or $j.original_market_files_modified -ne $false -or $j.production_activated -ne $false -or $j.ready_for_production_merge -ne $false -or $j.source_vendor_units_certified -ne $false -or $j.no_day_week_month_materialized -ne $true){throw 'Unsafe 3-day final SHA-backed candidate source coverage'}
foreach($spec in $daySpecs){
    $day=[string]$spec[0]
    $expected=[int]$spec[1]
    $r=$j.per_day.PSObject.Properties[$day].Value
    if($null -eq $r -or $r.source_eligible -ne $expected -or $r.previous_stockdays -ne $p.per_day.PSObject.Properties[$day].Value.previous_stockdays -or $r.uncovered_at_start -ne $p.per_day.PSObject.Properties[$day].Value.uncovered_at_start -or $r.new_stockdays -ne $r.uncovered_at_start -or $r.new_candidate_rows -ne (28*$r.new_stockdays)){throw ('Unsafe completed candidate day: '+$day)}
    Write-Host ('PASS_OCT_PRIVATE_CANDIDATE_DATE DATE='+$day+' SOURCE_STOCKDAYS='+$expected+' NEW='+$r.new_stockdays+' UNSTAGED=0')
}
Write-Host ('PASS_OCT_08_09_12_FULL_DAY_PRIVATE_HIGH_CYCLE_COVERAGE FOUR_DATES_STOCKDAYS='+$j.final_verified_stockdays_all_oct+' FOUR_DATES_CANDIDATE_ROWS='+$j.final_candidate_rows_all_oct+' NEW_STOCKDAYS='+$j.new_stockdays+' NEW_CANDIDATE_ROWS='+$j.new_candidate_rows+' ORIGINAL_MARKET_WRITES=FALSE PRODUCTION_MERGED=FALSE')
