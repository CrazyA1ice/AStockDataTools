# Use an EXISTING checked purchased-minute SQLite index to audit several days.
# Pure read-only audit; does not scan purchased Parquet bars or create any
# additional index, H5 output, Parquet, CSV, or JSON.
param([string]$FromDay='2026-01-05',[string]$ThroughDay='2026-01-07',[string]$Index='')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\audit-minute-index-window-readonly.py'
$root='D:\stock'
foreach($f in @($py,$tool)){
    if(-not (Test-Path -LiteralPath $f -PathType Leaf)){throw "Missing readonly indexed-audit requirement: $f"}
}
$test='test_audit_minute_index_window_readonly.py'
& $py -B -m unittest discover -s (Join-Path $module 'tests') -p $test -v
if($LASTEXITCODE -ne 0){throw 'New 4-test indexed-audit regression failed; real-market audit not started'}
if([string]::IsNullOrWhiteSpace($Index)){
    $dir=Join-Path $module 'work\unified_parquet\minute_key_index'
    if(-not (Test-Path -LiteralPath $dir -PathType Container)){throw 'No prebuilt private key index. First run the existing bounded index builder.'}
    $matches=@(Get-ChildItem -LiteralPath $dir -Filter "purchased-minute-keys-$FromDay-$ThroughDay-*.sqlite" -File)
    if($matches.Count -ne 1){throw "Expected EXACTLY one prebuilt key index for $FromDay..$ThroughDay, found $($matches.Count). Use -Index to select an existing file (no new index is built)."}
    $Index=$matches[0].FullName
}
if(-not (Test-Path -LiteralPath $Index -PathType Leaf)){throw "Key index file missing: $Index"}
Write-Host "===== Reusing existing key index (no purchased Parquet scan) ====="
Write-Host $Index
& $py -B $tool --root $root --index $Index --from-day $FromDay --through-day $ThroughDay
if($LASTEXITCODE -ne 0){throw 'Read-only multi-day indexed minute diff FAILED; source files remain unchanged'}
Write-Host 'PASS: multi-day exact minute-key audit reused prebuilt index; 0 purchased bars copied and 0 market files written.'
