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
    # Opt-in extra QMT data in the SAME existing task, only after on-host
    # read-only/physical validation. Absent config keeps old eight-period job.
    $optPath=Join-Path $module 'work\qmt_extra\schedule-enabled.json'
    $extraRan=$false
    if(Test-Path -LiteralPath $optPath -PathType Leaf){
        $opt=Get-Content -LiteralPath $optPath -Raw -Encoding UTF8 | ConvertFrom-Json
        [int]$stocks=0
        [int]$assets=0
        if($opt.format -ne 'qmt_extra_schedule_v1' -or
           -not [int]::TryParse([string]$opt.stock_limit,[ref]$stocks) -or
           -not [int]::TryParse([string]$opt.asset_limit,[ref]$assets) -or
           $stocks -lt 1 -or $stocks -gt 1000 -or
           $assets -lt 1 -or $assets -gt 100){
            throw 'Invalid QMT extras opt-in batch size; no supplementary downloads run'
        }
        $start=[string]$opt.start
        try{
            [void][datetime]::ParseExact($start,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture)
        }catch{
            throw 'Invalid QMT extras opt-in start date'
        }
        & $engine -NoProfile -ExecutionPolicy Bypass -File $runner -Mode extras -ExtraStart $start -ExtraStockLimit $stocks -ExtraAssetLimit $assets
        if($LASTEXITCODE -ne 0){
            throw ('QMT extras batch failed with exit '+$LASTEXITCODE)
        }
        $extraRan=$true
        Write-Host 'MARKET_SCHEDULE_QMT_EXTRA_BATCH_SUCCESS'
    }
    $details=if($extraRan){'Eight-period updater and QMT extras batch finished'}else{'Eight-period updater finished; QMT extras disabled'}
    Save-RunStatus -State 'SUCCESS' -Details $details
}catch{
    $reason=$_.Exception.Message
    Write-Host ('MARKET_SCHEDULE_RUN_FAILED='+$reason)
    Save-RunStatus -State 'FAILED' -Details $reason
    throw
}finally{
    Stop-Transcript | Out-Null
}
