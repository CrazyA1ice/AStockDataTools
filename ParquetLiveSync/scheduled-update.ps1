# Unified eight-period Windows Task Scheduler entry, under the logged-in QMT user.
# Does NOT install anything; use install-schedule.ps1 -Action Install explicitly.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
$runner=Join-Path $module 'update-market.ps1'
$workspace=Join-Path $module 'work'
if(-not (Test-Path -LiteralPath $workspace -PathType Container)){
    New-Item -Path $workspace -ItemType Directory -Force | Out-Null
}
$log=Join-Path $workspace 'scheduled-update.log'
$status=Join-Path $workspace 'last-scheduled-run.json'
$started=(Get-Date).ToString('o')
function Save-RunStatus {
    param([string]$State,[string]$Details)
    $result=[ordered]@{
        format='all_eight_cycle_scheduled_update_v1'
        status=$State
        started_local=$started
        ended_local=(Get-Date).ToString('o')
        command=$runner
        message=$Details
        log_path=$log
        QMT_session_required=$true
    }
    $temp=$status+'.part'
    $result | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $status -Force
}
Start-Transcript -Path $log -Append | Out-Null
try{
    Write-Host ('MARKET_SCHEDULE_RUN_START='+$started)
    if(-not (Test-Path -LiteralPath $runner -PathType Leaf)){
        throw 'Unified market updater missing'
    }
    if(-not (Test-Path -LiteralPath 'D:\stock\AllCycleAStockData\1min' -PathType Container)){
        throw 'Original market data storage missing'
    }
    $engine=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    & $engine -NoProfile -ExecutionPolicy Bypass -File $runner -Mode auto
    if($LASTEXITCODE -ne 0){throw ('Unified eight-cycle market updater failed with exit '+$LASTEXITCODE)}
    Write-Host 'MARKET_SCHEDULE_ALL_EIGHT_CYCLE_SUCCESS'
    # Explicit local opt-in only, after QMT extras have passed Windows
    # real-data preflight. This is the SAME task, not a second scheduler.
    $extrasOptIn=Join-Path $module 'work\qmt_extra\schedule-enabled.json'
    $extrasRan=$false
    if(Test-Path -LiteralPath $extrasOptIn -PathType Leaf){
        $opt=Get-Content -LiteralPath $extrasOptIn -Raw -Encoding UTF8 | ConvertFrom-Json
        if($opt.format -ne 'qmt_extra_schedule_v1' -or
           $opt.stock_limit -isnot [int] -or $opt.stock_limit -lt 1 -or $opt.stock_limit -gt 1000 -or
           $opt.asset_limit -isnot [int] -or $opt.asset_limit -lt 1 -or $opt.asset_limit -gt 100 -or
           [string]$opt.start -notmatch '^20[0-9]{2}-[01][0-9]-[0-3][0-9]
}catch{
    $reason=$_.Exception.Message
    Write-Host ('MARKET_SCHEDULE_RUN_FAILED='+$reason)
    Save-RunStatus -State 'FAILED' -Details $reason
    throw
}finally{
    Stop-Transcript | Out-Null
}
){
            throw 'Invalid QMT extras schedule opt-in; no extra downloads started'
        }
        & $engine -NoProfile -ExecutionPolicy Bypass -File $runner -Mode extras -ExtraStart ([string]$opt.start) -ExtraStockLimit ([int]$opt.stock_limit) -ExtraAssetLimit ([int]$opt.asset_limit)
        if($LASTEXITCODE -ne 0){throw ('Optional QMT extra data batch failed with exit '+$LASTEXITCODE)}
        $extrasRan=$true
        Write-Host 'MARKET_SCHEDULE_QMT_EXTRA_BATCH_SUCCESS'
    }
    $detail=if($extrasRan){'Eight periods and opted-in QMT extras batch finished'}else{'Eight periods finished; QMT extras not enabled'}
    Save-RunStatus -State 'SUCCESS' -Details $detail
}catch{
    $reason=$_.Exception.Message
    Write-Host ('MARKET_SCHEDULE_RUN_FAILED='+$reason)
    Save-RunStatus -State 'FAILED' -Details $reason
    throw
}finally{
    Stop-Transcript | Out-Null
}
