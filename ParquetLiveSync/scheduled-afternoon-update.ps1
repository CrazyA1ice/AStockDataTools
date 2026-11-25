# One 20:05 China-time trigger -> K-lines, sectors, adjustments, finance LAST.
# Finance has a nightly deadline; completed runs attempt durable WeCom push.
param(
    [switch]$Apply,
    [string]$Root = "D:\stock",
    [string]$FinanceDir = "D:\software\JHQMT\datadir\Finance",
    [ValidateRange(0,1000)][int]$AdjustmentStockLimit = 80,
    [ValidateRange(1,10000)][int]$FinanceDailyStockLimit = 200,
    [ValidateRange(1,1095)][int]$FinanceLookbackDays = 120,
    [ValidateSet('Scheduled','Manual')][string]$Invocation = 'Scheduled',
    [switch]$HistoryOnly
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$module=Split-Path -Parent $PSCommandPath
$repo=Split-Path -Parent $module
$update=Join-Path $module 'update-market.ps1'
$catchup=Join-Path $module 'run-market-catchup.ps1'
$finance=Join-Path $module 'run-qmt-financial-daily.ps1'
$notifier=Join-Path $module 'notify-market-update.ps1'
$qmtProbe=Join-Path $module 'qmt_connect_preflight.py'
$work=Join-Path $module 'work'
$china=[TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$chinaNow=[TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$china)
if(-not $Apply){
    Write-Host 'MARKET_1630_PREVIEW_ONLY=TRUE'
    Write-Host ('MARKET_1630_CHINA_NOW='+$chinaNow.ToString('o'))
    Write-Host ('MARKET_2005_RUN_START_CHINA='+$chinaNow.ToString('o'))
    Write-Host 'MARKET_1630_MODE=UNIFIED_SINGLE_RUN'
    Write-Host 'MARKET_1630_SECTIONS=EIGHT_PERIODS,SECTORS,ADJUSTMENTS_ROTATING,FINANCIAL_DAILY'
    Write-Host 'MARKET_1630_FINANCIAL_RUNTIME_LIMIT=40_MINUTES_MAX; HARD_NIGHTLY_CUTOFF=23:20_CHINA'
    Write-Host 'MARKET_1630_WINDOWS_TASK_RUNTIME_LIMIT=NONE'
    Write-Host ('MARKET_1630_ADJUSTMENTS_PER_RUN_LIMIT='+$AdjustmentStockLimit)
    Write-Host ('MARKET_1630_FINANCE_DAILY_MAX_SYMBOLS='+$FinanceDailyStockLimit)
    Write-Host 'MARKET_1630_FINANCE_FULL_UNIVERSE_DAILY=FALSE'
    Write-Host 'MARKET_1630_NOTIFICATION=WECOM_CHUNKED_PUSH_AFTER_ALL_OUTCOMES; WINDOWS_TOAST_DISABLED'
    Write-Host 'MARKET_1630_MULTISOURCE=EIGHT_PERIODS_ONLY;OTHER_TYPES_UNVERIFIED'
    return
}
# Do not replay a missed 20:05 scheduled job after the user's shutdown time.
# Manual HistoryOnly remains explicitly available for daytime recovery.
if($Invocation -eq 'Scheduled' -and
   ($chinaNow.TimeOfDay -lt (New-TimeSpan -Hours 20 -Minutes 5) -or
    $chinaNow.TimeOfDay -ge (New-TimeSpan -Hours 23 -Minutes 20) -or
    (Get-Date).TimeOfDay -ge (New-TimeSpan -Hours 23 -Minutes 20))){
    Write-Host 'MARKET_2005_SCHEDULED_OUTSIDE_EVENING_WINDOW_NO_EXECUTION=TRUE'
    return
}
# Shared named mutex: Task Scheduler IgnoreNew alone does not protect manual GUI runs.
# Fail closed if the scheduled task or another manual invocation already owns it.
$runMutex=[System.Threading.Mutex]::new($false,'Local\AStockDataTools2005AllStages')
$runMutexHeld=$false
try {
    try {$runMutexHeld=$runMutex.WaitOne(0)}
    catch [System.Threading.AbandonedMutexException] {$runMutexHeld=$true}
    if(-not $runMutexHeld){
        Write-Host 'MARKET_2005_ALREADY_RUNNING=TRUE'
        exit 9
    }
    Write-Host ('MARKET_2005_MUTEX_ACQUIRED=TRUE invocation='+$Invocation)
# Delayed StartWhenAvailable tasks can start the NEXT morning, before 20:05.
# They may resume accepted old market days, but never fetch the current day's
# finance/sectors/adjustments before the user-defined nightly cutoff.
if($chinaNow.TimeOfDay -lt (New-TimeSpan -Hours 20 -Minutes 5)){
    $HistoryOnly=$true
    Write-Host 'MARKET_2005_PRE_CUTOFF_HISTORY_ONLY=TRUE'
}
$started=(Get-Date).ToString('o')
$log=Join-Path $work ('afternoon-'+$chinaNow.ToString('yyyyMMdd-HHmmss')+'.log')
$status=Join-Path $work $(if($HistoryOnly){'last-precutoff-market-only.json'}else{'last-afternoon-unified.json'})
$engine=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$completed=New-Object System.Collections.ArrayList
$failures=New-Object System.Collections.ArrayList
$stageRecords=[ordered]@{}
$financeDeferred=$false
$transcribing=$false
$qmtPreflightStatus='NOT_RUN'
$qmtPreflightAttempts=0
$stageNames=@('EIGHT_PERIODS','SECTORS','ADJUSTMENTS_ROTATING','FINANCIAL_DAILY')
if($HistoryOnly){$stageNames=@('EIGHT_PERIODS')}
$runScope=if($HistoryOnly){'MARKET_HISTORY_ONLY_PRE_2005'}else{'ALL_FOUR_SECTIONS'}
function Invoke-MarketStage {
    param([string]$Label,[string]$Script,[string[]]$Arguments)
    $stageLog=Join-Path $work ('afternoon-'+$chinaNow.ToString('yyyyMMdd-HHmmss')+'-'+$Label+'.log')
    $code=-1
    Write-Host ('MARKET_1630_STEP_START='+$Label)
    Write-Host ('MARKET_2005_STEP_START='+$Label)
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
        Write-Host ('MARKET_2005_STEP_DONE='+$Label)
    }catch{
        $msg=$Label+': '+$_.Exception.Message
        [void]$failures.Add($msg)
        Write-Host ('MARKET_1630_STEP_FAILED='+$msg)
        Write-Host ('MARKET_2005_STEP_FAILED='+$msg)
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
    foreach($file in @($update,$catchup,$finance,$notifier,$qmtProbe)){
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
    # QMT can be visible on Windows while its xtquant service is not yet
    # ready (for example after StartWhenAvailable replay). Do not run any
    # data stage until this independent, one-attempt child probe succeeds.
    # The child has its own 25-second hard timeout; six attempts are bounded
    # and the waits between attempts are exactly 10 seconds.
    $qmtPreflightStatus='CONNECTING'
    $python=Join-Path $repo '.venv\Scripts\python.exe'
    for($attempt=1;$attempt -le 6;$attempt++){
        $qmtPreflightAttempts=$attempt
        Write-Host ('MARKET_2005_QMT_PREFLIGHT_ATTEMPT='+$attempt+'/6')
        $code=-1
        $savedErrorActionPreference=$ErrorActionPreference
        try {
            # PowerShell 5.1 treats native stderr as ErrorRecord. The vendor
            # emits expected failures there; only the EXIT CODE is decisive.
            $ErrorActionPreference='Continue'
            & $python -u -B $qmtProbe --timeout-seconds 25 2>&1 |
                ForEach-Object {Write-Host ([string]$_)}
            $code=$LASTEXITCODE
        }finally{
            $ErrorActionPreference=$savedErrorActionPreference
        }
        if($code -eq 0){
            $qmtPreflightStatus='CONNECTED'
            Write-Host ('MARKET_2005_QMT_PREFLIGHT_CONNECTED_ATTEMPT='+$attempt)
            break
        }
        Write-Host ('MARKET_2005_QMT_PREFLIGHT_RETRYABLE_EXIT='+$code)
        if($attempt -lt 6){
            Write-Host 'MARKET_2005_QMT_PREFLIGHT_SLEEP_SECONDS=10'
            Start-Sleep -Seconds 10
        }
    }
    if($qmtPreflightStatus -ne 'CONNECTED'){
        $qmtPreflightStatus='QMT_SERVICE_UNAVAILABLE'
        Write-Host 'MARKET_2005_QMT_SERVICE_UNAVAILABLE=TRUE'
        throw 'QMT_SERVICE_UNAVAILABLE: xtquant get_client did not connect after six bounded attempts; no update stages executed'
    }
    # A slow QMT startup must not create an after-midnight scheduled run.
    $afterQmtProbe=[TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$china)
    if($Invocation -eq 'Scheduled' -and
       ($afterQmtProbe.TimeOfDay -ge (New-TimeSpan -Hours 23 -Minutes 20) -or
        (Get-Date).TimeOfDay -ge (New-TimeSpan -Hours 23 -Minutes 20))){
        throw 'EVENING_CUTOFF_REACHED_AFTER_QMT_PREFLIGHT_NO_STAGES_EXECUTED'
    }
    # Each source is verified by its own pipeline. No second scheduled retry.
    # Failure in an independent stage is captured; other stages still run.
    # Market/sector/adjustment updates should not wait for a long or
    # quarantined financial vendor scan. Run financial LAST; preserve the
    # existing one-trigger schedule and all private stock-level cursors.
    Invoke-MarketStage -Label 'EIGHT_PERIODS' -Script $catchup -Arguments @('-Root',$Root)
    if(-not $HistoryOnly){
        Invoke-MarketStage -Label 'SECTORS' -Script $update -Arguments @('-Mode','extras','-Root',$Root,'-ExtraSection','sectors','-ExtraStockLimit','1','-ExtraAssetLimit','0')
        $start=$chinaNow.Date.AddDays(-30).ToString('yyyy-MM-dd')
        Invoke-MarketStage -Label 'ADJUSTMENTS_ROTATING' -Script $update -Arguments @('-Mode','extras','-Root',$Root,'-ExtraSection','adjustments','-ExtraStockLimit',[string]$AdjustmentStockLimit,'-ExtraAssetLimit','0','-ExtraStart',$start)
        # Finance always runs after K-lines, sectors and adjustments. It may
        # continue the next evening instead of running while the PC is shut
        # down. A 5m buffer covers the importer's single 180s worker call.
        $beforeFinance=[TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$china)
        $financeStop=$beforeFinance.Date.AddHours(23).AddMinutes(20)
        $localBeforeFinance=Get-Date
        $localFinanceStop=$localBeforeFinance.Date.AddHours(23).AddMinutes(20)
        $financeMinutes=[int][Math]::Floor([Math]::Min(
            ($financeStop-$beforeFinance).TotalMinutes,
            ($localFinanceStop-$localBeforeFinance).TotalMinutes))-5
        if($financeMinutes -ge 10){
            $financeBudget=[Math]::Min(40,$financeMinutes)
            Write-Host ('MARKET_2005_FINANCE_QMT_PRIMARY_VERSIONED=TRUE max_minutes='+$financeBudget)
            Invoke-MarketStage -Label 'FINANCIAL_DAILY' -Script $finance -Arguments @('-Root',$Root,'-FinanceDir',$FinanceDir,'-LookbackDays',[string]$FinanceLookbackDays,'-MaxSymbols',[string]$FinanceDailyStockLimit,'-MaxMinutes',[string]$financeBudget,'-QMTPrimaryVersioned')
        }else{
            $financeDeferred=$true
            $lateLog=Join-Path $work ('afternoon-'+$chinaNow.ToString('yyyyMMdd-HHmmss')+'-FINANCIAL_DAILY.log')
            Set-Content -LiteralPath $lateLog -Encoding UTF8 -Value 'FINANCIAL_DEFERRED_CUTOFF_CHINA_2320=TRUE; NO_QMT_FINANCE_DOWNLOAD; CURSOR_UNCHANGED'
            $stageRecords['FINANCIAL_DAILY']=@{exit_code=87;status='DEFERRED_CUTOFF';log_path=$lateLog}
            Write-Host 'MARKET_2005_FINANCE_DEFERRED_BY_NIGHTLY_CUTOFF=TRUE'
        }
    }else{
        Write-Host 'MARKET_MANUAL_HISTORY_ONLY=TRUE; NO_CURRENT_FINANCE_SECTOR_ADJUSTMENT_QUERIES'
    }
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
        invocation=$Invocation
        history_only=[bool]$HistoryOnly
        run_scope=$runScope
        qmt_preflight_status=$qmtPreflightStatus
        qmt_preflight_attempts=[int]$qmtPreflightAttempts
        qmt_probe_only_no_market_downloads=$true
        started_local=$started
        finished_local=(Get-Date).ToString('o')
        china_start=$chinaNow.ToString('o')
        steps_expected=$stageNames
        steps_completed=@($completed.ToArray())
        stage_records=$stageRecords
        errors=@($failures.ToArray())
        validation=$null
        financial_complete_universe=$false
        finance_deferred_by_cutoff=[bool]$financeDeferred
        adjustments_complete_universe=$false
        other_extra_multisource_verified=$false
        log_path=$log
    }
    # Verification is derived exclusively from current invocation stage logs.
    # Failure to parse NEVER creates a false PASS and never suppresses notice.
    $stepText='执行'+$completed.Count+'/'+$stageNames.Count+'；数据校验未验证；跨源验证未验证'
    if($HistoryOnly){
        $stepText='仅历史行情补更；板块/除权/财务本轮未运行；未做跨源完整认证'
        $result.validation=@{data_validation='UNVERIFIED';cross_validation='UNVERIFIED';execution='MARKET_HISTORY_ONLY'}
    }else{
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
        # Only explicit, receipt-backed finance/adjustment rotation is a
        # successful *execution*. Preserve validation PARTIAL and UNVERIFIED.
        # Old verifiers omit routine_continuation and fail closed as before.
        $routineContinuation=($outcome -eq 'SUCCESS' -and
                              $verification.routine_continuation -eq $true -and
                              $verification.execution -eq 'PASS' -and
                              $verification.data_validation -eq 'PARTIAL' -and
                              $verification.cross_validation -ne 'FAIL')
        if($outcome -eq 'SUCCESS' -and
           ($verification.data_validation -in @('FAIL','PARTIAL') -or
            $verification.cross_validation -eq 'FAIL')){
            if($routineContinuation){
                $result['operational_classification']='ROUTINE_CONTINUATION'
                Write-Host 'MARKET_2005_ROUTINE_ROTATION_COMPLETED_NO_ERROR=TRUE'
            }else{
                $outcome='PARTIAL'
                $result.status=$outcome
            }
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
    }
    if($qmtPreflightStatus -eq 'QMT_SERVICE_UNAVAILABLE'){
        $stepText='QMT_SERVICE_UNAVAILABLE：xtquant连接预检6次失败；四个数据阶段均未运行。请确认QMT已登录并等待服务初始化，然后从GUI安全补更。'
    }
    try {
        $result.errors=@($failures.ToArray())
        $result.finished_local=(Get-Date).ToString('o')
        $part=$status+'.part'
        $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $part -Encoding UTF8
        Move-Item -LiteralPath $part -Destination $status -Force
        Write-Host ('MARKET_1630_SUMMARY='+($result | ConvertTo-Json -Compress -Depth 12))
        Write-Host ('MARKET_2005_RUN_RESULT='+$result.status)
        Write-Host ('MARKET_2005_RUN_LOG='+$log)
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
        & $engine -NoProfile -ExecutionPolicy Bypass -File $notifier -Status $outcome -Summary $stepText -LogPath $log -StatusPath $status -ExpectedStart $started
        if($LASTEXITCODE -ne 0){throw ('Notification exit '+$LASTEXITCODE)}
        Write-Host 'MARKET_1630_USER_NOTIFICATION_ATTEMPTED=TRUE'
    }catch{
        Write-Host ('MARKET_1630_USER_NOTIFICATION_FAILED='+$_.Exception.Message)
    }
}
if($failures.Count){throw ('Market daily update failed: '+($failures -join '; '))}
if($outcome -eq 'PARTIAL'){
    if($financeDeferred -and $failures.Count -eq 0 -and
       $completed.Count -eq ($stageNames.Count-1)){
        # An honest PARTIAL receipt and push are still emitted; a planned
        # bedtime deferral is not a broken Windows scheduled task.
        Write-Host 'MARKET_2005_ROUTINE_FINANCE_CONTINUATION_NEXT_EVENING=TRUE'
    }else{
        throw 'MARKET_2005_PARTIAL_DATA_VALIDATION: detailed same-run logs and status receipt retained'
    }
}
}finally{
    if($runMutexHeld){$runMutex.ReleaseMutex()}
    $runMutex.Dispose()
}
