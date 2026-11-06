# Read-only H5 historical private VWAP anomaly attribution, 1990..1996.
# Does not edit original H5, purchased Parquet, private candidate or production.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$python=Join-Path $repo '.venv\Scripts\python.exe'
$tests=Join-Path $module 'tests'
$tool=Join-Path $module 'tools\attribute-pre2011-private-h5-day-vwap-outliers-readonly.py'
if(-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $tool -PathType Leaf)){throw 'Historical H5 private VWAP anomaly attribution prerequisites missing'}
Write-Host '===== 11 fictional read-only root-cause attribution safety tests ====='
& $python -B -m unittest discover -s $tests -p 'test_attribute_pre2011_private_h5_day_vwap_outliers_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Private VWAP root-cause attribution synthetic safety tests failed, no originals modified'}
Write-Host '===== REAL 1990..1996 private history READONLY month/prefix/hashed-stock exception attribution ====='
$lines=@()
& $python -B $tool --source-root 'D:\stock' --from-year 1990 --through-year 1996 | Tee-Object -Variable lines
if($LASTEXITCODE -ne 0){throw 'Original historical private H5 candidate outlier attribution failed; no originals/private candidates modified'}
$annual=@($lines|Where-Object {$_ -like 'PRIVATE_H5_VWAP_ATTRIBUTION_YEAR=*'})
if($annual.Count -ne 7){throw 'Historical H5 private outlier root-cause attribution must cover exactly 7 years'}
$totals=@($lines|Where-Object {$_ -like 'PRIVATE_H5_VWAP_ATTRIBUTION_SUMMARY=*'})
if($totals.Count -ne 1){throw 'Expected one valid terminal root-cause attribution summary'}
$proof=([string]$totals[0]).Substring('PRIVATE_H5_VWAP_ATTRIBUTION_SUMMARY='.Length)|ConvertFrom-Json
$agg=$proof.aggregate
if($proof.state -ne 'pre2011_private_h5_vwap_outlier_readonly_attribution_not_unit_certification' -or $proof.first_year -ne 1990 -or $proof.last_year -ne 1996 -or $proof.years_verified -ne 7 -or $agg.candidate_stockdays_checked -ne 215238 -or $agg.positive_volume_and_amount -ne 215173 -or $agg.vwap_inside_bar -ne 207650 -or $agg.vwap_below_low -ne 4509 -or $agg.vwap_above_high -ne 3014 -or $agg.outliers_total -ne 7523 -or $proof.factors_are_competing_hypotheses_not_auto_repair -ne $true -or $proof.all_source_stats_and_private_sha_rechecked -ne $true -or $proof.original_h5_redecoded_again_by_attribution -ne $false -or $proof.h5_volume_amount_price_units_certified -ne $false -or $proof.official_adjustment_semantics_certified -ne $false -or $proof.historical_security_master_certified -ne $false -or $proof.source_or_private_files_modified -ne $false -or $proof.production_activated -ne $false -or $proof.ready_for_production_merge -ne $false){throw '1990-1996 private H5 VWAP anomaly root-cause SAFE summary disagrees with previous full history'}
# ASCII-only strings: Windows PowerShell 5.1 treats UTF-8 without BOM as ANSI.
foreach($line in $annual){
    $payload=([string]$line).Substring('PRIVATE_H5_VWAP_ATTRIBUTION_YEAR='.Length)
    $year=$payload | ConvertFrom-Json
    if($year.outliers_total -gt 0){
        if($year.number_of_sessions_with_outliers -le 0 -or @($year.top_anomalous_sessions).Count -eq 0){
            throw 'Missing anomalous trading-session concentration'
        }
        foreach($session in @($year.top_anomalous_sessions)){
            if($session.outliers_that_session -gt $session.positive_volume_amount_that_session -or $session.positive_volume_amount_that_session -gt $session.candidate_stockdays_that_session -or $session.day_sha256_prefix12.Length -ne 12){
                throw 'Anomalous trading-session counts or date fingerprint invalid'
            }
        }
    }
}
Write-Host ('PASS_PRIVATE_H5_VWAP_1990_1996_ATTRIBUTION=215238 OUTLIERS='+$agg.outliers_total+' COMPETING_FACTOR_HYPOTHESES_ONLY=TRUE UNIT_CERTIFIED=FALSE PRODUCTION_MERGED=FALSE')
Write-Host 'Examine PRIVATE_H5_VWAP_ATTRIBUTION_YEAR summaries for month/prefix concentration and high-outlier hashed source groups; no source or candidate changes performed.'
