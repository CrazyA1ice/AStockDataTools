# Mainline: auto-resolve SHA-linked private 22,274-day research evidence.
# No original H5/Parquet bars are opened; only small SHA-bound SAFE reports
# and a 83-stockday private key manifest are read. Creates a single ignored
# seven-field research config iff every exact SHA and offline plan verifies.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$resolver=Join-Path $module 'tools\resolve-registered-day-22274-evidence-offline.py'
$tests=Join-Path $module 'tests'
$version='e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23'
foreach($file in @($py,$resolver)){
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw "Missing SHA-linked daily mainline evidence prerequisite: $file"}
}
& $py -B -m unittest discover -s $tests -p 'test_resolve_registered_day_22274_evidence_offline.py' -v
if($LASTEXITCODE -ne 0){throw 'Private 22,274 day offline evidence resolver regression failed'}
Write-Host '===== SHA-linked existing private day evidence; ORIGINAL MARKET BARS NOT READ ====='
$lines=@(& $py -B $resolver --version-sha256 $version --write-private-config)
if($LASTEXITCODE -ne 0){$lines | Out-Host;throw 'Private 22,274 evidence not uniquely SHA-resolvable; no source data modified'}
$safe=($lines -join [Environment]::NewLine) | ConvertFrom-Json
if($safe.state -ne 'private_22274_research_evidence_ready_locally' -or $safe.version_sha256 -ne $version -or $safe.identified_evidence_inputs -ne 7 -or $safe.whole_plus_mixed_candidate_count -ne 22274 -or $safe.historical_year_reports_SHA_reconciled -ne $true -or $safe.private_83_stockday_key_manifest_verified -ne $true -or $safe.original_market_files_read -ne $false -or $safe.original_market_files_written -ne $false -or $safe.market_ohlcva_copied -ne $false -or $safe.production_source_pointer_changed -ne $false -or $safe.live_original_h5_and_purchased_parquet_rechecked_now -ne $false){throw 'Private 22,274 offline evidence gate safety contract mismatch'}
$expected=Join-Path $module ("work\unified_parquet\registered-day-research-"+$version+".json")
if([IO.Path]::GetFullPath([string]$safe.private_config_path) -ne [IO.Path]::GetFullPath($expected) -or -not (Test-Path -LiteralPath $expected -PathType Leaf)){throw 'Private day research config was not created under the exact gitignored work directory'}
Write-Host ('DAY_EVIDENCE_CONFIG='+$expected)
Write-Host ('EXACT_PRIVATE_VERSION='+$version)
Write-Host 'PASS: 7 SHA-linked local evidence inputs resolved and versioned; next: opt-in full H5/Parquet live day-source research query. NO source market file or active pointer modified.'
