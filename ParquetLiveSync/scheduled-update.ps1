# Run only by an opt-in Windows task; H5/purchased market sources remain read-only.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
$python=Join-Path $repo '.venv\Scripts\python.exe'
$worker=Join-Path $module 'live_sync.py'
$private=Join-Path $module 'work'
New-Item -Path $private -ItemType Directory -Force | Out-Null
$log=Join-Path $private 'scheduled-update.log'
Start-Transcript -Path $log -Append | Out-Null
try {
    if(-not (Test-Path -LiteralPath $python -PathType Leaf)){throw 'ParquetLiveSync Python environment missing'}
    if(-not (Test-Path -LiteralPath 'D:\stock' -PathType Container)){throw 'Original D:\stock data root missing'}
    Write-Host ('START_LOCAL_PARQUET_DAILY_UPDATE='+(Get-Date).ToString('o'))
    & $python -B $worker --root 'D:\stock' --auto-recent-90-days --materialize-local-day
    if($LASTEXITCODE -ne 0){throw 'Scheduled DAY update failed; previously committed receipts remain'}
    Write-Host 'PASS_LOCAL_DAILY_PARQUET_UPDATE'
} finally {Stop-Transcript | Out-Null}
