# Canonical Windows launcher for the established three-tab data manager.
# No test suite on every open, no scheduled-task installation or data writes.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$module = Split-Path -Parent $PSCommandPath
$repo = Split-Path -Parent $module
$python = Join-Path $repo '.venv\Scripts\python.exe'
$entry = Join-Path $module 'market_simple_desktop.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Python virtual environment missing: .venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) {
    throw 'Three-tab market data manager entry missing'
}
# PYTHONINSPECT=0 still enables the interactive >>> prompt in Python.
# Keep the GUI lifecycle noninteractive even if the parent shell inherited it.
Remove-Item Env:PYTHONINSPECT -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONSTARTUP -ErrorAction SilentlyContinue
& $python -u -B $entry
if ($LASTEXITCODE -ne 0) {
    throw ('Three-tab market data manager exited with code ' + $LASTEXITCODE)
}
