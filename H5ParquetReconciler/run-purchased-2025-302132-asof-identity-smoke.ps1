# Explicit research-only original vendor source code with historical as-of labels.
# No global A-share filter widening, index rebuild, OHLCVA cache or market write.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\query-purchased-2025-302132-asof-identity-readonly.py'
$tests=Join-Path $module 'tests'
foreach($file in @($py,$tool)){if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw "Missing 302132 research pilot prerequisite: $file"}}
foreach($pattern in @('test_query_parquet_primary_readonly.py','test_query_purchased_2025_302132_asof_identity_readonly.py')){
    & $py -B -m unittest discover -s $tests -p $pattern -v
    if($LASTEXITCODE -ne 0){throw "Documented 302132 research safety regression failed: $pattern; source not queried"}
}
foreach($trial in @(@('5min','2025-01-02','2025-01-02',48,48,0),@('5min','2025-02-17','2025-02-17',48,0,48),@('1min','2025-02-17','2025-02-17',241,0,241))){
    $period=[string]$trial[0];$start=[string]$trial[1];$end=[string]$trial[2];$expected=[int]$trial[3];$expectedOld=[int]$trial[4];$expectedNew=[int]$trial[5]
    $data=@(& $py -B $tool --root 'D:\stock' --period $period --from-day $start --through-day $end --max-candidate-rows 30000000 --max-result-bars 1000)
    if($LASTEXITCODE -ne 0){$data | Out-Host;throw "302132 original purchased research query failed: $period $start"}
    $safe=($data -join [Environment]::NewLine) | ConvertFrom-Json
    if($safe.status -ne 'explicit_2025_documented_vendor_code_source_relabel_research_only' -or $safe.source_symbol -ne 'SZ302132' -or $safe.official_code_change_day -ne '2025-02-17' -or $safe.source_matching_bars -ne $expected -or $safe.observed_complete_source_stockdays -ne 1 -or $safe.original_vendor_source_code_preserved -ne $true -or $safe.A_share_global_code_filter_changed -ne $false -or $safe.private_licensed_bar_cache_written -ne $false -or $safe.H5_fallback_invoked -ne $false -or $safe.original_market_files_modified -ne $false -or $safe.production_identity_mapping_activated -ne $false -or $safe.raw_ohlcva_in_safe_summary -ne $false){throw "302132 source-asof identity safety mismatch: $period $start"}
    $old=$safe.source_bars_annotated_by_asof_code.PSObject.Properties['SZ300114'];$oldCount=if($null -eq $old){0}else{[long]$old.Value}
    $new=$safe.source_bars_annotated_by_asof_code.PSObject.Properties['SZ302132'];$newCount=if($null -eq $new){0}else{[long]$new.Value}
    if($oldCount -ne $expectedOld -or $newCount -ne $expectedNew -or ($oldCount+$newCount) -ne $expected){throw "302132 incorrect historical as-of label: $period $start"}
    Write-Host ("PASS PERIOD="+$period+" DAY="+$start+" RAW_VENDOR_SYMBOL=SZ302132 RAW_SOURCE_BARS="+$expected+" OFFICIAL_ASOF_300114="+$oldCount+" OFFICIAL_ASOF_302132="+$newCount+" PRIVATE_CACHE=0 MARKET_WRITE=0")
}
Write-Host 'PASS: 2025 documented code-relabelled vendor source can be researched with correct historical as-of labels; original source/indices untouched and no production activation.'
