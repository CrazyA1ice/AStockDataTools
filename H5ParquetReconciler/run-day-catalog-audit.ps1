# SHA-verify already materialized 1990-2026 day catalog and summarize RAW quarantine reasons.
# IMPORTANT: does not convert RAW again, touch original market data, or activate production.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$module = Split-Path -Parent $PSCommandPath
$repo = Split-Path -Parent $module
Set-Location -LiteralPath $repo
$python = Join-Path $repo '.venv\Scripts\python.exe'
$script = Join-Path $module 'tools\audit-full-history-day-quarantine-and-catalog.py'
$test = Join-Path $module 'tests\test_audit_full_history_day_quarantine_and_catalog.py'
$history = Join-Path $module 'reports\pre2011-day-historical-candidates-and-2011-2026-union-3c808c8da646.json'
$raw = Join-Path $module 'reports\pre2011-full21-verify-9bba81ed3c33.json'
$modern = Join-Path $module 'reports\private-2011-2026-all16-sha-bound-version-15fb74d42d0b.json'
$modernSha = 'bd64abcd0580cbed404c31bc2db3a05f9b2411880fa24d6bf3b14ecabcdb0c05'

foreach ($f in @($python, $script, $test, $history, $raw, $modern)) {
    if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { throw "Missing required verified source or program: $f" }
}
if ((Get-FileHash -LiteralPath $modern -Algorithm SHA256).Hash.ToLowerInvariant() -ne $modernSha) {
    throw 'Existing 2011-2026 private version SHA differs: fail closed'
}
& $python -m py_compile $script $test
if ($LASTEXITCODE -ne 0) { throw 'Python syntax preflight failed; nothing changed' }
& $python -m unittest discover -s (Join-Path $module 'tests') -p 'test_audit_full_history_day_quarantine_and_catalog.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Historical catalog 4-test preflight failed; no original files touched' }

$historySha = (Get-FileHash -LiteralPath $history -Algorithm SHA256).Hash.ToLowerInvariant()
$id = [Guid]::NewGuid().ToString('N').Substring(0, 12)
$out = Join-Path $module "reports\pre2011-historical-reject-reasons-catalog-$id.json"
& $python $script --candidate-version-safe $history --candidate-version-sha256 $historySha --full21-safe $raw --modern-version-safe $modern --modern-version-sha256 $modernSha --out $out --audit-sha-bound-private-only
if ($LASTEXITCODE -ne 0) { throw 'Original 21-year private Parquet SHA or quarantine reason audit failed; prior data unchanged' }
$r = Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json
if ($r.status -ne 'full_history_all21_quarantine_reasons_and_private_day_tiers_sha_reverified_not_activated' -or
    $r.historical_purchase_schema_unverified_candidate_rows -ne 3673987 -or
    $r.historical_native_quarantined_rows -ne 8340 -or
    $r.modern_purchased_first_private_rows -ne 14137981 -or
    $r.all_history_source_rows_accounted -ne 17820308 -or
    $r.historical_purchase_schema_semantics_certified -ne $false -or
    $r.ready_for_production_query -ne $false -or
    $r.original_market_or_previous_private_files_modified -ne $false) {
    throw 'SHA-verified catalog cannot be marked as passed: unexpected totals or safety flags'
}
Write-Host 'PASS: 1990-2010 tentative 3673987 + raw quarantine 8340; modern original 14137981 unchanged'
Write-Host 'Historical source total = 17820308; full market production NOT activated'
Write-Host 'Quarantine reasons:'
$r.all_historical_quarantine_reasons | Format-List
Write-Host "SAFE: $out"
