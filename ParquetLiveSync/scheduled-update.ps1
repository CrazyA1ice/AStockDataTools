param([switch]$IncludeClosedWeekMonth)
# Run only by an opt-in Windows task; H5 and original historical files protected.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
$python=Join-Path $repo '.venv\Scripts\python.exe'
$worker=Join-Path $module 'live_sync.py'
$three=Join-Path $module 'update_pipeline.py'
$private=Join-Path $module 'work'
New-Item -Path $private -ItemType Directory -Force | Out-Null
$log=Join-Path $private 'scheduled-update.log'
Start-Transcript -Path $log -Append | Out-Null
try {
    if(-not (Test-Path -LiteralPath $python -PathType Leaf)){throw 'ParquetLiveSync Python environment missing'}
    if(-not (Test-Path -LiteralPath 'D:\stock' -PathType Container)){throw 'Original D:\stock data root missing'}
    Write-Host ('START_LOCAL_PARQUET_DAILY_UPDATE='+(Get-Date).ToString('o'))
    if($IncludeClosedWeekMonth){
        Write-Host 'MODE=EXPLICIT_THREE_PERIOD_SCHEDULE; DAY_THEN_CLOSED_WEEK_MONTH'
        & $python -B $three --root 'D:\stock' --recent-days 90 --apply
        if($LASTEXITCODE -ne 0){throw 'Scheduled DAY/WEEK/MONTH pipeline failed; previous SHA-verified commits remain'}
        Write-Host 'PASS_SCHEDULED_THREE_PERIOD_PARQUET_PIPELINE'
    }else{
        Write-Host 'MODE=BACKWARD_COMPATIBLE_DAY_ONLY'
        & $python -B $worker --root 'D:\stock' --auto-recent-90-days --materialize-local-day
        if($LASTEXITCODE -ne 0){throw 'Scheduled DAY update failed; previously committed receipts remain'}
        Write-Host 'PASS_LOCAL_DAILY_PARQUET_UPDATE'
    }
} finally {Stop-Transcript | Out-Null}
