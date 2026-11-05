# Research-only readiness gate for the immutable 22,274-day candidate overlay.
# Tests are synthetic; inventory opens registered version metadata and SAFE
# file hashes only, never licensed OHLCVA/H5 or production data pointers.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tests=Join-Path $module 'tests'
$inventory=Join-Path $module 'tools\inspect-registered-private-day-22274-readiness-readonly.py'
foreach($file in @($py,$inventory)){
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw "Missing private 22274 daily readiness prerequisite: $file"}
}
foreach($pattern in @(
    'test_query_purchased_primary_all_eight_cycles_readonly.py',
    'test_query_purchased_primary_all_eight_cycles_registered_day_overlay_readonly.py',
    'test_inspect_registered_private_day_22274_readiness_readonly.py',
    'test_query_private_combined_day_22274_readonly.py'
)){
    & $py -B -m unittest discover -s $tests -p $pattern -v
    if($LASTEXITCODE -ne 0){throw "Mainline private 22274 daily gate test failed: $pattern; no source opened"}
}
Write-Host '===== Verified PRIVATE 22,274 registered-day versions: no market-data reads ====='
$rows=@(& $py -B $inventory --max-versions 30)
if($LASTEXITCODE -ne 0){$rows | Out-Host;throw 'Private day readiness inventory invalid; no market writes'}
$state=($rows -join [Environment]::NewLine) | ConvertFrom-Json
if($state.original_market_files_modified -ne $false -or $state.live_h5_purchased_source_reverified_by_this_inventory -ne $false -or $state.source_market_bars_opened -ne $false -or $state.active_source_pointer_changed -ne $false -or $state.ready_for_production -ne $false -or $state.candidate_total_new_stockday_rows_per_version -ne 22274 -or $state.candidate_whole_date_rows_per_version -ne 22191 -or $state.candidate_mixed_stockday_rows_per_version -ne 83){throw 'Private 22274 readiness/provenance contract violated'}
if($state.registered_immutable_version_count -ne @($state.registered_immutable_versions).Count){throw 'Private registered-version count mismatch'}
Write-Host ("DAY_PRIVATE_VERSION_STATE="+$state.status)
Write-Host ("REGISTERED_22274_VERSION_COUNT="+$state.registered_immutable_version_count)
foreach($id in @($state.registered_immutable_versions)){
    Write-Host ("REGISTERED_RESEARCH_SHA256="+$id)
}
Write-Host ("NEXT_GATE="+$state.next_gate)
Write-Host 'PASS: research-only all-eight-cycle day branch installed and private version inventory inspected; full live source recheck required before any private bar query; production unchanged.'
