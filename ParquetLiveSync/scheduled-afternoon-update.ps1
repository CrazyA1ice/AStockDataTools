# One 16:30 China-time trigger -> market, finance, sectors, adjustments.
# No runtime deadline. Every finished run attempts user notification.
param(
    [switch]$Apply,
    [string]$Root = "D:\stock",
    [string]$FinanceDir = "D:\software\JHQMT\datadir\Finance",
    [ValidateRange(0,1000)][int]$AdjustmentStockLimit = 80,
    [ValidateRange(1,1095)][int]$FinanceLookbackDays = 120
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
$update=Join-Path $module 'update-market.ps1'
$finance=Join-Path $module 'run-qmt-financial-daily.ps1'
$notifier=Join-Path $module 'notify-market-update.ps1'
$work=Join-Path $module 'work'
$china=[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$chinaNow=[TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$china)
if(-not $Apply){
    Write-Host 'MARKET_1630_PREVIEW_ONLY=TRUE'
    Write-Host ('MARKET_1630_CHINA_NOW='+$chinaNow.ToString('o'))
    Write-Host 'MARKET_1630_MODE=UNIFIED_SINGLE_RUN'
    Write-Host 'MARKET_1630_SECTIONS=EIGHT_PERIODS,FINANCIAL_DAILY,SECTORS,ADJUSTMENTS_ROTATING'
    Write-Host 'MARKET_1630_FINANCIAL_RUNTIME_LIMIT=NONE'
    Write-Host 'MARKET_1630_WINDOWS_TASK_RUNTIME_LIMIT=NONE'
    Write-Host ('MARKET_1630_ADJUSTMENTS_PER_RUN_LIMIT='+$AdjustmentStockLimit)
    Write-Host 'MARKET_1630_NOTIFICATION=WINDOWS_DESKTOP_AFTER_ALL_OUTCOMES'
    Write-Host 'MARKET_1630_MULTISOURCE=EIGHT_PERIODS_ONLY;OTHER_TYPES_UNVERIFIED'
    return
}
$started=(Get-Date).ToString('o')
$log=Join-Path $work ('afternoon-'+$chinaNow.ToString('yyyyMMdd-HHmmss')+'.log')
$status=Join-Path $work 'last-afternoon-unified.json'
$engine=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$completed=New-Object System.Collections.ArrayList
$failures=New-Object System.Collections.ArrayList
$transcribing=$false
$stageNames=@('EIGHT_PERIODS','FINANCIAL_DAILY','SECTORS','ADJUSTMENTS_ROTATING')
function Invoke-MarketStage {
    param([string]$Label,[string]$Script,[string[]]$Arguments)
    Write-Host ('MARKET_1630_STEP_START='+$Label)
    try {
        & $engine -NoProfile -ExecutionPolicy Bypass -File $Script @Arguments
        if($LASTEXITCODE -ne 0){throw ('Exit code '+$LASTEXITCODE)}
        [void]$completed.Add($Label)
        Write-Host ('MARKET_1630_STEP_DONE='+$Label)
    }catch{
        $msg=$Label+': '+$_.Exception.Message
        [void]$failures.Add($msg)
        Write-Host ('MARKET_1630_STEP_FAILED='+$msg)
    }
}
try {
    # Detached worktrees have divergent private state; never use them for Apply.
    if(-not(Test-Path -LiteralPath (Join-Path $repo '.git') -PathType Container)){
        throw 'READONLY_PREVIEW_WORKTREE: Apply requires canonical checkout'
    }
    foreach($relative in @('market_update\commits.json','qmt_extra\progress.json',
                           'qmt_extra\financial-cache-progress.json')){
        $file=Join-Path $work $relative
        if(-not(Test-Path -LiteralPath $file -PathType Leaf)){
            throw ('Missing canonical private state: '+$file)
        }
    }
    foreach($file in @($update,$finance,$notifier)){
        if(-not(Test-Path -LiteralPath $file -PathType Leaf)){
            throw ('Missing unified market component: '+$file)
        }
    }
    if(-not(Test-Path -LiteralPath (Join-Path $repo '.venv\Scripts\python.exe') -PathType Leaf)){
        throw 'Missing project Python'
    }
    if(-not(Test-Path -LiteralPath (Join-Path $Root 'AllCycleAStockData\1min') -PathType Container)){
        throw 'Missing original physical market dataset'
    }
    if(Test-Path -LiteralPath (Join-Path $work 'qmt_extra\schedule-enabled.json') -PathType Leaf){
        throw 'Legacy extras schedule opt-in exists: refuse overlap'
    }
    New-Item -ItemType Directory -Path $work -Force | Out-Null
    Start-Transcript -Path $log -ErrorAction Stop | Out-Null
    $transcribing=$true
    Set-Location -LiteralPath $repo
    Write-Host ('MARKET_1630_CHINA_NOW='+$chinaNow.ToString('o'))
    Write-Host 'MARKET_1630_MODE=UNIFIED_SINGLE_RUN'
    # Each source is verified by its own pipeline. No second scheduled retry.
    # Failure in an independent stage is captured; other stages still run.
    Invoke-MarketStage -Label 'EIGHT_PERIODS' -Script $update -Arguments @('-Mode','auto','-Root',$Root)
    Invoke-MarketStage -Label 'FINANCIAL_DAILY' -Script $finance -Arguments @('-Root',$Root,'-FinanceDir',$FinanceDir,'-LookbackDays',[string]$FinanceLookbackDays)
    Invoke-MarketStage -Label 'SECTORS' -Script $update -Arguments @('-Mode','extras','-Root',$Root,'-ExtraSection','sectors','-ExtraStockLimit','1','-ExtraAssetLimit','0')
    $start=$chinaNow.Date.AddDays(-30).ToString('yyyy-MM-dd')
    Invoke-MarketStage -Label 'ADJUSTMENTS_ROTATING' -Script $update -Arguments @('-Mode','extras','-Root',$Root,'-ExtraSection','adjustments','-ExtraStockLimit',[string]$AdjustmentStockLimit,'-ExtraAssetLimit','0','-ExtraStart',$start)
}catch{
    [void]$failures.Add('RUNNER: '+$_.Exception.Message)
    Write-Host ('MARKET_1630_RUNNER_FAILED='+$_.Exception.Message)
}finally{
    if($failures.Count -eq 0 -and $completed.Count -eq $stageNames.Count){
        $outcome='SUCCESS'
    }elseif($completed.Count -gt 0){
        $outcome='PARTIAL'
    }else{
        $outcome='FAILED'
    }
    $result=[ordered]@{
        format='qmt_daily_single_trigger_v2'
        status=$outcome
        outcome_meaning='Step execution only; source completeness remains unverified'
        mode='UNIFIED_SINGLE_RUN'
        started_local=$started
        finished_local=(Get-Date).ToString('o')
        china_start=$chinaNow.ToString('o')
        steps_expected=$stageNames
        steps_completed=@($completed.ToArray())
        errors=@($failures.ToArray())
        financial_complete_universe=$false
        adjustments_complete_universe=$false
        other_extra_multisource_verified=$false
        log_path=$log
    }
    try {
        New-Item -ItemType Directory -Path $work -Force | Out-Null
        $part=$status+'.part'
        $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $part -Encoding UTF8
        Move-Item -LiteralPath $part -Destination $status -Force
        Write-Host ('MARKET_1630_SUMMARY='+($result | ConvertTo-Json -Compress -Depth 6))
    }catch{
        [void]$failures.Add('STATUS_SAVE: '+$_.Exception.Message)
        $outcome=if($completed.Count -gt 0){'PARTIAL'}else{'FAILED'}
        Write-Host ('MARKET_1630_STATUS_WRITE_FAILED='+$_.Exception.Message)
    }
    if($transcribing){
        try {Stop-Transcript | Out-Null}
        catch {Write-Host ('MARKET_1630_TRANSCRIPT_STOP_FAILED='+$_.Exception.Message)}
    }
    $stepText='K线/财务/板块/除权 已完成 '+$completed.Count+'/'+$stageNames.Count+' 项'
    if($failures.Count){$stepText+='；失败：'+($failures -join '; ')}
    else{$stepText+='；注意：全市场覆盖与全部跨源一致性仍待核实'}
    try {
        if(-not(Test-Path -LiteralPath $notifier -PathType Leaf)){
            throw 'Notification script missing'
        }
        & $engine -NoProfile -ExecutionPolicy Bypass -File $notifier -Status $outcome -Summary $stepText -LogPath $log
        if($LASTEXITCODE -ne 0){throw ('Notification exit '+$LASTEXITCODE)}
        Write-Host 'MARKET_1630_USER_NOTIFICATION_ATTEMPTED=TRUE'
    }catch{
        Write-Host ('MARKET_1630_USER_NOTIFICATION_FAILED='+$_.Exception.Message)
    }
}
if($failures.Count){throw ('Market daily update failed: '+($failures -join '; '))}
