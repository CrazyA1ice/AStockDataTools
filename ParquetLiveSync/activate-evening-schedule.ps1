# Explicit, bounded cutover from a pinned detached review worktree to
# the canonical AStockDataTools Windows 20:05 task. Default is preview only.
# Must NOT merge GitHub main, start market downloads, or send a test message.
param(
    [string]$CanonicalRepo='D:\ChatGPT\AStockDataTools',
    [string]$ReviewWorktree='',
    [switch]$Apply,
    [switch]$ConfirmCanaryReceived
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$pin='d32bf31dda8c5faece770311c8ce7e2ff0f893c5'
$branch='feat/daily-autopilot-shadow-health-and-finance-plan-20261121'
if(-not $ReviewWorktree){$ReviewWorktree=Join-Path $CanonicalRepo 'work\gui-quickcheck-review'}
$source=Join-Path $ReviewWorktree 'ParquetLiveSync'
$target=Join-Path $CanonicalRepo 'ParquetLiveSync'
$python=Join-Path $CanonicalRepo '.venv\Scripts\python.exe'
$private=Join-Path $target 'work\qmt_extra'
$config=Join-Path $private 'market-notification.private.json'
$taskName='AStockDataTools-ParquetLiveSync'
$oldFinanceName='AStockDataTools-QMT-Financial-Daily'
$relative=@(
    'scheduled-afternoon-update.ps1',
    'run-qmt-financial-daily.ps1',
    'qmt_extra_financial_cache_import.py',
    'install-schedule.ps1',
    'notify-market-update.ps1',
    'market_daily_verification.py',
    'market_update_push.py',
    'setup-market-notification.ps1'
)
if(-not(Test-Path -LiteralPath (Join-Path $CanonicalRepo '.git') -PathType Container)){
    throw 'CANONICAL_MAIN_REPO_MISSING'
}
if(-not(Test-Path -LiteralPath $python -PathType Leaf) -or
   -not(Test-Path -LiteralPath $private -PathType Container)){
    throw 'CANONICAL_PYTHON_OR_PRIVATE_STATE_MISSING'
}
$headActual=(& git -C $ReviewWorktree rev-parse HEAD)
if($LASTEXITCODE -ne 0 -or $headActual.Trim() -ne $pin){
    throw 'REVIEW_WORKTREE_NOT_PINNED'
}
$reviewDirty=@(& git -C $ReviewWorktree status --porcelain)
if($LASTEXITCODE -ne 0 -or $reviewDirty.Count -gt 0){
    throw 'REVIEW_WORKTREE_DIRTY'
}
foreach($name in $relative){
    $path=Join-Path $source $name
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){
        throw ('REVIEW_SOURCE_MISSING_'+$name)
    }
    $modified=@(& git -C $CanonicalRepo status --porcelain -- ('ParquetLiveSync/'+$name))
    if($LASTEXITCODE -ne 0 -or $modified.Count -gt 0){
        throw ('CANONICAL_LOCAL_FILE_CHANGED_'+$name)
    }
}
foreach($name in @('run-market-catchup.ps1','update-market.ps1',
                    'qmt_connect_preflight.py','qmt_extra_financial_cache_worker.py',
                    'qmt_extra_data.py','market_sources.json')){
    if(-not(Test-Path -LiteralPath (Join-Path $target $name) -PathType Leaf)){
        throw ('CANONICAL_DEPENDENCY_MISSING_'+$name)
    }
}
$china=[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([datetime]::UtcNow,'China Standard Time')
$minute=$china.Hour*60+$china.Minute
if($minute -ge 1160 -and $minute -lt 1240){
    throw 'AVOID_2005_ACTIVE_UPDATE_WINDOW'
}
$active=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$oldFinance=Get-ScheduledTask -TaskName $oldFinanceName -ErrorAction SilentlyContinue
if($null -ne $active -and [string]$active.State -eq 'Running'){
    throw 'MARKET_SCHEDULE_CURRENTLY_RUNNING'
}
if($null -ne $oldFinance -and [string]$oldFinance.State -eq 'Running'){
    throw 'OLD_FINANCE_SCHEDULE_CURRENTLY_RUNNING'
}
# Validate the production private recipient *before* any task change.
if($Apply){
    if(-not $ConfirmCanaryReceived){
        throw 'CONFIRM_REAL_WECOM_CANARY_ON_HANDSET_BEFORE_APPLY'
    }
    if(-not(Test-Path -LiteralPath $config -PathType Leaf)){
        throw 'PRIVATE_WECOM_RECIPIENT_NOT_CONFIGURED'
    }
    & $python -B (Join-Path $source 'market_update_push.py') --config $config --validate-config
    if($LASTEXITCODE -ne 0){throw 'PRIVATE_WECOM_RECIPIENT_INVALID'}
}
# Offline checks are run even if the caller only requested preview.
Push-Location $source
try {
    foreach($test in @('test_market_update_push.py','test_market_daily_verification.py',
                       'test_finance_qmt_primary_versioned.py')){
        & $python -B -m unittest discover -s tests -p $test -q
        if($LASTEXITCODE -ne 0){throw ('PINNED_SOURCE_PYTHON_TEST_FAILED_'+$test)}
    }
    foreach($test in @('test_notify_market_mock.ps1',
                       'test_install_afternoon_schedule_mock.ps1',
                       'test_schedule_evening_push_mock.ps1')){
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $source ('tests\'+$test))
        if($LASTEXITCODE -ne 0){throw ('PINNED_SOURCE_PS_TEST_FAILED_'+$test)}
    }
}finally{
    Pop-Location
}
Write-Host ('EVENING_SCHEDULE_PIN_VERIFIED='+$pin)
Write-Host 'EVENING_SCHEDULE_SEQUENCE=KLINE,SECTORS,ADJUSTMENTS,QMT_FINANCE_LAST'
Write-Host 'EVENING_NOTIFICATION=WECOM_NO_WINDOWS_POPUP'
Write-Host ('EVENING_STANDALONE_FINANCE_STATUS='+$(if($null -eq $oldFinance){'NOT_INSTALLED'}else{[string]$oldFinance.State}))
if(-not $Apply){
    Write-Host 'EVENING_SCHEDULE_ACTIVATION_PREVIEW_ONLY_NO_LOCAL_CHANGES'
    return
}
$backup=Join-Path $private ('evening-schedule-backup-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $backup -ErrorAction Stop | Out-Null
$oldRecords=@{}
$mainTaskExisted=($null -ne $active)
$oldFinanceEnabled=($null -ne $oldFinance -and [string]$oldFinance.State -ne 'Disabled')
$oldTaskXml=Join-Path $backup 'existing-market-task.xml'
if($mainTaskExisted){
    $text=Export-ScheduledTask -TaskName $taskName -ErrorAction Stop
    [IO.File]::WriteAllText($oldTaskXml,$text,
                            [System.Text.UTF8Encoding]::new($false))
}
$copied=New-Object System.Collections.ArrayList
try{
    foreach($name in $relative){
        $before=Join-Path $target $name
        $oldRecords[$name]=(Test-Path -LiteralPath $before -PathType Leaf)
        if($oldRecords[$name]){
            Copy-Item -LiteralPath $before -Destination (Join-Path $backup $name) -ErrorAction Stop
        }
    }
    foreach($name in $relative){
        $from=Join-Path $source $name
        $to=Join-Path $target $name
        Copy-Item -LiteralPath $from -Destination $to -Force -ErrorAction Stop
        [void]$copied.Add($name)
        if((Get-FileHash -LiteralPath $from -Algorithm SHA256).Hash -ne
           (Get-FileHash -LiteralPath $to -Algorithm SHA256).Hash){
            throw ('DEPLOYED_FILE_SHA_MISMATCH_'+$name)
        }
    }
    # Syntax/parsing in canonical main checkout, with no network.
    foreach($name in $relative){
        if($name.EndsWith('.ps1')){
            $tok=$null; $errs=$null
            [void][System.Management.Automation.Language.Parser]::ParseFile(
                (Join-Path $target $name),[ref]$tok,[ref]$errs)
            if($null -ne $errs -and $errs.Count -gt 0){
                throw ('CANONICAL_POWERSHELL_SYNTAX_ERROR_'+$name)
            }
        }
    }
    & $python -B (Join-Path $target 'qmt_extra_financial_cache_import.py') --help | Out-Null
    if($LASTEXITCODE -ne 0){throw 'CANONICAL_FINANCE_IMPORT_UNAVAILABLE'}
    & $python -B (Join-Path $target 'market_update_push.py') --config $config --validate-config
    if($LASTEXITCODE -ne 0){throw 'CANONICAL_WECOM_CONFIG_UNAVAILABLE'}
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $target 'scheduled-afternoon-update.ps1') -Invocation Manual | Out-Null
    if($LASTEXITCODE -ne 0){throw 'CANONICAL_SCHEDULE_PREVIEW_FAILED'}
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $target 'install-schedule.ps1') -Action Install
    if($LASTEXITCODE -ne 0){throw 'CANONICAL_SCHEDULE_INSTALL_FAILED'}
    $installed=Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    if($installed.Triggers.Count -ne 1 -or
       $installed.Actions[0].Arguments -notmatch 'scheduled-afternoon-update.ps1'){
        throw 'POST_INSTALL_SINGLE_TASK_IDENTITY_MISMATCH'
    }
    Write-Host ('EVENING_SCHEDULE_ACTIVATED=TRUE backup='+$backup)
    Write-Host 'EVENING_WECOM_PROVIDER_ACK_IS_NOT_HANDSET_DELIVERY_PROOF'
    Write-Host 'EVENING_SCHEDULE_NO_MARKET_JOB_STARTED=TRUE'
}catch{
    $errorText=$_.Exception.Message
    Write-Host ('EVENING_SCHEDULE_ACTIVATION_FAILED='+$errorText)
    foreach($name in @($copied.ToArray())){
        $to=Join-Path $target $name
        try{
            if($oldRecords[$name]){
                Copy-Item -LiteralPath (Join-Path $backup $name) -Destination $to -Force
            }elseif(Test-Path -LiteralPath $to){
                Remove-Item -LiteralPath $to -Force
            }
        }catch{Write-Host ('EVENING_SCRIPT_ROLLBACK_FAILED_'+$name)}
    }
    # Restoring a registered task may require Windows permissions. Backup XML
    # remains available for manual rollback if Windows refuses this operation.
    try{
        if($mainTaskExisted){
            Register-ScheduledTask -TaskName $taskName -Xml (
                Get-Content -LiteralPath $oldTaskXml -Raw -Encoding UTF8) -Force | Out-Null
        }else{
            $created=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            if($null -ne $created){Unregister-ScheduledTask -TaskName $taskName -Confirm:$false}
        }
    }catch{Write-Host 'EVENING_WINDOWS_TASK_ROLLBACK_REQUIRES_MANUAL_XML_RESTORE'}
    if($oldFinanceEnabled){
        try{Enable-ScheduledTask -TaskName $oldFinanceName | Out-Null}
        catch{Write-Host 'OLD_0030_TASK_REENABLE_REQUIRES_MANUAL_ACTION'}
    }
    throw 'EVENING_SCHEDULE_ACTIVATION_ROLLED_BACK_OR_MANUAL_RECOVERY_REQUIRED'
}
