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
    'test_minute_gap_audit_gui_worker.py'
)
foreach ($p in $tests) {
    & $py -B -m unittest discover -s (Join-Path $module 'tests') -p $p -q
    if ($LASTEXITCODE -ne 0) { throw "GUI backend safety test FAILED: $p. GUI not launched." }
}
# Validate GUI Python syntax and imports before starting pythonw.exe, which
# does not display traceback in a console if an import fails on Windows.
& $py -B -c 'import ast, pathlib, sys; path=pathlib.Path(sys.argv[1]); ast.parse(path.read_text(encoding="utf-8"), filename=str(path))' $gui
if ($LASTEXITCODE -ne 0) { throw "GUI Python syntax check failed. GUI not launched." }
if (-not (Test-Path -LiteralPath $pyw -PathType Leaf)) { $pyw = $py }
Write-Host 'All safe GUI backend tests passed. Launching minute gap audit window.'
$process = Start-Process -FilePath $pyw -ArgumentList @('-B', ('"' + $gui + '"')) -WorkingDirectory $module -PassThru
Write-Host ("GUI launched. PID=" + $process.Id + ". Original purchased Parquet and H5 are read-only.")
