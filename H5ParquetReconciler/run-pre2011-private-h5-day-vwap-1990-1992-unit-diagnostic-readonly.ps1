# Read-only H5 private 1990..1992 candidate VWAP/turnover/volume evidence.
# Not a vendor unit certification; anomalies are AGGREGATED not suppressed.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$python=Join-Path $repo '.venv\Scripts\python.exe'
$tests=Join-Path $module 'tests'
$tool=Join-Path $module 'tools\audit-pre2011-private-day-amount-volume-vwap-unit-diagnostics-readonly.py'
if(-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $tool -PathType Leaf)){throw 'Historical unit diagnostic read-only prerequisites missing'}
Write-Host '===== Synthetic historical private H5 price-volume-amount unit diagnostic safety tests ====='
& $python -B -m unittest discover -s $tests -p 'test_audit_pre2011_private_day_amount_volume_vwap_unit_diagnostics_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Private VWAP/turnover diagnostic tests failed; no original market source opened'}
Write-Host '===== REAL PRIVATE 1990..1992 read-only implied VWAP/amount-volume analysis ====='
$lines=@()
& $python -B $tool --source-root 'D:\stock' --from-year 1990 --through-year 1992 | Tee-Object -Variable lines
if($LASTEXITCODE -ne 0){throw 'Historical H5 candidate internal amount/volume/price analysis failed; no originals/private candidates modified'}
$annual=@($lines|Where-Object {$_ -like 'PRIVATE_H5_UNIT_YEAR=*'})
if($annual.Count -ne 3){throw 'Did not independently diagnose exactly three annual private candidates'}
$totals=@($lines|Where-Object {$_ -like 'PRIVATE_H5_UNIT_DIAGNOSTIC_SUMMARY=*'})
if($totals.Count -ne 1){throw 'Expected exactly one candidate unit diagnostic SAFE summary'}
$proof=([string]$totals[0]).Substring('PRIVATE_H5_UNIT_DIAGNOSTIC_SUMMARY='.Length)|ConvertFrom-Json
if($proof.state -ne 'private_h5_day_candidate_vwap_unit_consistency_diagnostic_only' -or $proof.first_year -ne 1990 -or $proof.last_year -ne 1992 -or $proof.years_checked -ne 3 -or $proof.candidate_stockdays_checked -ne 7959 -or $proof.all_years_source_sha_bound_and_private_sha_rechecked -ne $true -or $proof.vwap_is_amount_divided_by_volume -ne $true -or $proof.ratio_candidate_factor_5pct_bands_are_hypotheses -ne $true -or $proof.detected_outliers_are_not_auto_removed -ne $true -or $proof.h5_physical_amount_and_volume_units_certified -ne $false -or $proof.official_adjustment_semantics_certified -ne $false -or $proof.official_historical_security_master_certified -ne $false -or $proof.production_merge_authorized -ne $false -or $proof.source_market_files_modified -ne $false -or $proof.historical_private_candidate_files_modified -ne $false -or $proof.private_report_file_written -ne $false){throw 'Private H5 candidate VWAP diagnostic summary safety/uncertainty gate failed'}
$c=$proof.aggregate; $part=[long]$c.positive_volume_and_amount+[long]$c.both_zero+[long]$c.only_volume_zero+[long]$c.only_amount_zero; $vwap=[long]$c.vwap_inside_bar+[long]$c.vwap_below_low+[long]$c.vwap_above_high
if($part -ne 7959 -or $vwap -ne [long]$c.positive_volume_and_amount){throw 'Candidate price/volume/amount diagnostic conservation failed'}
Write-Host ('PASS_PRIVATE_H5_DAY_1990_1992_VWAP_DIAGNOSTIC=7959 VWAP_WITHIN_BAR='+$c.vwap_inside_bar+' VWAP_BELOW_LOW='+$c.vwap_below_low+' VWAP_ABOVE_HIGH='+$c.vwap_above_high+' VENDOR_UNIT_CERTIFIED=FALSE PRODUCTION_MERGED=FALSE')
Write-Host 'PASS: read-only candidate unit-consistency evidence only; ratio anomalies require investigation, not automatic data repairs.'
