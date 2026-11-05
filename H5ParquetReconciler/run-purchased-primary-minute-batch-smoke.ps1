# Bound 2-symbol real-market read-only research query; original source never written.
# First test synthetic priority/SHA/time contracts, then query both 1m and 5m.
param([string[]]$Symbols=@('SH600000','SZ000001'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$query=Join-Path $module 'tools\query-purchased-primary-minute-with-private-gap-readonly.py'
$test=Join-Path $module 'tests'
if(-not (Test-Path -LiteralPath $py -PathType Leaf) -or -not (Test-Path -LiteralPath $query -PathType Leaf)){
    throw 'Python or purchased-primary minute query tool missing'
}
if($Symbols.Count -ne 2 -or $Symbols[0] -eq $Symbols[1]){
    throw 'Smoke gate expects exactly two distinct candidate securities'
}
& $py -B -m unittest discover -s $test -p 'test_query_purchased_primary_minute_with_private_gap_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Synthetic query safety suite failed; real-market query not started'}
foreach($period in @('1min','5min')){
    $call=@($query,'--root','D:\stock','--symbols') + $Symbols + @('--period',$period,'--from-day','2026-09-30','--through-day','2026-10-13','--allow-verified-private-h5')
    $result=@(& $py -B @call)
    if($LASTEXITCODE -ne 0){throw "Read-only two-security query failed: $period"}
    $report=($result -join [Environment]::NewLine) | ConvertFrom-Json
    if($report.symbol_count -ne 2 -or $report.production_query_activated -ne $false -or $report.new_market_files_written -ne $false -or $report.original_market_files_modified -ne $false -or $report.h5_minute_vendor_physical_units_certified -ne $false){
        throw "Multi-security safety contract failed: $period"
    }
    $buyExpected=if($period -eq '1min'){241}else{48}
    $gapExpected=if($period -eq '1min'){240}else{48}
    foreach($symbol in $Symbols){
        $item=$report.per_symbol.PSObject.Properties[$symbol].Value
        if($item.dates.'2026-09-30'.source -ne 'purchased_parquet' -or $item.dates.'2026-09-30'.bars -ne $buyExpected){
            throw "Purchased source routing mismatch: $symbol $period"
        }
        foreach($day in @('2026-10-08','2026-10-09','2026-10-12','2026-10-13')){
            if($item.dates.PSObject.Properties[$day].Value.source -ne 'verified_private_h5_gap' -or $item.dates.PSObject.Properties[$day].Value.bars -ne $gapExpected){
                throw "H5-only private source routing mismatch: $symbol $period $day"
            }
        }
        $expected=$buyExpected + (4 * $gapExpected)
        if($item.matching_bar_count -ne $expected -or $item.h5_private_physical_SHA_checked -ne $true){
            throw "Per-security SHA/rows mismatch: $symbol $period"
        }
    }
    $expectedTotal=2 * ($buyExpected + (4 * $gapExpected))
    if($report.matching_bar_count -ne $expectedTotal -or $report.bars_by_source.purchased_parquet -ne (2 * $buyExpected) -or $report.bars_by_source.verified_private_h5_gap -ne (8 * $gapExpected)){
        throw "Batch aggregate provenance or total count mismatch: $period"
    }
    Write-Host ("PASS PERIOD="+$period+" SECURITIES="+($Symbols -join ',')+" PURCHASED="+$report.bars_by_source.purchased_parquet+" VERIFIED_H5="+$report.bars_by_source.verified_private_h5_gap+" TOTAL="+$report.matching_bar_count)
}
Write-Host 'PASS: two-security purchased-primary/H5-gap research batch, 2 cycles, 5 trading dates; 0 market writes and no production activation.'
