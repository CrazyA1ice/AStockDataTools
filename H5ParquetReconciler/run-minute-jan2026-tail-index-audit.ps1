# Progress 2026 January without repeating the already verified 01-05..07 source scan.
# Exact purchased source keys are indexed ONCE for 01-08..31 (24 calendar days).
# Every rerun REUSES the finished existing index (never creates duplicate).
# Only the private key-only SQLite is writable; source Parquet/H5 are read-only.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$ensure=Join-Path $module 'tools\ensure-minute-key-index-window.py'
$audit=Join-Path $module 'tools\audit-minute-index-window-readonly.py'
$root='D:\stock'
$from='2026-01-08'
$through='2026-01-31'
foreach($f in @($py,$ensure,$audit)){
    if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing prerequisite: $f"}
}
$tests=@('test_preview_minute_exact_key_diff_readonly.py','test_build_minute_purchased_key_index.py','test_audit_minute_index_window_readonly.py','test_ensure_minute_key_index_window.py')
foreach($test in $tests){
    & $py -B -m unittest discover -s (Join-Path $module 'tests') -p $test -v
    if($LASTEXITCODE -ne 0){throw "Minute monthly-index synthetic tests FAILED: $test. Real market not accessed."}
}
Write-Host "===== Ensure source-key-only window $from..$through ====="
$json=& $py -B $ensure --root $root --from-day $from --through-day $through
if($LASTEXITCODE -ne 0){throw 'Source-key SQLite preparation failed. No original market write.'}
$idx=($json -join [Environment]::NewLine) | ConvertFrom-Json
if(-not (Test-Path -LiteralPath $idx.index_path -PathType Leaf)){throw 'Expected completed private SQLite index absent'}
Write-Host "Index status=$($idx.status); new_private_index_created=$($idx.new_private_index_created)"
Write-Host "Index=$($idx.index_path)"
Write-Host "Purchased OHLCVA copied=$($idx.purchased_ohlcva_rows_copied)"
Write-Host "===== Real month-tail 1min/5min H5 exact-key read-only audit ====="
& $py -B $audit --root $root --index $idx.index_path --from-day $from --through-day $through
if($LASTEXITCODE -ne 0){throw 'Month-tail minute audit FAILED, original Parquet/H5 unchanged; do not treat as accepted coverage'}
Write-Host 'PASS: Jan08-Jan31 purchased-source keys indexed/reused, exact H5-only candidates audited, ZERO vendor OHLCVA copies or new market files.'
