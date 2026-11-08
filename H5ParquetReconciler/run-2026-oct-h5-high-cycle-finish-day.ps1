# October 13th: complete previously SHA-verified H5 5min-derived
# 15/30/60m research candidates, then independently verify DAY coverage.
# All previously staged private run receipts are retained, no original
# market/H5, production Parquet, active pointers, day/week/month are written.
param([switch]$PreviewOnly)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$audit=Join-Path $module 'tools\audit-2026-oct-high-cycle-private-day-coverage-readonly.py'
$batcher=Join-Path $module 'run-2026-oct-h5-high-cycle-bounded-rollout.ps1'
foreach($p in @($py,$audit,$batcher)){if(-not (Test-Path -LiteralPath $p -PathType Leaf)){throw ('Missing Oct 13 final-coverage gate: '+$p)}}
& $py -B -m unittest discover -s (Join-Path $module 'tests') -p 'test_audit_2026_oct_high_cycle_private_day_coverage_readonly.py' -q
if($LASTEXITCODE -ne 0){throw 'Independent final day coverage test failure'}
# First inspect ONLY existing isolated receipts and complete H5 5m source.
$before=@(& $py -B $audit --day 2026-10-13 --audit-readonly)
if($LASTEXITCODE -ne 0){throw 'Oct 13 original SHA-verified completion baseline rejected'}
$found=@($before|Where-Object {$_ -like 'PRIVATE_OCT_HIGH_CYCLE_DAY_COVERAGE=*'})
if($found.Count -ne 1){throw 'Unique Oct 13 coverage baseline not returned'}
$x=([string]$found[0]).Substring('PRIVATE_OCT_HIGH_CYCLE_DAY_COVERAGE='.Length)|ConvertFrom-Json
if($x.status -ne 'oct_2026_single_day_sha_verified_private_15_30_60min_candidate_coverage_readonly' -or $x.day -ne '2026-10-13' -or $x.stage_runs_all_october_sha_verified -lt 11 -or $x.stage_stockdays_all_october_sha_verified -lt 888 -or $x.eligible_full_h5_5min_source_stockdays -ne 5549 -or $x.this_date_staged_complete_stockdays -lt 882 -or $x.this_date_unstaged_complete_stockdays -ne ($x.eligible_full_h5_5min_source_stockdays-$x.this_date_staged_complete_stockdays) -or $x.all_october_private_candidate_rows -ne (28*$x.stage_stockdays_all_october_sha_verified) -or $x.full_existing_receipt_and_parquet_sha_reverified -ne $true -or $x.full_original_market_or_h5_files_modified -ne $false -or $x.new_market_private_or_production_files_written -ne $false -or $x.production_activated -ne $false -or $x.vendor_physical_units_certified -ne $false -or $x.private_only_research_candidate_coverage -ne $true){throw 'Oct 13 baseline not compatible with last verified 8-batch run'}
$remaining=[int]$x.this_date_unstaged_complete_stockdays
$needed=[int][math]::Ceiling($remaining/100)
Write-Host ('OCT_13_FINAL_COVERAGE_PREFLIGHT PREVIOUS_RUNS='+$x.stage_runs_all_october_sha_verified+' PREVIOUS_STOCKDAYS_ALL_DAYS='+$x.stage_stockdays_all_october_sha_verified+' COMPLETE_5MIN_STOCKDAYS='+$x.eligible_full_h5_5min_source_stockdays+' STAGED_THIS_DAY='+$x.this_date_staged_complete_stockdays+' UNCOVERED='+$remaining+' BATCHES_NEEDED='+$needed+' PREVIEW_ONLY='+[bool]$PreviewOnly)
if($needed -gt 60){throw 'More than maximum 60 bounded batches required; must split the day into more than one explicitly approved run'}
if($PreviewOnly){Write-Host 'PASS_OCT_13_FULL_DAY_PRIVATE_CANDIDATE_PREFLIGHT_ONLY NEW_FILES=0';return}
if($needed -gt 0){
    # Existing Windows-validated batcher has strict per-run source SHA, exact
    # Parquet row readback, independent PowerShell SHA and receipt checks.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $batcher -BatchSize 100 -MaxBatches $needed
    if($LASTEXITCODE -ne 0){throw 'Some batches may have succeeded. Verify immutable receipts BEFORE rerun; no market source modified'}
}
# Audit ALL receipts and current complete H5 5-minute day again, and require
# exact source stockday coverage. This writes no new file.
$lines=@(& $py -B $audit --day 2026-10-13 --audit-readonly --require-complete)
if($LASTEXITCODE -ne 0){throw 'Oct 13 high-cycle candidate day coverage NOT COMPLETE; inspect current receipt inventory'}
$report=@($lines|Where-Object {$_ -like 'PRIVATE_OCT_HIGH_CYCLE_DAY_COVERAGE=*'})
if($report.Count -ne 1){throw 'Missing final unique SHA-verified high-cycle coverage receipt'}
$j=([string]$report[0]).Substring('PRIVATE_OCT_HIGH_CYCLE_DAY_COVERAGE='.Length)|ConvertFrom-Json
if($j.status -ne $x.status -or $j.day -ne '2026-10-13' -or $j.this_date_coverage_complete -ne $true -or $j.this_date_unstaged_complete_stockdays -ne 0 -or $j.eligible_full_h5_5min_source_stockdays -ne 5549 -or $j.this_date_staged_complete_stockdays -ne 5549 -or $j.stage_stockdays_all_october_sha_verified -ne ($x.stage_stockdays_all_october_sha_verified+$remaining) -or $j.private_candidate_15min_rows_for_this_date -ne 88784 -or $j.private_candidate_30min_rows_for_this_date -ne 44392 -or $j.private_candidate_60min_rows_for_this_date -ne 22196 -or $j.full_existing_receipt_and_parquet_sha_reverified -ne $true -or $j.full_original_market_or_h5_files_modified -ne $false -or $j.new_market_private_or_production_files_written -ne $false -or $j.production_activated -ne $false -or $j.vendor_physical_units_certified -ne $false -or $j.unadjusted_time_label_semantics_certified -ne $false -or $j.private_only_research_candidate_coverage -ne $true){throw 'Oct 13 finished stage coverage row-count/SHA gate not accepted'}
Write-Host ('PASS_OCT_13_FULL_DAY_PRIVATE_HIGH_CYCLE_COVERAGE VERIFIED_SOURCE_STOCKDAYS='+$j.this_date_staged_complete_stockdays+' UNSTAGED=0 TOTAL_THIS_DAY_ROWS='+($j.private_candidate_15min_rows_for_this_date+$j.private_candidate_30min_rows_for_this_date+$j.private_candidate_60min_rows_for_this_date)+' TOTAL_ALL_OCT_PRIVATE_ROWS='+$j.all_october_private_candidate_rows+' SOURCE_SHA256='+$j.existing_private_h5_source_sha256+' ORIGINAL_MARKET_WRITES=FALSE PRODUCTION_MERGED=FALSE')
