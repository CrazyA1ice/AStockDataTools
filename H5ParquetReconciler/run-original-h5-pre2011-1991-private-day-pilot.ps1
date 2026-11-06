# First renewable 1991-2010 historical H5 private candidate validation, 1991 ONLY.
# This one-line entry is opt-in PRIVATE stage, not 20-year batch/production.
# Original D:\stock H5 and purchased Parquet stay read-only.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$python=Join-Path $repo '.venv\Scripts\python.exe'
$tests=Join-Path $module 'tests'
$script=Join-Path $module 'tools\stage-original-h5-pre2011-annual-private-day.py'
if(-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $script -PathType Leaf)){throw 'Historical 1991 annual private-day pilot prerequisites missing'}
Write-Host '===== Annual historical private day staging: 1991..2010, synthetic safety contracts ====='
& $python -B -m unittest discover -s $tests -p 'test_stage_original_h5_pre2011_annual_private_day.py' -v
if($LASTEXITCODE -ne 0){throw 'Historical annual 1991-2010 private-stage tests failed; real H5 and purchased Parquet NOT opened'}
Write-Host '===== Source stat SHA + purchased physical absence gate; PRIVATE 1991 ONLY ====='
$lines=@(& $python -B $script --source-root 'D:\stock' --year 1991 --stage-private)
if($LASTEXITCODE -ne 0){$lines | Out-Host;throw '1991 H5 historical day source/private annual stage failed closed; no source/production modification'}
$summary=($lines -join [Environment]::NewLine)|ConvertFrom-Json
$validStates=@('verified_private_candidate_not_promoted','already_verified_private_candidate_not_promoted')
if(($validStates -cnotcontains [string]$summary.state) -or $summary.format -ne 'AStockDataTools private pre2011 annual H5 day research candidate v1' -or $summary.year -ne 1991 -or $summary.period -ne 'day' -or $summary.candidate_stockday_rows -ne 2043 -or $summary.other_code_source_rows_not_staged -ne 738 -or $summary.distinct_source_dates -ne 304 -or $summary.purchased_pre2011_all_day_files_confirmed_absent -ne $true -or $summary.native_day_keys_and_OHLCVA_geometry_checked -ne $true -or $summary.historical_security_master_certified -ne $false -or $summary.official_historical_trading_calendar_certified -ne $false -or $summary.h5_volume_amount_price_units_certified -ne $false -or $summary.corporate_action_adjustment_certified -ne $false -or $summary.original_market_files_written -ne $false -or $summary.purchased_parquet_replaced -ne $false -or $summary.h5_mirror_created -ne $false -or $summary.production_pointer_modified -ne $false -or $summary.ready_for_production_merge -ne $false){throw '1991 annual private candidate source safety contract mismatch'}
$relative=[string]$summary.private_stage_relative_dir
if($relative -cnotmatch '^work/unified_parquet/historical_pre2011_daily_pilots/1991-research-[a-f0-9]{16}$'){throw 'Private 1991 annual stage escaped ignored work directory'}
$artifact=Join-Path $module $relative
$parquet=Join-Path $artifact 'day.parquet'
$manifest=Join-Path $artifact 'manifest.json'
if(-not (Test-Path -LiteralPath $parquet -PathType Leaf) -or -not (Test-Path -LiteralPath $manifest -PathType Leaf)){throw 'Private 1991 candidate or manifest missing'}
$sha=(Get-FileHash -LiteralPath $parquet -Algorithm SHA256).Hash.ToLowerInvariant()
if($sha -cne [string]$summary.private_parquet_sha256 -or $summary.private_parquet_row_count -ne 2043){throw 'Private 1991 annual Parquet SHA or source-row count mismatch'}
$registered=Get-Content -LiteralPath $manifest -Encoding UTF8 -Raw|ConvertFrom-Json
if($registered.state -ne 'verified_private_candidate_not_promoted' -or $registered.candidate_stockday_rows -ne 2043 -or $registered.private_parquet_sha256 -cne $sha -or $registered.purchased_original_state_sha256 -cne $summary.purchased_original_state_sha256 -or $registered.h5_original_state_sha256 -cne $summary.h5_original_state_sha256 -or $registered.ready_for_production_merge -ne $false){throw '1991 annual original-source, private-manifest or promotion gate mismatch'}
Write-Host ('PASS_PRIVATE_1991_H5_DAY_STAGED=2043 OTHER_CODE_EXCLUDED=738 SOURCE_PQ_PRE2011_ABSENT=TRUE UNIT_CERTIFIED=FALSE PRODUCTION_MERGED=FALSE STATE='+$summary.state)
Write-Host ('PRIVATE_STAGE_RELATIVE_DIR='+$relative)
Write-Host ('PRIVATE_1991_DAY_PARQUET_SHA256='+$sha)
Write-Host 'PASS: 1991 original H5 and purchased Parquet unchanged. Private artifact independently SHA-verified; year 1992..2010 NOT RUN.'
