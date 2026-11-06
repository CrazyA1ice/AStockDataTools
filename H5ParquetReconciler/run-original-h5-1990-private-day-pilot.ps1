# Mainline 1990 H5-only daily historical private candidate pilot.
# Tests + full purchased 24-file/139-footer absence gate + original H5 stat SHA
# + all exact 24 A-code native day keys/OHLCVA geometry, then explicit
# local private stage. NEVER rewrites original H5/Parquet or activates production.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tests=Join-Path $module 'tests'
$tool=Join-Path $module 'tools\stage-original-h5-1990-private-day-pilot.py'
if(-not (Test-Path -LiteralPath $py -PathType Leaf) -or -not (Test-Path -LiteralPath $tool -PathType Leaf)){throw 'Historical 1990 private pilot prerequisites missing'}
Write-Host '===== 1990 daily H5 historical private candidate synthetic safety tests ====='
& $py -B -m unittest discover -s $tests -p 'test_stage_original_h5_1990_private_day_pilot.py' -v
if($LASTEXITCODE -ne 0){throw '1990 historical H5 private-stage synthetic tests failed; no real H5/PQ source opened'}
Write-Host '===== Source SHA + purchased 24-file 139-rowgroup absence + 24 H5 native bars: explicit PRIVATE staging only ====='
$lines=@(& $py -B $tool --source-root 'D:\stock' --stage-private)
if($LASTEXITCODE -ne 0){$lines | Out-Host;throw '1990 private H5 day stage failed closed; no production market files modified'}
$safe=($lines -join [Environment]::NewLine) | ConvertFrom-Json
if($safe.format -ne 'AStockDataTools isolated uncertified 1990 H5 candidate day private v1' -or $safe.state -ne 'verified_private_candidate_not_promoted' -or $safe.year -ne 1990 -or $safe.period -ne 'day' -or $safe.candidate_stockday_rows -ne 24 -or $safe.other_code_source_rows_not_staged -ne 16 -or $safe.distinct_source_dates -ne 8 -or $safe.purchased_pre2011_absent_in_all_24_original_day_files -ne $true -or $safe.h5_1990_source_exact_key_and_OHLCVA_geometry_passed -ne $true -or $safe.historical_security_master_certified -ne $false -or $safe.official_historical_trading_calendar_certified -ne $false -or $safe.h5_volume_amount_price_units_certified -ne $false -or $safe.corporate_action_adjustment_certified -ne $false -or $safe.raw_OHLCVA_in_manifest -ne $false -or $safe.original_market_files_written -ne $false -or $safe.purchased_parquet_replaced -ne $false -or $safe.h5_mirror_created -ne $false -or $safe.production_pointer_modified -ne $false -or $safe.ready_for_production_merge -ne $false -or $safe.private_parquet_written -ne $true -or $safe.private_parquet_row_count -ne 24){throw 'Private H5 1990 candidate stage safety fields inconsistent'}
$relative=[string]$safe.private_stage_relative_dir
if($relative -cnotmatch '^work/unified_parquet/historical_pre2011_daily_pilots/1990-research-[a-f0-9]{16}$'){throw 'Private historical day stage escaped expected ignored work tree'}
$stage=Join-Path $module $relative
$file=Join-Path $stage 'day.parquet'
$manifest=Join-Path $stage 'manifest.json'
if(-not (Test-Path -LiteralPath $file -PathType Leaf) -or -not (Test-Path -LiteralPath $manifest -PathType Leaf)){throw 'Private historical candidate materialization incomplete'}
$digest=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
if($digest -cne ([string]$safe.private_parquet_sha256)){throw 'Private historical candidate Parquet SHA256 differed from stage manifest'}
$proof=Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
if($proof.private_parquet_sha256 -cne $digest -or $proof.state -ne $safe.state -or $proof.ready_for_production_merge -ne $false -or $proof.h5_volume_amount_price_units_certified -ne $false -or $proof.candidate_stockday_rows -ne 24){throw 'Private historical candidate manifest/source safety disagreement'}
Write-Host ('PASS_PRIVATE_1990_H5_DAY_STAGED=24 OTHER_CODE_EXCLUDED=16 SOURCE_PQ_PRE2011_ABSENT=TRUE UNIT_CERTIFIED=FALSE PRODUCTION_MERGED=FALSE')
Write-Host ('PRIVATE_STAGE_RELATIVE_DIR='+$relative)
Write-Host ('PRIVATE_1990_DAY_PARQUET_SHA256='+$digest)
Write-Host 'PASS: original H5 and purchased Parquet unchanged; only one ignored research candidate + manifest created, no active pointer or production data writes.'
