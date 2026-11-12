param([switch]$IncludeClosedWeekMonth)
# Opt-in Windows scheduled updates; last-run status is visible in the simple GUI.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
$python=Join-Path $repo '.venv\Scripts\python.exe'
$day=Join-Path $module 'live_sync.py'
$three=Join-Path $module 'update_pipeline.py'
$private=Join-Path $module 'work'
New-Item -Path $private -ItemType Directory -Force | Out-Null
$log=Join-Path $private 'scheduled-update.log'
$status=Join-Path $private 'last-scheduled-run.json'
$mode=if($IncludeClosedWeekMonth){'DAY_WEEK_MONTH'}else{'DAY_ONLY'}
$started=(Get-Date).ToString('o')
function Write-PrivateScheduleStatus {
    param([string]$Status,[string]$Message)
    $body=[ordered]@{
        format='parquet_live_sync_scheduled_run_v1'
        status=$Status
        mode=$mode
        start_time_local=$started
        finished_time_local=(Get-Date).ToString('o')
        message=$Message
        log_path=$log
    }
    $temp=$status+'.part'
    $body | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $status -Force
}
Start-Transcript -Path $log -Append | Out-Null
try {
    Write-Host ('START_LOCAL_PARQUET_DAILY_UPDATE='+$started+' MODE='+$mode)
    if(-not (Test-Path -LiteralPath $python -PathType Leaf)){throw 'Local Parquet Python environment missing'}
    if(-not (Test-Path -LiteralPath 'D:\stock' -PathType Container)){throw 'Local D:\stock dataset root missing'}
    if($IncludeClosedWeekMonth) {
        & $python -B $three --root 'D:\stock' --recent-days 90 --apply
        if($LASTEXITCODE -ne 0){throw ('DAY/WEEK/MONTH Python pipeline exited with '+$LASTEXITCODE)}
        Write-Host 'PASS_SCHEDULED_THREE_PERIOD_PARQUET_PIPELINE'
    } else {
        & $python -B $day --root 'D:\stock' --auto-recent-90-days --materialize-local-day
        if($LASTEXITCODE -ne 0){throw ('DAY Python pipeline exited with '+$LASTEXITCODE)}
        Write-Host 'PASS_LOCAL_DAILY_PARQUET_UPDATE'
    }
    Write-PrivateScheduleStatus -Status 'SUCCESS' -Message '已完成并保留完整运行日志'
} catch {
    $message=$_.Exception.Message
    Write-Host ('FAILED_SCHEDULED_PARQUET_PIPELINE '+$message)
    Write-PrivateScheduleStatus -Status 'FAILED' -Message $message
    throw
} finally {
    Stop-Transcript | Out-Null
}
