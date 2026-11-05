# Read-only gate: original purchased Parquet all eight K-line cycles (two years)
# Synthetic tests first; all real OHLCVA remains in local Python memory.
param([string]$Symbol='SH600000')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$query=Join-Path $module 'tools\query-purchased-primary-all-eight-cycles-readonly.py'
$tests=Join-Path $module 'tests'
foreach($f in @($py,$query)){if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing query prerequisite: $f"}}
foreach($pattern in @('test_query_parquet_primary_readonly.py','test_query_purchased_primary_minute_with_private_gap_readonly.py','test_query_purchased_primary_all_eight_cycles_readonly.py')){
    & $py -B -m unittest discover -s $tests -p $pattern -v
    if($LASTEXITCODE -ne 0){throw "All-cycle read-only regression failed: $pattern; no real query"}
}
foreach($year in @('2025','2026')){
    foreach($cycle in @('15min','30min','60min','day','week','month')){
        $first=if($cycle -in @('week','month')){"$year-09-01"}else{"$year-09-30"}
        $last="$year-09-30"
        $data=@(& $py -B $query --root 'D:\stock' --symbol $Symbol --period $cycle --from-day $first --through-day $last)
        if($LASTEXITCODE -ne 0){throw "Purchased $cycle $year read-only query failed"}
        $safe=($data -join [Environment]::NewLine) | ConvertFrom-Json
        if($safe.matching_bar_count -lt 1 -or $safe.bars_by_source.purchased_parquet -ne $safe.matching_bar_count -or $safe.original_market_files_modified -ne $false -or $safe.new_market_or_index_files_written -ne $false -or $safe.production_query_activated -ne $false -or $safe.vendor_physical_units_certified -ne $false -or $safe.corporate_action_adjustments_certified -ne $false){throw "Purchased source/metadata contract mismatch: $cycle $year"}
        Write-Host ("PURCHASED_DIRECT YEAR="+$year+" PERIOD="+$cycle+" BARS="+$safe.matching_bar_count+" SOURCE=purchased_parquet RAW_SOURCE_TIME_LABEL=True")
    }
}
foreach($period in @('1min','5min')){
    $data=@(& $py -B $query --root 'D:\stock' --symbol $Symbol --period $period --from-day '2026-09-30' --through-day '2026-10-13' --allow-verified-private-h5)
    if($LASTEXITCODE -ne 0){throw "Existing H5-gated minute adapter query failed: $period"}
    $safe=($data -join [Environment]::NewLine) | ConvertFrom-Json
    $want=if($period -eq '1min'){1201}else{240}
    if($safe.matching_bar_count -ne $want -or $safe.bars_by_source.purchased_parquet -lt 1 -or $safe.bars_by_source.verified_private_h5_gap -lt 1 -or $safe.production_query_activated -ne $false){throw "Minute all-cycle adapter source contract mismatch: $period"}
    Write-Host ("MINUTE_DELEGATE PERIOD="+$period+" TOTAL="+$safe.matching_bar_count+" PURCHASED="+$safe.bars_by_source.purchased_parquet+" VERIFIED_H5="+$safe.bars_by_source.verified_private_h5_gap)
}
Write-Host 'PASS: 8 purchased K-line cycles locally read, 2025/2026 six-period samples plus existing 1/5min source-priority fallback; 0 source writes; NOT production-certified.'
