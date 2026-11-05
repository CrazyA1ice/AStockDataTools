# Locate existing 22274 H5 candidate source evidence without reading H5/Parquet.
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
Set-Location -LiteralPath $repo
$py=Join-Path $repo '.venv\Scripts\python.exe'
$tool=Join-Path $module 'tools\inspect-private-22274-existing-evidence-paths-readonly.py'
$tests=Join-Path $module 'tests'
$version='e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23'
if(-not (Test-Path -LiteralPath $py -PathType Leaf)){throw 'Python venv missing'}
& $py -B -m unittest discover -s $tests -p 'test_inspect_private_22274_existing_evidence_paths_readonly.py' -v
if($LASTEXITCODE -ne 0){throw 'Existing evidence locator tests failed'}
& $py -B $tool --version-sha256 $version --max-files 2500
if($LASTEXITCODE -ne 0){throw 'Existing 22274 source evidence discovery failed; no market data read'}
Write-Host 'PASS: registered private 22274 version source evidence paths enumerated; no data scans, no source writes, no production activation.'
