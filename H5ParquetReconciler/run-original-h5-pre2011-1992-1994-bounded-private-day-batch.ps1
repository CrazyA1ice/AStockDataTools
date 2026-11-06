# Bounded 1992..1994 H5 DAILY private stage: only three years, restartable.
# Every year rechecks original 3 H5 source stat SHA and ALL purchased day
# Parquet footers, exact year counts, full private candidate roundtrip/SHA.
# No original H5 or purchased Parquet modifications; no production merge.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$python=Join-Path $repo '.venv\Scripts\python.exe'
$tests=Join-Path $module 'tests'
$runner=Join-Path $module 'tools\run-h5-pre2011-private-annual-batch.py'
if(-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $runner -PathType Leaf)){throw 'Historical H5 annual private batch prerequisites missing'}
Write-Host '===== 1991-2010 annual H5 synthetic safety contract regression ====='
& $python -B -m unittest discover -s $tests -p 'test_stage_original_h5_pre2011_annual_private_day.py' -v
if($LASTEXITCODE -ne 0){throw 'Annual private H5 source/manifest tests failed; no market source opened'}
Write-Host '===== 1992-2010 bounded batch / restart / SHA safety contract regression ====='
& $python -B -m unittest discover -s $tests -p 'test_run_h5_pre2011_private_annual_batch.py' -v
if($LASTEXITCODE -ne 0){throw 'Private annual batch safety tests failed; no market source opened'}
Write-Host '===== ONE PRIVATE BATCH ONLY: 1992..1994 (3 audited annual stages) ====='
$lines=@()
& $python -B $runner --source-root 'D:\stock' --from-year 1992 --through-year 1994 --max-years 3 --stage-private | Tee-Object -Variable lines
$exit=$LASTEXITCODE
if($exit -ne 0){throw 'Controlled 1992-1994 private H5 historical day batch failed closed; already verified earlier year checkpoints remain in local ignored work'}
$summaryLine=@($lines|Where-Object {$_ -like 'PRIVATE_H5_BATCH_SUMMARY=*'})
if($summaryLine.Count -ne 1){throw 'Private H5 annual batch did not emit exactly one terminal aggregate SAFE proof'}
$summary=([string]$summaryLine[0]).Substring('PRIVATE_H5_BATCH_SUMMARY='.Length)|ConvertFrom-Json
if($summary.state -ne 'private_annual_1992_2010_bounded_batch_completed_not_promoted' -or $summary.from_year -ne 1992 -or $summary.through_year -ne 1994 -or $summary.year_limit -ne 3 -or @($summary.years_completed).Count -ne 3 -or ([string]::Join(',',@($summary.years_completed))) -ne '1992,1993,1994' -or $summary.new_or_revalidated_private_stockdays -ne 78672 -or $summary.all_private_year_checkpoints_verified -ne $true -or $summary.original_h5_and_purchased_parquet_modified -ne $false -or $summary.production_activated -ne $false -or $summary.historical_security_master_certified -ne $false -or $summary.historical_trading_calendar_certified -ne $false -or $summary.h5_price_volume_amount_units_certified -ne $false -or $summary.candidate_OHLCVA_exported_to_console -ne $false){throw 'Private 1992-1994 final three-year SAFE source/production gate failed'}
Write-Host 'PASS_PRIVATE_H5_PRE2011_1992_1994=78672 THREE_ANNUAL_SHA_CHECKPOINTS=TRUE PRODUCTION_MERGED=FALSE UNIT_CERTIFIED=FALSE'
Write-Host 'PASS: 1992..1994 isolated historical day research partitions SHA-verified; stop before 1995, no production pointer or original source files changed.'
