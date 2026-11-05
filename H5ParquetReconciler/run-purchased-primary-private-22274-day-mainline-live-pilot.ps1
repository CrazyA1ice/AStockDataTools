# One-step mainline real daily research pilot: registered 22,274 H5-only
# candidates with purchased Parquet priority. NO PRODUCTION WRITES.
# Reuses immutable version/SAFE inputs, H5/PQ live exact-key recheck.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$resolver=Join-Path $module 'tools\resolve-registered-day-22274-evidence-offline.py'
$all=Join-Path $module 'tools\query-purchased-primary-all-eight-cycles-readonly.py'
$tests=Join-Path $module 'tests'
$version='e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23'
foreach($f in @($py,$resolver,$all)){if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing 22,274 live day source gate prerequisite: $f"}}
foreach($pattern in @('test_resolve_registered_day_22274_evidence_offline.py','test_query_purchased_primary_all_eight_cycles_registered_day_overlay_readonly.py','test_query_private_combined_day_22274_readonly.py')){
    & $py -B -m unittest discover -s $tests -p $pattern -v
    if($LASTEXITCODE -ne 0){throw "Daily 22,274 synthetic safety regression failed: $pattern; no H5/Parquet originals opened"}
}
Write-Host '===== SHA-linked private 22,274 daily evidence recovery (metadata only) ====='
$r=@(& $py -B $resolver --version-sha256 $version --write-private-config)
if($LASTEXITCODE -ne 0){$r | Out-Host;throw 'Unable to SHA-bind all original registered day evidence inputs'}
$proof=($r -join [Environment]::NewLine) | ConvertFrom-Json
if($proof.state -ne 'private_22274_research_evidence_ready_locally' -or $proof.version_sha256 -ne $version -or $proof.identified_evidence_inputs -ne 7 -or $proof.original_market_files_read -ne $false -or $proof.original_market_files_written -ne $false -or $proof.production_source_pointer_changed -ne $false){throw 'Unsafe or incomplete recovered private day evidence'}
$conf=Join-Path $module ("work\unified_parquet\registered-day-research-"+$version+".json")
if([IO.Path]::GetFullPath([string]$proof.private_config_path) -ne [IO.Path]::GetFullPath($conf) -or -not (Test-Path -LiteralPath $conf -PathType Leaf)){throw 'Private day evidence path escaped private work directory'}
Write-Host ("SHA_LINKED_EVIDENCE=7 PRIVATE_VERSION="+$version)
Write-Host '===== Live original H5/Parquet day-key/SHA recheck + single-source research bar (may scan original daily sources) ====='
$rows=@(& $py -B $all --root 'D:\stock' --symbol SH600000 --period day --from-day 2026-10-09 --through-day 2026-10-09 --max-result-bars 5 --max-candidate-rows 30000000 --allow-registered-private-day --private-day-config $conf)
if($LASTEXITCODE -ne 0){$rows | Out-Host;throw 'Registered private daily full LIVE source recheck or query failed closed; do not activate or merge any candidate'}
$summary=($rows -join [Environment]::NewLine) | ConvertFrom-Json
if($summary.period -ne 'day' -or $summary.symbol -ne 'SH600000' -or $summary.registered_private_day_version_sha256 -ne $version -or $summary.registered_private_22274_day_overlay_explicitly_enabled -ne $true -or $summary.verified_private_h5_fallback_enabled -ne $false -or $summary.purchased_source_priority -ne $true -or $summary.production_query_activated -ne $false -or $summary.original_market_files_modified -ne $false -or $summary.new_market_or_index_files_written -ne $false -or $summary.no_raw_ohlcva_in_safe_summary -ne $true -or $summary.routing -ne 'explicit_immutable_22274_day_live_verified_purchased_first'){throw 'Private 22,274 real daily source query failed strict provenance contract'}
$base=$summary.bars_by_source.PSObject.Properties['purchased_parquet']
$whole=$summary.bars_by_source.PSObject.Properties['private_h5_whole_date_candidate']
$mixed=$summary.bars_by_source.PSObject.Properties['private_h5_mixed_stockday_candidate']
if($null -eq $base -or $null -eq $whole -or $null -eq $mixed){throw 'Missing one private day source-provenance counter'}
if([long]$base.Value -ne 0 -or [long]$whole.Value -ne 1 -or [long]$mixed.Value -ne 0 -or $summary.matching_bar_count -ne 1){throw '2026-10-09 SH600000 expected whole-market H5-only source 1 bar; fail closed'}
Write-Host ("PASS_REAL_2026_10_09_SH600000_DAY=1 PURCHASED="+$base.Value+" PRIVATE_WHOLE="+$whole.Value+" PRIVATE_MIXED="+$mixed.Value)
Write-Host 'PASS: registered 22,274 day candidate query live-verified, purchased-first, original H5 and Parquet unchanged, no production pointer or mirror activated.'
