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
$stageRecords=[ordered]@{}
$transcribing=$false
$stageNames=@('EIGHT_PERIODS','FINANCIAL_DAILY','SECTORS','ADJUSTMENTS_ROTATING')
function Invoke-MarketStage {
    param([string]$Label,[string]$Script,[string[]]$Arguments)
    $stageLog=Join-Path $work ('afternoon-'+$chinaNow.ToString('yyyyMMdd-HHmmss')+'-'+$Label+'.log')
    $code=-1
    Write-Host ('MARKET_1630_STEP_START='+$Label)
    try {
        # Preserve full single-line JSON receipts from *this run*. Out-File
        # can word-wrap JSON using host width in Windows PowerShell 5.1.
        # A direct UTF-8 writer keeps the evidence lossless and streamed.
        $writer=[System.IO.StreamWriter]::new(
            $stageLog,$false,[System.Text.UTF8Encoding]::new($true))
        $savedErrorActionPreference=$ErrorActionPreference
        try {
            # Windows PowerShell 5.1 translates native-process STDERR into
            # nonterminating ErrorRecord objects after 2>&1. Under Stop,
            # even a harmless unittest progress line or an intermediate QMT
            # UTF-8 worker diagnostic aborts this stage before Python's own
            # retry/split logic can handle it. Capture both streams without
            # treating STDERR text as an exception; inspect process EXIT CODE.
            $ErrorActionPreference='Continue'
            & $engine -NoProfile -ExecutionPolicy Bypass -File $Script @Arguments 2>&1 |
                ForEach-Object {
                    $line=[string]$_
                    Write-Host $line
                    $writer.WriteLine($line)
                }
            $code=$LASTEXITCODE
        }finally{
            $ErrorActionPreference=$savedErrorActionPreference
            $writer.Dispose()
        }
        if($code -ne 0){throw ('Exit code '+$code)}
        [void]$completed.Add($Label)
        Write-Host ('MARKET_1630_STEP_DONE='+$Label)
    }catch{
        $msg=$Label+': '+$_.Exception.Message
        [void]$failures.Add($msg)
        Write-Host ('MARKET_1630_STEP_FAILED='+$msg)
    }finally{
        $stageRecords[$Label]=@{exit_code=[int]$code;log_path=$stageLog}
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
        format='qmt_daily_single_trigger_v3'
        status=$outcome
        outcome_meaning='Execution status only; see same-run validation evidence'
        mode='UNIFIED_SINGLE_RUN'
        started_local=$started
        finished_local=(Get-Date).ToString('o')
        china_start=$chinaNow.ToString('o')
        steps_expected=$stageNames
        steps_completed=@($completed.ToArray())
        stage_records=$stageRecords
        errors=@($failures.ToArray())
        validation=$null
        financial_complete_universe=$false
        adjustments_complete_universe=$false
        other_extra_multisource_verified=$false
        log_path=$log
    }
    # Verification is derived exclusively from current invocation stage logs.
    # Failure to parse NEVER creates a false PASS and never suppresses notice.
    $stepText='执行'+$completed.Count+'/'+$stageNames.Count+'；数据校验未验证；跨源验证未验证'
    try {
        New-Item -ItemType Directory -Path $work -Force | Out-Null
        $python=Join-Path $repo '.venv\Scripts\python.exe'
        $verifier=Join-Path $module 'market_daily_verification.py'
        $inputPath=Join-Path $work ('verification-input-'+$chinaNow.ToString('yyyyMMdd-HHmmss')+'.json')
        $verificationPath=Join-Path $work ('verification-'+$chinaNow.ToString('yyyyMMdd-HHmmss')+'.json')
        if(-not(Test-Path -LiteralPath $python -PathType Leaf) -or
           -not(Test-Path -LiteralPath $verifier -PathType Leaf)){
            throw 'Verification parser unavailable'
        }
        $result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $inputPath -Encoding UTF8
        $localConfig=Join-Path $work 'market_update\sources.local.json'
        $config=if(Test-Path -LiteralPath $localConfig -PathType Leaf){
            $localConfig
        }else{Join-Path $module 'market_sources.json'}
        & $python -B $verifier --run-json $inputPath --out-json $verificationPath --sources-config $config
        if($LASTEXITCODE -ne 0){throw ('Verification parser exit '+$LASTEXITCODE)}
        $verification=Get-Content -LiteralPath $verificationPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $result.validation=$verification
        $stepText=[string]$verification.notification_text
        # Stage exit 0 does NOT imply verification passed. Report PARTIAL
        # whenever current evidence identifies real quality issues.
        if($outcome -eq 'SUCCESS' -and
           ($verification.data_validation -in @('FAIL','PARTIAL') -or
            $verification.cross_validation -eq 'FAIL')){
            $outcome='PARTIAL'
            $result.status=$outcome
        }
        Write-Host ('MARKET_1630_DATA_VALIDATION='+$verification.data_validation)
        Write-Host ('MARKET_1630_CROSS_VALIDATION='+$verification.cross_validation)
    }catch{
        [void]$failures.Add('VERIFICATION: '+$_.Exception.Message)
        $outcome=if($completed.Count -gt 0){'PARTIAL'}else{'FAILED'}
        $result.status=$outcome
        $stepText+='；验证报告生成失败：'+$_.Exception.Message
        Write-Host ('MARKET_1630_VERIFICATION_FAILED='+$_.Exception.Message)
    }
    try {
        $result.errors=@($failures.ToArray())
        $result.finished_local=(Get-Date).ToString('o')
        $part=$status+'.part'
        $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $part -Encoding UTF8
        Move-Item -LiteralPath $part -Destination $status -Force
        Write-Host ('MARKET_1630_SUMMARY='+($result | ConvertTo-Json -Compress -Depth 12))
    }catch{
        [void]$failures.Add('STATUS_SAVE: '+$_.Exception.Message)
        $outcome=if($completed.Count -gt 0){'PARTIAL'}else{'FAILED'}
        $stepText+='；运行报告保存失败'
        Write-Host ('MARKET_1630_STATUS_WRITE_FAILED='+$_.Exception.Message)
    }
    if($transcribing){
        try {Stop-Transcript | Out-Null}
        catch {Write-Host ('MARKET_1630_TRANSCRIPT_STOP_FAILED='+$_.Exception.Message)}
    }
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
