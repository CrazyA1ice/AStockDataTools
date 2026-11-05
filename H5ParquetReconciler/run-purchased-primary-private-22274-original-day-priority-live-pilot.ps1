# Mainline purchased-primary real-day proof on a registered 83-mixed-date.
# Read-only original H5/Parquet source evidence; no symbol or OHLCVA output.
# The selected day is SHA-bound, only one full live source recheck performed.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tests=Join-Path $module 'tests'
$resolver=Join-Path $module 'tools\resolve-registered-day-22274-evidence-offline.py'
$pilot=Join-Path $module 'tools\query-registered-private-day-purchased-first-live-pilot-readonly.py'
$version='e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23'
$conf=Join-Path $module ('work\unified_parquet\registered-day-research-'+$version+'.json')
foreach($file in @($py,$resolver,$pilot)){
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw "Missing purchased-primary real daily research prerequisite: $file"}
}
& $py -B -m unittest discover -s $tests -p 'test_query_registered_private_day_purchased_first_live_pilot_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Purchased primary real day proof synthetic tests failed; original H5/Parquet were not opened'}
Write-Host '===== Verify seven exact SHA-linked private day research inputs (metadata only) ====='
$lines=@(& $py -B $resolver --version-sha256 $version --write-private-config)
if($LASTEXITCODE -ne 0){$lines | Out-Host;throw 'Existing original day source SHA evidence cannot be validated'}
$proof=($lines -join [Environment]::NewLine) | ConvertFrom-Json
if($proof.state -ne 'private_22274_research_evidence_ready_locally' -or $proof.version_sha256 -ne $version -or $proof.identified_evidence_inputs -ne 7 -or $proof.whole_plus_mixed_candidate_count -ne 22274 -or $proof.original_market_files_written -ne $false -or $proof.market_ohlcva_copied -ne $false -or $proof.production_source_pointer_changed -ne $false -or [IO.Path]::GetFullPath([string]$proof.private_config_path) -ne [IO.Path]::GetFullPath($conf)){throw 'SHA-bound private daily source configuration failed strict safety check'}
Write-Host '===== Purchased Parquet daily bar identical after explicit H5/Parquet full live fusion gate ====='
$rows=@(& $py -B $pilot --root 'D:\stock' --version-sha256 $version --private-day-config $conf --max-candidate-rows 30000000)
if($LASTEXITCODE -ne 0){$rows | Out-Host;throw 'Purchased-primary real daily live check failed closed; original sources not rewritten'}
$safe=($rows -join [Environment]::NewLine) | ConvertFrom-Json
if($safe.status -ne 'verified_registered_22274_purchased_parquet_primary_real_stockday' -or $safe.registered_private_day_version_sha256 -ne $version -or $safe.matching_bars -ne 1 -or $safe.source_security_identifier_redacted -ne $true -or $safe.candidate_83_mixed_day_context_verified -ne $true -or $safe.all_six_OHLCVA_values_and_source_timestamp_equal_purchased_original -ne $true -or $safe.purchased_source_file_and_rowgroup_preserved -ne $true -or $safe.H5_value_override -ne $false -or $safe.full_h5_purchased_live_source_gate_passed -ne $true -or $safe.original_market_files_modified -ne $false -or $safe.production_query_activated -ne $false -or $safe.raw_price_values_in_safe_summary -ne $false){throw 'Purchased-first daily source proof safety summary disagreed with original evidence'}
$base=$safe.bars_by_source.PSObject.Properties['purchased_parquet']
$whole=$safe.bars_by_source.PSObject.Properties['private_h5_whole_date_candidate']
$mixed=$safe.bars_by_source.PSObject.Properties['private_h5_mixed_stockday_candidate']
if($null -eq $base -or $null -eq $whole -or $null -eq $mixed -or [long]$base.Value -ne 1 -or [long]$whole.Value -ne 0 -or [long]$mixed.Value -ne 0){throw 'Purchased-first daily original source row lost or H5 incorrectly overrode it'}
Write-Host ('PASS_REAL_PURCHASED_FIRST_ON_MIXED_DATE='+$safe.source_day+' PURCHASED=1 PRIVATE_WHOLE=0 PRIVATE_MIXED=0 SIX_OHLCVA_EXACT=TRUE SYMBOL_REDACTED=TRUE')
Write-Host 'PASS: original purchased Parquet daily OHLCVA, exact timestamp and provenance preserved through full registered H5/PQ live recheck; no production write.'
