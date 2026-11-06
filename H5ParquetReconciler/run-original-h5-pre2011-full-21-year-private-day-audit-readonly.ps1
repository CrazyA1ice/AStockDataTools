# Independently verify the existing 1990..2010 21 PRIVATE H5 historical
# daily Parquet candidates. READ-ONLY: no stage, merge, file output or repair.
# Each year SHA256, physical typed schema, all rows, source/source-state,
# stockday uniqueness, dates, A-code candidate, market/annual counts, OHLCVA.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$python=Join-Path $repo '.venv\Scripts\python.exe'
$tests=Join-Path $module 'tests'
$audit=Join-Path $module 'tools\audit-original-h5-pre2011-private-21-year-day-readonly.py'
if(-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $audit -PathType Leaf)){throw 'Read-only 1990-2010 private history audit prerequisites missing'}
Write-Host '===== 21-year independent private candidate audit synthetic unit tests ====='
& $python -B -m unittest discover -s $tests -p 'test_audit_original_h5_pre2011_private_21_year_day_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Private 21-year read-only audit unit tests failed; ORIGINAL H5/PQ NOT opened'}
Write-Host '===== Real full 21-year private candidate READONLY SHA/schema/keys/OHLCVA audit ====='
$lines=@()
& $python -B $audit --source-root 'D:\stock' | Tee-Object -Variable lines
$code=$LASTEXITCODE
if($code -ne 0){throw 'Real 21-year private daily H5 candidate integrity check failed; no private/prod/market source modified'}
$completed=@($lines|Where-Object {$_ -like 'READONLY_PRIVATE_H5_YEAR_PASS=*'})
if($completed.Count -ne 21){throw 'Historical private complete-year audit did not verify exactly 21 annual SHA checkpoints'}
$final=@($lines|Where-Object {$_ -like 'READONLY_PRIVATE_H5_21_YEAR_AUDIT_SUMMARY=*'})
if($final.Count -ne 1){throw 'Historical private complete-year audit missing exactly one SAFE terminal summary'}
$result=([string]$final[0]).Substring('READONLY_PRIVATE_H5_21_YEAR_AUDIT_SUMMARY='.Length)|ConvertFrom-Json
if($result.state -ne 'full_1990_2010_private_h5_day_21_year_files_shas_schema_keys_quality_verified_readonly_not_promoted' -or $result.years_verified -ne 21 -or [string]::Join(',',@($result.years_first_last)) -ne '1990,2010' -or $result.private_a_code_stockday_rows_verified -ne 3682327 -or $result.other_code_source_rows_excluded -ne 631281 -or $result.all_annual_private_parquet_sha256_valid -ne $true -or $result.all_annual_manifest_source_state_checked -ne $true -or $result.all_annual_candidate_keys_unique_and_year_bound -ne $true -or $result.all_annual_OHLCVA_geometry_finite_nonnegative -ne $true -or $result.original_h5_ohlcva_redecoded_by_full_audit -ne $false -or $result.source_stat_SHA_is_not_full_byte_SHA -ne $true -or $result.historical_security_master_certified -ne $false -or $result.official_trading_calendar_certified -ne $false -or $result.h5_price_volume_amount_units_certified -ne $false -or $result.corporate_action_adjustment_certified -ne $false -or $result.original_market_sources_modified -ne $false -or $result.private_candidate_files_modified -ne $false -or $result.production_activated -ne $false -or $result.ready_for_production_merge -ne $false){throw '21-year read-only full private candidate SAFE summary fields did not meet strict quality gates'}
Write-Host 'PASS_FULL_PRE2011_PRIVATE_H5_DAY_AUDIT=3682327 YEARS=21 OTHER_EXCLUDED=631281 SHA_SCHEMA_KEYS_OHLCVA_PASS=TRUE UNIT_CERTIFIED=FALSE PRODUCTION_MERGED=FALSE'
