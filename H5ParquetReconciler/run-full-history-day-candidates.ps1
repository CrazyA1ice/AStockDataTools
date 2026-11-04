# Offline, resume-safe 1990-2010 historical DAY candidate materialization.
# Does NOT activate production, overwrite purchased Parquet, or touch source H5.
# PowerShell 5.1+; invoke from any directory:
# powershell.exe -NoProfile -ExecutionPolicy Bypass -File H5ParquetReconciler\run-full-history-day-candidates.ps1 -Run
param([switch]$Run)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$module = Split-Path -Parent $PSCommandPath
$repo = Split-Path -Parent $module
Set-Location -LiteralPath $repo
$python = Join-Path $repo '.venv\Scripts\python.exe'
$old = Join-Path $module 'reports\pre2011-full21-verify-9bba81ed3c33.json'
$modern = Join-Path $module 'reports\private-2011-2026-all16-sha-bound-version-15fb74d42d0b.json'
$modernSha = 'bd64abcd0580cbed404c31bc2db3a05f9b2411880fa24d6bf3b14ecabcdb0c05'
$writer = Join-Path $module 'tools\build-1990-2026-private-day-candidate-version.py'
$tests = @('test_stage_pre2011_day_normalized_candidates_with_quarantine.py', 'test_build_1990_2026_private_day_candidate_version.py')

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Missing .venv Python; no market files were accessed.' }
foreach ($f in @($old, $modern, $writer)) {
    if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { throw "Missing immutable source/tool: $f" }
}
if ((Get-FileHash -LiteralPath $modern -Algorithm SHA256).Hash.ToLowerInvariant() -ne $modernSha) {
    throw 'The already accepted 2011-2026 16-year version SHA changed. Refusing to continue.'
}
& $python -m py_compile (Join-Path $module 'tools\stage-pre2011-day-normalized-candidates-with-quarantine.py') $writer
if ($LASTEXITCODE -ne 0) { throw 'Python syntax preflight failed. No data was written.' }
foreach ($test in $tests) {
    & $python -m unittest discover -s (Join-Path $module 'tests') -p $test -v
    if ($LASTEXITCODE -ne 0) { throw "Offline materialization test failed: $test" }
}
Write-Host 'PASS: pinned modern version, conversion syntax and four focused offline tests.'
if (-not $Run) {
    Write-Host 'No market data written. Run with -Run to classify all 21 old annual RAW shards.'
    exit 0
}

$work = Join-Path $module 'work'
if (-not (Test-Path -LiteralPath $work -PathType Container)) {
    New-Item -ItemType Directory -Path $work -Force | Out-Null
}
$idfile = Join-Path $work 'pre2011_day_candidate_job_id.txt'
if (Test-Path -LiteralPath $idfile -PathType Leaf) {
    $id = (Get-Content -LiteralPath $idfile -Raw -Encoding ASCII).Trim()
} else {
    $proposed = [Guid]::NewGuid().ToString('N').Substring(0, 12)
    try {
        $stream = [System.IO.File]::Open($idfile, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        try {
            $bytes = [System.Text.Encoding]::ASCII.GetBytes($proposed)
            $stream.Write($bytes, 0, $bytes.Length)
        } finally { $stream.Dispose() }
        $id = $proposed
    } catch [System.IO.IOException] {
        $id = (Get-Content -LiteralPath $idfile -Raw -Encoding ASCII).Trim()
    }
}
if ($id -notmatch '^[0-9a-f]{12}$') {
    throw 'Stored run ID is invalid. Preserve it and inspect the job before retrying.'
}
# A fresh receipt name allows a completed run to recheck the existing annual
# artifacts without overwriting prior receipts or staging them again.
$receiptId = [Guid]::NewGuid().ToString('N').Substring(0, 12)
$out = Join-Path $module "reports\pre2011-day-historical-candidates-and-2011-2026-union-$receiptId.json"
Write-Host "Resume-safe historical run ID: $id"
& $python $writer --full21-safe $old --modern-version-safe $modern --modern-version-sha256 $modernSha --run-id $id --out $out --build-full-history-day-candidate-version
if ($LASTEXITCODE -ne 0) {
    throw 'Historical candidate stage failed. Keep run-ID and partial artifacts; rerun the same command to resume.'
}
$r = Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json
if ($r.status -ne '1990_2026_day_full_history_private_candidates_with_raw_quarantine_not_activated' -or
    $r.raw_1990_2010_h5_rows_preserved -ne 3682327 -or
    $r.modern_2011_2026_accepted_private_rows -ne 14137981 -or
    $r.all_1990_2026_source_rows_without_overlap -ne 17820308 -or
    $r.historical_candidate_vendor_units_or_corporate_actions_certified -ne $false -or
    $r.original_market_files_or_previous_private_shards_modified -ne $false -or
    $r.private_active_pointer_modified -ne $false -or
    ($r.purchase_schema_historical_hypothesis_rows + $r.historical_native_raw_quarantined_rows) -ne 3682327) {
    throw 'Candidate receipt failed 37-year conservation/safety validation; DO NOT activate it.'
}
Write-Host "PASS: original 1990-2010 RAW classified: $($r.raw_1990_2010_h5_rows_preserved)"
Write-Host "Tentative purchase-schema historical rows: $($r.purchase_schema_historical_hypothesis_rows)"
Write-Host "Losslessly quarantined original historical rows: $($r.historical_native_raw_quarantined_rows)"
Write-Host "Pre-existing 2011-2026 physical rows referenced only: $($r.modern_2011_2026_accepted_private_rows)"
Write-Host 'NOT a vendor-certified/activated full-history DAY database.'
Write-Host "SAFE: $out"
