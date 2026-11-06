# Original H5 vs staged historical private Parquet six-field exact arithmetic.
# First live range 1990..1992 ONLY; no change to original market or private files.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$python=Join-Path $repo '.venv\Scripts\python.exe'
$tests=Join-Path $module 'tests'
$tool=Join-Path $module 'tools\compare-original-h5-pre2011-private-day-ohlcva-exact-readonly.py'
if(-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $tool -PathType Leaf)){throw 'Original H5 exact private Parquet source recheck prerequisites missing'}
Write-Host '===== Fictional H5 source vs private Parquet six-field exact equality safety tests ====='
& $python -B -m unittest discover -s $tests -p 'test_compare_original_h5_pre2011_private_day_ohlcva_exact_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Original H5 exact source vs private Parquet synthetic tests failed; real H5/PQ not opened'}
Write-Host '===== ORIGINAL H5 1990..1992 all A-code day bars compared to private Parquet, NO WRITES ====='
$lines=@()
& $python -B $tool --source-root 'D:\stock' --from-year 1990 --through-year 1992 | Tee-Object -Variable lines
if($LASTEXITCODE -ne 0){throw 'Original H5 1990-1992 actual source vs private candidate exact six-field comparison failed closed; no source/production writes'}
$passes=@($lines|Where-Object {$_ -like 'EXACT_H5_PRIVATE_YEAR_PASS=*'})
if($passes.Count -ne 3){throw 'Expected exactly 1990-1992 original-H5 private-data exact PASS lines'}
$summaryLines=@($lines|Where-Object {$_ -like 'EXACT_H5_PRIVATE_SOURCE_COMPARE_SUMMARY=*'})
if($summaryLines.Count -ne 1){throw 'Expected one original-H5 exact private-data summary'}
$proof=([string]$summaryLines[0]).Substring('EXACT_H5_PRIVATE_SOURCE_COMPARE_SUMMARY='.Length)|ConvertFrom-Json
if($proof.state -ne 'original_h5_vs_pre2011_private_parquet_exact_candidate_6field_readonly_not_promoted' -or $proof.first_year -ne 1990 -or $proof.last_year -ne 1992 -or $proof.years_verified -ne 3 -or $proof.exact_h5_source_stockdays_compared -ne 7959 -or $proof.excluded_other_source_day_keys -ne 1866 -or $proof.full_1990_2010_coverage_compared -ne $false -or $proof.all_selected_h5_candidate_keys_and_six_fields_exact_equal -ne $true -or $proof.price_volume_amount_candidate_factors_verified_as_applied -ne $true -or $proof.h5_price_volume_amount_units_certified -ne $false -or $proof.historical_security_master_certified -ne $false -or $proof.official_trading_calendar_certified -ne $false -or $proof.corporate_action_adjustment_certified -ne $false -or $proof.original_source_stat_not_full_byte_hash -ne $true -or $proof.original_market_sources_modified -ne $false -or $proof.private_candidate_files_modified -ne $false -or $proof.production_activated -ne $false -or $proof.ready_for_production_merge -ne $false){throw '1990-1992 H5 exact-source vs private candidate SAFE verification summary mismatch'}
Write-Host 'PASS_ORIGINAL_H5_EXACT_PRIVATE_DAY_1990_1992=7959 SOURCE_AND_SIX_FIELDS_EXACT=TRUE UNIT_CERTIFIED=FALSE PRODUCTION_MERGED=FALSE'
Write-Host 'PASS: original H5/PQ sources and 21 annual private Parquet files unchanged; 1993..2010 not re-compared in this pilot.'
