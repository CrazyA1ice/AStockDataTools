# Canonical Windows launcher for the existing three-tab market data manager.
# Normal startup runs NO tests. -QuickCheck is an explicit, offline-only smoke test.
param(
    [switch]$QuickCheck,
    [string]$PythonPath = '',
    [string]$ReviewMainRepo = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$module = Split-Path -Parent $PSCommandPath
$repo = Split-Path -Parent $module
$python = if ($PythonPath) { $PythonPath } else { Join-Path $repo '.venv\Scripts\python.exe' }
$entry = Join-Path $module 'market_simple_desktop.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Python virtual environment missing: .venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) {
    throw 'Three-tab market data manager entry missing'
}
# PYTHONINSPECT=0 is still interpreted as true by Python. Avoid >>> on exit.
Remove-Item Env:PYTHONINSPECT -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONSTARTUP -ErrorAction SilentlyContinue
if ($QuickCheck) {
    # No QMT API, no financial writes, no scheduling. Synthetic tests only.
    $tests = Join-Path $module 'tests'
    if (-not (Test-Path -LiteralPath $tests -PathType Container)) {
        throw 'Focused GUI test directory missing'
    }
    $oldPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
    try {
        $env:PYTHONPATH = if ($oldPythonPath) { $module + ';' + $oldPythonPath } else { $module }
        & $python -u -B -m unittest discover -s $tests -p 'test_market_center_simple_desktop.py' -q
        if ($LASTEXITCODE -ne 0) { throw 'Three-tab GUI focused synthetic tests FAILED' }
        & $python -u -B -m unittest discover -s $tests -p 'test_qmt_extra_data.py' -k table_probe -k probe_cli -k valid_probe_cli -k probe_version_missing -q
        if ($LASTEXITCODE -ne 0) { throw 'QMT table probe focused synthetic tests FAILED' }
        Write-Host 'QUICK_GUI_CHECK_PASS: GUI + QMT nine-table read-only mock tests'
    }
    finally {
        [Environment]::SetEnvironmentVariable('PYTHONPATH', $oldPythonPath, 'Process')
    }
    return
}
# The review path reads only the canonical checkout's existing work/ ledgers.
# It MUST run from a detached .git-file worktree; all writer buttons are blocked.
if ($ReviewMainRepo) {
    if ($QuickCheck) { throw 'QuickCheck and ReviewMainRepo are separate modes' }
    if (-not (Test-Path -LiteralPath (Join-Path $repo '.git') -PathType Leaf)) {
        throw 'Read-only review requires a detached worktree'
    }
    $main = (Resolve-Path -LiteralPath $ReviewMainRepo -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath (Join-Path $main '.git') -PathType Container)) {
        throw 'Canonical main checkout not found'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $main 'ParquetLiveSync\work') -PathType Container)) {
        throw 'Canonical market-work ledger directory not found'
    }
    $oldReview = [Environment]::GetEnvironmentVariable('ASTOCK_GUI_REVIEW_REPO', 'Process')
    try {
        $env:ASTOCK_GUI_REVIEW_REPO = $main
        & $python -u -B $entry
        if ($LASTEXITCODE -ne 0) {
            throw ('Read-only three-tab review exited with code ' + $LASTEXITCODE)
        }
    }
    finally {
        [Environment]::SetEnvironmentVariable(
            'ASTOCK_GUI_REVIEW_REPO', $oldReview, 'Process')
    }
    return
}
# Normal path is unchanged, always one GUI and no tests.
& $python -u -B $entry
if ($LASTEXITCODE -ne 0) {
    throw ('Three-tab market data manager exited with code ' + $LASTEXITCODE)
}
