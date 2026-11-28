# Single supported Windows GUI launcher: market_update_dashboard.py.
# Do not run the full offline test suite or require unrelated historical
# Parquet manifests on every launch. Manual data writes remain guarded by
# the dashboard and its shared scheduled-afternoon-update.ps1 runner.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$module = Split-Path -Parent $PSCommandPath
$repo = Split-Path -Parent $module
$python = Join-Path $repo '.venv\Scripts\python.exe'
$dashboard = Join-Path $module 'market_update_dashboard.py'
if(-not (Test-Path -LiteralPath $python -PathType Leaf)){throw 'MARKET_GUI_PROJECT_VENV_MISSING'}
if(-not (Test-Path -LiteralPath $dashboard -PathType Leaf)){throw 'MARKET_GUI_DASHBOARD_MISSING'}
Write-Host 'MARKET_GUI_CANONICAL=market_update_dashboard.py'
& $python -u -B $dashboard
if($LASTEXITCODE -ne 0){throw 'MARKET_GUI_EXIT_FAILED'}
