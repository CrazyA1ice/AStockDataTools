# Safe read-only minute-gap GUI launcher, ASCII for Windows PowerShell 5.1.
# This launcher NEVER starts the retired full-minute Parquet copy worker.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$module = Split-Path -Parent $PSCommandPath
$repo = Split-Path -Parent $module
$py = Join-Path $repo '.venv\Scripts\python.exe'
$pyw = Join-Path $repo '.venv\Scripts\pythonw.exe'
$gui = Join-Path $module 'tools\minute-gap-audit-gui.py'
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) { throw "Project Python venv missing: $py" }
if (-not (Test-Path -LiteralPath $gui -PathType Leaf)) { throw "Safe minute audit GUI missing: $gui" }
$tests = @(
    'test_preview_minute_exact_key_diff_readonly.py',
    'test_build_minute_purchased_key_index.py',
    'test_audit_minute_index_window_readonly.py',
    'test_ensure_minute_key_index_window.py',
    'test_minute_gap_audit_gui_worker.py',
    'test_historical_daily_h5_coverage_gui.py'
)
foreach ($p in $tests) {
    & $py -B -m unittest discover -s (Join-Path $module 'tests') -p $p -q
    if ($LASTEXITCODE -ne 0) { throw "GUI backend safety test FAILED: $p. GUI not launched." }
}
# Windows PowerShell 5.1 strips embedded quotes from Python -c strings.
# Execute a real .py preflight instead of passing code through native args.
$preflight = Join-Path $module 'tools\preflight-minute-gap-audit-gui.py'
if (-not (Test-Path -LiteralPath $preflight -PathType Leaf)) { throw "Missing GUI preflight script: $preflight" }
& $py -B $preflight --gui $gui
if ($LASTEXITCODE -ne 0) { throw "GUI Python UTF-8 syntax/import preflight failed. GUI not launched." }
if (-not (Test-Path -LiteralPath $pyw -PathType Leaf)) { $pyw = $py }
Write-Host 'All safe GUI backend tests passed. Launching minute gap audit window.'
$process = Start-Process -FilePath $pyw -ArgumentList @('-B', ('"' + $gui + '"')) -WorkingDirectory $module -PassThru
Write-Host ("GUI launched. PID=" + $process.Id + ". Original purchased Parquet and H5 are read-only.")
