# Research-only 83 mixed-H5 stockday real probe. Never prints exact
# private candidate stock identifiers, OHLCVA, or any source market bar.
# Exactly one SHA-selected 2026 stockday; full live original H5/PQ source gate.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tests=Join-Path $module 'tests'
$resolver=Join-Path $module 'tools\resolve-registered-day-22274-evidence-offline.py'
$pilot=Join-Path $module 'tools\query-registered-private-day-83-mixed-live-pilot-readonly.py'
$version='e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23'
$conf=Join-Path $module ("work\unified_parquet\registered-day-research-"+$version+".json")
foreach($file in @($py,$resolver,$pilot)){
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw "Missing registered 83-mixed live research prerequisite: $file"}
}
& $py -B -m unittest discover -s $tests -p 'test_query_registered_private_day_83_mixed_live_pilot_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Private 83-mixed daily sample safety tests failed; no live H5/PQ source opened'}
Write-Host '===== SHA-linked existing private 22,274 evidence (metadata only) ====='
$lines=@(& $py -B $resolver --version-sha256 $version --write-private-config)
if($LASTEXITCODE -ne 0){$lines | Out-Host;throw 'Existing SHA-linked evidence recovery failed; no live market data read'}
$proof=($lines -join [Environment]::NewLine) | ConvertFrom-Json
if($proof.state -ne 'private_22274_research_evidence_ready_locally' -or $proof.version_sha256 -ne $version -or $proof.identified_evidence_inputs -ne 7 -or $proof.whole_plus_mixed_candidate_count -ne 22274 -or $proof.original_market_files_written -ne $false -or $proof.live_original_h5_and_purchased_parquet_rechecked_now -ne $false -or [IO.Path]::GetFullPath([string]$proof.private_config_path) -ne [IO.Path]::GetFullPath($conf) -or -not (Test-Path -LiteralPath $conf -PathType Leaf)){throw 'Private 83-mixed exact SHA evidence contract failed'}
Write-Host '===== ONE private SHA-selected 2026 mixed stockday: FULL live original H5/PQ key+source recheck ====='
$rows=@(& $py -B $pilot --root 'D:\stock' --version-sha256 $version --private-day-config $conf --max-candidate-rows 30000000 --max-result-bars 3)
if($LASTEXITCODE -ne 0){$rows | Out-Host;throw 'Private 83 mixed-day full H5/Parquet live query failed closed; never activate source or merge candidates'}
$summary=($rows -join [Environment]::NewLine) | ConvertFrom-Json
if($summary.state -ne 'registered_22274_mixed_83_real_stockday_passed_live' -or $summary.verified_candidate_version_sha256 -ne $version -or $summary.period -ne 'day' -or $summary.source_security_identifier_redacted -ne $true -or $summary.live_original_h5_and_purchased_parquet_rechecked -ne $true -or $summary.matched_bars -ne 1 -or $summary.source_market_files_modified -ne $false -or $summary.private_candidate_version_changed -ne $false -or $summary.h5_mirror_created -ne $false -or $summary.production_active_pointer_changed -ne $false -or $summary.source_ohlcva_values_exposed_in_safe -ne $false){throw 'Mixed 83-day LIVE daily research verification summary invalid'}
$base=$summary.bars_by_source.PSObject.Properties['purchased_parquet']
$whole=$summary.bars_by_source.PSObject.Properties['private_h5_whole_date_candidate']
$mixed=$summary.bars_by_source.PSObject.Properties['private_h5_mixed_stockday_candidate']
if($null -eq $base -or $null -eq $whole -or $null -eq $mixed -or [long]$base.Value -ne 0 -or [long]$whole.Value -ne 0 -or [long]$mixed.Value -ne 1){throw 'Mixed 83-day LIVE source count mismatch'}
Write-Host ('PASS_REAL_PRIVATE_83_MIXED_DAY='+$summary.source_day+' PURCHASED=0 PRIVATE_WHOLE=0 PRIVATE_MIXED=1 SYMBOL_REDACTED=TRUE')
Write-Host 'PASS: exactly one 2026 mixed source stockday live-verified against registered 22,274 version; market original unchanged, no production write.'
