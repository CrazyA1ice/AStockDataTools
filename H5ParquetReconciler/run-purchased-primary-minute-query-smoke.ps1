# Explicit read-only purchased-first minute research query smoke test.
# Does not create or copy market Parquet/H5, indexes, stage files or pointers.
# Requires previously audited private minute-key indexes and October gap SAFEs.
param([string]$Symbol='SH600000')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$query=Join-Path $module 'tools\query-purchased-primary-minute-with-private-gap-readonly.py'
$tests=Join-Path $module 'tests'
foreach($file in @($py,$query)){
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){
        throw "Missing local query requirement: $file"
    }
}
Write-Host '===== Synthetic source priority / native time / SHA safety tests ====='
& $py -B -m unittest discover -s $tests -p 'test_query_purchased_primary_minute_with_private_gap_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Synthetic purchased-first query tests failed; market query not started'}
foreach($period in @('1min','5min')){
    Write-Host "===== Local purchased -> verified H5 research query $period ====="
    $output=@(& $py -B $query --root 'D:\stock' --symbol $Symbol --period $period --from-day '2026-09-30' --through-day '2026-10-13' --allow-verified-private-h5)
    if($LASTEXITCODE -ne 0){throw "Read-only purchased-first $period query failed"}
    $summary=($output -join [Environment]::NewLine) | ConvertFrom-Json
    $expected=if($period -eq '1min'){241}else{48}
    $expectedGap=if($period -eq '1min'){240}else{48}
    if($summary.dates.'2026-09-30'.source -ne 'purchased_parquet' -or $summary.dates.'2026-09-30'.bars -ne $expected){
        throw "Purchased original source routing/row count mismatch: $period"
    }
    if($summary.dates.'2026-10-13'.source -ne 'verified_private_h5_gap' -or $summary.dates.'2026-10-13'.bars -ne $expectedGap){
        throw "SHA-verified private H5 gap routing/row count mismatch: $period"
    }
    if($summary.production_query_activated -ne $false -or $summary.original_market_files_modified -ne $false -or $summary.new_market_files_written -ne $false -or $summary.h5_minute_vendor_physical_units_certified -ne $false){
        throw "Query safety or vendor-units contract violated: $period"
    }
    Write-Host ("PERIOD="+$period+" PURCHASED_0930="+$summary.dates.'2026-09-30'.bars+" H5_ONLY_1013="+$summary.dates.'2026-10-13'.bars+" TOTAL="+$summary.matching_bar_count+" H5_SHA_CHECKED="+$summary.h5_private_physical_SHA_checked)
}
Write-Host 'PASS: existing purchased Parquet and existing SHA-verified private H5 minute gap read via one explicit research API; no market writes or production activation.'
